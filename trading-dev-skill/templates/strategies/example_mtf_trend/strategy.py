#!/usr/bin/env python3
"""example_mtf_trend — Strategy 接口层（多周期参考实现）

与 example_ma_cross 的区别：本策略订阅 3 个周期（1d / 4h / 1h），
演示多周期策略的两个硬性要求：

1. Strategy._get_indicator_timeframes() 必须把每个指标用的周期都收集进来，
   漏一个，analyze() 里 get_closed_data() 就拿到空 DataFrame。
2. Core.analyze() 必须对每个周期分别调用 get_closed_data()，
   绝不能直接用 klines_data[tf] 的原始 df（最后一根可能未闭合 = 未来函数）。
"""

from strategy_core.base import BaseStrategy

from .example_mtf_trend_core import ExampleMtfTrendCore


class Strategy(BaseStrategy):
    """三周期趋势跟随示例：1d 定方向、4h 找触发、1h 做确认"""

    STRATEGY_TYPE = "example_mtf_trend"
    DEFAULT_TIMEFRAME = "4h"   # 主周期 = timeframes[0]

    def _create_core(self):
        return ExampleMtfTrendCore(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
            global_config=self._get_global_config(),
        )

    def _get_indicator_timeframes(self) -> set:
        """★ 多周期策略：每个 *_timeframes 参数都要收进来。

        集合内容 = 主周期 timeframes[0] ∪ 趋势周期 ∪ 确认周期。
        基类用它注册订阅、拉数据、算需要补多少历史。
        """
        tf_set = set(self.timeframes)          # 4h（触发周期，主周期）
        p = self.params or {}
        tf_set.add(p.get("trend_timeframe", "1d"))    # 1d 趋势过滤
        tf_set.add(p.get("confirm_timeframe", "1h"))  # 1h RSI 确认
        return tf_set
