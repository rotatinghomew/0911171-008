from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR


class CostLedger:
    def __init__(self) -> None:
        self.statements: dict[str, dict] = {}

    def settle(self, statement_id: str, attribution: dict, rule: str, cost_cents: int) -> dict:
        if not isinstance(cost_cents, int) or cost_cents < 0:
            raise ValueError("费用须为非负整数分")
        values = {channel: Decimal(str(value)) for channel, value in attribution["value_by_rule"][rule].items()}
        if "unattributed" in values:
            raise ValueError("渠道名与未归因科目冲突")
        values["unattributed"] = Decimal(str(attribution["unattributed_value"]))
        if any(value < 0 for value in values.values()):
            raise ValueError("分摊依据不能为负")
        total = sum(values.values())
        if not total and cost_cents:
            raise ValueError("没有归因价值时无法分摊费用")
        exact = {channel: Decimal(cost_cents) * value / total if total else Decimal(0) for channel, value in values.items()}
        cents = {channel: int(amount.to_integral_value(rounding=ROUND_FLOOR)) for channel, amount in exact.items()}
        remainder = cost_cents - sum(cents.values())
        ranking = sorted(exact, key=lambda channel: (-(exact[channel] - cents[channel]), channel))
        for channel in ranking[:remainder]:
            cents[channel] += 1
        statement = {"rule": rule, "cost_cents": cost_cents, "cents": cents, "basis": deepcopy(attribution)}
        if statement_id in self.statements and self.statements[statement_id] != statement:
            raise ValueError("已确认费用分摊不能被同号替换")
        self.statements[statement_id] = deepcopy(statement)
        return deepcopy(statement)
