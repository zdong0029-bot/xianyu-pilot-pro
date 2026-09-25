from datetime import datetime, timedelta
from decimal import Decimal

from app.services.market_intelligence import compare_price, normalize_search_item, price_decimal, trend_rows


def test_missing_metrics_are_not_zero():
    item = normalize_search_item({"itemId": "1001", "price": "¥99", "wantCount": 0})
    assert item["wantCount"] == 0
    assert item["viewCount"] is None
    assert item["soldCount"] is None


def test_trend_requires_two_observations_and_known_metrics():
    now = datetime.utcnow()
    first = {"id": 1, "item_id": "1001", "captured_at": now - timedelta(hours=1), "title": "商品",
             "price": Decimal("99"), "view_count": None, "want_count": 2, "sold_count": 0}
    single = trend_rows([first])[0]
    assert single["heatScore"] is None
    latest = {**first, "id": 2, "captured_at": now, "want_count": 5, "sold_count": 1}
    ranked = trend_rows([latest, first])[0]
    assert ranked["viewDelta"] is None
    assert ranked["wantDelta"] == 3
    assert ranked["soldDelta"] == 1
    assert ranked["heatScore"] == 25


def test_comparison_includes_minimum_quantity_and_shipping():
    comparison = compare_price("¥100", "80", "20", 2)
    assert comparison["comparisonUnitPrice"] == 90
    assert comparison["difference"] == 10
    assert comparison["minimumQuantity"] == 2
    assert price_decimal("-5") is None
