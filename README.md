# Portal · NAS 门户系统

自托管门户 Dashboard：统一登录、应用 Icon 磁贴、多网络环境智能解析、服务器性能监控、端口监控、AI 助手与 Flow 自动化。单 Docker 容器部署。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/design-proposal](docs/design-proposal.md) | 总体设计方案（架构/技术选型/部署）v0.2 |
| [docs/feature-spec](docs/feature-spec.md) | 功能详述（18 模块 / 221 功能点）v1.2 |
| [docs/api-spec](docs/api-spec.md) | 接口与数据模型详述（31 张表 / 90+ 端点）v1.0 |
| [docs/dev-plan](docs/dev-plan.md) | 开发计划（24 阶段 / 108 步骤，含完成状态）v1.1 |
| [redmine/](redmine/) | Redmine 任务清单（CSV 可导入）与说明 |
| [logs/](logs/) | 工作日志（每次任务的记录） |

## 目录结构

```
Portal/
├── frontend/   # Vue 3 + TypeScript + Vite + Element Plus
├── backend/    # Python 3.12 + FastAPI + SQLAlchemy(SQLite 主库)
├── docs/       # 设计与契约文档（MD + HTML 双版本）
├── redmine/    # Redmine 任务导入文件
└── logs/       # 工作日志
```

## 本地开发

```bash
# 后端（端口 8000）
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows；Linux 用 source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 前端（端口 5173，/api 代理到 8000）
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 ，登录页底部"后端连接自检"可验证联调。

## 部署（NAS）

```bash
docker compose up -d --build
```

访问 http://localhost:8080 。数据全部持久化在 `./data` 卷。详见 docs/design-proposal §8。
