"""
Strategy Core - 常量定义

集中管理风控参数默认值和时间周期常量，避免在多处重复定义。
注意：百分比使用数值形式，如 20 表示 20%
"""

# ========== 时间周期常量 ==========
# 时间周期转分钟数映射
TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "1d": 1440,
}

# 默认最小 K 线数量要求
DEFAULT_MIN_BARS_REQUIRED = 11

# ========== 风控参数默认值 ==========
# 固定止损默认值 (20%)
DEFAULT_FIXED_STOP_LOSS_PCT = 20.0

# 回落止盈默认值
DEFAULT_TRAILING_ACTIVATION_PCT = 20.0
DEFAULT_TRAILING_DRAWDOWN_PCT = 5.0

# 固定止盈默认值 (0 表示禁用)
DEFAULT_FIXED_TAKE_PROFIT_PCT = 0.0

# ========== 兼容旧常量名（逐步迁移后可删除）==========
DEFAULT_STOP_LOSS_PCT = DEFAULT_FIXED_STOP_LOSS_PCT
DEFAULT_TRAILING_PROFIT_ACTIVATION = DEFAULT_TRAILING_ACTIVATION_PCT
DEFAULT_TRAILING_PROFIT_DRAWDOWN = DEFAULT_TRAILING_DRAWDOWN_PCT