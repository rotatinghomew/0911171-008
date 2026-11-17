"""内部联合获客费用分摊台账。

原账（``settle``）一经确认便不再改写。规则份额变化时通过 ``revise`` 追加
更正分录，分录只记录与当前累计余额的差额，因此：

* 旧周报的原始依据仍可通过 ``audit`` 还原；
* 更正不会覆盖原账，也不会悄悄改写历史；
* 同样内容的重复确认返回已有记录，不会重复入账。

台账只按归因规则份额分摊内部成本，不代表广告带来的增量收益。
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
from hashlib import sha256
import json


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _fingerprint(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:16]


class CostLedger:
    def __init__(self) -> None:
        self.statements: dict[str, dict] = {}
        self._adjustments: list[dict] = []
        self._sequence = 0

    # ------------------------------------------------------------------
    # 分摊计算
    # ------------------------------------------------------------------
    def _cents_for(self, attribution: dict, rule: str, cost_cents: int) -> dict[str, int]:
        if not isinstance(cost_cents, int) or cost_cents < 0:
            raise ValueError("费用须为非负整数分")
        try:
            rule_values = attribution["value_by_rule"][rule]
        except KeyError as error:
            raise ValueError(f"归因依据缺少规则: {rule}") from error
        values = {channel: Decimal(str(value)) for channel, value in rule_values.items()}
        if "unattributed" in values:
            raise ValueError("渠道名与未归因科目冲突")
        values["unattributed"] = Decimal(str(attribution["unattributed_value"]))
        if any(value < 0 for value in values.values()):
            raise ValueError("分摊依据不能为负")
        total = sum(values.values())
        if not total and cost_cents:
            raise ValueError("没有归因价值时无法分摊费用")
        exact = {
            channel: Decimal(cost_cents) * value / total if total else Decimal(0)
            for channel, value in values.items()
        }
        cents = {channel: int(amount.to_integral_value(rounding=ROUND_FLOOR)) for channel, amount in exact.items()}
        remainder = cost_cents - sum(cents.values())
        ranking = sorted(exact, key=lambda channel: (-(exact[channel] - cents[channel]), channel))
        for channel in ranking[:remainder]:
            cents[channel] += 1
        if sum(cents.values()) != cost_cents:
            raise AssertionError("分摊舍入未守恒")
        return cents

    # ------------------------------------------------------------------
    # 原账
    # ------------------------------------------------------------------
    def settle(self, statement_id: str, attribution: dict, rule: str, cost_cents: int) -> dict:
        cents = self._cents_for(attribution, rule, cost_cents)
        statement = {
            "statement_id": statement_id,
            "kind": "original",
            "rule": rule,
            "cost_cents": cost_cents,
            "cents": cents,
            "basis": deepcopy(attribution),
            "interpretation": self._interpretation(),
        }
        if statement_id in self.statements and self.statements[statement_id] != statement:
            raise ValueError("已确认费用分摊不能被同号替换")
        self.statements[statement_id] = deepcopy(statement)
        return deepcopy(statement)

    # ------------------------------------------------------------------
    # 更正
    # ------------------------------------------------------------------
    def revise(
        self,
        statement_id: str,
        attribution: dict,
        rule: str,
        cost_cents: int,
        *,
        reason: str | None = None,
        adjustment_id: str | None = None,
    ) -> dict:
        """按新的归因依据追加更正分录，返回新的累计状态。

        ``cost_cents`` 是同一费用期间的修订后总额。分录仅记录新旧分配的
        差额，因此可以逐项核对，也能在重复调用时保持幂等。
        """

        if statement_id not in self.statements:
            raise ValueError("原分摊记录不存在")
        original = self.statements[statement_id]
        if not isinstance(cost_cents, int) or cost_cents < 0:
            raise ValueError("费用须为非负整数分")
        new_cents = self._cents_for(attribution, rule, cost_cents)
        current = self.balance(statement_id)
        channels = sorted(set(current) | set(new_cents))
        delta = {channel: new_cents.get(channel, 0) - current.get(channel, 0) for channel in channels}
        if not any(delta.values()):
            # 依据可能变了，但分摊金额没有变化：不产生零金额分录。
            return self.audit(statement_id)
        fingerprint = _fingerprint(
            {
                "statement_id": statement_id,
                "rule": rule,
                "cost_cents": cost_cents,
                "value_by_rule": attribution.get("value_by_rule", {}).get(rule, {}),
                "unattributed_value": attribution.get("unattributed_value", 0),
                "channels": channels,
            }
        )
        for existing in self._adjustments:
            if existing["statement_id"] != statement_id:
                continue
            if existing["content_fingerprint"] == fingerprint:
                # 相同会计内容的重复确认不重复入账。
                return self.audit(statement_id)
        if adjustment_id is None:
            adjustment_id = f"{statement_id}:adj:{len(self._adjustments) + 1}"
        if any(item["adjustment_id"] == adjustment_id for item in self._adjustments):
            raise ValueError("更正分录编号已存在")

        self._sequence += 1
        after = {channel: current.get(channel, 0) + delta.get(channel, 0) for channel in channels}
        if sum(after.values()) != cost_cents:
            raise AssertionError("更正后累计分摊未达到修订总额")
        adjustment = {
            "adjustment_id": adjustment_id,
            "statement_id": statement_id,
            "kind": "adjustment",
            "sequence": self._sequence,
            "rule": rule,
            "cost_cents": cost_cents,
            "reason": reason,
            "cents": delta,
            "balance_after": dict(sorted(after.items())),
            "basis": deepcopy(attribution),
            "original_fingerprint": _fingerprint(original["basis"]),
            "content_fingerprint": fingerprint,
        }
        self._adjustments.append(deepcopy(adjustment))
        return self.audit(statement_id)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def adjustments(self, statement_id: str) -> list[dict]:
        return [
            deepcopy(item)
            for item in self._adjustments
            if item["statement_id"] == statement_id
        ]

    def balance(self, statement_id: str) -> dict[str, int]:
        """原账加上全部更正分录后的累计分摊。"""

        if statement_id not in self.statements:
            raise ValueError("原分摊记录不存在")
        balance = dict(self.statements[statement_id]["cents"])
        for adjustment in self._adjustments:
            if adjustment["statement_id"] != statement_id:
                continue
            for channel, cents in adjustment["cents"].items():
                balance[channel] = balance.get(channel, 0) + cents
        return dict(sorted(balance.items()))

    def audit(self, statement_id: str) -> dict:
        """还原原始依据与全部更正，供财务逐项核对。"""

        if statement_id not in self.statements:
            raise ValueError("原分摊记录不存在")
        original = deepcopy(self.statements[statement_id])
        adjustments = self.adjustments(statement_id)
        return {
            "statement_id": statement_id,
            "original": original,
            "adjustments": adjustments,
            "balance": self.balance(statement_id),
            "confirmation": self._interpretation(),
        }

    def _interpretation(self) -> dict:
        return {
            "basis": "rule_share",
            "incremental": False,
            "note": "规则份额仅用于分摊内部成本，不代表广告带来的增量收益。",
        }
