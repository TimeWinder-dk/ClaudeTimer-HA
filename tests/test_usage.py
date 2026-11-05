import unittest
from datetime import UTC, datetime, timedelta

from support import usage

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def limit(kind="session", percent=10.0, resets_in=timedelta(hours=1), **kw):
    return usage.UsageLimit(kind=kind, group=kind, percent=percent, resets_at=NOW + resets_in, **kw)


class ParseTests(unittest.TestCase):
    def test_limits_array_is_preferred_and_keyed_by_model(self):
        raw = {
            "five_hour": {"utilization": 99, "resets_at": "2026-11-05T13:00:00Z"},
            "limits": [
                {"kind": "session", "group": "session", "percent": 12.5, "resets_at": "2026-11-05T14:00:00Z"},
                {"kind": "weekly_all", "group": "weekly", "percent": 40, "resets_at": "2026-11-09T08:00:00+00:00"},
                {"kind": "weekly_scoped", "group": "weekly", "percent": 70,
                 "resets_at": "2026-11-09T08:00:00Z", "scope": {"model": {"display_name": "Fable"}}},
                {"kind": "weekly_scoped", "group": "weekly", "percent": 5,
                 "resets_at": "2026-11-09T08:00:00Z", "scope": {"model": {"display_name": "Opus"}}},
                {"group": "ignored-without-kind"},
            ],
        }
        snap = usage.parse_usage(raw, NOW)
        self.assertEqual(
            list(snap.limits),
            ["session", "weekly_all", "weekly_scoped_fable", "weekly_scoped_opus"],
        )
        self.assertEqual(snap.limits["session"].percent, 12.5)
        self.assertEqual(snap.limits["weekly_scoped_fable"].object_slug, "weekly_fable")
        self.assertEqual(snap.limits["weekly_all"].object_slug, "weekly")
        self.assertEqual(snap.next_reset, datetime(2026, 11, 5, 14, tzinfo=UTC))

    def test_legacy_fallback(self):
        raw = {"five_hour": {"utilization": 30, "resets_at": "2026-11-05T13:00:00Z"},
               "seven_day": {"utilization": 60, "resets_at": None}}
        snap = usage.parse_usage(raw, NOW)
        self.assertEqual(snap.limits["session"].percent, 30)
        self.assertIsNone(snap.limits["weekly_all"].resets_at)

    def test_empty_response(self):
        snap = usage.parse_usage({}, NOW)
        self.assertEqual(snap.limits, {})
        self.assertIsNone(snap.extra)

    def test_spend_schema(self):
        raw = {"spend": {"enabled": True, "percent": 25,
                         "used": {"amount_minor": 1250, "currency": "USD", "exponent": 2},
                         "limit": {"amount_minor": 5000, "currency": "USD", "exponent": 2}}}
        extra = usage.parse_usage(raw, NOW).extra
        self.assertEqual((extra.used, extra.limit, extra.currency), (12.5, 50.0, "USD"))

    def test_translation_keys(self):
        self.assertEqual(limit().translation(), ("session", {}))
        self.assertEqual(limit("weekly_scoped", model="Fable").translation(), ("weekly_model", {"model": "Fable"}))
        self.assertEqual(limit("monthly_x").translation(), ("other", {"limit": "Monthly x"}))

    def test_levels_match_windows_app(self):
        self.assertEqual([usage.usage_level(p) for p in (49.9, 50, 79.9, 80)],
                         ["good", "warning", "warning", "critical"])


class ForecastTests(unittest.TestCase):
    def test_on_track(self):
        # 2,5 af 5 timer gået, 20 % brugt -> 40 % ved nulstilling.
        fc = usage.forecast(limit(percent=20, resets_in=timedelta(hours=2.5)), NOW)
        self.assertEqual(fc.projected_percent, 40)
        self.assertFalse(fc.over_pace)
        self.assertEqual(fc.elapsed_percent, 50)

    def test_over_pace_gives_time_of_hitting_limit(self):
        # 1 af 5 timer gået, 50 % brugt -> 100 % efter 2 timer i alt, dvs. om 1 time.
        fc = usage.forecast(limit(percent=50, resets_in=timedelta(hours=4)), NOW)
        self.assertTrue(fc.over_pace)
        self.assertEqual(fc.projected_percent, 250)
        self.assertEqual(fc.hits_limit_at, NOW + timedelta(hours=1))

    def test_too_early_in_window(self):
        fc = usage.forecast(limit(percent=30, resets_in=timedelta(hours=4, minutes=55)), NOW)
        self.assertFalse(fc.available)

    def test_limit_reached(self):
        fc = usage.forecast(limit(percent=100), NOW)
        self.assertTrue(fc.over_pace)

    def test_unknown_window_length(self):
        self.assertFalse(usage.forecast(limit("monthly_x", percent=50), NOW).available)


if __name__ == "__main__":
    unittest.main()
