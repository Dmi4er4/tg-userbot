#!/usr/bin/env bash
set -euo pipefail

DOCKER_IMAGE="${DOCKER_IMAGE:-tg-userbot}"
DEPLOY_HOST="${DEPLOY_HOST:?DEPLOY_HOST is required}"
DEPLOY_PATH="${DEPLOY_PATH:-/root/tg-userbot}"
PROFILE="${PROFILE:-}"

docker compose build userbot-1
docker tag tg-userbot-userbot-1 "$DOCKER_IMAGE:latest"
docker push "$DOCKER_IMAGE:latest"

PROFILE_FLAG=""
if [ -n "$PROFILE" ]; then
    PROFILE_FLAG="--profile $PROFILE"
fi

ssh -t "root@$DEPLOY_HOST" "cd $DEPLOY_PATH && docker compose -f docker-compose.prod.yml $PROFILE_FLAG pull && docker compose -f docker-compose.prod.yml $PROFILE_FLAG up -d"
