# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 右侧面板“壳”（从 legacy App._build_right_panel 物理搬迁）。

本轮（第34轮）只搬“壳”：元素列表标题 + elem_listbox + prop_container 滚动框 +
其上的 bind（选中/右键/滚轮关下拉/拉宽同步 right_w）。右面板的“肉”
（_refresh_property_panel 几百行属性填充逻辑）仍留在 legacy，待后续单独细切片搬迁。

搬迁规则（机械、可逐字对照 legacy 源码）：
- 函数签名由方法 _build_right_panel(self) 改为模块函数 build_right_panel(app)；
- 函数体内 self 全部改为 app；
- 全局名 ctk / Listbox / SINGLE / T / THEME / _native / _disp_font 改由本模块 import 提供
  （不再依赖 legacy 模块全局），其中 _native/_disp_font 用别名保持函数体内写法不变；
- 控件回调（app.on_select_element_from_list / app.on_elem_list_right_click）仍指向 App 方法
  （后者运行时解析到 RIGHTCLICK_PATCH 覆盖版，与 legacy 原 bind 等价），行为不变。

依赖已“洗净”且方向正确：本模块只依赖 ui.theme / ui.utils / ui.widgets / customtkinter /
tkinter，【不】依赖 legacy_app 的任何全局名。

SearchableCombobox 取自 ui.widgets（减债方向：panels 不反向依赖 legacy）。其 _open_instance
是类变量、存在类对象上；bridge 已把 legacy.SearchableCombobox 指向同一类对象，故本模块与
主界面读写的是同一份 _open_instance，_dismiss_popup 行为与 legacy 逐字等价。

写入 app 的属性（与 legacy 原方法完全相同）：
    app.elem_listbox, app.prop_container, app._prop_canvas_last_width
读取 app 的属性/方法：
    app._panel, app.main_paned, app.right_w, app.list_font,
    app.on_select_element_from_list, app.on_elem_list_right_click
"""

import customtkinter as ctk

from tkinter import Listbox, SINGLE

from ..theme import T, THEME, native as _native
from ..utils import disp_font as _disp_font
from ..widgets.searchable_combobox import SearchableCombobox


def build_right_panel(app):
    """构建右侧面板的壳。app = 主窗口 App 实例。"""
    panel = app._panel(app.main_paned)
    app.main_paned.add(panel, width=app.right_w, minsize=280, stretch="never")

    ctk.CTkLabel(
        panel, text="元素列表", font=_disp_font(15, True), text_color=T("text"),
    ).pack(anchor="w", padx=12, pady=(12, 2))

    app.elem_listbox = _native(
        Listbox(
            panel, selectmode=SINGLE, height=6,
            bg=THEME["panel"], fg=THEME["text"],
            selectbackground=THEME["sel"], selectforeground=THEME["text"],
            highlightthickness=0, borderwidth=0, activestyle="none",
            font=app.list_font,
        ),
        bg="panel", fg="text", selectbackground="sel", selectforeground="text",
    )
    app.elem_listbox.pack(fill="x", padx=10, pady=(0, 8))
    app.elem_listbox.bind("<<ListboxSelect>>", app.on_select_element_from_list)
    app.elem_listbox.bind("<Button-3>", app.on_elem_list_right_click)

    app.prop_container = ctk.CTkScrollableFrame(
        panel, label_text="属性",
        fg_color=T("panel2"), label_fg_color=T("panel2"),
        label_text_color=T("text"), label_font=_disp_font(13, True),
    )
    app.prop_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _dismiss_popup(_e=None):
        if SearchableCombobox._open_instance is not None:
            SearchableCombobox._open_instance._close_popup()

    app._prop_canvas_last_width = None

    def _dismiss_popup_on_canvas_resize(event):
        if app._prop_canvas_last_width == event.width:
            return
        app._prop_canvas_last_width = event.width
        _dismiss_popup()

    try:
        app.prop_container._parent_canvas.bind("<MouseWheel>", _dismiss_popup, add="+")
        app.prop_container._parent_canvas.bind("<Button-4>", _dismiss_popup, add="+")
        app.prop_container._parent_canvas.bind("<Button-5>", _dismiss_popup, add="+")
        app.prop_container._parent_canvas.bind(
            "<Configure>", _dismiss_popup_on_canvas_resize, add="+",
        )
    except Exception:
        pass

    def _sync_right_w(event):
        app.right_w = event.width

    panel.bind("<Configure>", _sync_right_w, add="+")