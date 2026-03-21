# ETF 投资智能体 — 系统设计方案

## 一、架构总览

```
┌─────────────────────────────────┐
│  Frontend: React + Vite         │
│  TailwindCSS + shadcn/ui        │
│  Recharts (图表)                │
└──────────┬──────────────────────┘
           │ REST API (JSON)
┌──────────▼──────────────────────┐
│  Backend: Python FastAPI         │
│  ┌──────────────────────────┐   │
│  │ 持仓管理 API (CRUD)      │   │
│  │ 行情服务 API             │   │
│  │ 智能决策 API (LLM)       │   │
│  └──────────────────────────┘   │
│  SQLAlchemy ORM + Pydantic      │
└──────┬──────────┬───────────────┘
       │          │
  ┌────▼───┐  ┌──▼───────────┐
  │ SQLite │  │ AKShare      │
  │   DB   │  │ (免费行情源) │
  └────────┘  └──────────────┘
```

## 二、技术选型

| 层级       | 技术                              | 说明                             |
|------------|-----------------------------------|----------------------------------|
| 前端框架   | React 18 + Vite                   | 快速开发 SPA                     |
| 前端UI     | TailwindCSS + shadcn/ui           | 现代美观                         |
| 图表       | Recharts                          | React 原生图表库                 |
| 后端框架   | FastAPI                           | 异步、高性能、自动 OpenAPI 文档  |
| ORM        | SQLAlchemy 2.0                    | 支持 SQLite/PostgreSQL 无缝切换  |
| 数据校验   | Pydantic v2                       | 请求/响应模型                    |
| 数据库     | SQLite（开发）/ PostgreSQL（生产）| 轻量启动，按需升级               |
| 外部行情   | AKShare                           | 免费、无需API Key、覆盖A股ETF    |
| 智能决策   | OpenAI / DeepSeek / Ollama        | 可插拔 LLM 引擎                  |
| 定时任务   | APScheduler                       | 定时刷新行情缓存                 |

## 三、数据库设计 (5张核心表)

### 3.1 etf_info — ETF品种缓存
| 字段       | 类型         | 说明              |
|------------|-------------|-------------------|
| code       | VARCHAR(10) | 主键，如 '510300' |
| name       | VARCHAR(100)| 名称              |
| category   | VARCHAR(50) | 宽基/行业/商品等  |
| exchange   | VARCHAR(10) | SH / SZ           |
| updated_at | DATETIME    | 更新时间          |

### 3.2 portfolio — 用户持仓
| 字段       | 类型          | 说明           |
|------------|--------------|----------------|
| id         | INTEGER PK   | 自增主键       |
| etf_code   | VARCHAR(10)  | ETF代码        |
| shares     | DECIMAL(12,2)| 持有份额       |
| cost_price | DECIMAL(10,4)| 成本价         |
| buy_date   | DATE         | 买入日期       |
| note       | TEXT         | 备注           |
| created_at | DATETIME     | 创建时间       |
| updated_at | DATETIME     | 更新时间       |

### 3.3 market_daily — 日线行情缓存
| 字段        | 类型          | 说明                      |
|-------------|--------------|---------------------------|
| id          | INTEGER PK   | 自增主键                  |
| etf_code    | VARCHAR(10)  | ETF代码                   |
| trade_date  | DATE         | 交易日                    |
| open_price  | DECIMAL(10,4)| 开盘价                    |
| close_price | DECIMAL(10,4)| 收盘价                    |
| high_price  | DECIMAL(10,4)| 最高价                    |
| low_price   | DECIMAL(10,4)| 最低价                    |
| volume      | BIGINT       | 成交量                    |
| change_pct  | DECIMAL(8,4) | 涨跌幅%                   |
| UNIQUE(etf_code, trade_date) |             |

### 3.4 advice_log — 决策建议日志
| 字段        | 类型          | 说明                         |
|-------------|--------------|------------------------------|
| id          | INTEGER PK   | 自增主键                     |
| etf_code    | VARCHAR(10)  | ETF代码                      |
| advice_type | VARCHAR(20)  | buy/sell/hold/add/reduce     |
| reason      | TEXT         | LLM 生成的理由               |
| confidence  | DECIMAL(5,2) | 置信度 0~100                 |
| created_at  | DATETIME     | 生成时间                     |

## 四、后端 API 设计

### 4.1 持仓管理
| 方法     | 路径                    | 说明                         |
|----------|------------------------|------------------------------|
| GET      | /api/portfolio         | 持仓列表(含实时市值、盈亏)   |
| POST     | /api/portfolio         | 新增持仓                     |
| PUT      | /api/portfolio/{id}    | 修改持仓                     |
| DELETE   | /api/portfolio/{id}    | 删除持仓                     |
| GET      | /api/portfolio/summary | 汇总: 总市值、盈亏、占比     |

### 4.2 行情服务
| 方法     | 路径                         | 说明             |
|----------|------------------------------|------------------|
| GET      | /api/market/quote/{code}     | 单个ETF实时行情  |
| GET      | /api/market/history/{code}   | 历史K线          |
| GET      | /api/etf/search?q=xxx       | 搜索ETF品种      |

### 4.3 智能决策
| 方法     | 路径                    | 说明                    |
|----------|------------------------|-------------------------|
| POST     | /api/advice/generate   | 生成全部持仓的决策建议  |
| GET      | /api/advice/history    | 历史建议记录            |

## 五、外部数据方案 — AKShare

AKShare 是开源免费的 Python 财经数据接口库，数据源为东方财富/新浪等。

### 核心接口:
```python
import akshare as ak

# 1. 全市场ETF实时行情
df = ak.fund_etf_spot_em()

# 2. 单只ETF历史日K线
df = ak.fund_etf_hist_em(
    symbol="510300",
    period="daily",
    start_date="20240101",
    end_date="20250321"
)

# 3. ETF基金列表
df = ak.fund_etf_category_sina(symbol="ETF基金")
```

### 优势:
- **免费**: 无需注册、无需API Key
- **全覆盖**: A股ETF、LOF、场外基金全品种
- **稳定**: 数据源来自东方财富/新浪，可靠性高
- **活跃**: 社区维护活跃，更新频繁

## 六、智能决策引擎设计

### 6.1 决策流程
```
用户触发"生成建议"
       │
       ▼
┌──────────────────┐
│ 遍历每个持仓品种  │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 拉取近60日K线    │ ← AKShare
│ 计算技术指标     │   MA5/MA10/MA20/RSI/MACD
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 计算持仓盈亏     │ ← 成本价 vs 当前价
│ 持仓天数/浮盈率  │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 构造 Prompt      │ ← 行情+指标+持仓状态
│ 调用 LLM API     │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ 解析LLM返回      │ → advice_type + reason + confidence
│ 存入 advice_log  │
└──────────────────┘
```

### 6.2 Prompt 模板
```
你是一名专业的ETF投资顾问。请根据以下信息给出投资建议。

## 品种信息
- 代码: {code}, 名称: {name}, 类别: {category}

## 持仓状态
- 份额: {shares}, 成本价: {cost_price}
- 当前价: {current_price}, 浮动盈亏: {pnl_pct}%
- 持仓天数: {holding_days}

## 近期行情 (最近20个交易日)
{recent_kline_summary}

## 技术指标
- MA5={ma5}, MA10={ma10}, MA20={ma20}
- RSI(14)={rsi}
- MACD: DIF={dif}, DEA={dea}, MACD柱={macd_bar}

请给出:
1. 操作建议: buy/sell/hold/add/reduce (五选一)
2. 理由: 50字以内
3. 置信度: 0~100

请以 JSON 格式返回:
{"advice_type": "...", "reason": "...", "confidence": ...}
```

### 6.3 LLM 可插拔设计
```python
# 抽象接口
class BaseLLMClient:
    async def chat(self, prompt: str) -> str: ...

# 实现
class OpenAIClient(BaseLLMClient):     # OpenAI GPT-4o
class DeepSeekClient(BaseLLMClient):   # DeepSeek (国内低成本)
class OllamaClient(BaseLLMClient):     # 本地部署 (无需联网)
```

推荐优先级: **DeepSeek > Ollama > OpenAI**
- DeepSeek: 国内可用，价格极低，效果好
- Ollama: 完全本地，隐私安全，无成本
- OpenAI: 效果最佳，但需翻墙+费用高

## 七、项目目录结构

```
etf/
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── config.py            # 配置(DB/LLM等)
│   ├── database.py          # 数据库连接
│   ├── models/
│   │   ├── __init__.py
│   │   ├── etf_info.py      # ETF品种 ORM
│   │   ├── portfolio.py     # 持仓 ORM
│   │   ├── market_daily.py  # 行情 ORM
│   │   └── advice_log.py    # 建议日志 ORM
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── portfolio.py     # 请求/响应 Pydantic 模型
│   │   ├── market.py
│   │   └── advice.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── portfolio.py     # 持仓 API
│   │   ├── market.py        # 行情 API
│   │   └── advice.py        # 决策 API
│   ├── services/
│   │   ├── __init__.py
│   │   ├── portfolio_service.py
│   │   ├── market_service.py   # AKShare 封装
│   │   ├── advisor_service.py  # 决策引擎
│   │   └── llm/
│   │       ├── __init__.py
│   │       ├── base.py         # 抽象接口
│   │       ├── openai_client.py
│   │       ├── deepseek_client.py
│   │       └── ollama_client.py
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── PortfolioTable.tsx    # 持仓表格(可编辑)
│   │   │   ├── PortfolioForm.tsx     # 新增/编辑持仓表单
│   │   │   ├── MarketQuote.tsx       # 实时行情卡片
│   │   │   ├── KLineChart.tsx        # K线图
│   │   │   ├── AdviceCard.tsx        # 决策建议卡片
│   │   │   └── PortfolioSummary.tsx  # 持仓汇总/饼图
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx         # 首页仪表盘
│   │   │   ├── Portfolio.tsx         # 持仓管理页
│   │   │   └── Advice.tsx            # 决策建议页
│   │   ├── services/
│   │   │   └── api.ts               # Axios API 封装
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
└── DESIGN.md                 # 本文档
```

## 八、前端页面规划

### 8.1 Dashboard (首页)
- 持仓总市值卡片 / 总盈亏卡片 / 今日涨跌
- 持仓分类饼图 (宽基/行业/商品等)
- 各品种盈亏柱状图

### 8.2 持仓管理页
- 可编辑表格: 品种代码、名称、份额、成本价、当前价、盈亏、操作
- 支持搜索ETF代码自动填充名称
- 新增/编辑弹窗表单

### 8.3 决策建议页
- 一键生成所有持仓的建议
- 每个品种一张卡片: 操作建议标签(颜色区分) + 理由 + 置信度进度条
- K线图 + 技术指标叠加展示
- 历史建议记录列表

## 九、快速启动指南

### 9.1 后端启动
```bash
cd backend

# 创建虚拟环境
python -m venv venv
.\venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 配置环境变量 (复制示例文件并修改)
copy .env.example .env
# 编辑 .env 填入 LLM API Key (DeepSeek推荐)

# 启动服务
uvicorn main:app --reload --port 8000

# 访问 API 文档
# http://localhost:8000/docs
```

### 9.2 前端启动
```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 访问前端
# http://localhost:3000
```

### 9.3 LLM 配置说明
在 `backend/.env` 中配置:

```env
# 使用 DeepSeek (推荐，国内可用，便宜)
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-xxxxxxxx

# 或使用 Ollama (本地免费)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

# 或使用 OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxxxxxxx
```

## 十、后续扩展方向

1. **用户系统**: 多用户 + JWT 认证
2. **交易记录**: 买卖流水，自动计算成本
3. **回测引擎**: 基于历史数据回测策略
4. **消息推送**: 企业微信/钉钉/邮件推送建议
5. **更多指标**: 估值PE/PB、资金流向、北向资金
6. **定投计划**: 设定定投规则，自动生成定投建议
