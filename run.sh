#!/usr/bin/env bash
# Full regeneration pipeline. Every artifact under raw/, build/ and dashboard/ is
# reproducible by running this; nothing downstream is edited by hand.
#
#   ./run.sh                 all stages
#   ./run.sh repos           re-enumerate repositories and reference counts
#   ./run.sh prs [repo...]   re-fetch pull requests (optionally a subset)
#   ./run.sh offline         rebuild db + dashboard from existing raw/, no network
#   ./run.sh dashboard       aggregate + render only
#   ./run.sh check           load the rendered page in a real DOM and assert it drew
set -euo pipefail

cd "$(dirname "$0")"
mkdir -p raw build dashboard
export PYTHONUNBUFFERED=1
PY=python3
S=scripts

stage() { printf '\n=== %s ===\n' "$1"; }

run_repos()     { stage "1/6 repositories";  $PY $S/fetch_repos.py; }
run_prs()       { stage "2/6 pull requests"; $PY $S/fetch_prs.py "$@"; }
run_build()     { stage "3/6 facts.db";      $PY $S/build_db.py; }
run_verify()    { stage "4/6 verify";        $PY $S/verify.py; }
run_aggregate() { stage "5/6 aggregate";     $PY $S/aggregate.py; }
run_render()    { stage "6/6 render";        $PY $S/render.py; }
run_check()     {
  stage "check render"
  local dir=build/domcheck
  if [ ! -d "$dir/node_modules/jsdom" ]; then
    echo "provisioning jsdom into $dir (one-off)"
    mkdir -p "$dir"
    ( cd "$dir" && npm init -y >/dev/null 2>&1 && npm i --silent jsdom@26.1.0 >/dev/null 2>&1 )
  fi
  # ESM resolves node_modules from the script's own directory, so run it from there.
  local root="$PWD"
  cp "$S/check_render.mjs" "$dir/check_render.mjs"
  ( cd "$dir" && node check_render.mjs "$root/dashboard/index.html" )
}

mode="${1:-all}"
shift || true

case "$mode" in
  all)
    run_repos; run_prs; run_build; run_verify; run_aggregate; run_render ;;
  repos)
    run_repos ;;
  prs)
    run_prs "$@"; run_build; run_verify; run_aggregate; run_render ;;
  offline)
    run_build; run_aggregate; run_render ;;
  dashboard)
    run_aggregate; run_render ;;
  check)
    run_check ;;
  *)
    echo "unknown mode: $mode" >&2; exit 2 ;;
esac

printf '\ndashboard: %s/dashboard/index.html\n' "$PWD"
