"""Agent 业务工具 - 从 Session 中抽取的独立工具定义。

包含工具：
- timer_job: 定时任务管理（Session 专用，需注入 JobScheduler）

技能读取由 SkillsMiddleware 通过内置 read_file 工具自动支持，
不再需要自定义 read_skill 工具。
"""

import json
import logging
from datetime import datetime

from langchain_core.tools import BaseTool, tool

from weclaw.utils.job_scheduler import JobScheduler

logger = logging.getLogger(__name__)


# ── 定时任务工具（Session 注入 JobScheduler）──────────────────


def create_timer_job_tool(scheduler: JobScheduler) -> BaseTool:
    """创建定时任务工具。

    Args:
        scheduler: JobScheduler 实例

    Returns:
        可注册到 Agent 的 BaseTool 实例
    """

    def _is_valid_fire_time(fire_time: str) -> bool:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                datetime.strptime(fire_time.split("+")[0].rstrip("Z"), fmt)
                return True
            except ValueError:
                continue
        return False

    @tool
    async def timer_job(action: str, params: dict) -> str:
        """定时任务工具，用于创建、更新、删除、查询定时提醒。

        action 可选值: add, update, delete, query, list
        params 参数说明:
          - add:    {"fire_time"|"interval", "description", "repeat_interval"?, "max_repeat"?}
          - update: {"job_id", "fire_time"|"interval", "description", ...}
          - delete: {"job_id"}
          - query:  {"job_id"}
          - list:   {}

        fire_time: ISO 8601 本地时间 (YYYY-MM-DDTHH:MM:SS)
        interval: 从现在起间隔秒数（正整数）
        """
        if scheduler is None:
            return "定时任务服务未初始化"
        try:
            if action == "add":
                desc = params.get("description")
                ft = params.get("fire_time")
                iv = params.get("interval")
                ri = params.get("repeat_interval")
                mr = params.get("max_repeat")
                if not desc:
                    return "参数缺失: description"
                if ft and iv:
                    return "fire_time 和 interval 不能同时传入"
                if not ft and not iv:
                    return "必须提供 fire_time 或 interval"
                if iv is not None:
                    iv = int(iv)
                    if iv <= 0:
                        return "interval 必须是正整数"
                elif not _is_valid_fire_time(ft):
                    return f"fire_time 格式错误: '{ft}'，需要 YYYY-MM-DDTHH:MM:SS"
                if ri is not None:
                    ri = int(ri)
                if mr is not None:
                    mr = int(mr)
                job_id = await scheduler.add_job(
                    description=desc, fire_time=ft, interval=iv,
                    repeat_interval=ri, max_repeat=mr,
                )
                return f"定时任务已创建，job_id: {job_id}"
            elif action == "update":
                jid = params.get("job_id")
                desc = params.get("description")
                ft = params.get("fire_time")
                iv = params.get("interval")
                ri = params.get("repeat_interval")
                mr = params.get("max_repeat")
                if not all([jid, desc]):
                    return "参数缺失: job_id 或 description"
                if iv is not None:
                    iv = int(iv)
                if ri is not None:
                    ri = int(ri)
                if mr is not None:
                    mr = int(mr)
                ok = await scheduler.update_job(
                    job_id=jid, description=desc, fire_time=ft,
                    interval=iv, repeat_interval=ri, max_repeat=mr,
                )
                return "更新成功" if ok else "job_id 不存在或已非 pending"
            elif action == "delete":
                jid = params.get("job_id")
                if not jid:
                    return "参数缺失: job_id"
                ok = await scheduler.delete_job(jid)
                return "删除成功" if ok else "job_id 不存在或已非 pending"
            elif action == "query":
                jid = params.get("job_id")
                if not jid:
                    return "参数缺失: job_id"
                job = await scheduler.get_job(jid)
                if job is None:
                    return "job_id 不存在"
                return json.dumps(job, ensure_ascii=False, default=str)
            elif action == "list":
                jobs = await scheduler.list_pending_jobs()
                if not jobs:
                    return "当前没有 pending 的定时任务"
                lines = [f"共 {len(jobs)} 个 pending 任务:"]
                for j in jobs:
                    lines.append(f"  - {j['job_id'][:8]}... {j['fire_time']} {j['description'][:50]}")
                return "\n".join(lines)
            else:
                return "未知 action，支持 add/update/delete/query/list"
        except Exception as e:
            return f"定时任务异常: {e}"

    return timer_job
