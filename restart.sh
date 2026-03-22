#!/bin/bash
# AI 助理重启脚本（清理逻辑已内置于 main.py）
cd "$(dirname "$0")"
source .venv/bin/activate
nohup python main.py >> logs/app.log 2>&1 &
echo "已后台启动 PID=$!，日志: tail -f logs/app.log"
