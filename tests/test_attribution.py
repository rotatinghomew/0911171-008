import unittest

from attribution.report import compare


class AttributionTests(unittest.TestCase):
    def test_duplicate_events_are_removed_before_allocation(self):
        event = {"event_id": "x", "channel": "mail", "occurred_at": 1}
        result = compare([event, event], {"mail": "email"})
        self.assertEqual(result["path_size"], 1)
        self.assertEqual(result["allocations"]["linear"], {"email": 1.0})

    def test_empty_path_has_no_credit(self):
        self.assertEqual(compare([], {})["allocations"]["last"], {})


if __name__ == "__main__":
    unittest.main()
