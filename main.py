# -*- coding: utf-8 -*-
"""
水印标注工坊 - 入口文件。

运行：
    python main.py
"""

import os

# ----------------------------------------------------------------------
# 1) 尽早初始化日志系统。
#    必须放在 `from ui import run` 之前：ui 包导入期间会执行 bridge.install()，
#    提前 setup 可让该阶段的日志也落盘。try/except 保证 app 包缺失时绝不阻塞启动。
# ----------------------------------------------------------------------
try:
    from app.logging_setup import setup_logging
    setup_logging()
except Exception:
    pass

# ----------------------------------------------------------------------
# 2) 触发配置中心单例（写 config_meta.json + 记一行 ws.config 日志）。
#    必须在 setup_logging() 之后：此时 handler 已挂，INFO 才能进文件/控制台。
#    try/except 保证配置中心任何异常都不阻塞启动（纯增量）。
# ----------------------------------------------------------------------
try:
    from app.config import get_config
    get_config()
except Exception:
    pass

from ui import run


def _apply_startup_patches():
    """
    在启动主界面前加载第一阶段性能/修复补丁。

    如果设置环境变量：

        WATERMARK_PERF=0

    则不加载补丁，便于对比原始行为。
    """
    if os.environ.get("WATERMARK_PERF", "1") == "0":
        return

    try:
        import performance_patch
        performance_patch.install()
    except Exception:
        try:
            import logging
            logging.getLogger("ws.boot").exception("加载 performance_patch 失败")
        except Exception:
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    _apply_startup_patches()
    try:
        import ui.edge_fix  # 边角归位·最终版；必须在 performance_patch 之后，作为最后覆盖者
    except Exception:
        import traceback; traceback.print_exc()
    run()