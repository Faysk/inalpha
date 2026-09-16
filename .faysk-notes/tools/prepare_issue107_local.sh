#!/usr/bin/env bash
set -euo pipefail

EXPECTED_BRANCH="fix/data-service-saturation"
NOTES_REF="origin/notes/issue-107"
MODE="${1:-prepare}"

sources=(
  ".faysk-notes/tools/test_macro_cache_stampede_draft.py"
  ".faysk-notes/tools/test_factor_live_cache_stampede_draft.py"
  ".faysk-notes/tools/test_backfill_pool_pressure_draft.py"
  ".faysk-notes/tools/issue107_slow_data_app.py"
  ".faysk-notes/tools/issue107_load_probe.py"
  ".faysk-notes/tools/issue107_timeout_persistence_probe.py"
  ".faysk-notes/tools/issue107_factor_app.py"
  ".faysk-notes/tools/issue107_target_check.py"
  ".faysk-notes/tools/issue107_factor_macro_probe.py"
  ".faysk-notes/tools/issue107_runner_poll_probe.py"
  ".faysk-notes/tools/issue107_mixed_workload_probe.py"
  ".faysk-notes/tools/issue107_sustained_mixed_probe.py"
  ".faysk-notes/tools/issue107_sustained_acceptance_probe.py"
  ".faysk-notes/tools/issue107_capture_env.ps1"
  ".faysk-notes/tools/issue107_benchmark_db.ps1"
  ".faysk-notes/tools/issue107_benchmark_db.sh"
)

destinations=(
  "services/factor/tests/test_issue107_macro_stampede_local.py"
  "services/factor/tests/test_issue107_live_cache_stampede_local.py"
  "services/data/tests/test_issue107_pool_pressure_local.py"
  "services/data/issue107_slow_data_app.py"
  "services/data/issue107_load_probe.py"
  "services/data/issue107_timeout_persistence_probe.py"
  "services/factor/issue107_factor_app.py"
  "services/factor/issue107_target_check.py"
  "services/factor/issue107_factor_macro_probe.py"
  "services/factor/issue107_runner_poll_probe.py"
  "services/factor/issue107_mixed_workload_probe.py"
  "services/factor/issue107_sustained_mixed_probe.py"
  "services/factor/issue107_sustained_acceptance_probe.py"
  "scripts/issue107_capture_env.ps1"
  "scripts/issue107_benchmark_db.ps1"
  "scripts/issue107_benchmark_db.sh"
)

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

is_tracked() {
  git ls-files --error-unmatch -- "$1" >/dev/null 2>&1
}

require_cmd git
repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git branch --show-current)"
if [[ "$branch" != "$EXPECTED_BRANCH" ]]; then
  echo "Expected branch '$EXPECTED_BRANCH', current branch is '$branch'." >&2
  exit 1
fi

if [[ "$MODE" == "cleanup" || "$MODE" == "--cleanup" ]]; then
  for destination in "${destinations[@]}"; do
    [[ -e "$destination" ]] || continue
    if is_tracked "$destination"; then
      echo "Refusing to touch tracked file: $destination" >&2
      exit 1
    fi
    rm -f -- "$destination"
    echo "removed $destination"
  done
  echo
  echo "Remaining git status:"
  git status --short
  exit 0
elif [[ "$MODE" != "prepare" ]]; then
  echo "Usage: $0 [prepare|cleanup]" >&2
  exit 2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Preserve/commit/stash your own work before materializing diagnostics." >&2
  git status --short >&2
  exit 1
fi

if ! git remote | grep -Fxq origin; then
  echo "Missing git remote 'origin' (expected Faysk/inalpha fork)." >&2
  exit 1
fi
if ! git remote | grep -Fxq upstream; then
  echo "Missing git remote 'upstream' (expected mirror29/inalpha)." >&2
  exit 1
fi

echo "Fetching reviewed upstream baseline and contributor notes..."
git fetch upstream main
git fetch origin notes/issue-107

head_sha="$(git rev-parse HEAD)"
upstream_sha="$(git rev-parse upstream/main)"
printf 'HEAD          %s\n' "$head_sha"
printf 'upstream/main %s\n' "$upstream_sha"

if [[ "$head_sha" != "$upstream_sha" ]]; then
  echo "Contribution branch is not exactly at upstream/main." >&2
  echo "Do not run an old baseline against a drifted checkout; review/rebase deliberately first." >&2
  exit 1
fi

for i in "${!sources[@]}"; do
  source_path="${sources[$i]}"
  destination="${destinations[$i]}"

  if [[ -e "$destination" ]]; then
    echo "Refusing to overwrite existing diagnostic path: $destination" >&2
    exit 1
  fi
  if is_tracked "$destination"; then
    echo "Refusing to overwrite tracked file: $destination" >&2
    exit 1
  fi
  if [[ ! -d "$(dirname "$destination")" ]]; then
    echo "Expected repository directory does not exist: $(dirname "$destination")" >&2
    exit 1
  fi

  git show "${NOTES_REF}:${source_path}" > "$destination"
  echo "materialized $destination"
done

echo
echo "Diagnostic/helper files are intentionally UNTRACKED:"
git status --short

echo
echo "Tool versions / availability:"
for cmd in docker uv python node pnpm; do
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" --version || true
  else
    echo "$cmd NOT FOUND"
  fi
done

echo
echo "Next: read the runbook without switching branches:"
echo "  git show origin/notes/issue-107:.faysk-notes/11-local-test-runbook.md"
echo "Factor/mixed benchmarks must use services/factor/issue107_factor_app.py and pass issue107_target_check.py first."
echo "Use issue107_sustained_acceptance_probe.py for cross-sectional sustained acceptance evidence."
echo "Useful local helpers now materialized under scripts/:"
echo "  scripts/issue107_capture_env.ps1"
echo "  scripts/issue107_benchmark_db.sh"
echo "Cleanup later with: bash $0 cleanup"
