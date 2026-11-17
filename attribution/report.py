from .paths import normalize_path
from .rules import credit


def compare(events: list[dict], channel_map: dict[str, str], rules: tuple[str, ...] = ("last", "linear")) -> dict:
    path = normalize_path(events, channel_map)
    return {"path_size": len(path), "allocations": {rule: credit(path, rule) for rule in rules}}
