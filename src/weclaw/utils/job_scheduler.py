"""异步定时任务调度器：APScheduler AsyncIOScheduler 精准触发 + SQLite 持久化。

每个 Agent 实例持有独立的 JobScheduler，任务按 session 隔离存储。
启动时自动从数据库恢复所有 pending 任务并重建调度器 job。
支持一次性任务和重复任务（repeat_interval）。
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Awaitable, Callable

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# 任务状态常量
STATUS_PENDING = "pending"
STATUS_FIRED = "fired"
STATUS_CANCELLED = "cancelled"


class JobScheduler:
    """异步定时任务调度器：APScheduler AsyncIOScheduler 精准触发 + SQLite 持久化。

    核心机制：
    - 添加任务时，同时写入 SQLite 并通过 APScheduler 注册调度 job
    - 一次性任务：使用 DateTrigger，触发后标记 fired
    - 重复任务：使用 IntervalTrigger，每次触发后 repeat_count+1，达到 max_repeat 后停止
    - 启动时从数据库恢复所有 pending 任务，已过期的立即触发，未过期的重建调度
    """

    def __init__(
        self,
        db_path: str,
        on_fire: Callable[[str, str], Awaitable[None]],
        on_alert: Callable[[list[dict]], Awaitable[None]] | None = None,
        alert_check_interval: int = 600,
        alert_ahead_seconds: int = 900,
    ) -> None:
        """
        Args:
            db_path:              SQLite 数据库文件路径（按 session 隔离）
            on_fire:              任务到期回调，签名 (job_id, description) -> None
            on_alert:             预警回调，签名 (upcoming_jobs: list[dict]) -> None
                                  传入即将到期的任务列表，由调用方决定如何通知用户。
                                  为 None 则不启用预警巡检。
            alert_check_interval: 预警巡检间隔秒数，默认 600（10 分钟）
            alert_ahead_seconds:  提前预警秒数，默认 900（15 分钟）
        """
        self._db_path = db_path
        self._on_fire = on_fire
        self._on_alert = on_alert
        self._alert_check_interval = alert_check_interval
        self._alert_ahead_seconds = alert_ahead_seconds
        self._db: aiosqlite.Connection | None = None
        self._scheduler = AsyncIOScheduler()
        self._alerted_job_ids: set[str] = set()  # 已预警过的 job_id，防止重复提醒

    async def start(self) -> None:
        """初始化数据库表 + 启动 APScheduler + 恢复所有 pending 任务 + 启动预警巡检。"""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_table()
        self._scheduler.start()
        await self._restore_pending_jobs()
        self._start_alert_checker()
        logger.info(f"JobScheduler 已启动，数据库: {self._db_path}")

    # 预警巡检任务的固定 job_id
    _ALERT_JOB_ID = "__alert_checker__"

    async def stop(self) -> None:
        """停止调度器：关闭 APScheduler（自动清理预警巡检 job）+ 关闭数据库连接。"""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

        if self._db is not None:
            await self._db.close()
            self._db = None

        logger.info("JobScheduler 已停止")

    async def add_job(
        self,
        description: str,
        fire_time: str | None = None,
        interval: int | None = None,
        repeat_interval: int | None = None,
        max_repeat: int | None = None,
    ) -> str:
        """添加定时任务：写入数据库 + 注册 APScheduler job。

        Args:
            description:     任务描述，到期后传给大模型处理
            fire_time:       触发时间，ISO 8601 本地时间格式（一次性任务）
            interval:        从现在起间隔多少秒后首次触发（与 fire_time 二选一）
            repeat_interval: 重复间隔秒数，设置后任务将按此间隔重复触发
            max_repeat:      最大重复次数，None 表示无限重复（仅 repeat_interval 有值时生效）

        Returns:
            job_id: 任务唯一标识（UUID）
        """
        job_id = str(uuid.uuid4())
        now = datetime.now()

        # 计算首次触发时间
        if interval is not None:
            first_fire_dt = now + timedelta(seconds=interval)
        elif fire_time is not None:
            first_fire_dt = self._parse_fire_time(fire_time)
        else:
            raise ValueError("必须提供 fire_time 或 interval 其中之一")

        fire_time_str = first_fire_dt.strftime("%Y-%m-%dT%H:%M:%S")

        await self._db.execute(
            "INSERT INTO jobs "
            "(job_id, fire_time, description, status, created_at, repeat_interval, max_repeat, repeat_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, fire_time_str, description, STATUS_PENDING,
             now.isoformat(), repeat_interval, max_repeat, 0),
        )
        await self._db.commit()

        # 注册 APScheduler job
        self._add_scheduler_job(job_id, first_fire_dt, repeat_interval)
        logger.info(f"添加定时任务: job_id={job_id}, fire_time={fire_time_str}, "
                    f"repeat_interval={repeat_interval}, max_repeat={max_repeat}")
        return job_id

    async def update_job(
        self,
        job_id: str,
        description: str,
        fire_time: str | None = None,
        interval: int | None = None,
        repeat_interval: int | None = None,
        max_repeat: int | None = None,
    ) -> bool:
        """更新定时任务：移除旧 APScheduler job + 更新数据库 + 注册新 job。

        Returns:
            True 更新成功，False 表示 job_id 不存在或已非 pending 状态
        """
        # 移除旧的 APScheduler job
        self._remove_scheduler_job(job_id)

        # 计算新的触发时间
        if interval is not None:
            first_fire_dt = datetime.now() + timedelta(seconds=interval)
        elif fire_time is not None:
            first_fire_dt = self._parse_fire_time(fire_time)
        else:
            return False

        fire_time_str = first_fire_dt.strftime("%Y-%m-%dT%H:%M:%S")

        cursor = await self._db.execute(
            "UPDATE jobs SET fire_time = ?, description = ?, "
            "repeat_interval = ?, max_repeat = ?, repeat_count = 0 "
            "WHERE job_id = ? AND status = ?",
            (fire_time_str, description, repeat_interval, max_repeat, job_id, STATUS_PENDING),
        )
        await self._db.commit()

        if cursor.rowcount == 0:
            return False

        # 注册新的 APScheduler job
        self._add_scheduler_job(job_id, first_fire_dt, repeat_interval)
        logger.info(f"更新定时任务: job_id={job_id}, fire_time={fire_time_str}")
        return True

    async def delete_job(self, job_id: str) -> bool:
        """删除定时任务：移除 APScheduler job + 标记为 cancelled。

        Returns:
            True 删除成功，False 表示 job_id 不存在或已非 pending 状态
        """
        self._remove_scheduler_job(job_id)

        cursor = await self._db.execute(
            "UPDATE jobs SET status = ? WHERE job_id = ? AND status = ?",
            (STATUS_CANCELLED, job_id, STATUS_PENDING),
        )
        await self._db.commit()

        if cursor.rowcount == 0:
            return False

        logger.info(f"删除定时任务: job_id={job_id}")
        return True

    async def get_job(self, job_id: str) -> dict | None:
        """根据 job_id 查询任务详情。"""
        async with self._db.execute(
            "SELECT job_id, fire_time, description, status, created_at, "
            "repeat_interval, max_repeat, repeat_count "
            "FROM jobs WHERE job_id = ?",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "job_id": row["job_id"],
                "fire_time": row["fire_time"],
                "description": row["description"],
                "status": row["status"],
                "created_at": row["created_at"],
                "repeat_interval": row["repeat_interval"],
                "max_repeat": row["max_repeat"],
                "repeat_count": row["repeat_count"],
            }

    async def list_pending_jobs(self) -> list[dict]:
        """列出所有 pending 状态的任务。"""
        async with self._db.execute(
            "SELECT job_id, fire_time, description, status, created_at, "
            "repeat_interval, max_repeat, repeat_count "
            "FROM jobs WHERE status = ? ORDER BY fire_time ASC",
            (STATUS_PENDING,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "job_id": row["job_id"],
                    "fire_time": row["fire_time"],
                    "description": row["description"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "repeat_interval": row["repeat_interval"],
                    "max_repeat": row["max_repeat"],
                    "repeat_count": row["repeat_count"],
                }
                for row in rows
            ]

    async def list_upcoming_jobs(self, within_seconds: int = 900) -> list[dict]:
        """列出即将在指定秒数内到期的 pending 任务（不含重复任务）。

        仅返回一次性任务（repeat_interval 为 NULL），用于到期预警提醒。
        重复任务本身会按周期自动触发，不需要额外预警。

        Args:
            within_seconds: 未来多少秒内到期的任务，默认 900（15 分钟）

        Returns:
            即将到期的任务列表，按 fire_time 升序排列
        """
        now = datetime.now()
        deadline = now + timedelta(seconds=within_seconds)
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
        deadline_str = deadline.strftime("%Y-%m-%dT%H:%M:%S")

        async with self._db.execute(
            "SELECT job_id, fire_time, description, status, created_at, "
            "repeat_interval, max_repeat, repeat_count "
            "FROM jobs "
            "WHERE status = ? AND fire_time > ? AND fire_time <= ? "
            "AND repeat_interval IS NULL "
            "ORDER BY fire_time ASC",
            (STATUS_PENDING, now_str, deadline_str),
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "job_id": row["job_id"],
                    "fire_time": row["fire_time"],
                    "description": row["description"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "repeat_interval": row["repeat_interval"],
                    "max_repeat": row["max_repeat"],
                    "repeat_count": row["repeat_count"],
                }
                for row in rows
            ]

    # ── 预警巡检 ──────────────────────────────────────────────

    def _start_alert_checker(self) -> None:
        """通过 APScheduler 注册预警巡检 job（如果配置了 on_alert 回调）。

        使用 IntervalTrigger 周期性触发 _check_and_alert，首次延迟 30 秒启动。
        相比 asyncio.sleep 循环，使用 APScheduler 统一调度更高效、更一致。
        """
        if self._on_alert is None:
            logger.info("未配置 on_alert 回调，跳过预警巡检")
            return

        logger.info(
            f"启动定时任务到期预警巡检: 每 {self._alert_check_interval} 秒检查一次，"
            f"提前 {self._alert_ahead_seconds} 秒预警"
        )

        # 首次延迟 30 秒后触发，之后按 check_interval 周期执行
        start_date = datetime.now() + timedelta(seconds=30)
        self._scheduler.add_job(
            func=self._check_and_alert,
            trigger=IntervalTrigger(
                seconds=self._alert_check_interval,
                start_date=start_date,
            ),
            id=self._ALERT_JOB_ID,
            replace_existing=True,
            misfire_grace_time=60,
        )

    async def _check_and_alert(self) -> None:
        """执行一次巡检：查找即将到期的任务，过滤已预警的，回调通知。"""
        upcoming_jobs = await self.list_upcoming_jobs(
            within_seconds=self._alert_ahead_seconds
        )
        if not upcoming_jobs:
            return

        # 过滤已预警的任务
        new_alerts = []
        for job in upcoming_jobs:
            job_id = job["job_id"]
            if job_id not in self._alerted_job_ids:
                new_alerts.append(job)
                self._alerted_job_ids.add(job_id)

        if not new_alerts:
            return

        logger.info(f"定时任务预警: {len(new_alerts)} 个任务即将到期")

        # 通过回调通知调用方
        try:
            await self._on_alert(new_alerts)
        except Exception as e:
            logger.exception(f"预警回调执行失败: {e}")

    # ── 内部方法 ──────────────────────────────────────────────

    async def _create_table(self) -> None:
        """创建定时任务表（直接重建，不兼容旧版本）。"""
        await self._db.execute("DROP TABLE IF EXISTS jobs")
        await self._db.execute("""
            CREATE TABLE jobs (
                job_id          TEXT PRIMARY KEY,
                fire_time       TEXT NOT NULL,
                description     TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL,
                repeat_interval INTEGER DEFAULT NULL,
                max_repeat      INTEGER DEFAULT NULL,
                repeat_count    INTEGER NOT NULL DEFAULT 0
            )
        """)
        await self._db.execute("""
            CREATE INDEX idx_jobs_status_fire_time
            ON jobs (status, fire_time)
        """)
        await self._db.commit()

    async def _restore_pending_jobs(self) -> None:
        """启动时恢复：加载所有 pending 任务，重新注册调度或立即触发。"""
        jobs = await self.list_pending_jobs()
        now = datetime.now()
        immediate_count = 0
        scheduled_count = 0

        for job in jobs:
            fire_dt = self._parse_fire_time(job["fire_time"])
            repeat_interval = job.get("repeat_interval")

            if fire_dt <= now:
                # 已过期：立即触发
                immediate_count += 1
                asyncio.ensure_future(self._fire_job(job["job_id"]))
            else:
                # 未过期：重建调度
                scheduled_count += 1
                self._add_scheduler_job(job["job_id"], fire_dt, repeat_interval)

        logger.info(
            f"恢复定时任务: 共 {len(jobs)} 个 pending 任务，"
            f"立即触发 {immediate_count} 个，重建调度 {scheduled_count} 个"
        )

    def _add_scheduler_job(
        self,
        job_id: str,
        first_fire_dt: datetime,
        repeat_interval: int | None,
    ) -> None:
        """向 APScheduler 注册一个调度 job。

        - 一次性任务：使用 DateTrigger
        - 重复任务：使用 IntervalTrigger（首次触发时间 = first_fire_dt）
        """
        # 先移除同名旧 job（防止重复注册）
        self._remove_scheduler_job(job_id)

        if repeat_interval is not None:
            trigger = IntervalTrigger(
                seconds=repeat_interval,
                start_date=first_fire_dt,
            )
        else:
            trigger = DateTrigger(run_date=first_fire_dt)

        self._scheduler.add_job(
            func=self._fire_job,
            trigger=trigger,
            args=[job_id],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=60,  # 允许最多 60 秒的触发延迟
        )

    def _remove_scheduler_job(self, job_id: str) -> None:
        """从 APScheduler 移除指定 job（不存在时静默忽略）。"""
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

    async def _fire_job(self, job_id: str) -> None:
        """任务到期触发：查询描述 + 处理重复逻辑 + 调用回调。"""
        # 从数据库查询任务（确保任务仍为 pending 状态）
        job = await self.get_job(job_id)
        if job is None or job["status"] != STATUS_PENDING:
            logger.debug(f"任务 {job_id} 已不是 pending 状态，跳过触发")
            self._remove_scheduler_job(job_id)
            return

        repeat_interval = job.get("repeat_interval")
        max_repeat = job.get("max_repeat")
        repeat_count = job.get("repeat_count", 0)
        new_repeat_count = repeat_count + 1

        if repeat_interval is not None:
            # 重复任务：更新 repeat_count 和下次触发时间
            next_fire_dt = datetime.now() + timedelta(seconds=repeat_interval)
            next_fire_str = next_fire_dt.strftime("%Y-%m-%dT%H:%M:%S")

            if max_repeat is not None and new_repeat_count >= max_repeat:
                # 已达最大重复次数：标记为 fired，移除调度
                await self._db.execute(
                    "UPDATE jobs SET status = ?, repeat_count = ?, fire_time = ? WHERE job_id = ?",
                    (STATUS_FIRED, new_repeat_count, next_fire_str, job_id),
                )
                await self._db.commit()
                self._remove_scheduler_job(job_id)
                logger.info(f"重复任务已完成所有触发: job_id={job_id}, 共触发 {new_repeat_count} 次")
            else:
                # 未达上限：更新计数和下次触发时间，保持 pending
                await self._db.execute(
                    "UPDATE jobs SET repeat_count = ?, fire_time = ? WHERE job_id = ?",
                    (new_repeat_count, next_fire_str, job_id),
                )
                await self._db.commit()
                logger.info(f"重复任务触发第 {new_repeat_count} 次: job_id={job_id}")
        else:
            # 一次性任务：标记为 fired
            await self._db.execute(
                "UPDATE jobs SET status = ? WHERE job_id = ?",
                (STATUS_FIRED, job_id),
            )
            await self._db.commit()
            logger.info(f"一次性任务触发: job_id={job_id}")

        logger.info(f"定时任务触发: job_id={job_id}, description={job['description'][:50]}...")

        # 调用外部回调（由 Agent/Client 处理）
        try:
            await self._on_fire(job_id, job["description"])
        except Exception as e:
            logger.exception(f"定时任务回调执行失败: job_id={job_id}, error={e}")

    @staticmethod
    def _parse_fire_time(fire_time_str: str) -> datetime:
        """解析时间字符串为本地时间 datetime 对象（不含时区信息）。

        支持格式：
        - "2026-03-18T12:00:00"（本地时间，推荐）
        - "2026-03-18 12:00:00"
        - "2026-03-18T12:00:00Z"（UTC，自动转换为本地时间）
        - "2026-03-18T12:00:00+08:00"（带时区，自动转换为本地时间）
        """
        try:
            normalized = fire_time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is not None:
                return dt.astimezone().replace(tzinfo=None)
            return dt
        except ValueError:
            return datetime.fromisoformat(fire_time_str.rstrip("Z").split("+")[0])
