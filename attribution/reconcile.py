"""旧审阅与新审阅之间的差异解释。

比较的是具体路径变化，而不是只看渠道合计：

* 事件进入或离开某笔转化的路径；
* 事件改归另一笔转化（触点占用或身份变化）；
* 渠道重分类导致同一事件的渠道改变；
* 未归因原因的变化。

渠道合计作为汇总保留，便于核对，但不能单独说明差异来源。
"""

from __future__ import annotations

from copy import deepcopy


def _interpretation() -> dict:
    return {
        "basis": "rule_share",
        "incremental": False,
        "note": "份额差异来自路径、身份或渠道口径变化，不代表增量因果效果。",
    }


def _journey_path_index(review: dict) -> dict[str, list[str]]:
    return {
        identifier: [touch["event_id"] for touch in detail.get("path", [])]
        for identifier, detail in review.get("journeys", {}).items()
    }


def _touch_owner(review: dict) -> dict[str, list[str]]:
    """事件编号到实际获得该触点份额的转化编号。

    ``journeys[*].path`` 只说明触点出现在哪笔转化的候选路径中；只有
    ``touches[*].credited_conversions`` 才说明价值实际归给了谁。两者必须
    分开，否则被跳过的触点会被误报为重复归属。
    """

    owners: dict[str, list[str]] = {}
    for event_id, touch in review.get("touches", {}).items():
        owners[event_id] = list(touch.get("credited_conversions", []))
    return owners


def explain(old: dict, new: dict) -> dict:
    old_paths = _journey_path_index(old)
    new_paths = _journey_path_index(new)
    old_owners = _touch_owner(old)
    new_owners = _touch_owner(new)
    old_touches = old.get("touches", {})
    new_touches = new.get("touches", {})

    journey_changes = []
    for identifier in sorted(set(old_paths) | set(new_paths)):
        old_path = old_paths.get(identifier, [])
        new_path = new_paths.get(identifier, [])
        old_detail = old.get("journeys", {}).get(identifier, {})
        new_detail = new.get("journeys", {}).get(identifier, {})
        added = [event for event in new_path if event not in old_path]
        removed = [event for event in old_path if event not in new_path]
        old_owner = {event: old_owners.get(event, []) for event in old_path}
        new_owner = {event: new_owners.get(event, []) for event in new_path}
        ownership = {
            event: {"before": old_owner.get(event, []), "after": new_owner.get(event, [])}
            for event in sorted(set(old_path) | set(new_path))
            if old_owner.get(event, []) != new_owner.get(event, [])
        }
        channel_changes = []
        for event in sorted(set(old_path) | set(new_path)):
            old_touch = old_touches.get(event, {})
            new_touch = new_touches.get(event, {})
            if old_touch and new_touch and old_touch.get("channel") != new_touch.get("channel"):
                channel_changes.append(
                    {
                        "event_id": event,
                        "before": old_touch.get("channel"),
                        "after": new_touch.get("channel"),
                    }
                )
        old_reason = old_detail.get("unattributed_reason")
        new_reason = new_detail.get("unattributed_reason")
        if (
            added
            or removed
            or ownership
            or channel_changes
            or old_reason != new_reason
            or old_detail.get("purchase") != new_detail.get("purchase")
            or old_detail.get("value") != new_detail.get("value")
        ):
            journey_changes.append(
                {
                    "conversion_id": identifier,
                    "path_added": added,
                    "path_removed": removed,
                    "ownership_changed": ownership,
                    "channel_changed": channel_changes,
                    "unattributed_before": old_reason,
                    "unattributed_after": new_reason,
                    "purchase_before": old_detail.get("purchase"),
                    "purchase_after": new_detail.get("purchase"),
                }
            )

    channel_deltas = {}
    for rule in sorted(set(old.get("value_by_rule", {})) | set(new.get("value_by_rule", {}))):
        before = old.get("value_by_rule", {}).get(rule, {})
        after = new.get("value_by_rule", {}).get(rule, {})
        channel_deltas[rule] = {
            channel: round(after.get(channel, 0.0) - before.get(channel, 0.0), 10)
            for channel in sorted(set(before) | set(after))
            if abs(after.get(channel, 0.0) - before.get(channel, 0.0)) > 1e-12
        }

    identity_changed = old.get("identity_fingerprint") != new.get("identity_fingerprint")
    channel_map_changed = old.get("channel_map") != new.get("channel_map")

    return deepcopy(
        {
            "journey_changes": journey_changes,
            "channel_deltas": channel_deltas,
            "unattributed_before": old.get("unattributed_value", 0),
            "unattributed_after": new.get("unattributed_value", 0),
            "unattributed_delta": round(
                new.get("unattributed_value", 0) - old.get("unattributed_value", 0), 10
            ),
            "identity_changed": identity_changed,
            "channel_map_changed": channel_map_changed,
            "summary": {
                "conversions_changed": len(journey_changes),
                "events_added": sum(len(item["path_added"]) for item in journey_changes),
                "events_removed": sum(len(item["path_removed"]) for item in journey_changes),
                "events_reclassified": sum(len(item["channel_changed"]) for item in journey_changes),
            },
            "interpretation": _interpretation(),
        }
    )
