# 工作日志 · 2026-09-01 · 009：澄清 redmine→readme，删除误建目录并完善 README

> 记录人：ZCode ｜ 性质：需求澄清修正

---

## 需求（用户原意）

刚才说错了，不需要 redmine，本意是 readme 文件。

## 完成情况

1. **删除上一轮误创建的 `redmine/` 目录**（含 portal-tasks.csv 与 README，已从本地与远程仓库移除）；
2. **完善根目录 `README.md`**（本项目正式的 readme 文件，此前已创建，本轮充实内容）：
   - 文档表补 HTML 版本链接（评审看 HTML）与各文档版本号；
   - 增加"当前进度 6/108，P0 进行中"指引（以 dev-plan 状态为准）；
   - 开发命令补 `npm test` / `pytest` 测试命令；
   - 增加"开发约定"小节（dev-plan 状态即进度、阶段两道测试关卡、logs 日志约定）；
   - 部署段补充 MySQL 推送等可选能力的开启方式说明。

## 关键决策

- 不保留 redmine CSV：dev-plan.md/.html 已是任务清单的唯一权威来源，避免两处维护（日志 008 曾生成 CSV，现已随目录删除，需要时可由 dev-plan 重新生成）。

## 遗留 / 下一步

1. P0 收尾：配置 ruff + ESLint（0.6）；
2. 进入 P1 认证与账户。
