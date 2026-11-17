def normalize_path(events: list[dict], channel_map: dict[str, str]) -> list[dict]:
    normalized = []
    seen = set()
    for event in sorted(events, key=lambda item: (item["occurred_at"], item["event_id"])):
        if event["event_id"] in seen:
            continue
        seen.add(event["event_id"])
        normalized.append({**event, "channel": channel_map.get(event["channel"], event["channel"])})
    return normalized
