"""配置中 ${VAR} 环境变量占位符解析

manager 与策略进程共用同一份实现，避免两个入口的占位符语义分叉。
"""

import os
import re
from typing import Any

# ${VAR} 占位符正则
_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def resolve_env_placeholders(obj: Any) -> Any:
    """递归解析配置中的 ${VAR} 占位符为环境变量值

    环境变量未设置时替换为 None（而非保留字面量 ${VAR}），
    让下游判断 None 走回退逻辑。
    """
    if isinstance(obj, dict):
        return {k: resolve_env_placeholders(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_env_placeholders(v) for v in obj]
    if isinstance(obj, str):
        m = _ENV_PATTERN.fullmatch(obj.strip())
        if m:
            # 整串就是 ${VAR}：返回环境变量原值（可能为 None）
            return os.environ.get(m.group(1))
        # 字符串中嵌入 ${VAR}：做替换，未设置的替换为空串
        return _ENV_PATTERN.sub(
            lambda mm: (os.environ.get(mm.group(1)) or ""), obj
        )
    return obj
