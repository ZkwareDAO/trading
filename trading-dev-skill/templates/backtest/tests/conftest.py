"""backtest 测试公共配置。

matplotlib 默认按显示环境选后端（TkAgg 等），无显示器的 CI/终端环境里
`plt.subplots()` 会抛 `TclError: couldn't connect to display`。图表测试只验证
文件生成与数据内容，不渲染交互窗口，统一强制非交互后端 Agg。
必须在 pyplot 首次导入前调用 `matplotlib.use()`——放在模块顶层 conftest
里先于所有测试模块加载，即可保证顺序。
"""

import matplotlib

matplotlib.use("Agg")
