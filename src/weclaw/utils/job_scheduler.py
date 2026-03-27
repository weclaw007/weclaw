"""异步定时任务调度器：APScheduler + SQLite 持久化。

每个 Agent 实例持有独立的 JobScheduler，任务按 session 隔离存储。
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

STATUS_PENDING = "pending"
STATUS_FIRED = "fired"
STATUS_CANCELLED = "cancelled"


class JobScheduler:
    """异步定时任务调度器"""

    _ALERT_JOB_ID = "__alert_checker__"

    def __init__(
        self,
        db_path: str,
        on_fire: Callable[[str, str], Awaitable[None]],
        on_alert: Callable[[list[dict]], Awaitable[None]] | None = None,
        alert_check_interval: int = 600,
        alert_ahead_seconds: int = 900,
    ) -> None:
        self._db_path = db_path
        self._on_fire = on_fire
        self._on_alert = on_alert
        self._alert_check_interval = alert_check_interval
        self._alert_ahead_seconds = alert_ahead_seconds
        self._db: aiosqlite.Connection | None = None
        self._scheduler = AsyncIOScheduler()
        self._alerted_job_ids: set[str] = set()

    async def start(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._create_table()
        self._scheduler.start()
        await self._restore_pending_jobs()
        self._start_alert_checker()
        logger.info(f"JobScheduler 已启动，数据库: {self._db_path}")

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def add_job(
        self,
        description: str,
        fire_time: str | None = None,
        interval: int | None = None,
        repeat_interval: int | None = None,
        max_repeat: int | None = None,
    ) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now()

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
        self._add_scheduler_job(job_id, first_fire_dt, repeat_interval)
        logger.info(f"添加定时任务: {job_id}, fire_time={fire_time_str}")
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
        self._remove_scheduler_job(job_id)
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
        self._add_scheduler_job(job_id, first_fire_dt, repeat_interval)
        return True

    async def delete_job(self, job_id: str) -> bool:
        self._remove_scheduler_job(job_id)
        cursor = await self._db.execute(
            "UPDATE jobs SET status = ? WHERE job_id = ? AND status = ?",
            (STATUS_CANCELLED, job_id, STATUS_PENDING),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def get_job(self, job_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT job_id, fire_time, description, status, created_at, "
            "repeat_interval, max_repeat, repeat_count FROM jobs WHERE job_id = ?",
            (job_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    async def list_pending_jobs(self) -> list[dict]:
        async with self._db.execute(
            "SELECT job_id, fire_time, description, status, created_at, "
            "repeat_interval, max_repeat, repeat_count "
            "FROM jobs WHERE status = ? ORDER BY fire_time ASC",
            (STATUS_PENDING,),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def list_upcoming_jobs(self, within_seconds: int = 900) -> list[dict]:
        now = datetime.now()
        deadline = now + timedelta(seconds=within_seconds)
        async with self._db.execute(
            "SELECT job_id, fire_time, description, status, created_at, "
            "repeat_interval, max_repeat, repeat_count "
            "FROM jobs WHERE status = ? AND fire_time > ? AND fire_time <= ? "
            "AND repeat_interval IS NULL ORDER BY fire_time ASC",
            (STATUS_PENDING, now.strftime("%Y-%m-%dT%H:%M:%S"),
             deadline.strftime("%Y-%m-%dT%H:%M:%S")),
        ) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    # ── 预警巡检 ──

    def _start_alert_checker(self) -> None:
        if self._on_alert is None:
            return
        start_date = datetime.now() + timedelta(seconds=30)
        self._scheduler.add_job(
            func=self._check_and_alert,
            trigger=IntervalTrigger(seconds=self._alert_check_interval, start_date=start_date),
            id=self._ALERT_JOB_ID,
            replace_existing=True,
            misfire_grace_time=60,
        )

    async def _check_and_alert(self) -> None:
        upcoming = await self.list_upcoming_jobs(within_seconds=self._alert_ahead_seconds)
        new_alerts = [j for j in upcoming if j["job_id"] not in self._alerted_job_ids]
        if not new_alerts:
            return
        for j in new_alerts:
            self._alerted_job_ids.add(j["job_id"])
        try:
            await self._on_alert(new_alerts)
        except Exception as e:
            logger.exception(f"预警回调执行失败: {e}")

    # ── 内部方法 ──

    async def _create_table(self) -> None:
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
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
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_fire_time ON jobs (status, fire_time)"
        )
        await self._db.commit()

    async def _restore_pending_jobs(self) -> None:
        jobs = await self.list_pending_jobs()
        now = datetime.now()
        for job in jobs:
            fire_dt = self._parse_fire_time(job["fire_time"])
            if fire_dt <= now:
                asyncio.ensure_future(self._fire_job(job["job_id"]))
            else:
                self._add_scheduler_job(job["job_id"], fire_dt, job.get("repeat_interval"))

    def _add_scheduler_job(self, job_id: str, first_fire_dt: datetime, repeat_interval: int | None) -> None:
        self._remove_scheduler_job(job_id)
        trigger = (
            IntervalTrigger(seconds=repeat_interval, start_date=first_fire_dt)
            if repeat_interval else DateTrigger(run_date=first_fire_dt)
        )
        self._scheduler.add_job(
            func=self._fire_job, trigger=trigger, args=[job_id],
            id=job_id, replace_existing=True, misfire_grace_time=60,
        )

    def _remove_scheduler_job(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass

    async def _fire_job(self, job_id: str) -> None:
        job = await self.get_job(job_id)
        if job is None or job["status"] != STATUS_PENDING:
            self._remove_scheduler_job(job_id)
            return

        repeat_interval = job.get("repeat_interval")
        max_repeat = job.get("max_repeat")
        new_count = job.get("repeat_count", 0) + 1

        if repeat_interval is not None:
            next_fire = (datetime.now() + timedelta(seconds=repeat_interval)).strftime("%Y-%m-%dT%H:%M:%S")
            if max_repeat is not None and new_count >= max_repeat:
                await self._db.execute(
                    "UPDATE jobs SET status = ?, repeat_count = ?, fire_time = ? WHERE job_id = ?",
                    (STATUS_FIRED, new_count, next_fire, job_id),
                )
                self._remove_scheduler_job(job_id)
            else:
                await self._db.execute(
                    "UPDATE jobs SET repeat_count = ?, fire_time = ? WHERE job_id = ?",
                    (new_count, next_fire, job_id),
                )
        else:
            await self._db.execute(
                "UPDATE jobs SET status = ? WHERE job_id = ?", (STATUS_FIRED, job_id),
            )
        await self._db.commit()

        try:
            await self._on_fire(job_id, job["description"])
        except Exception as e:
            logger.exception(f"定时任务回调执行失败: {job_id}, {e}")

    @staticmethod
    def _parse_fire_time(fire_time_str: str) -> datetime:
        try:
            normalized = fire_time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is not None:
                return dt.astimezone().replace(tzinfo=None)
            return dt
        except ValueError:
            return datetime.fromisoformat(fire_time_str.rstrip("Z").split("+")[0])
