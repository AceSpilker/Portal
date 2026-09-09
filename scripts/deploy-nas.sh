#!/usr/bin/env bash
# 一键部署到局域网 NAS（192.168.5.88 Docker 单容器，063 部署形态）。
# 用法：scripts/deploy-nas.sh   （在仓库任意位置可执行）
#
# 流程：
# 1. tar over ssh 同步源码到 /volume1/docker/portal（排除 .git/node_modules/.venv/data/logs 等，
#    NAS 侧 data/ 卷与手工 docker-compose.override.yml 不受影响；群晖 rsync 协议不兼容，勿改用 rsync）；
# 2. sudo docker compose up -d --build——docker.sock 仅 root 可写：
#    - ~/.nas-portal.sudo 存在（单行 NAS 密码，600）→ sudo -S 免交互；
#    - 否则回退 ssh -t 交互输入（NAS 用户 AceSpilker）。
set -euo pipefail

cd "$(dirname "$0")/.."

DOCKER_BIN=/var/packages/ContainerManager/target/usr/bin/docker
PASS_FILE="$HOME/.nas-portal.sudo"

echo "==> 同步源码到 nas-portal:/volume1/docker/portal ..."
COPYFILE_DISABLE=1 tar \
  --exclude .git --exclude node_modules --exclude .venv --exclude data \
  --exclude logs --exclude .pytest_cache --exclude .ruff_cache \
  --exclude frontend/dist --exclude '._*' --exclude .DS_Store \
  -czf - . | ssh nas-portal "cd /volume1/docker/portal && tar xzf -"

echo "==> 重建并启动容器 ..."
if [[ -f "$PASS_FILE" ]]; then
  ssh nas-portal "cd /volume1/docker/portal && sudo -S ${DOCKER_BIN} compose up -d --build" < "$PASS_FILE"
else
  ssh -t nas-portal "cd /volume1/docker/portal && sudo ${DOCKER_BIN} compose up -d --build"
fi

echo "==> 部署完成，等待健康检查 ..."
sleep 20
ssh nas-portal "curl -sf http://127.0.0.1:8080/api/health >/dev/null && echo 'health: OK' || echo 'health: FAIL'"
