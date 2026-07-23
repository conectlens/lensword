#!/usr/bin/env bash
#
# Run the same checks CI runs, in one command.
#
# The gates below mirror .github/workflows/ci.yml. If a gate is added, removed
# or renamed there, change it here too — the value of this script is that a
# green run locally means a green run in CI, and that only holds while the two
# lists agree.
#
# Usage:
#   scripts/verify.sh              # run every gate, report all results
#   scripts/verify.sh --fail-fast  # stop at the first failing gate
#   scripts/verify.sh --docker     # also build both images (slow, needs Docker)
#
# Exit status is 0 only if every gate that ran passed.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Pinned in .github/workflows/ci.yml. A local toolchain that differs can pass
# here and still fail there, so a mismatch is reported rather than ignored.
CI_PYTHON_VERSION="3.12"
CI_NODE_MAJOR="20"

FAIL_FAST=0
RUN_DOCKER=0

for arg in "$@"; do
  case "$arg" in
    --fail-fast) FAIL_FAST=1 ;;
    --docker)    RUN_DOCKER=1 ;;
    -h|--help)   sed -n '3,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [ -t 1 ]; then
  BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=''; RED=''; GREEN=''; YELLOW=''; RESET=''
fi

note() { printf '%s\n' "${YELLOW}note:${RESET} $*" >&2; }
fail() { printf '%s\n' "${RED}error:${RESET} $*" >&2; exit 2; }

# --- Preflight -------------------------------------------------------------
#
# Missing dependencies are a setup problem, not a test failure. They exit 2 with
# the command to run, rather than being reported as a red gate — a red gate here
# would say the code is broken when nothing has been checked at all.

PYTHON="backend/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
  fail "no backend virtualenv. Create one with:
    python${CI_PYTHON_VERSION} -m venv backend/.venv
    backend/.venv/bin/pip install -r backend/requirements.txt"
fi

if [ ! -d "frontend/node_modules" ]; then
  fail "frontend dependencies are not installed. Install them with:
    (cd frontend && npm ci)"
fi

local_python="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [ "$local_python" != "$CI_PYTHON_VERSION" ]; then
  note "backend virtualenv runs Python $local_python, CI runs $CI_PYTHON_VERSION."
  note "a pass here does not guarantee a pass in CI. Rebuild backend/.venv with python$CI_PYTHON_VERSION."
fi

local_node="$(node --version 2>/dev/null | sed 's/^v\([0-9]*\).*/\1/')"
if [ -n "$local_node" ] && [ "$local_node" != "$CI_NODE_MAJOR" ]; then
  note "local Node is $local_node.x, CI runs ${CI_NODE_MAJOR}.x."
fi

# --- Gates -----------------------------------------------------------------
#
# Every gate runs by default even after one fails, because CI sets
# `fail-fast: false` and runs the backend and frontend jobs in parallel: a red
# CI run reports every broken gate at once, and this script is only a faithful
# preview of CI if it does the same.

GATE_NAMES=()
GATE_RESULTS=()
GATE_SECONDS=()
FAILED=0

run_gate() {
  local name="$1" dir="$2"
  shift 2

  if [ "$FAIL_FAST" -eq 1 ] && [ "$FAILED" -ne 0 ]; then
    GATE_NAMES+=("$name"); GATE_RESULTS+=("SKIP"); GATE_SECONDS+=("0")
    return
  fi

  printf '\n%s\n' "${BOLD}==> $name${RESET}"
  local started ended status
  started=$SECONDS
  ( cd "$dir" && "$@" )
  status=$?
  ended=$SECONDS

  GATE_NAMES+=("$name")
  GATE_SECONDS+=("$((ended - started))")
  if [ "$status" -eq 0 ]; then
    GATE_RESULTS+=("PASS")
  else
    GATE_RESULTS+=("FAIL")
    FAILED=$((FAILED + 1))
  fi
}

run_gate "backend  · pytest"     backend  ".venv/bin/python" -m pytest -v
run_gate "frontend · lint"       frontend npm run lint
run_gate "frontend · typecheck+build" frontend npm run build
run_gate "frontend · vitest"     frontend npm test

if [ "$RUN_DOCKER" -eq 1 ]; then
  run_gate "docker   · backend image"  . docker build -q -t lensword-backend-verify backend
  run_gate "docker   · frontend image" . docker build -q -t lensword-frontend-verify frontend
fi

# --- Summary ---------------------------------------------------------------

printf '\n%s\n' "${BOLD}Summary${RESET}"
for i in "${!GATE_NAMES[@]}"; do
  case "${GATE_RESULTS[$i]}" in
    PASS) marker="${GREEN}PASS${RESET}" ;;
    FAIL) marker="${RED}FAIL${RESET}" ;;
    *)    marker="${YELLOW}SKIP${RESET}" ;;
  esac
  printf '  %s  %-34s %3ss\n' "$marker" "${GATE_NAMES[$i]}" "${GATE_SECONDS[$i]}"
done

if [ "$RUN_DOCKER" -eq 0 ]; then
  printf '\n  %s\n' "CI also builds both Docker images. Add --docker to check that here."
fi

if [ "$FAILED" -ne 0 ]; then
  printf '\n%s\n' "${RED}$FAILED gate(s) failed.${RESET}"
  exit 1
fi

printf '\n%s\n' "${GREEN}All gates passed.${RESET}"
