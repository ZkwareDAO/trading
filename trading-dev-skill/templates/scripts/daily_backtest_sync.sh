#!/bin/bash
# 每日信号对比 + OpenViking 数据同步
#
# 功能：
#   1. 执行当日信号对比（实盘 vs 回测）
#   2. 同步交易数据到 OpenViking
#
# Crontab 配置：
#   0 8 * * * /path/to/cta-strategy-code/scripts/daily_backtest_sync.sh >> logs/daily_comparison.log 2>&1
#
# 参数：
#   --yesterday      对比昨天
#   --days N         对比最近 N 天（默认当天）
#   --config PATH    指定信号对比配置文件（默认 signal_comparison/configs/batch.yaml）
#   --openviking-config PATH    指定 OpenViking 配置文件路径（默认 config/openviking_sync.yaml）
#   环境变量方式（已弃用）：YESTERDAY=1 或 DAYS=N
#

set -e

# === 环境变量设置（解决 Crontab PATH 问题）===
# 加载 nvm（确保 ov 命令可用）
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && source "$NVM_DIR/nvm.sh"

# 加载用户环境（获取其他工具的 PATH）
source ~/.bashrc 2>/dev/null || source ~/.zshrc 2>/dev/null || true

# 确保 ov 在 PATH 中（nvm 安装的 node 全局包）
if [ -d "$HOME/.nvm/versions/node" ]; then
    NODE_BIN=$(find "$HOME/.nvm/versions/node" -maxdepth 3 -type d -name bin 2>/dev/null | head -1)
    if [ -n "$NODE_BIN" ] && [ -d "$NODE_BIN" ]; then
        export PATH="$NODE_BIN:$PATH"
    fi
fi

# 动态获取项目目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# 激活虚拟环境（如果存在）
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -z "$VIRTUAL_ENV" ]; then
    echo "Warning: No virtual environment activated"
fi

# 创建日志目录
mkdir -p logs

# 日志文件
LOG_FILE="logs/daily_comparison_$(date +%Y%m%d).log"

echo "========================================" | tee -a "$LOG_FILE"
echo "每日信号对比任务启动: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# 解析命令行参数
DAYS_ARG=""
START_DATE_ARG=""
END_DATE_ARG=""
COMPARISON_CONFIG="signal_comparison/configs/batch.yaml"
OPENVIKING_CONFIG_ARG=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --yesterday)
            DAYS_ARG="--yesterday"
            YESTERDAY_DATE=$(date -d 'yesterday' +%Y%m%d)
            START_DATE_ARG="--start $YESTERDAY_DATE"
            END_DATE_ARG="--end $YESTERDAY_DATE"
            shift
            ;;
        --days)
            DAYS_ARG="--days $2"
            END_DATE=$(date +%Y%m%d)
            START_DATE=$(date -d "$2 days ago" +%Y%m%d)
            START_DATE_ARG="--start $START_DATE"
            END_DATE_ARG="--end $END_DATE"
            shift 2
            ;;
        --config)
            COMPARISON_CONFIG="$2"
            shift 2
            ;;
        --openviking-config)
            OPENVIKING_CONFIG_ARG="--config $2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

# 兼容环境变量方式（已弃用）
if [ -n "$DAYS" ]; then
    DAYS_ARG="--days $DAYS"
    END_DATE=$(date +%Y%m%d)
    START_DATE=$(date -d "$DAYS days ago" +%Y%m%d)
    START_DATE_ARG="--start $START_DATE"
    END_DATE_ARG="--end $END_DATE"
elif [ "$YESTERDAY" = "1" ]; then
    DAYS_ARG="--yesterday"
    YESTERDAY_DATE=$(date -d 'yesterday' +%Y%m%d)
    START_DATE_ARG="--start $YESTERDAY_DATE"
    END_DATE_ARG="--end $YESTERDAY_DATE"
fi

# 1. 执行信号对比
echo "[Step 1] 执行信号对比..." | tee -a "$LOG_FILE"
if python3 -m signal_comparison batch --config "$COMPARISON_CONFIG" $START_DATE_ARG $END_DATE_ARG 2>&1 | tee -a "$LOG_FILE"; then
    echo "[Step 1] 信号对比完成" | tee -a "$LOG_FILE"
else
    echo "[Step 1] 信号对比失败，继续执行同步..." | tee -a "$LOG_FILE"
fi

echo "" | tee -a "$LOG_FILE"

# 2. 同步到 OpenViking
echo "[Step 2] 同步数据到 OpenViking..." | tee -a "$LOG_FILE"
SYNC_DATE_ARG="--today"
if [ -n "$START_DATE_ARG" ]; then
    # 如果指定了日期，转换格式从 YYYYMMDD 到 YYYY-MM-DD
    RAW_DATE=$(echo "$START_DATE_ARG" | sed 's/--start //')
    SYNC_DATE_ARG="--date $(date -d "$RAW_DATE" +%Y-%m-%d)"
fi
if python3 -m strategy_core.openviking_sync $OPENVIKING_CONFIG_ARG sync $SYNC_DATE_ARG 2>&1 | tee -a "$LOG_FILE"; then
    echo "[Step 2] 同步完成" | tee -a "$LOG_FILE"
else
    echo "[Step 2] 同步失败" | tee -a "$LOG_FILE"
    exit 1
fi

echo "" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"
echo "任务完成: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"