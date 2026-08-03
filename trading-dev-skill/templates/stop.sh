#!/bin/bash
#
# stop.sh - 停止 CTA 策略核心系统
#
# 用法:
#   ./stop.sh                # 停止服务
#   ./stop.sh --help         # 显示帮助信息
#
# 说明:
#   1. 先发送 SIGTERM 给主进程，等待优雅退出
#   2. 主进程会自动停止所有策略子进程
#   3. 超时后强制终止残留进程
#   4. 最后清理所有相关进程（兜底）
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="cta_strategy_core.pid"

echo "======================================"
echo "CTA 策略核心系统 停止"
echo "======================================"
echo ""

# 读取 PID 文件
STOPPED=0
if [ -f "$PID_FILE" ]; then
    CORE_PID=$(cat "$PID_FILE")
    echo "停止 CTA 策略核心系统 (PID: $CORE_PID)..."

    # 发送 SIGTERM 信号（主进程会优雅停止子进程）
    kill -TERM "$CORE_PID" 2>/dev/null || true

    # 等待进程退出（最多 30 秒，给子进程足够时间退出）
    for i in {1..30}; do
        if ! kill -0 "$CORE_PID" 2>/dev/null; then
            echo "   进程已退出"
            STOPPED=1
            break
        fi
        sleep 1
        echo -n "."
    done
    echo ""

    # 如果还在运行，发送 SIGKILL
    if [ $STOPPED -eq 0 ] && kill -0 "$CORE_PID" 2>/dev/null; then
        echo "   优雅停止超时，强制终止..."
        kill -9 "$CORE_PID" 2>/dev/null || true
        sleep 2
    fi

    rm -f "$PID_FILE"
else
    echo "PID 文件不存在，尝试通过进程名查找..."
fi

# 清理残留进程（先发送 SIGTERM，等待优雅退出）
echo "清理残留进程..."
CLEANED=0

# 清理主进程
if pkill -TERM -f "python.*run_strategies_manager.py" 2>/dev/null; then
    echo "   发送 SIGTERM 到主进程..."
    CLEANED=1
    sleep 5
fi

# 清理策略子进程（兜底）
if pgrep -f "python.*run_strategy.py" >/dev/null 2>&1; then
    echo "   发现残留策略子进程，发送 SIGTERM..."
    pkill -TERM -f "python.*run_strategy.py" 2>/dev/null || true
    sleep 3

    # 检查是否还有残留
    if pgrep -f "python.*run_strategy.py" >/dev/null 2>&1; then
        echo "   强制终止残留策略子进程..."
        pkill -9 -f "python.*run_strategy.py" 2>/dev/null || true
    fi
fi

# 最终清理主进程（强制）
if pgrep -f "python.*run_strategies_manager.py" >/dev/null 2>&1; then
    echo "   强制终止残留主进程..."
    pkill -9 -f "python.*run_strategies_manager.py" 2>/dev/null || true
fi

if [ $CLEANED -eq 0 ]; then
    echo "   无残留进程"
fi

sleep 1

echo ""
echo "======================================"
echo "服务已停止"
echo "======================================"
