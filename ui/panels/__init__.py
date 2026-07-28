# -*- coding: utf-8 -*-
"""ui/panels：从 legacy App 拆出的面板构建/填充逻辑。各子模块 import 互相 try/except
隔离，任一失败不连累其它，也不拖垮 bridge_panels 对已就绪面板的注入。"""

try:
    from .left_panel import build_left_panel
except Exception:
    build_left_panel = None

try:
    from .right_panel import build_right_panel
except Exception:
    build_right_panel = None

try:
    from .toolbar import build_toolbar
except Exception:
    build_toolbar = None

try:
    from .bottom_bar import build_bottom_bar
except Exception:
    build_bottom_bar = None

try:
    from .canvas_view import build_canvas
except Exception:
    build_canvas = None

try:
    from .property_panel import refresh_property_panel
except Exception:
    refresh_property_panel = None


__all__ = [
    "build_left_panel", "build_right_panel",
    "build_toolbar", "build_bottom_bar", "build_canvas",
    "refresh_property_panel",
]