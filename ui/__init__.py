# -*- coding: utf-8 -*-
"""
ui 包入口。

本文件用于正式把原来的单文件 ui.py 迁移为 ui/ 包结构。

当前阶段：

    ui/legacy_app.py  = 原 ui.py 的完整旧代码，暂时不改动
    ui/__init__.py    = 对外暴露 run / App
    ui/bridge.py      = 把新拆出的 组件/对话框/服务/透视/导出 注入 legacy_app
    ui/bridge_panels.py = 把新拆出的 面板构建逻辑 注入 legacy_app（第33轮新增，独立于 bridge.py）

后续重构会逐步从 ui/legacy_app.py 中拆出：

    ui/constants.py        （已完成）
    ui/theme.py            （已完成）
    ui/utils.py            （已完成）
    ui/widgets/            （SearchableCombobox 已完成）
    ui/dialogs/            （Rect/Perspective/Help/Match/Library 已完成）
    ui/services/           （geometry/warp/autodetect/edge_snap/template_inspector 已完成）
    ui/panels/             （left_panel 第33轮完成；right/bottom/toolbar/canvas 待后续）

在这些拆分完成之前，main.py 仍然只需要：

    from ui import run
"""

import importlib.util
import os
import sys


_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
_LEGACY_APP_PATH = os.path.join(_PACKAGE_DIR, "legacy_app.py")


def _load_legacy_from_root_ui():
    """
    兼容旧结构：如果 ui/legacy_app.py 不存在，但项目根目录还有 ui.py，
    则尝试加载根目录 ui.py。

    这是迁移过程中的兜底方案，正式迁移完成后不应依赖它。
    """
    old_ui_path = os.path.join(_PROJECT_ROOT, "ui.py")

    if not os.path.exists(old_ui_path):
        raise ImportError(
            "无法找到 ui/legacy_app.py，也无法找到根目录 ui.py。\n"
            "请确认已经完成迁移：\n"
            "    原 ui.py -> ui/legacy_app.py\n"
            "并且存在：\n"
            "    ui/__init__.py"
        )

    module_name = "watermark_studio_legacy_ui_single_file"

    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(module_name, old_ui_path)

        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载旧版 ui.py：{old_ui_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    return module


if os.path.exists(_LEGACY_APP_PATH):
    from .legacy_app import run, App
else:
    _legacy_module = _load_legacy_from_root_ui()
    run = _legacy_module.run
    App = _legacy_module.App


# ----------------------------------------------------------------------
# 安装组件/对话框/服务/透视/导出 桥接
# ----------------------------------------------------------------------
try:
    from . import bridge

    bridge.install()
except Exception:
    import traceback

    traceback.print_exc()


# ----------------------------------------------------------------------
# 【第33轮】安装面板拆分桥接（独立于 bridge.py，避免改动已稳定的 bridge）
# ----------------------------------------------------------------------
try:
    from . import bridge_panels

    bridge_panels.install()
except Exception:
    import traceback

    traceback.print_exc()


__all__ = ["run", "App"]