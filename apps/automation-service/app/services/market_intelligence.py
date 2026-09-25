"""Market monitoring calculations shared by collection and API routes."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def optional_count(value: Any) -> int | None:
    """An absent platform metric is unknown, not zero."""
    if value is None or value == "":
        return None
    try:
        result = int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def price_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).replace(",", "").strip()
    if raw.startswith("-") or re.search(r"-\s*\d", raw):
        return None
    match = re.search(r"\d+(?:\.\d+)?", raw)
    if not match:
        return None
    try:
        result = Decimal(match.group())
    except InvalidOperation:
        return None
    return result if result >= 0 else None


def normalize_search_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    item_id = str(raw.get("itemId") or "").strip()
    if not item_id or len(item_id) > 80:
        return None
    return {
        "itemId": item_id,
        "title": str(raw.get("title") or "")[:300],
        "price": price_decimal(raw.get("price")),
        "link": str(raw.get("link") or "")[:500],
        "image": str(raw.get("image") or raw.get("imageUrl") or "")[:500],
        "viewCount": optional_count(raw.get("viewCount")),
        "wantCount": optional_count(raw.get("wantCount")),
        "soldCount": optional_count(raw.get("soldCount")),
    }


def trend_rows(rows: list[dict[str, Any]], days: int = 7) -> list[dict[str, Any]]:
    """Use first/last observed values inside the requested window.

    A metric contributes only when both observations exist. A first
    observation is a baseline, never a fabricated increase from zero.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["item_id"])].append(row)
    result = []
    for item_id, history in grouped.items():
        history.sort(key=lambda row: (row["captured_at"], row.get("id", 0)))
        last = history[-1]
        deltas: dict[str, int | None] = {}
        for field in ("view_count", "want_count", "sold_count"):
            known = [count for row in history if (count := optional_count(row.get(field))) is not None]
            deltas[field] = max(0, known[-1] - known[0]) if len(known) > 1 else None
        available = [value for value in deltas.values() if value is not None]
        score = (deltas["view_count"] or 0) + 5 * (deltas["want_count"] or 0) + 10 * (deltas["sold_count"] or 0)
        result.append({
            "itemId": item_id,
            "title": last.get("title") or "",
            "price": float(last["price"]) if last.get("price") is not None else None,
            "link": last.get("link") or "",
            "image": last.get("image") or "",
            "capturedAt": last["captured_at"].isoformat() if isinstance(last["captured_at"], datetime) else str(last["captured_at"]),
            "sampleCount": len(history),
            "viewDelta": deltas["view_count"],
            "wantDelta": deltas["want_count"],
            "soldDelta": deltas["sold_count"],
            "heatScore": score if available else None,
            "scoreFormula": "浏览增量 + 想要增量×5 + 已售增量×10",
            "windowDays": days,
        })
    result.sort(key=lambda row: (row["heatScore"] is not None, row["heatScore"] or -1), reverse=True)
    return result


def compare_price(xianyu_price: Any, quote_price: Any, shipping: Any = 0, min_qty: int = 1) -> dict[str, Any] | None:
    own, quote, freight = price_decimal(xianyu_price), price_decimal(quote_price), price_decimal(shipping)
    if own is None or quote is None or freight is None or min_qty < 1:
        return None
    # 1688's batch minimum is visible to callers; do not silently treat it as one unit.
    landed = quote + freight / Decimal(min_qty)
    return {"xianyuPrice": float(own), "quoteUnitPrice": float(quote), "shippingPerUnit": float(freight / Decimal(min_qty)),
            "minimumQuantity": min_qty, "comparisonUnitPrice": float(landed), "difference": float(own - landed)}
