#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-verify}"
EXPECTED_DATABASE="inalpha_issue107"
POSTGRES_USER="quant"

case "$ACTION" in
  verify|reset-bars) ;;
  *)
    echo "Usage: $0 [verify|reset-bars]" >&2
    exit 2
    ;;
esac

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

psql_scalar() {
  docker compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$EXPECTED_DATABASE" -v ON_ERROR_STOP=1 -Atc "$1"
}

psql_exec() {
  docker compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$EXPECTED_DATABASE" -v ON_ERROR_STOP=1 -c "$1"
}

require_cmd git
require_cmd docker

repo_root="$(git rev-parse --show-toplevel)"
infra_dir="$repo_root/infra"
[[ -f "$infra_dir/docker-compose.yml" ]] || {
  echo "infra/docker-compose.yml not found under repository root: $repo_root" >&2
  exit 1
}

cd "$infra_dir"

if ! docker compose ps --status running --services | grep -Fxq postgres; then
  echo "The infra postgres service is not running. Start it before using this helper." >&2
  exit 1
fi

# Database name is intentionally fixed. This helper must never accept an arbitrary target for a
# destructive reset.
actual_database="$(psql_scalar 'select current_database();')"
if [[ "$actual_database" != "$EXPECTED_DATABASE" ]]; then
  echo "Safety check failed: expected '$EXPECTED_DATABASE', psql reports '$actual_database'." >&2
  exit 1
fi

bars_regclass="$(psql_scalar "select coalesce(to_regclass('public.bars')::text, '');")"
case "$bars_regclass" in
  bars|public.bars) bars_ready=true ;;
  *) bars_ready=false ;;
esac

printf 'benchmark_database=%s\n' "$actual_database"
printf 'bars_table_ready=%s\n' "$bars_ready"

if [[ "$bars_ready" != true ]]; then
  if [[ "$ACTION" == "reset-bars" ]]; then
    echo "public.bars does not exist in $EXPECTED_DATABASE. Apply current migrations first." >&2
    exit 1
  fi
  echo "Database identity is correct; migrations still need to create public.bars."
  exit 0
fi

before="$(psql_scalar 'select count(*) from public.bars;')"
printf 'bars_count_before=%s\n' "$before"

if [[ "$ACTION" == "verify" ]]; then
  echo "verify only: no data changed"
  exit 0
fi

echo "Resetting ONLY public.bars in the dedicated benchmark database..."
psql_exec 'TRUNCATE TABLE public.bars;' >/dev/null

after="$(psql_scalar 'select count(*) from public.bars;')"
printf 'bars_count_after=%s\n' "$after"
if [[ "$after" != "0" ]]; then
  echo "Reset verification failed: public.bars count is '$after', expected 0." >&2
  exit 1
fi

echo "benchmark bars reset complete"
