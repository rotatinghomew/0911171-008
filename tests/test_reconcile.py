import unittest

from attribution.journeys import JourneyBook
from attribution.reconcile import explain


def event(event_id, person_id, occurred_at, channel, received_at=None):
    return {
        "event_id": event_id,
        "person_id": person_id,
        "occurred_at": occurred_at,
        "channel": channel,
        "received_at": occurred_at if received_at is None else received_at,
    }


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.book = JourneyBook()
        self.book.register("c1", "p1", 100, 10)
        self.book.register("c2", "p1", 120, 10)
        self.events = [
            event("ad", "p1", 90, "search"),
            event("mail", "p1", 110, "email"),
        ]

    def test_difference_is_explained_by_path_not_just_channel_totals(self):
        old = self.book.review(self.events, lookback=100, scope="repeat")
        self.book.record_channel_change(130, {"email": "lifecycle"})
        new = self.book.review(self.events, lookback=100, scope="repeat")
        diff = explain(old, new)
        self.assertTrue(diff["channel_map_changed"])
        self.assertEqual(diff["channel_deltas"]["last"], {"email": -10, "lifecycle": 10})
        by_conversion = {item["conversion_id"]: item for item in diff["journey_changes"]}
        self.assertEqual(by_conversion["c2"]["channel_changed"][0]["event_id"], "mail")
        self.assertEqual(by_conversion["c2"]["channel_changed"][0]["before"], "email")
        self.assertEqual(by_conversion["c2"]["channel_changed"][0]["after"], "lifecycle")
        # 同一路径、同一触点，只是渠道口径变化：路径本身没有增删。
        self.assertEqual(by_conversion["c2"]["path_added"], [])
        self.assertEqual(by_conversion["c2"]["path_removed"], [])

    def test_late_recorded_event_is_reported_as_received_after_review(self):
        old = self.book.review(self.events, lookback=100, scope="repeat")
        self.events.append(event("late", "p1", 115, "social", received_at=200))
        new = self.book.review(self.events, lookback=100, scope="repeat")
        self.assertEqual(new["journeys"]["c2"]["allocations"]["last"]["by_touch"], {"late": 1.0})
        restored = self.book.review(self.events, lookback=100, scope="repeat", as_of=150)
        self.assertEqual(restored["journeys"]["c2"]["allocations"]["last"]["by_touch"], {"mail": 1.0})
        self.assertEqual([item["event_id"] for item in restored["recorded_later_events"]], ["late"])
        self.assertEqual(restored["fingerprint"], old["fingerprint"])
        diff = explain(old, new)
        changed = {item["conversion_id"]: item for item in diff["journey_changes"]}
        self.assertEqual(changed["c2"]["path_added"], ["late"])
        self.assertEqual(changed["c2"]["path_removed"], [])
        # 差异解释到具体路径变化：末触点由 mail 转为 late。
        self.assertEqual(diff["channel_deltas"]["last"], {"email": -10, "social": 10})

    def test_ownership_change_is_explained_when_scope_switches(self):
        old = self.book.review(self.events, lookback=100, scope="first")
        new = self.book.review(self.events, lookback=100, scope="repeat")
        diff = explain(old, new)
        changed = {item["conversion_id"]: item for item in diff["journey_changes"]}
        self.assertEqual(changed["c1"]["unattributed_before"], None)
        self.assertEqual(changed["c1"]["unattributed_after"], "purchase_scope")
        self.assertEqual(changed["c2"]["unattributed_before"], "purchase_scope")
        self.assertEqual(changed["c2"]["unattributed_after"], None)
        self.assertEqual(changed["c2"]["path_added"], ["mail"])

    def test_conversion_registered_later_is_excluded_from_old_review(self):
        later = JourneyBook()
        later.register("c1", "p1", 100, 10)
        old = later.review([], lookback=30, scope="first")
        later.register("c2", "p1", 200, 15, recorded_at=300)
        new = later.review([], lookback=30, scope="first", as_of=250)
        self.assertEqual([item["conversion_id"] for item in new["excluded_conversions"]], ["c2"])
        self.assertEqual(new["total_conversion_value"], 10)
        self.assertEqual(new["fingerprint"], old["fingerprint"])
        current = later.review([], lookback=30, scope="first")
        self.assertEqual(current["total_conversion_value"], 25)

    def test_channel_change_can_be_rolled_back_to_previous_basis(self):
        book = JourneyBook()
        book.register("c1", "p1", 100, 10)
        events = [event("a", "p1", 90, "mail")]
        book.record_channel_change(120, {"mail": "email"})
        book.record_channel_change(140, {"email": "lifecycle"})
        old = book.review(events, lookback=30, scope="first")
        current = book.review(events, lookback=30, scope="first", as_of=130)
        self.assertEqual(old["value_by_rule"]["last"], {"lifecycle": 10})
        self.assertEqual(current["value_by_rule"]["last"], {"email": 10})
        diff = explain(old, current)
        self.assertTrue(diff["channel_map_changed"])
        self.assertEqual(diff["channel_deltas"]["last"], {"email": 10, "lifecycle": -10})

    def test_incremental_claim_is_not_made(self):
        review = self.book.review(self.events, lookback=100, scope="repeat")
        diff = explain(review, review)
        self.assertFalse(diff["interpretation"]["incremental"])
        self.assertEqual(diff["summary"]["conversions_changed"], 0)


if __name__ == "__main__":
    unittest.main()
