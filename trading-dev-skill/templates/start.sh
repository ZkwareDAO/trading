#!/bin/bash
#
# start.sh - 启动 CTA 策略核心系统
#
# 用法:
#   ./start.sh                # 使用 config/settings.yaml
#   ./start.sh --config PATH  # 指定配置文件路径
#   ./start.sh --help         # 显示帮助信息
#
# 注意:
#   策略运行配置全部在 config/settings.yaml 中设置
#   包括: 策略列表、代币、运行模式(live/paper_trading)等
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="cta_strategy_core.pid"

# 默认配置
CONFIG="config/settings.yaml"
STRATEGIES="config/strategies.yaml"
LOG_LEVEL="INFO"

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --config PATH      指定系统配置文件路径 (默认: config/settings.yaml)"
            echo "  --strategies PATH  指定策略配置文件路径 (默认: config/strategies.yaml)"
            echo "  --dev              开发模式（DEBUG 日志级别）"
            echo "  --help, -h         显示帮助信息"
            echo ""
            echo "配置说明:"
            echo "  系统配置: data_manager, signal_logging, strategy_engine 等"
            echo "  策略配置: 策略列表、代币、运行模式(live/paper_trading)"
            echo ""
            echo "示例:"
            echo "  $0                                          # 使用默认配置"
            echo "  $0 --config config/zktrading.yaml           # 使用 zktrading 系统配置"
            echo "  $0 --strategies config/strategies.prod.yaml # 使用生产策略配置"
            echo "  $0 --dev                                    # 开发模式"
            exit 0
            ;;
        --dev)
            LOG_LEVEL="DEBUG"
            shift
            ;;
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --strategies)
            STRATEGIES="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1，使用 --help 查看用法"
            exit 1
            ;;
    esac
done

echo "======================================"
echo "CTA 策略核心系统 启动"
echo "======================================"
echo ""

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "错误：未找到 python3"
    exit 1
fi

echo "Python 版本：$(python3 --version)"
echo ""

# 停止已有进程（使用 PID 文件）
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "正在停止已有进程 (PID: $OLD_PID)..."
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 2
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill -9 "$OLD_PID" 2>/dev/null || true
            sleep 1
        fi
    fi
    rm -f "$PID_FILE"
fi

# 清理残留进程
pkill -9 -f "python.*run_strategies_manager.py" 2>/dev/null || true
sleep 1
echo ""

# 检查虚拟环境
PYTHON_CMD="python3"
if [[ -d ".venv" ]]; then
    echo "检测到 .venv，使用虚拟环境..."
    PYTHON_CMD=".venv/bin/python3"
fi

# 检查依赖
if ! $PYTHON_CMD -c "import yaml" 2>/dev/null; then
    echo "警告：依赖未安装，正在安装..."
    if [[ -d ".venv" ]]; then
        .venv/bin/pip install -r requirements.txt
    else
        pip install -r requirements.txt
    fi
fi

# 检查配置文件
if [[ ! -f "$CONFIG" ]]; then
    echo "错误：系统配置文件不存在: $CONFIG"
    exit 1
fi

if [[ ! -f "$STRATEGIES" ]]; then
    echo "错误：策略配置文件不存在: $STRATEGIES"
    exit 1
fi

# 创建日志目录
mkdir -p "$SCRIPT_DIR/logs"

# 启动
echo "启动 CTA 策略核心系统..."
echo "   系统配置: $CONFIG"
echo "   策略配置: $STRATEGIES"
echo "   日志级别: $LOG_LEVEL"
echo "   日志目录: logs/{日期}/"
echo ""

# 启动（日志由 Python 的 DailyDirectoryFileHandler 管理，stdout 重定向到 /dev/null）
PYTHONPATH="$SCRIPT_DIR" nohup $PYTHON_CMD -u run_strategies_manager.py --config "$CONFIG" --strategies "$STRATEGIES" --log-level "$LOG_LEVEL" >/dev/null 2>&1 &
CORE_PID=$!
echo "   PID: $CORE_PID"
sleep 2

# 检查是否启动成功
if kill -0 $CORE_PID 2>/dev/null; then
    echo "   ✓ CTA 策略核心系统 启动成功"
else
    echo "   ✗ CTA 策略核心系统 启动失败"
    # 查找最新日志目录
    LATEST_LOG=$(ls -td "$SCRIPT_DIR/logs"/*/ 2>/dev/null | head -1)
    if [ -n "$LATEST_LOG" ]; then
        echo "   最新日志:"
        cat "$LATEST_LOG"strategies_runtime.log 2>/dev/null || true
    fi
    exit 1
fi
echo ""

echo "======================================"
echo "启动完成!"
echo "======================================"
echo ""
echo "查看日志:"
echo "  tail -f logs/\$(date -u +%Y-%m-%d)/strategies_runtime.log"
echo "  tail -f logs/\$(date -u +%Y-%m-%d)/strategies/*.log"
echo ""
echo "停止服务:"
echo "  ./stop.sh"
echo ""

# 保存 PID 文件
echo "$CORE_PID" > "$PID_FILE"
