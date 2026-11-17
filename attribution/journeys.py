"""转化台账与归因审阅。

原有 ``JourneyBook`` 按每笔转化独立截取路径，账本之间没有身份拼接，也不
记录跨转化的触点占用。为了支持复购与跨设备审阅，这里在同一份转化总体、
回溯范围和渠道口径下重新计算，并保留逐触点去向。原有 ``allocate`` 仍按
旧语义工作，避免改变已有周报的计算方式。
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from .identity import IdentityGraph
from .report import compare
from .rules import VALID_PURCHASE_SCOPES, VALID_RULES, credit_journey, eligible


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:16]


class JourneyBook:
    def __init__(self) -> None:
        self.conversions: dict[str, dict] = {}
        self._channel_changes: list[dict] = []
        self._channel_sequence = 0

    def register(
        self,
        conversion_id: str,
        person_id: str,
        occurred_at: int,
        value: float,
        *,
        recorded_at: int | None = None,
    ) -> None:
        if value < 0:
            raise ValueError("转化价值不能为负")
        conversion = {
            "person_id": person_id,
            "occurred_at": occurred_at,
            "value": value,
            "recorded_at": occurred_at if recorded_at is None else recorded_at,
        }
        if conversion_id in self.conversions and self.conversions[conversion_id] != conversion:
            raise ValueError("转化编号已用于另一条记录")
        self.conversions[conversion_id] = conversion

    def record_channel_change(
        self,
        at: int,
        mapping: dict[str, str],
        *,
        change_id: str | None = None,
        reason: str | None = None,
    ) -> str:
        """记录一次渠道口径调整，审阅时可按 ``as_of`` 还原调整前的口径。"""

        if not isinstance(at, int):
            raise ValueError("渠道调整时间必须为整数")
        if not mapping:
            raise ValueError("渠道调整不能为空")
        for source, target in mapping.items():
            if not isinstance(source, str) or not isinstance(target, str) or not source or not target:
                raise ValueError("渠道名称必须为非空字符串")
        self._channel_sequence += 1
        if change_id is None:
            change_id = f"channel-change-{self._channel_sequence}"
        if any(change["change_id"] == change_id for change in self._channel_changes):
            raise ValueError("渠道调整编号已存在")
        self._channel_changes.append(
            {
                "change_id": change_id,
                "at": at,
                "mapping": dict(mapping),
                "reason": reason,
                "sequence": self._channel_sequence,
            }
        )
        return change_id

    def channel_map_at(self, base: dict[str, str] | None, as_of: int | None = None) -> dict[str, str]:
        """按审阅时点组合渠道别名。``base`` 是最早的口径。

        调整按时间顺序叠加：既可以直接改写某个原始渠道，也可以把上一次
        调整产生的新渠道继续重分类（``mail→email`` 后再 ``email→lifecycle``，
        原始 ``mail`` 事件最终归入 ``lifecycle``）。
        """

        result = dict(base or {})
        changes = [
            change for change in self._channel_changes
            if as_of is None or change["at"] <= as_of
        ]
        changes.sort(key=lambda change: (change["at"], change["sequence"]))
        for change in changes:
            mapping = change["mapping"]
            result = {
                source: mapping.get(target, target)
                for source, target in result.items()
            }
            result.update(mapping)
        # 只保留发生变化的来源，避免把恒等映射混入渠道口径。
        return {source: target for source, target in result.items() if source != target}

    def allocate(self, events: list[dict], channel_map: dict[str, str], lookback: int) -> dict:
        """原有口径：每笔转化独立截取路径，不做跨设备身份拼接或触点占用。"""

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

    def review(
        self,
        events: list[dict],
        *,
        lookback: int,
        scope: str = "repeat",
        rules: tuple[str, ...] = ("last", "linear"),
        as_of: int | None = None,
        identities: IdentityGraph | None = None,
        channel_map: dict[str, str] | None = None,
        include_proposed: bool = False,
    ) -> dict:
        """在统一口径下审阅每笔转化、触点和身份关联。

        ``scope`` 为 ``first`` 时只归属首购，``repeat`` 时只归属复购；
        另一种转化的价值留在未归因中，并在 ``unattributed_by_reason`` 说明。
        ``as_of`` 同时约束身份关联状态、渠道口径、事件接收时间和转化登记
        时间，用于还原旧周报的依据。确认的身份关联才参与归属；``proposed``
        关联仅在身份说明中列出，不会悄悄改变份额。
        """

        if lookback <= 0:
            raise ValueError("回溯时长必须为正")
        if scope not in VALID_PURCHASE_SCOPES:
            raise ValueError(f"不支持的购买口径: {scope}")
        if not rules:
            raise ValueError("至少需要一种归因规则")
        for rule in rules:
            if rule not in VALID_RULES:
                raise ValueError(f"unsupported attribution rule: {rule}")

        identity_graph = identities if identities is not None else IdentityGraph()
        state = identity_graph.state(as_of, include_proposed=include_proposed)
        potential_state = identity_graph.state(as_of, include_proposed=True)
        effective_map = self.channel_map_at(channel_map, as_of)

        # 同一事件编号只保留一条，避免同一触点在台账内凭空增殖。
        deduped: dict[str, dict] = {}
        for event in sorted(events, key=lambda item: (item["occurred_at"], item["event_id"])):
            if event["event_id"] in deduped:
                continue
            received_at = event.get("received_at", event["occurred_at"])
            deduped[event["event_id"]] = {
                **event,
                "received_at": received_at,
                "channel": event["channel"],
            }

        recorded_later: list[dict] = []
        visible_events: list[dict] = []
        for event in deduped.values():
            if as_of is not None and event["received_at"] > as_of:
                recorded_later.append(
                    {
                        "event_id": event["event_id"],
                        "received_at": event["received_at"],
                        "reason": "received_later",
                    }
                )
                continue
            visible_events.append(event)
        visible_events.sort(key=lambda item: (item["occurred_at"], item["event_id"]))

        included_conversions: dict[str, dict] = {}
        excluded_conversions: list[dict] = []
        for identifier, conversion in sorted(self.conversions.items()):
            if as_of is not None and conversion["recorded_at"] > as_of:
                excluded_conversions.append(
                    {
                        "conversion_id": identifier,
                        "recorded_at": conversion["recorded_at"],
                        "reason": "recorded_later",
                    }
                )
                continue
            included_conversions[identifier] = conversion

        total_conversion_value = sum(item["value"] for item in included_conversions.values())

        # 身份确认后的首购边界：同一身份内按转化时间、编号稳定取最早一笔。
        first_purchase: dict[str, str] = {}
        identity_key_by_conversion: dict[str, str] = {}
        for identifier, conversion in sorted(
            included_conversions.items(),
            key=lambda item: (item[1]["occurred_at"], item[0]),
        ):
            key = state.resolve(conversion["person_id"])
            identity_key_by_conversion[identifier] = key
            first_purchase.setdefault(key, identifier)
        first_purchase_by_conversion = {
            identifier: first_purchase[key]
            for identifier, key in identity_key_by_conversion.items()
        }

        # 先到先得：更早的已归属转化占用其窗口内全部候选触点；同一时刻按
        # 转化编号稳定排序。占用跨规则共享，保证同一触点的价值不会在两笔
        # 转化里重复消耗，未归因也保持单一口径。
        processing_order = sorted(
            included_conversions,
            key=lambda identifier: (
                included_conversions[identifier]["occurred_at"],
                identifier,
            ),
        )
        used_events: dict[str, str] = {}
        journey_details: dict[str, dict] = {}
        value_by_rule: dict[str, dict[str, float]] = {rule: {} for rule in rules}
        unattributed_by_reason: dict[str, float] = {}
        touch_register: dict[str, dict] = {}

        def add_unattributed(reason: str, value: float) -> None:
            unattributed_by_reason[reason] = unattributed_by_reason.get(reason, 0.0) + value

        for identifier in processing_order:
            conversion = included_conversions[identifier]
            first_id = first_purchase_by_conversion[identifier]
            purchase = "first" if first_id == identifier else "repeat"
            target = (
                (scope == "first" and purchase == "first")
                or (scope == "repeat" and purchase == "repeat")
            )
            identity_key = identity_key_by_conversion[identifier]
            confirmed_links = state.links_touching(conversion["person_id"], ("confirmed",))
            proposed_links = state.links_touching(conversion["person_id"], ("proposed",))
            rejected_links = state.links_touching(conversion["person_id"], ("rejected",))
            detail = {
                "person_id": conversion["person_id"],
                "identity_key": identity_key,
                "occurred_at": conversion["occurred_at"],
                "recorded_at": conversion["recorded_at"],
                "value": conversion["value"],
                "purchase": purchase,
                "first_purchase_id": first_id,
                "target": target,
                "attributed": False,
                "unattributed_value": conversion["value"],
                "unattributed_reason": None,
                "path": [],
                "allocations": {},
                "identity": {
                    "confirmed_links": confirmed_links,
                    "proposed_links": proposed_links,
                    "rejected_links": rejected_links,
                },
            }

            if not target:
                detail["unattributed_reason"] = "purchase_scope"
                add_unattributed("purchase_scope", conversion["value"])
                journey_details[identifier] = detail
                continue

            component = state.component(conversion["person_id"])
            first_conversion = included_conversions[first_id]
            path_events = []
            for event in visible_events:
                if state.resolve(event["person_id"]) not in component:
                    continue
                if not eligible(
                    event["occurred_at"],
                    conversion["occurred_at"],
                    first_conversion["occurred_at"],
                    lookback,
                    scope,
                ):
                    continue
                path_events.append(
                    {
                        "event_id": event["event_id"],
                        "person_id": event["person_id"],
                        "occurred_at": event["occurred_at"],
                        "channel": effective_map.get(event["channel"], event["channel"]),
                        "received_at": event["received_at"],
                    }
                )

            path_events.sort(key=lambda item: (item["occurred_at"], item["event_id"]))
            if not path_events:
                # 缺失路径不等于直接访问：只记录为未归因，不虚构渠道。
                if self._has_unconfirmed_events(
                    conversion["person_id"], conversion["occurred_at"],
                    visible_events, state, potential_state,
                    lookback, scope, first_conversion, component,
                ):
                    detail["unattributed_reason"] = "identity_unconfirmed"
                    add_unattributed("identity_unconfirmed", conversion["value"])
                else:
                    detail["unattributed_reason"] = "empty_path"
                    add_unattributed("empty_path", conversion["value"])
                journey_details[identifier] = detail
                continue

            touches = []
            for event in path_events:
                used_by = used_events.get(event["event_id"])
                touches.append(
                    {
                        **event,
                        "in_scope": True,
                        "available": used_by is None,
                        "used_by": used_by,
                    }
                )
                touch_register.setdefault(
                    event["event_id"],
                    {
                        "event_id": event["event_id"],
                        "channel": event["channel"],
                        "occurred_at": event["occurred_at"],
                        "person_id": event["person_id"],
                        "conversions": [],
                        "credited_conversions": [],
                        "value_by_rule": {rule: 0.0 for rule in rules},
                    },
                )
                if identifier not in touch_register[event["event_id"]]["conversions"]:
                    touch_register[event["event_id"]]["conversions"].append(identifier)

            available_touches = [touch for touch in touches if touch["available"]]
            if not available_touches:
                detail["path"] = path_events
                detail["unattributed_reason"] = "all_touches_used"
                add_unattributed("all_touches_used", conversion["value"])
                journey_details[identifier] = detail
                continue

            allocations = {}
            for rule in rules:
                result = credit_journey(touches, rule)
                allocations[rule] = {
                    "by_channel": dict(result["by_channel"]),
                    "by_touch": dict(result["by_touch"]),
                    "value_by_touch": {
                        event_id: share * conversion["value"]
                        for event_id, share in result["by_touch"].items()
                    },
                    "skipped": dict(result["skipped"]),
                }
                for channel, share in result["by_channel"].items():
                    value_by_rule[rule][channel] = value_by_rule[rule].get(channel, 0.0) + share * conversion["value"]
                for event_id, share in result["by_touch"].items():
                    touch_register[event_id]["value_by_rule"][rule] += share * conversion["value"]
                    if identifier not in touch_register[event_id]["credited_conversions"]:
                        touch_register[event_id]["credited_conversions"].append(identifier)

            # 归属与规则无关：本笔转化占用其窗口内全部候选触点，后续转化
            # 不再重复计价。这样无论只请求 last 还是比较多种规则，同一触点
            # 都归给同一笔转化，规则差异只体现在分配方式上。
            for touch in available_touches:
                used_events.setdefault(touch["event_id"], identifier)

            detail.update(
                {
                    "attributed": True,
                    "unattributed_value": 0.0,
                    "path": [
                        {key: value for key, value in touch.items() if key != "available"}
                        for touch in touches
                    ],
                    "allocations": allocations,
                    "identity": {
                        "confirmed_links": confirmed_links,
                        "proposed_links": proposed_links,
                        "rejected_links": rejected_links,
                    },
                }
            )
            journey_details[identifier] = detail

        unattributed_value = sum(unattributed_by_reason.values())
        for rule in rules:
            allocated = sum(value_by_rule[rule].values())
            if abs(allocated + unattributed_value - total_conversion_value) > 1e-9:
                raise AssertionError("转化价值未守恒")

        snapshot = {
            "params": {
                "lookback": lookback,
                "scope": scope,
                "rules": list(rules),
                "as_of": as_of,
                "include_proposed": include_proposed,
            },
            "channel_map": dict(effective_map),
            "channel_changes": [
                deepcopy(change)
                for change in sorted(self._channel_changes, key=lambda item: (item["at"], item["sequence"]))
                if as_of is None or change["at"] <= as_of
            ],
            "identity_fingerprint": state.fingerprint(),
            "identity_links": state.links(),
            "potential_identity_links": potential_state.links(),
            "journeys": journey_details,
            "value_by_rule": {rule: dict(sorted(values.items())) for rule, values in value_by_rule.items()},
            "unattributed_value": unattributed_value,
            "unattributed_by_reason": dict(sorted(unattributed_by_reason.items())),
            "total_conversion_value": total_conversion_value,
            "touches": {
                key: {
                    **value,
                    "conversions": list(value["conversions"]),
                    "credited_conversions": list(value["credited_conversions"]),
                    "value_by_rule": dict(value["value_by_rule"]),
                }
                for key, value in sorted(touch_register.items())
            },
            "excluded_conversions": excluded_conversions,
            "recorded_later_events": recorded_later,
        }
        snapshot["fingerprint"] = _fingerprint(
            {
                # ``as_of`` 只是查询时点；同一时点的结果应得到相同的依据指纹，
                # 便于确认旧周报能否被精确还原。
                "params": {
                    "lookback": lookback,
                    "scope": scope,
                    "rules": list(rules),
                    "include_proposed": include_proposed,
                },
                "channel_map": snapshot["channel_map"],
                "identity_fingerprint": snapshot["identity_fingerprint"],
                "journeys": {
                    identifier: {
                        "path": [touch["event_id"] for touch in detail["path"]],
                        "unattributed_reason": detail["unattributed_reason"],
                    }
                    for identifier, detail in journey_details.items()
                },
            }
        )
        return deepcopy(snapshot)

    def _has_unconfirmed_events(
        self,
        person_id: str,
        conversion_at: int,
        visible_events: list[dict],
        confirmed_state,
        potential_state,
        lookback: int,
        scope: str,
        first_conversion: dict,
        confirmed_component: set[str],
    ) -> bool:
        """确认身份没有路径时，判断拟议身份是否能带来候选事件。

        仅用于解释未归因原因，不会把这些事件计入份额。典型场景：手机与
        电脑的关联仍为 ``proposed``，因此手机上的触点不能计入已确认身份。
        """

        potential_component = potential_state.component(person_id)
        for event in visible_events:
            person_id = event["person_id"]
            if potential_state.resolve(person_id) not in potential_component:
                continue
            # 已确认身份内的事件本应进入路径；到不了这里说明是别的原因。
            if confirmed_state.resolve(person_id) in confirmed_component:
                continue
            if eligible(
                event["occurred_at"],
                conversion_at,
                first_conversion["occurred_at"],
                lookback,
                scope,
            ):
                return True
        return False
