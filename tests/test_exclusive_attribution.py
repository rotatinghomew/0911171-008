import unittest

from attribution.identity import IdentityGraph
from attribution.journeys import JourneyBook


def event(event_id, person_id, occurred_at, channel, received_at=None):
    return {
        "event_id": event_id,
        "person_id": person_id,
        "occurred_at": occurred_at,
        "channel": channel,
        "received_at": occurred_at if received_at is None else received_at,
    }


class ExclusiveAttributionTests(unittest.TestCase):
    def test_same_touch_not_consumed_by_two_conversions(self):
        book = JourneyBook()
        book.register("c0", "p1", 50, 5)   # 首购，没有路径
        book.register("c1", "p1", 100, 10)
        book.register("c2", "p1", 150, 10)
        events = [
            event("ad", "p1", 60, "search"),
            event("mail", "p1", 140, "email"),
        ]
        result = book.review(events, lookback=100, scope="repeat")
        journeys = result["journeys"]
        self.assertEqual(journeys["c1"]["allocations"]["last"]["by_touch"], {"ad": 1.0})
        self.assertEqual(journeys["c2"]["allocations"]["last"]["by_touch"], {"mail": 1.0})
        self.assertEqual(journeys["c2"]["allocations"]["last"]["skipped"]["ad"], "used")
        # 同一触点只出现在一笔已归属转化中。
        self.assertEqual(result["touches"]["ad"]["credited_conversions"], ["c1"])
        for rule in ("last", "linear"):
            self.assertEqual(result["value_by_rule"][rule]["search"], 10)
            self.assertEqual(result["value_by_rule"][rule]["email"], 10)
        self.assertEqual(result["unattributed_value"], 5)

    def test_linear_denominator_excludes_consumed_touches(self):
        book = JourneyBook()
        book.register("c0", "p1", 50, 5)
        book.register("c1", "p1", 100, 10)
        book.register("c2", "p1", 150, 20)
        events = [
            event("ad", "p1", 60, "search"),
            event("social", "p1", 140, "social"),
        ]
        result = book.review(events, lookback=100, scope="repeat", rules=("linear",))
        linear = result["journeys"]["c2"]["allocations"]["linear"]
        self.assertEqual(linear["by_touch"], {"social": 1.0})
        self.assertEqual(linear["skipped"]["ad"], "used")
        self.assertEqual(result["value_by_rule"]["linear"]["search"], 10)
        self.assertEqual(result["value_by_rule"]["linear"]["social"], 20)

    def test_first_purchase_scope_keeps_repeat_value_unattributed(self):
        book = JourneyBook()
        book.register("c1", "p1", 100, 10)
        book.register("c2", "p1", 120, 20)
        events = [event("ad", "p1", 90, "search"), event("mail", "p1", 115, "email")]
        result = book.review(events, lookback=100, scope="first")
        self.assertTrue(result["journeys"]["c1"]["attributed"])
        self.assertEqual(result["journeys"]["c1"]["allocations"]["last"]["by_touch"], {"ad": 1.0})
        self.assertEqual(result["journeys"]["c2"]["unattributed_reason"], "purchase_scope")
        self.assertEqual(result["unattributed_value"], 20)
        self.assertEqual(result["total_conversion_value"], 30)
        for rule, values in result["value_by_rule"].items():
            self.assertAlmostEqual(sum(values.values()) + result["unattributed_value"], 30)
            self.assertEqual(result["journeys"]["c1"]["allocations"][rule]["by_channel"], {"search": 1.0})

    def test_repeat_scope_requires_event_after_first_purchase(self):
        book = JourneyBook()
        book.register("c1", "p1", 100, 10)
        book.register("c2", "p1", 200, 10)
        events = [event("first-ad", "p1", 95, "search"), event("second-ad", "p1", 190, "social")]
        result = book.review(events, lookback=1000, scope="repeat")
        self.assertEqual(result["journeys"]["c2"]["allocations"]["last"]["by_touch"], {"second-ad": 1.0})
        self.assertEqual(result["journeys"]["c2"]["allocations"]["linear"]["by_touch"], {"second-ad": 1.0})

    def test_empty_path_is_not_direct_visit(self):
        book = JourneyBook()
        book.register("c1", "p1", 100, 10)
        result = book.review([], lookback=30, scope="first")
        detail = result["journeys"]["c1"]
        self.assertEqual(detail["unattributed_reason"], "empty_path")
        self.assertEqual(detail["path"], [])
        self.assertEqual(result["value_by_rule"]["last"], {})
        self.assertEqual(result["unattributed_value"], 10)

    def test_negative_value_still_rejected(self):
        book = JourneyBook()
        with self.assertRaises(ValueError):
            book.register("c1", "p1", 100, -1)


class CrossDeviceTests(unittest.TestCase):
    def test_confirmed_identity_merges_mobile_and_desktop_path(self):
        book = JourneyBook()
        book.register("c1", "desktop", 100, 10)
        identities = IdentityGraph()
        identities.link("phone", "desktop", "confirmed", 50)
        events = [
            event("mobile-ad", "phone", 80, "search"),
            event("desktop-ad", "desktop", 95, "email"),
        ]
        result = book.review(events, lookback=30, scope="first", identities=identities)
        self.assertEqual(result["journeys"]["c1"]["identity_key"], "desktop")
        self.assertEqual(
            result["journeys"]["c1"]["allocations"]["linear"]["by_touch"],
            {"desktop-ad": 0.5, "mobile-ad": 0.5},
        )
        self.assertEqual(result["journeys"]["c1"]["identity"]["confirmed_links"][0]["status"], "confirmed")

    def test_unconfirmed_identity_is_reported_not_silently_merged(self):
        book = JourneyBook()
        book.register("c1", "desktop", 100, 10)
        identities = IdentityGraph()
        identities.link("phone", "desktop", "proposed", 50)
        events = [event("mobile-ad", "phone", 80, "search")]
        result = book.review(events, lookback=30, scope="first", identities=identities)
        detail = result["journeys"]["c1"]
        self.assertEqual(detail["unattributed_reason"], "identity_unconfirmed")
        self.assertEqual(result["value_by_rule"]["last"], {})
        self.assertEqual(result["unattributed_value"], 10)
        self.assertEqual(detail["identity"]["proposed_links"][0]["status"], "proposed")

    def test_proposed_identity_can_be_reviewed_as_sensitivity_without_default_merge(self):
        book = JourneyBook()
        book.register("c1", "desktop", 100, 10)
        identities = IdentityGraph()
        identities.link("phone", "desktop", "proposed", 50)
        events = [event("mobile-ad", "phone", 80, "search")]
        default = book.review(events, lookback=30, scope="first", identities=identities)
        sensitive = book.review(
            events, lookback=30, scope="first", identities=identities, include_proposed=True
        )
        self.assertEqual(default["unattributed_value"], 10)
        self.assertEqual(sensitive["unattributed_value"], 0)
        self.assertEqual(
            sensitive["journeys"]["c1"]["allocations"]["last"]["by_touch"], {"mobile-ad": 1.0}
        )
        # 敏感性审阅的指纹不同于默认口径，避免被误当成已确认依据。
        self.assertNotEqual(default["fingerprint"], sensitive["fingerprint"])

    def test_rule_subset_does_not_change_ownership(self):
        book = JourneyBook()
        book.register("c0", "p1", 10, 1)
        book.register("c1", "p1", 100, 10)
        book.register("c2", "p1", 200, 10)
        events = [
            event("ad", "p1", 60, "search"),
            event("mail", "p1", 90, "email"),
            event("site", "p1", 150, "social"),
        ]
        both = book.review(events, lookback=100, scope="repeat", rules=("last", "linear"))
        only_last = book.review(events, lookback=100, scope="repeat", rules=("last",))
        self.assertEqual(both["value_by_rule"]["last"], only_last["value_by_rule"]["last"])
        # 归属（候选路径与占用）与规则子集无关；只有计价会随规则不同。
        for event_id in ("ad", "mail", "site"):
            self.assertEqual(
                both["touches"][event_id]["conversions"],
                only_last["touches"][event_id]["conversions"],
            )
        self.assertEqual(
            [touch["event_id"] for touch in only_last["journeys"]["c2"]["path"]],
            ["site"],
        )
        # c1 占用了 ad 与 mail；c2 只能看到窗口内的 site。
        self.assertEqual(
            [touch["event_id"] for touch in only_last["journeys"]["c1"]["path"]],
            ["ad", "mail"],
        )
        self.assertEqual(only_last["touches"]["ad"]["credited_conversions"], [])
        # 同一结果内，每个触点的价值最多归给一笔转化。
        for touch in both["touches"].values():
            owners = touch["credited_conversions"]
            self.assertEqual(len(owners), len(set(owners)))
            self.assertLessEqual(len(owners), 1)

    def test_candidate_path_and_credited_touches_are_reported_separately(self):
        book = JourneyBook()
        book.register("c0", "p1", 50, 5)
        book.register("c1", "p1", 100, 10)
        book.register("c2", "p1", 150, 20)
        events = [event("ad", "p1", 60, "search"), event("mail", "p1", 140, "email")]
        result = book.review(events, lookback=100, scope="repeat")
        # ad 同时是 c1、c2 的候选触点，但只对 c1 产生价值。
        self.assertEqual(result["touches"]["ad"]["conversions"], ["c1", "c2"])
        self.assertEqual(result["touches"]["ad"]["credited_conversions"], ["c1"])
        self.assertEqual(result["journeys"]["c2"]["allocations"]["last"]["skipped"]["ad"], "used")

    def test_rejected_identity_restores_old_attribution_but_keeps_reviewable_links(self):
        book = JourneyBook()
        book.register("c1", "desktop", 30, 10)
        identities = IdentityGraph()
        identities.link("phone", "desktop", "confirmed", 10)
        identities.link("phone", "desktop", "rejected", 40)
        events = [event("mobile-ad", "phone", 20, "search")]
        # 当前状态为否决：手机事件不并入。
        current = book.review(events, lookback=30, scope="first", identities=identities)
        self.assertEqual(current["journeys"]["c1"]["unattributed_reason"], "empty_path")
        # 按周报时点还原：关联当时仍为确认。
        restored = book.review(events, lookback=30, scope="first", identities=identities, as_of=35)
        self.assertEqual(restored["journeys"]["c1"]["allocations"]["last"]["by_touch"], {"mobile-ad": 1.0})
        self.assertEqual(restored["unattributed_value"], 0)
        # 当前审阅仍能看到否决记录，不会把历史抹掉。
        self.assertEqual(current["journeys"]["c1"]["identity"]["rejected_links"][0]["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
