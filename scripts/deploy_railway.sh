#!/usr/bin/env bash
# Deploy the Till for Qloo demo to Railway (new project "till-qloo", service "till"), from this directory.
# Run ONLY after Von approves hosting. Never touches the till-gitlab-demo project (GitLab entry, frozen).
#
#   bash scripts/deploy_railway.sh          dry run: checks + prints commands
#   bash scripts/deploy_railway.sh --run    deploy (requires the FAOS harness gate to print CONSISTENT)
#
# Uses the Dockerfile via railway.json; health check /agent/status. QLOO_API_KEY goes from .env to Railway over
# stdin, never on the command line. No Claude or ElevenLabs keys are set by default, so the public demo cannot
# spend money (keyword router + browser voice); see VON_STEPS.md to opt in.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
RUN=0; [[ "${1:-}" == "--run" ]] && RUN=1
run() { printf '  $ %s\n' "$*"; if [[ $RUN == 1 ]]; then "$@"; fi; }
die() { echo "ABORT: $*"; exit 1; }

echo "== checks"
command -v railway >/dev/null || die "railway CLI missing (brew install railway)"
railway whoami >/dev/null 2>&1 || die "railway CLI not logged in"
[[ -f railway.json && -f Dockerfile ]] || die "railway.json or Dockerfile missing"
git check-ignore -q .env || die ".env not gitignored (railway up uploads files that are not ignored)"
key=""
[[ -f .env ]] && key="$(grep -E '^QLOO_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '"' || true)"
[[ -n "$key" ]] && echo "  ok  QLOO_API_KEY found in .env (not printed)" \
                || echo "  WARN no QLOO_API_KEY in .env: the demo would run in labeled mock mode"

echo "== global deploy gate: bash ~/sandbox-harness/tests/faos.sh must return CONSISTENT"
if [[ $RUN == 1 ]]; then
  rc=0; out="$(bash ~/sandbox-harness/tests/faos.sh 2>&1)" || rc=$?
  echo "$out" | tail -5
  # faos.sh exits 0 = CONSISTENT, 3 = CONSISTENT_WITH_WARNINGS, 1 = INCONSISTENT. Only 0 passes unattended.
  [[ $rc == 0 || $rc == 3 ]] || die "faos.sh exit $rc, not CONSISTENT (3 = warnings: Von decides)"
else
  echo "  $ bash ~/sandbox-harness/tests/faos.sh   (runs on --run; abort unless CONSISTENT)"
fi

[[ $RUN == 0 ]] && echo "== DRY RUN: nothing below is executed"
echo "== create project + service (skip if .railway link already points at till-qloo)"
if ! railway status 2>/dev/null | grep -qi "till-qloo"; then
  run railway init --name till-qloo
  run railway add --service till
fi
if [[ -n "$key" ]]; then
  printf '  $ railway variable set QLOO_API_KEY --stdin --service till --skip-deploys   (value from .env via stdin)\n'
  [[ $RUN == 1 ]] && printf '%s' "$key" | railway variable set QLOO_API_KEY --stdin --service till --skip-deploys
fi
# Claude for the public demo (Von 2026-10-22: reuse the existing key; the server pins the prompt and caps calls a day).
akey="$(grep -E '^(export )?ANTHROPIC_API_KEY=' ~/.secrets 2>/dev/null | tail -1 | sed -E 's/^(export )?ANTHROPIC_API_KEY=//; s/^["'"'"']//; s/["'"'"']$//')"
if [[ -n "$akey" ]]; then
  printf '  $ railway variable set ANTHROPIC_API_KEY --stdin --service till --skip-deploys   (value from ~/.secrets via stdin)\n'
  [[ $RUN == 1 ]] && printf '%s' "$akey" | railway variable set ANTHROPIC_API_KEY --stdin --service till --skip-deploys
fi
run railway variable set TILL_LLM_DAILY_CAP=300 --service till --skip-deploys
run railway up --service till --detach
run railway domain --service till
echo "== then verify (Claude): curl -fsS https://<domain>/agent/status  and  .venv/bin/python tests/test_protocol.py https://<domain>/mcp"
echo "   If builds fail with 'secret RAILWAY_GIT_REPO_OWNER not found', connect the GitHub repo:"
echo "   railway service source connect --repo ydescieux2-del/till-qloo --branch main --service till"
