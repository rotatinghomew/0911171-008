import unittest

from attribution.journeys import JourneyBook
from attribution.settlement import CostLedger


class SettlementTests(unittest.TestCase):
    def test_rounding_conserves_cost_and_confirmation_is_idempotent(self):
        book = JourneyBook()
        book.register("c1", "p1", 10, 1)
        book.register("c2", "p2", 10, 1)
        events = [{"event_id": "a", "person_id": "p1", "occurred_at": 9, "channel": "mail"}]
        allocation = book.allocate(events, {}, 10)
        ledger = CostLedger()
        statement = ledger.settle("week1", allocation, "linear", 101)
        self.assertEqual(sum(statement["cents"].values()), 101)
        self.assertEqual(statement["cents"]["mail"], 51)
        self.assertEqual(ledger.settle("week1", allocation, "linear", 101), statement)
        with self.assertRaises(ValueError):
            ledger.settle("week1", allocation, "last", 101)

    def test_no_value_does_not_turn_into_arbitrary_cost_shares(self):
        with self.assertRaises(ValueError):
            CostLedger().settle("week1", {"value_by_rule": {"last": {}}, "unattributed_value": 0}, "last", 10)
