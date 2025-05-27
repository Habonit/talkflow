#!/bin/bash

PROJECT_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"
SCRIPT_DIR="$PROJECT_ROOT/scripts"

echo "Git Hook 설치"

HOOK_FILE="$SCRIPT_DIR/prepare-commit-msg"

if [ ! -f "$HOOK_FILE" ]; then
  echo "prepare-commit-msg (X). $HOOK_FILE 확인"
  exit 1
fi

cp "$HOOK_FILE" "$HOOKS_DIR/prepare-commit-msg"
chmod +x "$HOOKS_DIR/prepare-commit-msg"

echo "Git Hook 설치 완료"