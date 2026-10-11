# 深交所公开行情源

通过深交所官网基金行情页面使用的公开 JSON 接口获取深市 ETF 数据，无需注册、密钥或额外依赖。

官方页面：
- https://fund.szse.cn/marketdata/trade/index.html
- https://fund.szse.cn/marketdata/etf/

## 接口与能力

| 接口 | 参数 | 接入用途 |
| --- | --- | --- |
| `https://www.szse.cn/api/market/ssjjhq/getTimeData` | `marketId=1&code=159915` | 场内价格、昨收、涨跌幅、开高低、成交量、真实成交额，有效 IOPV 和溢价率 |
| `https://www.szse.cn/api/market/ssjjhq/getHistoryData` | `marketId=1&code=159915&cycleType=32` | 未复权历史日线 OHLCV、真实成交额、场内涨跌幅 |
| `https://www.szse.cn/api/report/ShowReport/data` | `CATALOGID=fund_etf&TABKEY=tab1&PAGENO=1&txtQueryKeyAndJC=创业板` | 代码/名称搜索，按页读取官方 ETF 列表 |

适配器仅处理六位 `15xxxx` 深市场内基金代码，不向该源请求沪市证券或场外基金。
报价和日线成交量由手乘以 100 转成份，金额单位为元。接口以整手显示时，转换后的成交量存在百份精度限制；日线成交额较快照取整到元，不使用价格乘成交量估算。
`netValue` 不直接当作 IOPV，只采用 `piciopv` 中交易时段内有效的非零观察值计算溢价率。
报价时间保留 `marketTime`（本次收盘快照为 15:30），不会改写成当前抓取时间。

## 优先级和限制

- 报价：沪深交易所公开源（按证券市场选择）→ 新浪 → 腾讯 → 妙想日线报价及其他既有回退源。行业指数仍保留同花顺专用分支。
- 日线：缓存 → 沪深交易所公开源 → 已配置的 Tushare → 妙想 → 新浪及其他既有回退源。
- 搜索：AkShare 无匹配或失败时，合并沪深交易所 ETF 搜索结果。
- 实测历史窗口为 201 条日线；超过可用长度（如 250 日）会继续回退，避免将不足的数据缓存为完整结果。
- 排除当天 15:10 前未完成日线、未来日期、超过 10 天的旧数据、错配证券和无效 OHLC/数值。
- 分时接口提供分钟价格/成交信息，但没有完整分钟 OHLC，因此本次不接入分钟 K 线。基金净值、ETF 规模尚未接入独立业务接口。
- 官网接口不是承诺长期稳定的开放 API，失败时继续既有回退链。

## 配置与保护

`SZSE_ENABLED=true` 默认开启，`false` 可关闭。Docker Compose 已使用 `backend/.env` 加载后端配置。
8 秒超时；报价缓存 20 秒，日线缓存 300 秒，搜索缓存 900 秒；并发相同请求去重；报价按证券顺序请求；请求失败冷却 60 秒；缓存和请求锁有容量限制。状态为单进程内存，随容器重建清空。

## 验证记录（2026-10-11）

| ETF | 最近日期 | 收盘价 | 60 日历史 | 最近日线成交额（元） |
| --- | --- | --- | --- | --- |
| 159915 创业板ETF易方达 | 2026-10-09 | 3.064 | 60 条 | 8,210,662,644 |
| 159919 沪深300ETF嘉实 | 2026-10-09 | 4.580 | 60 条 | 1,209,481,469 |
| 159920 恒生ETF华夏 | 2026-10-09 | 1.421 | 60 条 | 219,719,890 |

三只 ETF 均在新 Docker 镜像中真实请求成功，60 日日线成交额完整。`159915` 代码搜索返回 1 条；`创业板` 名称搜索成功读取两页并返回 20 条。

单元测试：`python -m unittest tests.test_szse_service tests.test_miaoxiang_service tests.test_market_service_history_fallback tests.test_portfolio_service_market_quote_time`。
