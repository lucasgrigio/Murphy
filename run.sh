#!/bin/bash
# Murphy — Website Evaluation System
#
# Usage:
#   ./run.sh                                    # default
#   ./run.sh https://stripe.com                 # custom URL
#   ./run.sh https://stripe.com --category saas # with category hint
#   ./run.sh https://example.com --max-tests 5  # limit tests

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

docker run --rm -it \
  --shm-size=1g \
  -v /tmp/browseruse-data:/data \
  -v "$PROJECT_DIR/murphy":/app/murphy \
  -v "$PROJECT_DIR/.env":/app/.env \
  --entrypoint python \
  murphy -m murphy "$@"
