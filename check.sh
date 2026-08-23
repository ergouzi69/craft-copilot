#!/bin/bash
# 反馈子系统：验证项目当前状态（对应 harness 五子系统之一）
# 用法：bash check.sh

cd "$(dirname "$0")"
# 优先用 venv python（环境子系统：项目自包含）
PY=".venv/Scripts/python.exe"
[ -f "$PY" ] || PY="python"

echo "=== craft-copilot 自检 ==="
FAIL=0

# 1. 语法检查（所有 py 文件能编译）
echo "--- 语法检查 ---"
$PY -m py_compile app/*.py app/agent/*.py app/tools/*.py app/services/*.py app/store/*.py 2>/dev/null && echo "✅ 语法 OK" || { echo "❌ 语法错误"; FAIL=1; }

# 2. 测试（有测试文件就跑）
echo "--- 测试 ---"
if [ -d tests ] && ls tests/test_*.py >/dev/null 2>&1; then
  $PY -m pytest tests -q 2>/dev/null && echo "✅ 测试全绿" || { echo "❌ 测试失败"; FAIL=1; }
else
  echo "⏳ 暂无测试（Phase 1 起会加）"
fi

# 3. 进度文件存在
echo "--- 状态 ---"
[ -f PROGRESS.md ] && echo "✅ PROGRESS.md 存在" || { echo "❌ 缺 PROGRESS.md"; FAIL=1; }

echo "=== 结果: $([ $FAIL -eq 0 ] && echo '✅ 通过' || echo '❌ 有问题') ==="
exit $FAIL
