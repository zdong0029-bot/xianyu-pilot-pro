"""轻量级定时任务 Worker。

独立运行方式：python run-worker.py
它不会接管 Java 业务数据，只扫描 scheduled_task 中到期且启用的任务，然后调用 automation_runtime 执行。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from .core.database import async_session
from .services.automation_runtime import execute_scheduled_task, list_due_tasks
from .services.upload_governance import probe_upload_storage, reconcile_storage_assets
from sqlalchemy import text
from .api.v1.routes.market import collect_watch

logger = logging.getLogger(__name__)
UPLOAD_IMAGES_ROOT = (Path(__file__).resolve().parent.parent / "uploads" / "images").resolve()

# 心跳文件路径：优先使用环境变量，否则使用系统临时目录（跨平台兼容）
if os.name == "nt":
    import tempfile
    DEFAULT_HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "automation-worker-heartbeat"
else:
    DEFAULT_HEARTBEAT_FILE = Path("/tmp/automation-worker-heartbeat")


def record_heartbeat(path: Path | None = None) -> None:
    target = path or Path(os.getenv("WORKER_HEARTBEAT_FILE", str(DEFAULT_HEARTBEAT_FILE)))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(f"{int(time.time())}\n", encoding="ascii")
    os.replace(temporary, target)


async def run_once(limit: int = 20) -> dict:
    async with async_session() as db:
        tasks = await list_due_tasks(db, limit=limit)
        results = []
        for task in tasks:
            try:
                results.append(await execute_scheduled_task(db, int(task["id"]), task.get("tenant_id")))
            except Exception as e:
                logger.error(
                    "定时任务执行失败 taskId=%s errorType=%s",
                    task.get("id"),
                    type(e).__name__,
                )
                results.append({
                    "ok": False,
                    "claimed": False,
                    "taskId": task.get("id"),
                    "message": "定时任务执行失败",
                })
        processed = sum(1 for result in results if result.get("claimed") is True)
        return {
            "candidates": len(tasks),
            "processed": processed,
            "skipped": len(tasks) - processed,
            "results": results,
        }


async def run_market_once(limit: int = 3) -> dict:
    """Collect bounded due watches; the DB claim prevents duplicate workers."""
    async with async_session() as db:
        rows = await db.execute(text("""
            SELECT id,tenant_id,user_id,account_id,keyword,search_mode
            FROM market_watch WHERE enabled=1 AND next_run_at<=UTC_TIMESTAMP()
            ORDER BY next_run_at,id LIMIT :limit
        """), {"limit": max(1, min(limit, 10))})
        watches = [dict(row) for row in rows.mappings().all()]
        results = []
        for watch in watches:
            result = await collect_watch(db, watch,
                {"tenant_id": watch["tenant_id"], "user_id": watch["user_id"], "auth_type": "internal"},
                due_only=True)
            results.append({"watchId": watch["id"], **result})
        return {"candidates": len(watches), "results": results}


async def run_forever(interval_seconds: int = 60) -> None:
    await probe_upload_storage(str(UPLOAD_IMAGES_ROOT))
    await reconcile_storage_assets(str(UPLOAD_IMAGES_ROOT))
    last_storage_check = time.monotonic()
    last_market_cleanup = time.monotonic()
    market_task: asyncio.Task | None = None

    async def market_cycle() -> None:
        nonlocal last_market_cleanup
        try:
            market_result = await run_market_once()
            if time.monotonic() - last_market_cleanup >= 86400:
                async with async_session() as db:
                    await db.execute(text("DELETE FROM market_snapshot WHERE captured_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY)"))
                    await db.commit()
                last_market_cleanup = time.monotonic()
            if market_result["candidates"]:
                logger.info("market worker processed %d watches", market_result["candidates"])
        except Exception as exc:
            logger.error("market worker loop failed errorType=%s", type(exc).__name__)

    logger.info("automation worker started, interval=%ss", interval_seconds)
    while True:
        try:
            if time.monotonic() - last_storage_check >= 300:
                await probe_upload_storage(str(UPLOAD_IMAGES_ROOT))
                await reconcile_storage_assets(str(UPLOAD_IMAGES_ROOT))
                last_storage_check = time.monotonic()
            result = await run_once()
            record_heartbeat()
            if result["processed"]:
                logger.info("automation worker processed tasks: %s", result)
            if market_task is None or market_task.done():
                market_task = asyncio.create_task(market_cycle())
        except Exception as exc:
            logger.error("automation worker loop failed errorType=%s", type(exc).__name__)
        await asyncio.sleep(max(interval_seconds, 5))
