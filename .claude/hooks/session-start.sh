#!/bin/bash
# SessionStart: готує середовище для тестів і linter у хмарній сесії Claude Code.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# venv у .venv (він у .gitignore); повторний запуск лише доустановлює відсутнє
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet -r agent/requirements.txt pytest ruff

# Додаємо .venv/bin у PATH для всієї сесії
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$CLAUDE_PROJECT_DIR/.venv/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi
