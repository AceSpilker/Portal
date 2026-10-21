# Portal · NAS 门户系统

自托管门户 Dashboard：统一登录、应用 Icon 磁贴、多网络环境智能解析、服务器性能监控、端口监控、AI 助手与 Flow 自动化。单 Docker 容器部署。

## 文档（MD + HTML 双版本，评审看 HTML）

| 文档 | 内容 | 版本 |
|---|---|---|
| [docs/design-proposal](docs/design-proposal.html) | 总体设计方案：架构（含可选 MySQL/Redis 存储体系）、技术选型、i18n 与动效规范、数据模型概览、前置问题决策表 | v0.7 |
| [docs/feature-spec](docs/feature-spec.html) | 功能详述：18 模块 / 220 功能点，功能细节权威来源 | v1.6 |
| [docs/api-spec](docs/api-spec.html) | 接口与数据模型详述：32 张表、90+ 端点、错误码、WS/SSE 协议 | v1.2 |
| [docs/dev-plan](docs/dev-plan.html) | 开发计划：26 阶段 / 120 步骤，带完成状态与测试关卡 | v1.5b |
| [docs/test-report](docs/test-report.html) | 全系统功能与 UI 测试报告：26 阶段功能点/交互/性能/安全全量结果 | v1.0 |

> Markdown 版本在同名 `.md` 文件；开发进度以 dev-plan 内的状态为准（当前 **120 / 120 全部完成**：26 阶段全部落地，v1.0 发布版形成；P3/P8/P23/P25 等长稳与真机项随 NAS 实机部署执行；P3/P8 待真实环境验收，P9/P10 待渠道真机收包验收，P23/P25 的 72h 长稳随 NAS 实机部署）。

## 目录结构

```
Portal/
├── frontend/   # 一期前端：Vue 3 + TypeScript + Vite + Element Plus（端口 5173，已冻结）
├── backend/    # 一期后端：Python 3.12 + FastAPI + SQLAlchemy（SQLite 主库，端口 8000，已冻结）
├── phase2/     # 二期工程（进行中）：Django 5.2 后端 + Art Design Pro 前端，见 phase2/README.md
├── docs/       # 设计与契约文档（MD + HTML 双版本；含二期框架分析/迁移方案输入）
└── logs/       # 工作日志（每次任务的需求/完成情况/决策/遗留）
```

> **二期（phase2）**：后端换 **Django 5.2 LTS + Django Ninja + Channels**，前端换 **Art Design Pro v3.0.2**（Vue3），部署改 **nginx 前端（/portal/ 二级路径）+ backend 双容器**（后端端口不暴露）。功能与一期 1:1 对齐。方案见 [phase2/doc/portal-v2-migration-plan.html](phase2/doc/portal-v2-migration-plan.html)，执行进度见 [phase2/doc/dev-plan.html](phase2/doc/dev-plan.html)（20 阶段 / 171 步），文档一站式浏览 [phase2/doc/index.html](phase2/doc/index.html)。一期保持冻结运行，二期验收后切流。

## 本地开发（一期）

```bash
# 后端（端口 8000）
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows；Linux 用 source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 前端（端口 5173，/api 与 /ws 代理到 8000）
cd frontend
npm install
npm run dev        # 开发
npm test           # Vitest 单元测试
npm run build      # 类型检查 + 构建到 dist/
```

打开 http://localhost:5173 ，登录页底部"后端连接自检"可验证前后端联调。

```bash
# 后端测试
cd backend && ../.venv/Scripts/python -m pytest -q
```

## 本地开发（二期 phase2）

```bash
# 后端（Django，端口 8001；F1 完成前端加密层前以明文模式运行）
cd phase2/backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
.venv/bin/python manage.py migrate
ENCRYPT_ENABLED=false .venv/bin/uvicorn config.asgi:application --reload --port 8001
.venv/bin/python -m pytest -q        # 26 用例（health/crypto/auth）

# 前端（Art Design Pro，端口 5175；代理 /api /ws /icons /tunnel → 8001）
cd phase2/frontend
pnpm install
pnpm dev
```

打开 http://127.0.0.1:5175/portal/ ，dev 管理员账号见 logs/113。

## 部署（NAS）

```bash
docker compose up -d --build
```

访问 http://localhost:8080 。数据全部持久化在 `./data` 卷（数据库/图标/上传文件/备份），升级镜像不丢数据。
MySQL 镜像推送、Docker 容器管理等可选能力通过环境变量开启，见 docker-compose.yml 注释与 api-spec §6.1。

## 开发约定

- 按 [dev-plan](docs/dev-plan.html) 的阶段/步骤推进，每完成一步更新其中状态；
- 每个阶段结束跑"单元测试 + 业务功能测试"两道关卡，通过才能标 ✅；
- 每次任务在 `logs/` 写日志（需求 / 完成情况 / 关键决策 / 遗留）。
