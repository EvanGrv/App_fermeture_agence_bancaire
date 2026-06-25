from datetime import date, timedelta
import run


class _Args:
    since = None
    lookback_days = None
    lookback_months = None


def test_default_since_is_18_months():
    since = run._since_from_args(_Args())
    attendu = (date.today() - timedelta(days=18 * 30)).isoformat()
    assert since == attendu


def test_explicit_since_still_wins():
    a = _Args()
    a.since = "2025-01-01"
    assert run._since_from_args(a) == "2025-01-01"
