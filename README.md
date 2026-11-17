# 营销触点归因

容器环境固定在仓库 Dockerfile 的 Python 3.11.14 镜像摘要，无第三方包或在线服务。执行 `docker build -t local-analytics .` 后，`docker run --rm --network none local-analytics` 运行内置例子；`docker run --rm --network none local-analytics python -m unittest discover -s tests -v` 运行测试。例子和测试只用合成数据，可离线运行。

该原型用合成触点路径比较不同渠道归因规则。路径整理、规则计算和摘要输出为独立职责；不连接广告平台或真实客户数据。

Python 3.11+ 标准库即可运行。执行 `python -m unittest discover -s tests -v`；运行 `python -m attribution.demo` 查看规则差异。分配贡献仅是规则结果，不代表增量因果效果。

`attribution.journeys.JourneyBook` 保存转化编号、人群身份、转化时间和价值，对每个转化截取回溯窗口，再汇总末触点和线性规则的价值。窗口两端均包含，空路径的价值归入未归因项，不丢弃该转化。当前各转化独立取路径，不做设备身份拼接或跨转化触点占用。唯一事件编号用于去重；当前台账不表示事件接收时间。

`attribution.settlement.CostLedger` 用确认的规则份额分摊内部联合获客费用，单位为整数分，舍入余额按小数余量和渠道名稳定分配，未归因单列科目。每笔分摊保存原归因依据，重复确认同样内容不会新增记录，不允许同号覆盖；目前没有更正分录。它是内部成本口径，不是给广告平台付款的接口。
