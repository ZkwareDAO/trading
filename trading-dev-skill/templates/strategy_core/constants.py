"""
Strategy Core - 常量定义

集中管理风控参数默认值和时间周期常量，避免在多处重复定义。
注意：百分比使用数值形式，如 20 表示 20%
"""

# ========== 时间周期常量 ==========
# 时间周期转分钟数映射
#
# 缺项不是"不支持"而是**静默降级** —— 两个消费方都以 `.get(tf, 0)` 取值后
# 跳过或回退，不报错：
#   1. BaseStrategy._calc_required_history_days：max_minutes=0 时直接
#      return 7，于是 12h 只补 7 天（14 根）、3d 只补 7 天（2.3 根），
#      连该方法自称的 15 根都不够。
#   2. backtest/run_backtest._calc_warmup_bars：tf_minutes=0 时 continue，
#      预热窗口退化成默认的 1 个 4h，指标在回测开头一段全是错的。
# 新增周期时必须同步登记到这里。
TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "3d": 4320,
    "1w": 10080,
}

# 默认最小 K 线数量要求
DEFAULT_MIN_BARS_REQUIRED = 11

# 指标预热所需根数。
# 取自 data_manager.indicators 中最苛刻的阈值：ADX 的 MIN_ROWS = 100
# （RSI/ATR 是 period*3，period=14 时 42 根，被 100 覆盖）。
# 用于 _calc_required_history_days 反推补齐天数。
# 注意 DEFAULT_MIN_BARS_REQUIRED=11 是"能不能跑"的下限（低于此不计算），
# 而这里是"算得准不准"的下限（低于此指标值与交易所不一致）。两者不同。
INDICATOR_WARMUP_BARS = 100

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