from .journeys import JourneyBook
from .settlement import CostLedger


def main() -> None:
    path = [{"event_id": "a", "person_id": "p1", "channel": "email", "occurred_at": 1}, {"event_id": "b", "person_id": "p1", "channel": "search", "occurred_at": 2}]
    book = JourneyBook()
    book.register("signup1", "p1", 3, 10)
    book.register("signup2", "p2", 3, 10)
    allocation = book.allocate(path, {}, 10)
    print(allocation)
    print(CostLedger().settle("november", allocation, "linear", 10001))


if __name__ == "__main__":
    main()
