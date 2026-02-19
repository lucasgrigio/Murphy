#!/bin/bash
URL="${1:-}"

docker run --rm \
  -v /tmp/browseruse-data:/data \
  -v "$(cd "$(dirname "$0")" && pwd)/run_task.py":/app/run_task.py \
  -v "$(cd "$(dirname "$0")" && pwd)/.env":/app/.env \
  --entrypoint python \
  browseruse /app/run_task.py $URL
