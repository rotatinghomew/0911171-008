"""归因规则。

``credit`` 保留原有含义：对一条路径按末触点或线性规则给出份额，路径中的
每个触点都可获得份额。它不关心触点是否已经服务过另一笔转化。

``credit_journey`` 增加两项业务约束：

* ``first``（首购）与 ``repeat``（复购）口径，决定回溯范围；
* 触点占用：一个已由更早转化消耗的事件，不能再次为后续转化提供份额，
  除非显式允许复用。被跳过的触点不参与线性分母。

两种规则都按渠道汇总份额，但审阅层会保留逐触点的分配，用于说明每个触点
究竟归给哪一笔转化。
"""

from __future__ import annotations

VALID_RULES = ("last", "linear")
VALID_PURCHASE_SCOPES = ("first", "repeat")


def credit(path: list[dict], rule: str) -> dict[str, float]:
    if not path:
        return {}
    channels = [item["channel"] for item in path]
    result: dict[str, float] = {}
    if rule == "last":
        result[channels[-1]] = 1.0
    elif rule == "linear":
        share = 1.0 / len(channels)
        for channel in channels:
            result[channel] = result.get(channel, 0.0) + share
    else:
        raise ValueError(f"unsupported attribution rule: {rule}")
    return result


def eligible(
    earliest: int | None,
    conversion_at: int,
    first_order: int,
    lookback: int,
    scope: str,
) -> bool:
    """判断事件时点是否符合所选购买口径的回溯范围。

    首购口径只看首笔转化的回溯窗口；复购口径要求事件发生在首笔转化之后，
    并在本次转化之前的回溯窗口内。缺失的路径不改写为直接访问。
    """

    if scope not in VALID_PURCHASE_SCOPES:
        raise ValueError(f"不支持的购买口径: {scope}")
    if conversion_at - lookback <= earliest <= conversion_at:
        if scope == "first":
            return True
        return earliest > first_order
    return False


def credit_journey(
    touches: list[dict],
    rule: str,
    *,
    include_available: bool = False,
) -> dict:
    """对一条已解析的转化路径计算逐触点分配。

    ``touches`` 中的每个元素至少有 ``event_id`` 与 ``channel``，以及
    ``available`` 表示该事件在本次转化时是否仍可被占用。返回：

    * ``by_channel``：渠道份额；
    * ``by_touch``：事件编号到份额的映射（仅可占用且被规则选中的触点）；
    * ``skipped``：事件编号到跳过原因（``used`` 或 ``scope``）。
    """

    if rule not in VALID_RULES:
        raise ValueError(f"unsupported attribution rule: {rule}")
    selected = []
    skipped: dict[str, str] = {}
    for touch in touches:
        if not touch.get("in_scope", True):
            skipped[touch["event_id"]] = "scope"
        elif not touch.get("available", True) and not include_available:
            skipped[touch["event_id"]] = "used"
        else:
            selected.append(touch)
    by_channel: dict[str, float] = {}
    by_touch: dict[str, float] = {}
    if selected and rule == "last":
        chosen = selected[-1]
        by_channel[chosen["channel"]] = 1.0
        by_touch[chosen["event_id"]] = 1.0
    elif selected and rule == "linear":
        share = 1.0 / len(selected)
        for touch in selected:
            by_channel[touch["channel"]] = by_channel.get(touch["channel"], 0.0) + share
            by_touch[touch["event_id"]] = share
    return {"by_channel": by_channel, "by_touch": by_touch, "skipped": skipped}
