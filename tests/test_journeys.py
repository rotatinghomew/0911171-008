import unittest

from attribution.journeys import JourneyBook


class JourneyTests(unittest.TestCase):
    def test_conversion_value_is_conserved_with_unattributed_value(self):
        book = JourneyBook()
        book.register("sale1", "p1", 100, 20)
        book.register("sale2", "p2", 100, 30)
        events = [
            {"event_id": "a", "person_id": "p1", "occurred_at": 80, "channel": "search"},
            {"event_id": "b", "person_id": "p1", "occurred_at": 90, "channel": "mail"},
            {"event_id": "future", "person_id": "p1", "occurred_at": 110, "channel": "social"},
        ]
        result = book.allocate(events, {}, 30)
        self.assertEqual(result["unattributed_value"], 30)
        self.assertEqual(result["value_by_rule"]["last"], {"mail": 20})
        for allocations in result["value_by_rule"].values():
            self.assertEqual(sum(allocations.values()) + result["unattributed_value"], 50)

    def test_conflicting_conversion_registration_is_rejected(self):
        book = JourneyBook()
        book.register("sale1", "p1", 100, 20)
        with self.assertRaises(ValueError):
            book.register("sale1", "p2", 100, 20)
