#!/usr/bin/env bash
set -euo pipefail

compose_file="docker-compose.postgres-test.yml"
cleanup() {
  docker compose -f "$compose_file" down --volumes --remove-orphans
}
trap cleanup EXIT

docker compose -f "$compose_file" up -d --wait
export POSTGRES_TEST_DSN='postgresql://evia_reader:evia_test_only@127.0.0.1:55432/evia_test'
export POSTGRES_TEST_ADMIN_DSN='postgresql://postgres:evia_test_only@127.0.0.1:55432/evia_test'
python -m pytest tests/test_postgresql_integration.py -q
