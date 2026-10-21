# Portal 二期工程（phase2）

后端 **Django 5.2 LTS** + 前端 **Art Design Pro v3.0.2** 的全新实现，功能与一期（`backend/` + `frontend/`）1:1 对齐。

```
phase2/
├── doc/               # 二期文档（迁移方案等）
├── backend/           # Django 工程（D0 脚手架阶段创建）
├── frontend/          # Art Design Pro v2 前端（D0 阶段自 frontend-artdesign/ 迁入，构建 base=/portal/）
├── deploy/            # 部署资产：Dockerfile.backend / Dockerfile.frontend / nginx/nginx.conf
└── docker-compose.yml # 双容器编排：nginx 前端（发布 8080）+ backend（不发布端口，仅内网）
```

- 文档中心：[doc/index.html](doc/index.html)（一站式浏览全部 9 份文档：一级目录=文件、二级目录=各文档章节，iframe 内嵌展示）
- 总体方案：[doc/portal-v2-migration-plan.html](doc/portal-v2-migration-plan.html)
- 开发计划：[doc/dev-plan.html](doc/dev-plan.html)（20 阶段 / 171 步骤 / 3 里程碑，每阶段双测试关卡）
- 部署形态：nginx 容器以二级路径 `/portal/` 托管前端打包产物并反代 `/api /ws /icons /tunnel /files` 至后端容器；后端端口不对宿主暴露。
- 一期保持冻结运行，二期验收后按 §11.4 切流，卷内数据（SQLite/密钥/图标）直接沿用。
