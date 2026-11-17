from .identity import IdentityGraph
from .journeys import JourneyBook
from .reconcile import explain
from .settlement import CostLedger


def main() -> None:
    events = [
        {"event_id": "ad", "person_id": "phone", "channel": "search", "occurred_at": 1},
        {"event_id": "mail", "person_id": "desktop", "channel": "email", "occurred_at": 4},
        {"event_id": "social", "person_id": "phone", "channel": "social", "occurred_at": 9},
    ]
    book = JourneyBook()
    book.register("signup", "desktop", 5, 10)
    book.register("repurchase", "desktop", 10, 10)
    identities = IdentityGraph()
    identities.link("phone", "desktop", "confirmed", 2)

    first = book.review(events, lookback=10, scope="first", identities=identities)
    repeat = book.review(events, lookback=10, scope="repeat", identities=identities)
    print("first purchase:", first["value_by_rule"]["last"], first["unattributed_value"])
    print("repeat purchase:", repeat["value_by_rule"]["last"], repeat["unattributed_value"])
    for item in explain(first, repeat)["journey_changes"]:
        print("changed:", item["conversion_id"], item["path_added"], item["unattributed_after"])

    ledger = CostLedger()
    ledger.settle("week-45", first, "last", 10000)
    audit = ledger.revise("week-45", repeat, "last", 10000, reason="复购口径复核")
    print("original:", audit["original"]["cents"])
    print("adjustments:", audit["adjustments"][0]["cents"])
    print("balance:", audit["balance"])


if __name__ == "__main__":
    main()
