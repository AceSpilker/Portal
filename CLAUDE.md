# Portal · 工作约定（每次会话必读）

> 本文件是 ZCode 在本仓库工作的长期约定。与 docs/dev-plan.md《执行约定》配合阅读，冲突时以用户当次指示为准。

## 每次完成任务后必做（不可省略）

1. **同步进度文档**：完成 dev-plan 步骤 → 该步骤状态 ⬜→✅、阶段看板、规模总览的进度数字（如 50/119）三处同步更新；
2. **同步契约文档**：新增/修改接口、数据表、枚举 → 同步 docs/api-spec.md（含权限列与阶段列）；需求变更 → 先改 docs/feature-spec.md 再同步 dev-plan；
3. **写工作日志**：`logs/YYYY-MM-DD_NNN-标题.md`，编号递增；包含需求原意、完成情况、测试结果、关键决策、遗留；
4. **提交并推送**：每个完成的逻辑单元单独 commit（格式 `type(scope): 中文描述`，如 `feat(P6): ...`、`fix(主题): ...`），完成后 push 到 origin main——用户在 Windows/macOS 两台机器间协作，不推送等于丢失；
5. **两道测试关卡**：后端 pytest + ruff、前端 vitest + vue-tsc + eslint + build 全绿才算完成；阶段结束跑业务功能测试（浏览器端到端）。

## 技术与环境要点

- **后端**：FastAPI + SQLAlchemy(async SQLite) + APScheduler，Python 3.13，venv 在 `backend/.venv`；启动 `uvicorn app.main:app --reload --port 8000`；
- **前端**：Vue3 + Element Plus + Pinia + ECharts(按需引入)，Vite 5173；启动 `npm run dev`；
- **Windows 热重载不可靠**：uvicorn --reload 可能停留在旧代码，改动后端后若行为未变，手动重启后端进程；
- **测试**：后端测试内聚合/清理逻辑用独立内存库（避免与 TestClient lifespan 的定时器互相干扰）；探活等 mock 用 httpx.MockTransport 或注入 transport；
- **传输加密**（P24）：curl 裸请求 /api 会 400 是正常现象，契约测试在 conftest 关闭加密；
- **进程管理**：杀端口占用用 `netstat -ano | findstr :8000` 找 PID 再 taskkill；PowerShell `Get-NetTCPConnection` 更准；
- **多平台**：监控采集需同时适配 Linux NAS(Docker 挂载 HOST_PROC/HOST_SYS)/macOS/Windows，平台分支必须写明依据与回退行为。

## 产品定位

- **桌面 Web 专用**（v1.4 需求变更）：不做移动端适配，保留窄窗口侧栏折叠；
- 自托管 NAS 门户：单管理员配置、家庭成员使用的多用户场景；
- 当前进度与下一步永远以 docs/dev-plan.md 的状态为准（状态即真相）。
