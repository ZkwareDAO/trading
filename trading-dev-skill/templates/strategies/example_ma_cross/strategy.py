#!/usr/bin/env python3
"""example_ma_cross — Strategy 接口层（参考实现）

这是 BaseStrategy 的**最简形态**：只设置两个类属性 + 实现两个方法，
不重写 on_kline()，K 线处理流程完全交给基类。

⚠️ 基类默认节奏（strategy_core/base/strategy.py:373-452）：
    每根 1m K 线都会走一次流程 ——
      有持仓 → check_realtime_exit()（每分钟检查出场）
      无持仓 → analyze()（每分钟尝试入场）

    也就是说 analyze() 是**每分钟**被调用的，不是每根 4h 才调一次。
    这不是 bug：指标用 get_closed_data() 取已闭合大周期 K 线（不会有未来函数），
    入场价用 realtime_price（1m 实时价），所以条件一旦成立就能立刻进场，
    不必等到大周期收线。

    如果你的策略要求"只在大周期闭合的那一分钟才判断入场"，
    需要自己重写 on_kline()，在里面加闭合边界判断。
    参考写法见本文件底部注释。
"""

from strategy_core.base import BaseStrategy

from .example_ma_cross_core import ExampleMaCrossCore


class Strategy(BaseStrategy):
    """双均线交叉示例策略"""

    # ========== 必需类属性 ==========
    # STRATEGY_TYPE 必须等于策略目录名，否则信号里的 strategy_type 对不上
    STRATEGY_TYPE = "example_ma_cross"
    # overrides 里的 timeframes 优先，这里只是兜底默认值
    DEFAULT_TIMEFRAME = "4h"

    # ========== 必需实现 ==========

    def _create_core(self):
        """创建 Core 实例。

        global_config 必须传：Core 用它读 use_bar_high_low_for_exit，
        决定出场检查用 bar 的高低点还是收盘价（core.py:67-91）。
        """
        return ExampleMaCrossCore(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
            global_config=self._get_global_config(),
        )

    def _get_indicator_timeframes(self) -> set:
        """声明本策略要订阅哪些 K 线周期。

        基类用这个集合决定：
        1. 向 DataManager 注册哪些周期（on_start）
        2. 每次调用 analyze() 时 klines_data 里有哪些 key
        3. 启动时自动补多少历史数据

        **每个指标都要把自己的 *_timeframes 参数收进来**，漏了的周期
        在 analyze() 里 get_closed_data() 会拿到空 DataFrame。
        """
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("ma_timeframes", self.DEFAULT_TIMEFRAME))
        return tf_set


# ============================================================================
# 附：需要"只在大周期闭合时入场"时的写法
# ============================================================================
#
# 基类默认每根 1m bar 都调 analyze()。若要改成只在主周期收线那一分钟判断，
# 重写 on_kline()，在入场分支前加一道闸：
#
#     from datetime import datetime
#     from typing import Any, Optional
#     from strategy_core.signal_logging import Signal
#
#     def _is_bar_closed(self, current_time: datetime) -> bool:
#         """当前 1m bar 是否落在主周期的闭合边界上"""
#         if current_time.minute != 0:
#             return False
#         tf = self.timeframes[0] if self.timeframes else self.DEFAULT_TIMEFRAME
#         if not tf.endswith("h"):
#             return True
#         return current_time.hour % int(tf[:-1]) == 0
#
#     def on_kline(self, kline: Any) -> Optional[Signal]:
#         symbol = self._parse_kline_symbol(kline) or self.symbols[0]
#         state = self._core._get_state(symbol)
#         # 持仓时照常每分钟检查出场，只对入场加闸
#         if not state.is_in_position():
#             self._update_kline_info(kline)
#             ts = self._current_kline_timestamp
#             if ts is None or not self._is_bar_closed(ts):
#                 return None
#         return super().on_kline(kline)
#
# 代价：入场价从"条件成立那一刻的实时价"变成"收线价"，回测与实盘更容易对齐，
# 但会错过 bar 内的价格。两种都对，取决于策略设计，想清楚再选。
