#!/bin/bash
# Murphy — Website Evaluation System
#
# Usage:
#   ./murphy/run.sh                                    # default
#   ./murphy/run.sh https://stripe.com                 # custom URL
#   ./murphy/run.sh https://stripe.com --category saas # with category hint
#   ./murphy/run.sh https://example.com --max-tests 5  # limit tests

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

docker run --rm -it \
  --shm-size=1g \
  -v /tmp/browseruse-data:/data \
  -v "$PROJECT_DIR/murphy":/app/murphy \
  -v "$PROJECT_DIR/.env":/app/.env \
  --entrypoint python \
  murphy -m murphy "$@"
