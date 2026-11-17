from copy import deepcopy

from .report import compare


class JourneyBook:
    def __init__(self) -> None:
        self.conversions: dict[str, dict] = {}

    def register(self, conversion_id: str, person_id: str, occurred_at: int, value: float) -> None:
        if value < 0:
            raise ValueError("转化价值不能为负")
        conversion = {"person_id": person_id, "occurred_at": occurred_at, "value": value}
        if conversion_id in self.conversions and self.conversions[conversion_id] != conversion:
            raise ValueError("转化编号已用于另一条记录")
        self.conversions[conversion_id] = conversion

    def allocate(self, events: list[dict], channel_map: dict[str, str], lookback: int) -> dict:
        if lookback <= 0:
            raise ValueError("回溯时长必须为正")
        totals: dict[str, dict[str, float]] = {"last": {}, "linear": {}}
        journeys = {}
        unattributed = 0.0
        for identifier, conversion in sorted(self.conversions.items()):
            path = [
                event for event in events
                if event["person_id"] == conversion["person_id"]
                and conversion["occurred_at"] - lookback <= event["occurred_at"] <= conversion["occurred_at"]
            ]
            result = compare(path, channel_map)
            journeys[identifier] = result
            if not result["path_size"]:
                unattributed += conversion["value"]
            for rule, allocations in result["allocations"].items():
                for channel, share in allocations.items():
                    totals[rule][channel] = totals[rule].get(channel, 0) + share * conversion["value"]
        return deepcopy({"journeys": journeys, "value_by_rule": totals, "unattributed_value": unattributed})
