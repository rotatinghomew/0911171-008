import unittest

from attribution.journeys import JourneyBook
from attribution.settlement import CostLedger


def event(event_id, person_id, occurred_at, channel):
    return {"event_id": event_id, "person_id": person_id, "occurred_at": occurred_at, "channel": channel}


class SettlementRevisionTests(unittest.TestCase):
    def _review(self, *, channel="mail", value=1):
        book = JourneyBook()
        book.register("c1", "p1", 10, value)
        book.register("c2", "p2", 10, value)
        return book.review([event("a", "p1", 9, channel)], lookback=10, scope="first")

    def test_revision_adjusts_without_overwriting_original(self):
        review = self._review()
        ledger = CostLedger()
        original = ledger.settle("week1", review, "linear", 101)
        self.assertEqual(original["cents"], {"mail": 51, "unattributed": 50})
        revised_review = review
        audit = ledger.revise("week1", revised_review, "linear", 201, reason="补记互动")
        self.assertEqual(audit["original"], original)
        self.assertEqual(audit["balance"], {"mail": 101, "unattributed": 100})
        self.assertEqual(audit["adjustments"][0]["cents"], {"mail": 50, "unattributed": 50})
        self.assertEqual(sum(audit["balance"].values()), 201)

    def test_duplicate_revision_is_not_posted_twice(self):
        review = self._review()
        ledger = CostLedger()
        ledger.settle("week1", review, "linear", 100)
        first = ledger.revise("week1", review, "linear", 150, reason="补记")
        second = ledger.revise("week1", review, "linear", 150, reason="重复确认")
        self.assertEqual(first["balance"], second["balance"])
        self.assertEqual(len(ledger.adjustments("week1")), 1)

    def test_revision_can_restore_old_basis_for_audit(self):
        book = JourneyBook()
        book.register("c1", "p1", 10, 1)
        book.register("c2", "p2", 10, 1)
        events = [event("a", "p1", 9, "mail")]
        ledger = CostLedger()
        old_review = book.review(events, lookback=10, scope="first")
        ledger.settle("week1", old_review, "linear", 100)
        # 跨周补记：事件接收时间在周报之后。
        late = {"event_id": "b", "person_id": "p1", "occurred_at": 9, "channel": "search", "received_at": 20}
        new_review = book.review(events + [late], lookback=10, scope="first")
        self.assertEqual(new_review["journeys"]["c1"]["allocations"]["linear"]["by_touch"], {"a": 0.5, "b": 0.5})
        audit = ledger.revise("week1", new_review, "linear", 100, reason="跨周补记")
        self.assertEqual(audit["balance"], {"mail": 25, "search": 25, "unattributed": 50})
        # 旧依据仍在 audit 中可查。
        self.assertEqual(audit["original"]["basis"], old_review)
        # 按旧时点重新审阅可以还原当时依据（晚到事件被排除）。
        restored = book.review(events + [late], lookback=10, scope="first", as_of=15)
        self.assertEqual([item["event_id"] for item in restored["recorded_later_events"]], ["b"])
        self.assertEqual(restored["fingerprint"], old_review["fingerprint"])

    def test_same_statement_id_still_cannot_be_overwritten(self):
        ledger = CostLedger()
        review = self._review()
        ledger.settle("week1", review, "linear", 100)
        with self.assertRaises(ValueError):
            ledger.settle("week1", review, "linear", 200)

    def test_zero_delta_revision_does_not_post_empty_entry(self):
        review = self._review()
        ledger = CostLedger()
        ledger.settle("week1", review, "linear", 100)
        audit = ledger.revise("week1", review, "linear", 100, reason="仅复核")
        self.assertEqual(audit["adjustments"], [])
        self.assertEqual(audit["balance"], audit["original"]["cents"])

    def test_channel_that_loses_all_share_is_zeroed_in_adjustment(self):
        book = JourneyBook()
        book.register("c1", "p1", 10, 1)
        book.register("c2", "p2", 10, 1)
        review = book.review(
            [event("a", "p1", 9, "mail"), event("b", "p2", 9, "mail")],
            lookback=10,
            scope="first",
        )
        ledger = CostLedger()
        ledger.settle("week1", review, "linear", 100)
        moved = {
            "value_by_rule": {"linear": {"search": 2}},
            "unattributed_value": 0,
        }
        audit = ledger.revise("week1", moved, "linear", 100, reason="渠道重分类")
        self.assertEqual(audit["balance"]["mail"], 0)
        self.assertEqual(audit["balance"]["search"], 100)
        self.assertEqual(audit["original"]["cents"]["mail"], 100)

    def test_revision_requires_original_statement(self):
        with self.assertRaises(ValueError):
            CostLedger().revise("missing", self._review(), "linear", 100)

    def test_settlement_states_rule_share_is_not_incremental(self):
        ledger = CostLedger()
        statement = ledger.settle("week1", self._review(), "linear", 100)
        self.assertFalse(statement["interpretation"]["incremental"])
        self.assertEqual(statement["interpretation"]["basis"], "rule_share")


if __name__ == "__main__":
    unittest.main()
