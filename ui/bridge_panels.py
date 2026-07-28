# -*- coding: utf-8 -*-
"""面板拆分桥接层。把 legacy App 的面板构建/填充方法重定向到 ui/panels/*.py 的纯函数，
物理搬迁 + 行为等价。独立成文件、不改已稳定的 bridge.py。

已拆：左面板(33) / 右面板壳(34) / 工具栏(43) / 底栏(44) / 画布(46) / 属性面板填充(47)。
属性面板是“肉”：_refresh_property_panel + 4 辅助(_contrast_color/_add_float_entry/
_add_numeric_row/_add_slider_row) 全转模块函数 refresh_property_panel(app)。其自递归与
上游 _select_element(legacy) 的 self._refresh_property_panel() 均运行时解析到本桥接覆盖版；
撤销靠 _redraw_canvas 副作用触发的 observe 入栈，与搬不搬属性面板无关，故不断链。

回退：单面板 import/覆盖失败 -> 该面板 try/except 不覆盖 -> legacy 原方法生效；
set WS_REFACTOR_PANELS=0 -> 全部回 legacy。
"""
import os
import sys
import logging


_log = logging.getLogger("ws.bridge_panels")


def _find_app_and_legacy():
    legacy = sys.modules.get("ui.legacy_app")
    if legacy is not None and hasattr(legacy, "App"):
        return legacy.App, legacy
    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("watermark_studio_legacy_ui") and hasattr(module, "App"):
            return module.App, module
    return None, None


def install():
    if os.environ.get("WS_REFACTOR_PANELS", "1") == "0":
        _log.info("WS_REFACTOR_PANELS=0，跳过面板拆分桥接")
        return False

    App, legacy = _find_app_and_legacy()
    if App is None:
        _log.warning("面板拆分桥接：找不到 App 类，跳过")
        return False
    if getattr(legacy, "_bridge_panels_installed", False):
        return True

    left_ok = False
    try:
        from .panels.left_panel import build_left_panel as _left_impl

        def _bridge_build_left_panel(self):
            _left_impl(self)

        App._build_left_panel = _bridge_build_left_panel
        left_ok = True
    except Exception:
        _log.exception("左面板拆分注入失败，回退 legacy 原 _build_left_panel")

    right_ok = False
    try:
        from .panels.right_panel import build_right_panel as _right_impl

        def _bridge_build_right_panel(self):
            _right_impl(self)

        App._build_right_panel = _bridge_build_right_panel
        right_ok = True
    except Exception:
        _log.exception("右面板拆分注入失败，回退 legacy 原 _build_right_panel")

    toolbar_ok = False
    try:
        from .panels.toolbar import build_toolbar as _tb_impl

        def _bridge_build_toolbar(self):
            _tb_impl(self)

        App._build_toolbar = _bridge_build_toolbar
        toolbar_ok = True
    except Exception:
        _log.exception("工具栏拆分注入失败，回退 legacy 原 _build_toolbar")

    bottom_ok = False
    try:
        from .panels.bottom_bar import build_bottom_bar as _bb_impl

        def _bridge_build_bottom_bar(self):
            _bb_impl(self)

        App._build_bottom_bar = _bridge_build_bottom_bar
        bottom_ok = True
    except Exception:
        _log.exception("底栏拆分注入失败，回退 legacy 原 _build_bottom_bar")

    canvas_ok = False
    try:
        from .panels.canvas_view import build_canvas as _cv_impl

        def _bridge_build_canvas(self):
            _cv_impl(self)

        App._build_canvas = _bridge_build_canvas
        canvas_ok = True
    except Exception:
        _log.exception("画布拆分注入失败，回退 legacy 原 _build_canvas")

    prop_ok = False
    try:
        from .panels.property_panel import refresh_property_panel as _rp_impl

        def _bridge_refresh_property_panel(self):
            _rp_impl(self)

        App._refresh_property_panel = _bridge_refresh_property_panel
        prop_ok = True
    except Exception:
        _log.exception("属性面板拆分注入失败，回退 legacy 原 _refresh_property_panel")

    try:
        _log.info("[WS-BRIDGE-PANELS] left=%s right=%s toolbar=%s bottom=%s canvas=%s prop=%s",
                  left_ok, right_ok, toolbar_ok, bottom_ok, canvas_ok, prop_ok)
    except Exception:
        pass

    legacy._bridge_panels_installed = True
    return left_ok or right_ok or toolbar_ok or bottom_ok or canvas_ok or prop_ok