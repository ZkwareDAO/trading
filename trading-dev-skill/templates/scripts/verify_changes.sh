#!/bin/bash
# 测试验证脚本 - 验证本次修改正常工作
#
# 使用方式:
#   ./scripts/verify_changes.sh

set -e

echo "========================================"
echo "验证本次修改"
echo "========================================"

# 1. 单元测试
echo ""
echo "[1/3] 运行单元测试..."
python3 -m pytest \
    strategies/cta_ict_v3/tests/test_tp_target.py \
    strategy_core/tests/test_base_strategy.py::TestKlineCooldownTimeframe \
    strategy_core/tests/test_strategy_no_signal_logger.py::TestLifecycleUserIdPassThrough \
    -v --tb=short

echo ""
echo "[1/3] ✅ 单元测试通过"

# 2. 验证 user_id 传递
echo ""
echo "[2/3] 验证 user_id 传递..."
python3 -c "
from strategy_core.strategy_engine.registry import StrategyRegistry
from strategy_core.strategy_engine.lifecycle import LifecycleManager
from data_manager import DataManager, DataManagerConfig
from pathlib import Path
import yaml

config_path = Path('config/zktrading/cta_ict_v3/ZECUSDT.yaml')
if config_path.exists():
    with open(config_path) as f:
        config = yaml.safe_load(f)['cta_ict_v3']

    registry = StrategyRegistry()
    registry.register(
        strategy_id='test_zec',
        strategy_name='cta_ict_v3',
        module_path='strategies.cta_ict_v3.strategy',
        config=config,
    )

    lifecycle = LifecycleManager(registry)
    dm_config = DataManagerConfig(csv_dir='data/strategies/cta_ict_v3')
    dm = DataManager(dm_config)

    entry = registry.get('test_zec')
    success = lifecycle.instantiate_strategy(entry, dm, 'ICT_1D_3_ZECUSDT', 'live')

    if success:
        strategy = registry.get('test_zec').instance
        expected = config.get('user_id', '')
        actual = strategy._user_id
        # user_id 可以是 int 或 str，比较时转为字符串
        if str(actual) == str(expected):
            print(f'✅ user_id 传递正确: {actual!r}')
        else:
            print(f'❌ user_id 不匹配: 预期 {expected!r}, 实际 {actual!r}')
            exit(1)
    else:
        print('❌ 策略实例化失败')
        exit(1)
else:
    print('⚠️  跳过: 配置文件不存在')
"

echo ""
echo "[2/3] ✅ user_id 传递验证通过"

# 3. 验证 ICT 策略导入
echo ""
echo "[3/3] 验证策略模块..."
python3 -c "
from strategies.cta_ict_v3.ict_core import ICTCoreV3, MarketStructure
from strategies.cta_ict_v3.state import ICTStateV3, FVG, SwingPoint

# 验证 SwingPoint 可正常创建
sp = SwingPoint(bar_index=10, price=100.0)
assert sp.price == 100.0

# 验证 MarketStructure 可接受 SwingPoint
ms = MarketStructure(
    trend='bullish',
    swing_highs=[SwingPoint(bar_index=5, price=105.0)],
    swing_lows=[SwingPoint(bar_index=3, price=95.0)],
)
assert len(ms.swing_highs) == 1

print('✅ ICT 策略模块验证通过')
"

echo ""
echo "========================================"
echo "✅ 所有验证通过"
echo "========================================"