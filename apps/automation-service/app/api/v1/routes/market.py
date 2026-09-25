"""Keyword watches and auditable market snapshots within the existing service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_db
from app.api.v1.routes.misc import _execute_search_with_mode
from app.core.response import ResultObject
from app.services.market_intelligence import compare_price, normalize_search_item, price_decimal, trend_rows
from app.services.xianyu_goods_sync import _resolve_account_cookie

router = APIRouter(prefix="/market", tags=["marketIntelligence"])


def _tenant_user(current_user: dict) -> tuple[int, int]:
    return int(current_user["tenant_id"]), int(current_user["user_id"])


async def collect_watch(db: AsyncSession, watch: dict, current_user: dict, *, due_only: bool = False) -> dict:
    tenant_id, user_id = _tenant_user(current_user)
    watch_id = int(watch["id"])
    claim = await db.execute(text("""
        UPDATE market_watch SET lock_until=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 4 MINUTE)
        WHERE id=:watch_id AND tenant_id=:tenant_id AND user_id=:user_id AND enabled=1
          AND (lock_until IS NULL OR lock_until<UTC_TIMESTAMP())
          AND (:due_only=0 OR next_run_at<=UTC_TIMESTAMP())
    """), {"watch_id": watch_id, "tenant_id": tenant_id, "user_id": user_id, "due_only": int(due_only)})
    await db.commit()
    if claim.rowcount != 1:
        return {"claimed": False, "reason": "采集未到期或正在执行"}
    account_id = int(watch["account_id"])
    try:
        cookie, error, resolved_id = await _resolve_account_cookie(db, tenant_id, account_id, current_user)
        if error or int(resolved_id or 0) != account_id:
            raise ValueError(error or "闲鱼账号不可用")
        result = await asyncio.to_thread(
            _execute_search_with_mode, str(watch["keyword"]), 1, 50, tenant_id, cookie, str(watch["search_mode"]),
        )
        items = result.get("items") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise ValueError("搜索结果格式异常")
        captured_at = datetime.utcnow()
        seen = set()
        saved = 0
        for raw in items:
            item = normalize_search_item(raw) if isinstance(raw, dict) else None
            if not item or item["itemId"] in seen:
                continue
            seen.add(item["itemId"])
            await db.execute(text("""
                INSERT INTO market_snapshot
                (tenant_id,watch_id,account_id,item_id,title,price,link,image,view_count,want_count,sold_count,captured_at)
                VALUES (:tenant_id,:watch_id,:account_id,:item_id,:title,:price,:link,:image,:view_count,:want_count,:sold_count,:captured_at)
            """), {"tenant_id": tenant_id, "watch_id": watch_id, "account_id": account_id,
                   "item_id": item["itemId"], "title": item["title"], "price": item["price"],
                   "link": item["link"], "image": item["image"], "view_count": item["viewCount"],
                   "want_count": item["wantCount"], "sold_count": item["soldCount"], "captured_at": captured_at})
            saved += 1
        await db.execute(text("""
            UPDATE market_watch SET lock_until=NULL,last_run_at=:now,
            next_run_at=DATE_ADD(:now, INTERVAL interval_minutes MINUTE),last_error=NULL
            WHERE id=:watch_id AND tenant_id=:tenant_id
        """), {"now": captured_at, "watch_id": watch_id, "tenant_id": tenant_id})
        await db.commit()
        return {"claimed": True, "saved": saved, "capturedAt": captured_at.isoformat() + "Z"}
    except Exception as exc:
        await db.rollback()
        # A failed source call never creates a zero-valued sample.
        await db.execute(text("""
            UPDATE market_watch SET lock_until=NULL,last_run_at=UTC_TIMESTAMP(),
            next_run_at=DATE_ADD(UTC_TIMESTAMP(), INTERVAL interval_minutes MINUTE),last_error=:error
            WHERE id=:watch_id AND tenant_id=:tenant_id
        """), {"error": str(exc)[:500], "watch_id": watch_id, "tenant_id": tenant_id})
        await db.commit()
        return {"claimed": True, "saved": 0, "error": str(exc)[:300]}


@router.get("/watches", response_model=ResultObject)
async def list_watches(db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    tenant_id, user_id = _tenant_user(current_user)
    rows = await db.execute(text("""
        SELECT id,account_id AS accountId,keyword,search_mode AS searchMode,
               interval_minutes AS intervalMinutes,enabled,next_run_at AS nextRunAt,
               last_run_at AS lastRunAt,last_error AS lastError
        FROM market_watch WHERE tenant_id=:tenant_id AND user_id=:user_id ORDER BY id DESC LIMIT 100
    """), {"tenant_id": tenant_id, "user_id": user_id})
    return ResultObject.success([dict(row) for row in rows.mappings().all()])


@router.post("/watches", response_model=ResultObject)
async def add_watch(body: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    tenant_id, user_id = _tenant_user(current_user)
    keyword = str(body.get("keyword") or "").strip()
    mode = str(body.get("searchMode") or "auto")
    try:
        account_id = int(body.get("accountId"))
        interval = int(body.get("intervalMinutes", 120))
    except (TypeError, ValueError):
        return ResultObject.validate_failed("账号或采集间隔无效")
    if not keyword or len(keyword) > 50 or mode not in {"auto", "fast", "slow"} or not 30 <= interval <= 1440:
        return ResultObject.validate_failed("关键词、搜索模式或采集间隔无效")
    cookie, error, resolved_id = await _resolve_account_cookie(db, tenant_id, account_id, current_user)
    if error or not cookie or int(resolved_id or 0) != account_id:
        return ResultObject.failed(error or "闲鱼账号不可用", 400)
    result = await db.execute(text("""
        INSERT INTO market_watch (tenant_id,user_id,account_id,keyword,search_mode,interval_minutes,next_run_at)
        VALUES (:tenant_id,:user_id,:account_id,:keyword,:mode,:interval,UTC_TIMESTAMP())
    """), {"tenant_id": tenant_id, "user_id": user_id, "account_id": account_id,
           "keyword": keyword, "mode": mode, "interval": interval})
    await db.commit()
    return ResultObject.success({"id": result.lastrowid})


@router.post("/watches/{watch_id}/collect", response_model=ResultObject)
async def collect_now(watch_id: int, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    tenant_id, user_id = _tenant_user(current_user)
    row = await db.execute(text("""
        SELECT id,account_id,keyword,search_mode FROM market_watch
        WHERE id=:id AND tenant_id=:tenant_id AND user_id=:user_id AND enabled=1
    """), {"id": watch_id, "tenant_id": tenant_id, "user_id": user_id})
    watch = row.mappings().first()
    if not watch:
        return ResultObject.failed("监控任务不存在", 404)
    result = await collect_watch(db, dict(watch), current_user)
    return ResultObject.success(result) if "error" not in result else ResultObject.failed(result["error"], 503)


@router.get("/trends", response_model=ResultObject)
async def trends(watchId: int = Query(...), days: int = Query(7, ge=1, le=30),
                 limit: int = Query(50, ge=1, le=100), db: AsyncSession = Depends(get_db),
                 current_user: dict = Depends(get_current_user)):
    tenant_id, user_id = _tenant_user(current_user)
    check = await db.execute(text("SELECT 1 FROM market_watch WHERE id=:id AND tenant_id=:tenant_id AND user_id=:user_id"),
                             {"id": watchId, "tenant_id": tenant_id, "user_id": user_id})
    if not check.first():
        return ResultObject.failed("监控任务不存在", 404)
    since = datetime.utcnow() - timedelta(days=days)
    rows = await db.execute(text("""
        SELECT id,item_id,title,price,link,image,view_count,want_count,sold_count,captured_at
        FROM market_snapshot WHERE tenant_id=:tenant_id AND watch_id=:watch_id AND captured_at>=:since
        ORDER BY captured_at DESC,id DESC LIMIT 5000
    """), {"tenant_id": tenant_id, "watch_id": watchId, "since": since})
    samples = rows.mappings().all()
    ranked = trend_rows([dict(row) for row in samples], days)
    return ResultObject.success({"items": ranked[:limit], "sampledItems": len(ranked),
                                 "windowDays": days, "truncated": len(samples) == 5000})


@router.post("/quotes", response_model=ResultObject)
async def add_quote(body: dict = Body(...), db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Manual evidence until authorized PDD/1688 data access is configured."""
    tenant_id, _ = _tenant_user(current_user)
    item_id = str(body.get("itemId") or "").strip()
    platform = str(body.get("platform") or "").lower().strip()
    url = str(body.get("sourceUrl") or "").strip()
    evidence = str(body.get("modelEvidence") or "").strip()
    price = price_decimal(body.get("price"))
    shipping = price_decimal(body.get("shipping", 0))
    try:
        minimum = int(body.get("minimumQuantity", 1))
    except (TypeError, ValueError):
        minimum = 0
    host = (urlparse(url).hostname or "").lower()
    allowed = {"pdd": ("pinduoduo.com", "yangkeduo.com"), "1688": ("1688.com",)}
    if (platform not in allowed or not any(host == domain or host.endswith("." + domain) for domain in allowed.get(platform, ()))
            or not url.startswith("https://") or not item_id or len(item_id) > 80 or not evidence
            or price is None or shipping is None or minimum < 1 or minimum > 10000):
        return ResultObject.validate_failed("平台、商品链接、同款证据或价格无效")
    item = await db.execute(text("""
        SELECT 1 FROM market_snapshot WHERE tenant_id=:tenant_id AND item_id=:item_id LIMIT 1
    """), {"tenant_id": tenant_id, "item_id": item_id})
    if not item.first():
        return ResultObject.failed("请先采集该闲鱼商品", 404)
    await db.execute(text("""
        INSERT INTO market_price_quote
        (tenant_id,item_id,platform,source_url,model_evidence,price,shipping,minimum_quantity,source_type,observed_at)
        VALUES (:tenant_id,:item_id,:platform,:url,:evidence,:price,:shipping,:minimum,'manual',UTC_TIMESTAMP())
    """), {"tenant_id": tenant_id, "item_id": item_id, "platform": platform, "url": url,
           "evidence": evidence[:300], "price": price, "shipping": shipping, "minimum": minimum})
    await db.commit()
    return ResultObject.success({"saved": True, "sourceType": "manual"})


@router.get("/comparisons", response_model=ResultObject)
async def comparisons(itemId: str = Query(...), db: AsyncSession = Depends(get_db),
                      current_user: dict = Depends(get_current_user)):
    tenant_id, _ = _tenant_user(current_user)
    item = await db.execute(text("""
        SELECT price FROM market_snapshot WHERE tenant_id=:tenant_id AND item_id=:item_id
        ORDER BY captured_at DESC,id DESC LIMIT 1
    """), {"tenant_id": tenant_id, "item_id": itemId[:80]})
    latest = item.mappings().first()
    if not latest:
        return ResultObject.failed("没有该商品的闲鱼价格快照", 404)
    rows = await db.execute(text("""
        SELECT platform,source_url,model_evidence,price,shipping,minimum_quantity,source_type,observed_at
        FROM market_price_quote WHERE tenant_id=:tenant_id AND item_id=:item_id
        ORDER BY observed_at DESC,id DESC LIMIT 30
    """), {"tenant_id": tenant_id, "item_id": itemId[:80]})
    offers = []
    for row in rows.mappings().all():
        data = dict(row)
        comparison = compare_price(latest["price"], data["price"], data["shipping"], data["minimum_quantity"])
        offers.append({"platform": data["platform"], "sourceUrl": data["source_url"],
                       "modelEvidence": data["model_evidence"], "sourceType": data["source_type"],
                       "observedAt": data["observed_at"].isoformat(), "comparison": comparison})
    return ResultObject.success({"itemId": itemId, "offers": offers, "automaticSourcesConfigured": False})
