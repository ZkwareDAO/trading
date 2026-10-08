"""
Signal Params Builder - 策略信号参数构建

从策略 overrides 配置中提取 params + risk + 信号相关字段，合并为
CtaSignalCSV.from_signal 所需的参数字典。

原实现位于 StrategyEngine._build_strategy_params（engine 随 factory 链路
移除后内联至此），字段映射保持不变：
- risk 新格式 (fixed_stop_loss_pct / trailing_profit.{activation_pct,drawdown_pct})
  优先于旧格式 (stop_loss_pct / trailing_profit_activation / trailing_profit_drawdown)
- capital.max_cash / max_parts / leverage 注入资金与杠杆
- signal.* 注入信号标识字段
"""

from typing import Dict, Any

from ..constants import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TRAILING_PROFIT_ACTIVATION,
    DEFAULT_TRAILING_PROFIT_DRAWDOWN,
)


def build_signal_params(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    构建信号参数字典（供 CtaSignalCSV.from_signal 使用）

    从策略 overrides 配置中提取 params + risk + 信号相关字段合并。

    Args:
        cfg: 策略 overrides 配置（strategies/<name>/overrides/<symbol>.yaml
             中 <strategy_name> 段的内容）

    Returns:
        策略参数字典
    """
    cfg = cfg or {}
    params = dict(cfg.get("params", {}) or {})

    # 注入信号标识字段
    if "user_id" in cfg:
        params["user_id"] = cfg["user_id"]
    if "strategy_type" in cfg:
        params["strategy_type"] = cfg["strategy_type"]
    if "risk_strategy_type" in cfg:
        params["risk_strategy_type"] = cfg["risk_strategy_type"]
    if "pos_type" in cfg:
        params["pos_type"] = cfg["pos_type"]

    # 注入策略元数据
    if "version" in cfg:
        params["strategy_version"] = cfg["version"]
    if "valid_before" in cfg:
        params["strategy_valid_before"] = cfg["valid_before"]

    # 注入策略内部名称和主时间框架
    strategy_cfg = cfg.get('strategy', {}) or {}
    if 'name' in strategy_cfg:
        params['strategy_type_name'] = strategy_cfg['name']
    if 'timeframe' in cfg:
        params['strategy_internal'] = cfg['timeframe']
    elif 'timeframes' in cfg:
        tfs = cfg['timeframes']
        params['strategy_internal'] = tfs[0] if isinstance(tfs, list) and tfs else ''

    # 注入信号配置
    signal_cfg = cfg.get("signal", {}) or {}
    if "exchange" in signal_cfg:
        params["signal_exchange"] = signal_cfg["exchange"]
    if "order_type" in signal_cfg:
        params["signal_order_type"] = signal_cfg["order_type"]
    if "slippage" in signal_cfg:
        params["signal_slippage"] = signal_cfg["slippage"]
    if "valid_before_hours" in signal_cfg:
        params["signal_valid_before_hours"] = signal_cfg["valid_before_hours"]
    if "quantity" in signal_cfg:
        params["signal_quantity"] = signal_cfg["quantity"]

    # 注入资金配置
    capital = cfg.get("capital", {}) or {}
    if "max_cash" in capital:
        params["strategy_cash"] = capital["max_cash"]
    if "max_parts" in capital:
        params["strategy_parts"] = capital["max_parts"]
    if "leverage" in capital:
        params["leverage"] = capital["leverage"]

    # 注入风控字段（支持新旧两种格式）
    risk = cfg.get("risk", {}) or {}
    trailing = risk.get("trailing_profit", {}) or {}

    # StopLossThreshold: 新格式 fixed_stop_loss_pct > 旧格式 stop_loss_pct > 默认值
    params["StopLossThreshold"] = risk.get(
        "fixed_stop_loss_pct",
        risk.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)
    )

    # TakeProfitBackThreshold: 新格式 activation_pct > 旧格式 trailing_profit_activation > 默认值
    params["TakeProfitBackThreshold"] = trailing.get(
        "activation_pct",
        risk.get("trailing_profit_activation", DEFAULT_TRAILING_PROFIT_ACTIVATION)
    )

    # TakeProfitBackDynamicFallPercent: 新格式 drawdown_pct > 旧格式 trailing_profit_drawdown > 默认值
    params["TakeProfitBackDynamicFallPercent"] = trailing.get(
        "drawdown_pct",
        risk.get("trailing_profit_drawdown", DEFAULT_TRAILING_PROFIT_DRAWDOWN)
    )

    return params
