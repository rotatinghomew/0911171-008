# 营销触点归因

容器环境固定在仓库 Dockerfile 的 Python 3.11.14 镜像摘要，无第三方包或在线服务。执行 `docker build -t local-analytics .` 后，`docker run --rm --network none local-analytics` 运行内置例子；`docker run --rm --network none local-analytics python -m unittest discover -s tests -v` 运行测试。例子和测试只用合成数据，可离线运行。

该原型用合成触点路径比较不同渠道归因规则。路径整理、规则计算和摘要输出为独立职责；不连接广告平台或真实客户数据。

Python 3.11+ 标准库即可运行。执行 `python -m unittest discover -s tests -v`；运行 `python -m attribution.demo` 查看规则差异。分配贡献仅是规则结果，不代表增量因果效果。

## 转化台账与归因审阅

`attribution.journeys.JourneyBook` 保存转化编号、人群身份、转化时间和价值，对每个转化截取回溯窗口，再汇总末触点和线性规则的价值。窗口两端均包含，空路径的价值归入未归因项，不丢弃该转化。`allocate` 保持原有口径：各转化独立取路径，不做设备身份拼接或跨转化触点占用。唯一事件编号用于去重；台账不表示事件接收时间。

`JourneyBook.review` 用于复购和跨设备路径审阅，在同一转化总体、回溯范围和渠道口径下比较规则：

* `scope="first"` 只归属首购，`scope="repeat"` 只归属复购；另一种转化的价值留在未归因中，并计入 `unattributed_by_reason`。
* 复购口径要求事件发生在同一身份的首笔转化之后，且仍在本次转化的回溯窗口内；首购口径只看首笔转化的窗口。
* 触点价值独占：更早的已归属转化先占用其窗口内触点，后续转化不会重复消耗同一触点的价值。线性规则只在未被占用的触点上平分，跳过原因保留在 `skipped`。
* 身份关联来自 `attribution.identity.IdentityGraph`，可按 `as_of` 还原当时状态。只有 `confirmed` 关联参与归属；`proposed` 关联只在身份说明中列出，除非显式传入 `include_proposed=True` 做敏感性审阅。被否决的关联仍保留在 `rejected_links` 中。
* `journeys[*].path` 是该笔转化的候选触点，`touches[*].credited_conversions` 才说明价值实际归给了哪笔转化，两者不可混用。
* 缺失路径不等于直接访问：空路径记为 `empty_path`；因身份尚未确认而缺失记为 `identity_unconfirmed`，均不虚构渠道。每笔转化的分配加未归因等于其原价值，规则合计加未归因等于转化总体价值。

## 差异解释

`attribution.reconcile.explain(old, new)` 逐笔说明路径变化：事件进入或离开哪笔转化、触点归属变化、渠道重分类、未归因原因变化；渠道合计差异单独保留，便于核对但不能代替路径解释。`as_of` 同时约束身份状态、渠道口径、事件接收时间和转化登记时间，因此旧周报的依据可以被还原，而不是被新数据覆盖。跨周补记的事件和事后登记的转化会在 `recorded_later_events` / `excluded_conversions` 中列出。

## 费用分摊

`attribution.settlement.CostLedger` 用确认的规则份额分摊内部联合获客费用，单位为整数分，舍入余额按小数余量和渠道名稳定分配，未归因单列科目。每笔分摊保存原归因依据，重复确认同样内容不会新增记录，不允许同号覆盖。

规则或路径变化时使用 `revise` 追加更正分录：原账保持不变，分录只记录与当前累计余额的差额，`audit` 同时给出原始依据、全部更正和累计余额。同一会计内容的重复更正不会重复入账。它是内部成本口径，不是给广告平台付款的接口；规则份额只用于分摊，不能说明广告带来的增量收益。
