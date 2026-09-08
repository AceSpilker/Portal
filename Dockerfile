# ===== 阶段一：前端构建 =====
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --registry=https://registry.npmmirror.com
COPY frontend/ ./
RUN npm run build

# ===== 阶段二：后端运行时 =====
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    FRONTEND_DIST=/app/frontend/dist

WORKDIR /app
COPY backend/requirements.txt ./
# 清华源在部分 NAS 容器内被 DNS 解析为纯 IPv6 导致不可达（实测 2026-09），用双栈可达的中科大源
RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.ustc.edu.cn/pypi/simple

COPY backend/ ./backend/
COPY --from=frontend-builder /build/dist ./frontend/dist

EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
