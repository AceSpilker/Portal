# Portal · 接口与数据模型详述（API Spec）

> **版本**：v1.0 ｜ **日期**：2026-09-01 ｜ **关联文档**：《功能详述 feature-spec》v1.3、《总体设计方案 design-proposal》v0.3
>
> **文档定位**：后端建表与前后端联调的**契约依据**——字段级数据模型（31 张表）、全量 API 端点、统一响应与错误码、WebSocket/SSE 实时协议、环境配置清单。开发时以此为准；字段或契约变更需升版本并在 `logs/` 记录。

---

## 1. 通用约定

| 项 | 约定 |
|---|---|
| Base URL | `/api`（前端同源部署；开发期 Vite proxy） |
| 认证 | `Authorization: Bearer <access_token>`；豁免：`/api/health`、`/api/auth/init`、`/api/auth/login`、`/api/hooks/*`、短链跳转 |
| 统一响应 | `{"code": 0, "message": "ok", "data": {...}}`；`code=0` 成功，非 0 见错误码；HTTP 状态码同时有意义（401/403/404/500） |
| 分页 | 请求 `?page=1&page_size=20`；响应 `data: {"items": [...], "total": 123, "page": 1, "page_size": 20}` |
| 时间 | 存储/传输统一 ISO8601 字符串（UTC），前端本地化显示 |
| ID | 自增整数；对外不暴露内部密文字段（Token/密钥只回传脱敏掩码） |
| 枚举 | `access_type`: domain/lan/ssh/vpn/custom；`role`: admin/user；`state`: up/down/unknown；`level`: info/warn/error；`trigger_type`: cron/webhook/manual/event；`open_mode`: newtab/current/iframe |
| 文档 | FastAPI 自动生成 `/docs`（OpenAPI），本文为业务契约补充 |

## 2. 错误码表

| code | 含义 | HTTP |
|---|---|---|
| 0 | 成功 | 200 |
| 1001 | 用户名或密码错误 | 401 |
| 1002 | token 无效 | 401 |
| 1003 | token 已过期（前端用 refresh 静默续期） | 401 |
| 1004 | 系统未初始化（应跳转初始化向导） | 403 |
| 1005 | 系统已初始化（重复初始化拒绝） | 403 |
| 1006 | 登录失败次数过多，已锁定 | 429 |
| 2001 | 参数校验失败（message 携带明细） | 422 |
| 3001 | 无权限（未登录/角色不足） | 401/403 |
| 4001 | 资源不存在 | 404 |
| 4002 | 名称/唯一键重复 | 409 |
| 4003 | 操作冲突（如已删除/已停用） | 409 |
| 4004 | 目标不可达（探活/推送失败等业务失败） | 200（业务失败，code 区分） |
| 5001 | 服务器内部错误 | 500 |
| 5002 | 依赖服务不可用（MySQL/AI/通知渠道） | 502 |

## 3. 数据模型（字段级，31 张表）

> **建表策略**：随阶段建表（下表"建表"列），M1 建 12 张；`sync_state` 表结构 M2 落地。所有表含 `created_at`，业务表含 `updated_at`（同步依赖），下表不再重复列出。

### 3.1 账户与安全

**users**（M1）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | INTEGER | PK 自增 | |
| username | TEXT | UNIQUE NOT NULL | |
| password_hash | TEXT | NOT NULL | bcrypt |
| role | TEXT | DEFAULT 'user' | admin / user |
| is_active | INTEGER | DEFAULT 1 | 禁用=0 |
| totp_secret | TEXT | NULL | M2 启用 |
| prefs | TEXT(JSON) | DEFAULT '{}' | 主题/手动环境偏好/语言等个人偏好 |

**user_sessions**（M2）：id PK；user_id FK；refresh_hash TEXT（refresh 令牌哈希）；device TEXT；ip TEXT；created_at；last_seen_at；revoked INT DEFAULT 0 —— 支持会话列表与踢出。

**api_tokens**（M2）：id；name；token_hash TEXT UNIQUE；scope TEXT（readonly/readwrite）；expires_at NULL；last_used_at NULL。

**audit_logs**（M1 基础）：id；user_id NULL；action TEXT（login/update_config/container_op/flow_run…）；detail TEXT；ip TEXT。

### 3.2 门户核心（应用/分组/入口）

**categories**（M1）：id；name NOT NULL；icon TEXT NULL；sort INT 0；collapsed INT 0。

**apps**（M1）：id；name NOT NULL；description ''；icon TEXT；icon_type TEXT（url/upload/emoji）；category_id FK NULL；sort INT 0；enabled INT 1；health_type TEXT（''/http/tcp/keyword）；health_target TEXT NULL（URL 或 host:port）；health_interval INT 60；open_mode TEXT（newtab/current/iframe）DEFAULT 'newtab'；visibility TEXT（all/admin/users）DEFAULT 'all'；favorite INT 0；tags TEXT(JSON) '[]'；remark TEXT ''；doc_url TEXT NULL；deleted INT 0（回收站）；deleted_at NULL。

**app_urls**（M1）：id；app_id FK CASCADE；access_type TEXT NOT NULL（domain/lan/ssh/vpn/custom）；url TEXT NOT NULL；label TEXT ''；sort INT 0。

**dashboard_layouts**（M1）：id；user_id FK；tab TEXT（标签页名）；sort INT；layout TEXT(JSON)（磁贴顺序/尺寸/分组折叠等布局状态）；updated_at。多标签页布局（M02-5）与 PC/移动端独立布局（M16-5）均存于此。

### 3.3 网络环境与访问解析

**network_profiles**（M1）：id；name NOT NULL；match_type TEXT（cidr/default）；cidrs TEXT(JSON) '[]'（如 ["192.168.1.0/24"]）；prefer_types TEXT(JSON)（如 ["lan","domain","vpn"]）；is_default INT 0；sort INT 0；enabled INT 1。

### 3.4 探活与服务器监控

**app_status**（M1）：app_id INTEGER PK（1:1）；state TEXT（up/down/unknown）；latency_ms INT NULL；checked_at TIMESTAMP；since TIMESTAMP（当前状态起始，用于可用率）；message TEXT ''。

**probe_events**（M1 建表/M2 重度使用）：id；app_id FK；event TEXT（up/down/slow）；latency_ms INT NULL；created_at。索引 (app_id, created_at)。

**monitor_samples**（M1）：id；ts TIMESTAMP（索引）；cpu REAL；load TEXT(JSON) [l1,l5,l15]；mem TEXT(JSON) {total,used,swap_used}；disks TEXT(JSON) [{mount,total,used,inode_p}]；nets TEXT(JSON) [{iface,rx,tx,rx_total,tx_total}]；io TEXT(JSON) NULL（M2：磁盘读写/IOPS）；temps TEXT(JSON) NULL（M2：温度）；procs TEXT(JSON) NULL（M2：Top 进程快照）。采样保留天数由设置控制，清理任务删除过期行。

**alert_rules**（M2）：id；name；metric TEXT（cpu/mem/disk/disk_io/temp）；target TEXT NULL（如挂载点 "/"）；op TEXT（'>'/'<'）；threshold REAL；duration_min INT 5（持续 N 分钟才触发）；level TEXT（warn/error）；enabled INT 1；last_fired_at NULL。

### 3.5 端口监控

**port_monitors**（M2）：id；name；host TEXT DEFAULT '127.0.0.1'；port INT NOT NULL；app_id FK NULL（与应用关联）；interval INT 60；enabled INT 1；state TEXT（up/down/unknown）；last_latency_ms INT NULL；last_checked_at NULL。

**port_events**（M2）：id；monitor_id FK；event TEXT（up/down）；latency_ms NULL；created_at。索引 (monitor_id, created_at)。

**port_listen_history**（M3）：id；ts；added TEXT(JSON)；removed TEXT(JSON)（监听端口快照差异）。

### 3.6 SSH 凭据与隧道

**credentials**（M2）：id；name；type TEXT（password/key）；host；port INT 22；username；secret TEXT（加密存储，接口只回掩码）。

**tunnels**（M2）：id；url_id FK（app_urls）；credential_id FK；local_port INT；status TEXT（running/stopped/error）；pid INT NULL；last_active_at；auto_close_min INT 30。

### 3.7 自动化（Flow）

**flows**（M2）：id；name NOT NULL；description ''；trigger_type TEXT（cron/webhook/manual/event）；trigger_config TEXT(JSON)；actions TEXT(JSON)（动作数组，含条件节点）；enabled INT 0；webhook_token TEXT NULL UNIQUE；retry INT 0；retry_interval INT 60；last_run_at NULL。

**flow_runs**（M2）：id；flow_id FK；trigger TEXT（cron/webhook/manual/event）；status TEXT（running/success/failed）；steps_log TEXT(JSON)（每步输入输出）；started_at；finished_at NULL；duration_ms INT NULL。

### 3.8 通知

**notifications**（M2）：id；title；body TEXT；level TEXT（info/warn/error）；source TEXT（probe/metric/port/flow/system）；is_read INT 0；dedup_key TEXT NULL（聚合去重）。

**notify_channels**（M2）：id；type TEXT（bark/telegram/smtp/webhook/wecom/dingtalk/feishu/ntfy）；name；config TEXT(JSON)（敏感字段回传脱敏）；enabled INT 1。

**notify_rules**（M2）：id；event TEXT（app_down/app_up/metric_alert/port_down/port_up/flow_failed/system）；channel_ids TEXT(JSON)；enabled INT 1；quiet_start/quiet_end TEXT NULL（免打扰时段，规则级）。

### 3.9 AI

**ai_conversations**（M2）：id；user_id FK；title；provider TEXT；created_at。

**ai_messages**（M2）：id；conversation_id FK CASCADE；role TEXT（user/assistant/system）；content TEXT；tokens INT 0；created_at。

### 3.10 效率模块

**calendar_events**（M2）：id；user_id FK；title；date DATE；time TEXT NULL（HH:mm）；repeat TEXT（none/daily/weekly/monthly/custom）；repeat_config TEXT(JSON)；remind_before_min INT 0；channel_ids TEXT(JSON)。

**todos**（M2）：id；user_id FK；title；done INT 0；due_date DATE NULL。

**wol_targets**（M1）：id；name；mac TEXT NOT NULL；note TEXT ''。

**short_links**（M2）：id；code TEXT UNIQUE；target TEXT；hits INT 0。

### 3.11 系统与同步

**settings**（M1）：key TEXT PK；value TEXT(JSON)；updated_at。约定键名分组：`general.*`、`appearance.*`、`ai.*`、`notify.*`、`security.*`、`backup.*`、`sync.*`。

**sync_state**（M2）：id；table_name TEXT UNIQUE；last_push_at NULL；rows_pushed INT 0；status TEXT（idle/running/failed）；message TEXT ''。

---

## 4. API 端点明细

> 权限列：P=公开（免认证）、A=任意登录用户、M=仅管理员。阶段列 = 端点落地阶段。

### 4.1 认证与账户

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET | /api/health | 健康检查（含初始化状态） | P | P0 |
| POST | /api/auth/init | 首次初始化创建管理员（仅无用户时可用，否则 1005） | P | P1 |
| POST | /api/auth/login | 登录 → {access, refresh, user}；失败 1001/1006 | P | P1 |
| POST | /api/auth/refresh | refresh 换新 access | A | P1 |
| POST | /api/auth/logout | 登出（refresh 失效） | A | P1 |
| GET | /api/auth/me | 当前用户 + 偏好 | A | P1 |
| PUT | /api/auth/password | 修改密码（其他会话失效） | A | P1 |
| GET/DELETE | /api/auth/sessions · /{id} | 会话列表 / 踢出 | A/M | M2 |
| POST | /api/auth/totp/{setup,enable,disable} | 两步验证 | A | M2 |
| GET/POST/PUT/DELETE | /api/users… | 用户管理 | M | M2 |

### 4.2 分类与应用

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET/POST | /api/categories · PUT/DELETE /{id} · PUT /sort | 分组 CRUD/排序 | A读 M写 | P2 |
| GET | /api/apps?keyword=&category=&tag= | 应用列表（聚合状态点、按可见性过滤） | A | P2 |
| POST | /api/apps · GET/PUT/DELETE /api/apps/{id} | 应用 CRUD（删除=进回收站） | M | P2 |
| PUT | /api/apps/sort | 批量保存排序与分组 | M | P2 |
| POST | /api/apps/{id}/favorite | 收藏/取消 | A | P4 |
| GET/POST | /api/apps/{id}/urls · PUT/DELETE /api/app-urls/{id} | 访问入口 CRUD | M | P2 |
| GET | /api/apps/{id}/resolve?env=auto \| {pid} | 智能解析：{recommended, alternatives[]} | A | P3 |
| GET/POST | /api/apps/export · /api/apps/import | JSON 导出/导入 | M | P2 |
| GET | /api/apps/templates · POST /api/apps/from-template | 应用模板库 | M | M2 |
| POST | /api/apps/{id}/restore · DELETE /api/apps/{id}/purge | 回收站恢复/彻底删除 | M | M2 |
| POST | /api/apps/{id}/check | 立即探活一次 | A | P6 |
| GET | /api/apps/{id}/history?range=24h | 探活历史/可用率 | A | M2 |
| POST | /api/apps/upload-icon | 图标上传（压缩存 /app/data/icons） | M | P2 |
| GET | /api/apps/favicon?url= | 抓取目标站图标 | M | P2 |

### 4.3 网络环境与隧道

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET/POST | /api/network-profiles · PUT/DELETE /{id} | 环境档案 CRUD | A读 M写 | P3 |
| POST | /api/network-profiles/detect | 返回 {client_ip, matched_profile, candidates} | A | P3 |
| POST | /api/network-profiles/{id}/test | 档案连通性测试 | M | P3 |
| PUT | /api/me/env | 手动环境偏好（覆盖自动） | A | P3 |
| GET | /api/connectivity/matrix | 全应用×全入口探测矩阵 | A读 M执行 | P3 |
| POST | /api/tunnels/{urlId}/open · GET /api/tunnels · DELETE /{id} | SSH 隧道开关（M2 服务端托管） | A | M2 |
| GET/POST/PUT/DELETE | /api/credentials… | SSH 凭据管理（回传脱敏） | M | M2 |

### 4.4 服务器监控 ★

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET | /api/monitor/system | 实时概览：系统信息/CPU/内存/磁盘/网络 | A | P5 |
| GET | /api/monitor/history?metric=cpu&range=24h | 历史曲线（支持 cpu/mem/disk/net/io/temp） | A | P5 |
| GET | /api/monitor/processes?sort=cpu | 进程 Top 榜 | M | M2 |
| GET | /api/monitor/temps | 温度（无传感器返回空数组） | A | M2 |
| GET | /api/monitor/docker-stats | 按容器资源占用 | A | M2 |
| GET/POST | /api/alerts/rules · PUT/DELETE /{id} · POST /{id}/test | 阈值告警规则 CRUD/测试 | M | M2 |
| GET | /api/alerts/events?level=&range= | 告警事件历史 | A | M2 |

### 4.5 端口监控 ★

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET | /api/ports/listen | 当前监听清单（协议/地址/端口/进程） | A | M2 |
| GET/POST | /api/ports/monitors · PUT/DELETE /{id} | 端口监控项 CRUD | A读 M写 | M2 |
| POST | /api/ports/monitors/import | 批量导入 host:port | M | M2 |
| GET | /api/ports/monitors/{id}/history?range= | 通断/延迟历史 | A | M3 |
| GET | /api/ports/lookup?port=8080 | 端口占用检索（进程/命令行） | A | M2 |
| GET | /api/ports/events?monitor_id= | 通断事件流水 | A | M2 |
| GET | /api/ports/security-scan | 裸露端口（0.0.0.0 监听无入口）检查 | M | M3 |

### 4.6 Docker 管理（可选模块）

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET | /api/docker/containers | 容器列表（状态/镜像/占用） | M | M2 |
| POST | /api/docker/containers/{name}/{op} | start/stop/restart（写审计） | M | M2 |
| GET | /api/docker/containers/{name}/logs?tail=200 | 日志（支持实时） | M | M2 |
| GET | /api/docker/containers/{name}/detail | 详情（环境变量脱敏） | M | M2 |

### 4.7 Flow 自动化

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET/POST | /api/flows · GET/PUT/DELETE /api/flows/{id} | Flow CRUD | A读 M写 | M2 |
| POST | /api/flows/{id}/run · /dry-run | 手动执行 / 试运行 | M | M2 |
| GET | /api/flows/{id}/runs · /api/flow-runs/{runId} | 执行历史/详情 | A读 | M2 |
| POST | /api/hooks/flow/{token} | Webhook 触发入口 | P（token 鉴权） | M2 |

### 4.8 AI 助手

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET/POST/PUT/DELETE | /api/ai/providers… | Provider 配置（key 回传掩码） | M | M2 |
| POST | /api/ai/providers/{id}/test · GET /{id}/models | 连接测试/模型列表 | M | M2 |
| POST | /api/ai/chat | SSE 流式对话（body: conversation_id, content） | A | M2 |
| GET/POST/DELETE | /api/ai/conversations… | 会话管理 | A | M2 |
| POST | /api/ai/generate/app-draft | 生成应用草稿 | A | M2 |

### 4.9 通知

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET | /api/notifications?level=&unread= | 站内通知 | A | M2 |
| PUT | /api/notifications/read-all · /{id}/read | 已读 | A | M2 |
| GET/POST/PUT/DELETE | /api/notify-channels… | 渠道 CRUD | M | M2 |
| POST | /api/notify-channels/{id}/test | 测试发送 | M | M2 |
| GET/PUT | /api/notify-rules | 事件→渠道路由规则 | M | M2 |

### 4.10 工具箱

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET/POST/DELETE | /api/tools/wol-targets… | WoL 设备列表 | A | P7 |
| POST | /api/tools/wol | 发送魔术包 {target_id 或 mac} | A | P7 |
| POST | /api/tools/ping · /api/tools/port-check | Ping / TCP 端口测试 | A | P7 |
| GET | /api/tools/qr?text=&size= | 二维码 PNG | A | P7 |
| POST | /api/tools/codec · /api/tools/timestamp · /api/tools/passgen | 编解码/时间戳/密码生成 | A | P7 |
| POST | /api/tools/api-test | 迷你 API 测试器 | A | M2 |
| GET/POST/DELETE | /api/tools/short-links… | 门户短链 | A | M2 |

### 4.11 效率模块（M2）

| 方法 | 路径 | 说明 | 阶段 |
|---|---|---|---|
| GET/POST/PUT/DELETE | /api/calendar/events… | 日历事件 CRUD | M2 |
| GET/POST/PUT/DELETE | /api/todos… | 待办 CRUD | M2 |
| GET | /api/files/list?path= | 目录浏览（白名单） | M2 |
| GET/POST | /api/files/download · /upload · /mkdir · /rename · /delete · /move | 文件操作 | M2 |
| GET | /api/downloads/summary · /tasks · POST /api/downloads/tasks | qBittorrent 集成 | M2 |
| GET | /api/media/recent | Jellyfin/Emby 最近入库 | M2 |

### 4.12 设置 / 同步 / 备份 / 系统

| 方法 | 路径 | 说明 | 权限 | 阶段 |
|---|---|---|---|---|
| GET/PUT | /api/settings | 键值批量读写 | A读 M写 | P7 |
| GET/PUT | /api/settings/sync | MySQL 同步配置与连接测试 | M | P23 |
| POST | /api/sync/push · GET /api/sync/status · POST /api/sync/restore | 立即推送 / 状态 / 从 MySQL 恢复 | M | P23 |
| GET | /api/backup/export · POST /api/backup/import | 全量导出/导入 | M | P2/P17 |
| POST | /api/backup/factory-reset | 恢复出厂（需密码二次确认） | M | M2 |
| GET/POST/DELETE | /api/tokens… | API Token 管理 | M | M2 |
| GET | /api/audit-logs?action=&range= | 审计日志 | M | M2 |
| GET | /api/system/info · /check · /check-update | 系统信息/健康自检/更新检查 | M | P8/M2 |

## 5. 实时协议（WebSocket / SSE）

**WS /ws/monitor**（P5）：连接后服务端每 2 秒推送
`{"type":"monitor","data":{"cpu":12.3,"cpu_per_core":[...],"load":[0.5,0.4,0.3],"mem":{...},"disks":[...],"nets":[...]}}`。

**WS /ws/notify**（P6 起）：
`{"type":"app_status","data":{"app_id":12,"state":"down","latency":null,"message":"connect timeout"}}`
`{"type":"port_status","data":{"monitor_id":3,"state":"up","latency":2}}`（M2）
`{"type":"notification","data":{"id":9,"title":"…","level":"warn"}}`（M2）。

**SSE POST /api/ai/chat**（M2）：`data: {"type":"delta","content":"…"}`
`data: {"type":"action","action":"navigate","app_id":12}`（意图导航，前端解析后跳转）
`data: {"type":"done","usage":{"prompt":320,"completion":118}}`
`data: {"type":"error","code":5002,"message":"provider unreachable"}`。

## 6. 环境与配置附录

### 6.1 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| PORT | 8000 | 服务监听端口 |
| SECRET_KEY | 必填 | JWT 签名与敏感字段加密密钥 |
| TZ | Asia/Shanghai | 时区 |
| DATA_DIR | /app/data | 数据卷根目录 |
| DB__TYPE | sqlite | 预留：运行主库固定 sqlite（MySQL 仅作镜像目标） |
| SYNC__ENABLED | false | MySQL 定时推送开关 |
| SYNC__INTERVAL_MIN | 30 | 推送间隔（分钟） |
| SYNC__MYSQL__HOST / PORT / USER / PASSWORD / DATABASE | — | MySQL 连接（也可在设置页配置，环境变量优先） |
| HOST_PROC / HOST_SYS | 空 | 宿主机只读挂载路径（如 /host/proc），为空则读容器自身 |
| DOCKER_SOCK_ENABLED | false | Docker 管理模块开关 |
| LOG_LEVEL | info | 日志级别 |

### 6.2 数据卷目录结构

```
/app/data
├── portal.db            # SQLite 主库
├── icons/               # 应用图标
├── uploads/             # 上传文件（壁纸/文件管理）
├── backups/             # 自动备份 JSON
└── keys/                # SSH 私钥（M2）
```

### 6.3 联动说明

- 表结构/端点变更 → 本文档升版本 → `logs/` 记录；
- 端点与功能点编号（M04-10 等）在代码中以注释互相索引，便于按 feature-spec 验收。
