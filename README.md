# ETF Investment Agent

一个面向个人投资者的 ETF 持仓管理与智能投顾项目，包含持仓录入、实时行情、ETF 级建议、账户级分析、账户金额管理和历史决策记录。

前端提供仪表盘与持仓管理界面，后端负责行情聚合、技术指标计算、账户分析和多模型 LLM 调用。

## Features

- 用户注册 / 登录 / JWT 鉴权
- ETF 持仓管理与持仓汇总
- ETF 实时行情与历史 K 线
- ETF 级投资建议生成
- 账户级投资建议生成
- 账户金额维护与建议仓位参考
- 决策历史记录
- 多 LLM 提供商切换
- Redis 行情缓存
- 定时分析任务

## Tech Stack

- Frontend: React 18, TypeScript, Vite, Recharts, Radix UI, Tailwind CSS
- Backend: FastAPI, SQLAlchemy Async, Pydantic, APScheduler
- Database: PostgreSQL / SQLite
- Cache: Redis
- Market Data: AKShare + fallback HTTP sources
- LLM Providers: DeepSeek, OpenAI, Gemini, Qwen, Ollama

## Project Structure

```text
.
├── backend/                # FastAPI backend
│   ├── models/             # SQLAlchemy models
│   ├── routers/            # API routes
│   ├── schemas/            # Pydantic schemas
│   ├── services/           # Business logic, market, LLM, scheduler
│   ├── main.py             # FastAPI entry
│   └── requirements.txt
├── frontend/               # React frontend
│   ├── src/components/     # UI components
│   ├── src/pages/          # Main pages
│   ├── src/services/       # API clients
│   └── package.json
├── docker-compose.yml
├── .env.example
└── DESIGN.md
```

## Core Pages

- Dashboard
  - 持仓汇总
  - 持仓分布可视化
  - ETF 智能决策建议
  - 账户投资建议
- Portfolio
  - 持仓增删改查
  - 行情刷新
  - ETF 详情与历史建议
- Advice History
  - ETF 决策历史
  - 账户分析历史

## Environment Variables

复制根目录示例配置：

```bash
cp .env.example backend/.env
```

关键配置项：

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/etf
JWT_SECRET=replace_with_a_long_random_secret
CORS_ORIGINS=["http://localhost:8123","http://127.0.0.1:8123"]

REDIS_URL=redis://redis:6379/0
REDIS_ENABLED=true

LLM_PROVIDER=deepseek

DEEPSEEK_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
QWEN_API_KEY=

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b

BARK_KEY=
BARK_URL=https://api.day.app
```

说明：

- `JWT_SECRET` 必填
- `CORS_ORIGINS` 使用 JSON 数组格式
- 只需配置你实际使用的 LLM 提供商
- Docker 部署时后端默认读取 `backend/.env`

## Run With Docker

最简单的启动方式：

```bash
docker compose up --build
```

默认访问地址：

- Frontend: `http://localhost:8123`
- Backend API: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

说明：

- `docker-compose.yml` 当前只包含 `frontend` 和 `backend`
- PostgreSQL / Redis 需要你自行提供，或按你的环境单独启动

## Run Locally

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

默认本地开发地址：

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`

## API Overview

主要接口分组：

- `/api/auth`
  - 登录、注册、当前用户、账户金额
- `/api/portfolio`
  - 持仓列表、汇总、增删改查
- `/api/market`
  - 行情、历史 K 线、ETF 搜索、行情刷新
- `/api/advice`
  - ETF 建议生成
  - 账户分析生成
  - 最新 ETF 建议
  - 最新账户分析
  - 决策历史
- `/api/llm`
  - LLM 提供商查询与切换

## Current Behavior

- ETF 建议和账户分析都会写入决策历史
- 首页默认读取最近一次账户分析，不会每次自动重新调用 LLM
- 手动点击“分析账户”才会刷新账户投资建议
- 持仓分布使用更细的分类体系，例如宽基指数、半导体芯片、医药医疗、贵金属、海外市场、红利策略等

## Notes

- 行情与新闻数据依赖外部数据源，稳定性受第三方接口影响
- 当前 Docker Compose 不直接拉起 PostgreSQL / Redis
- 前端生产构建目前存在较大的 bundle warning，但不影响运行
- 项目更适合作为个人工具或 MVP，生产化前建议补齐更正式的迁移、监控和测试体系

## License

如需开源发布，请根据你的实际计划补充许可证文件，例如 `MIT`。
