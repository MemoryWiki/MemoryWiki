#!/usr/bin/env bash
set -euo pipefail

COV_FAIL_UNDER="${COV_FAIL_UNDER:-65}"
PYTHON="${PYTHON:-python3}"

"$PYTHON" -m pytest tests -q
"$PYTHON" -m coverage erase
"$PYTHON" -m pytest tests --cov=memory_system --cov=memorywiki_mcp --cov-report=term-missing --cov-fail-under="$COV_FAIL_UNDER"
"$PYTHON" -m bandit -q -r memory_system memorywiki_mcp -x tests
"$PYTHON" -m pip_audit . --progress-spinner off
"$PYTHON" -m build
"$PYTHON" -m twine check dist/*
