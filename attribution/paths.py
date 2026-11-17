"""路径整理。

原有的 ``normalize_path`` 只做事件去重与渠道别名映射；审阅层还要按身份关联
解析事件归属、按审阅时点还原渠道重分类，因此复用同一个去重顺序。
"""

from __future__ import annotations


def normalize_path(events: list[dict], channel_map: dict[str, str]) -> list[dict]:
    normalized = []
    seen = set()
    for event in sorted(events, key=lambda item: (item["occurred_at"], item["event_id"])):
        if event["event_id"] in seen:
            continue
        seen.add(event["event_id"])
        normalized.append({**event, "channel": channel_map.get(event["channel"], event["channel"])})
    return normalized


def deduplicate(events: list[dict]) -> list[dict]:
    """按事件编号去重，保留最早到达排序中的第一条。"""

    result = []
    seen = set()
    for event in sorted(events, key=lambda item: (item["occurred_at"], item["event_id"])):
        if event["event_id"] in seen:
            continue
        seen.add(event["event_id"])
        result.append(dict(event))
    return result
