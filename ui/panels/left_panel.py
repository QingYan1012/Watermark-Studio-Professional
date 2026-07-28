# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 左侧图片列表面板（从 legacy App._build_left_panel 物理搬迁）。

搬迁规则（机械、可逐字对照 legacy 源码）：
- 函数签名由方法 _build_left_panel(self) 改为模块函数 build_left_panel(app)；
- 函数体内 self 全部改为 app；
- 全局名 T / THEME / _native / _disp_font / Listbox / EXTENDED / SORT_MODE_LABELS / ctk
  改由本模块 import 提供（不再依赖 legacy 模块全局），其中 _native/_disp_font 用别名
  保持函数体内调用写法不变；
- 控件回调（app.on_select_image / on_remove_image / on_clear_all_images /
  on_edit_current_data / on_sort_mode_change）仍指向 App 方法，行为不变。

依赖已“洗净”：本模块只依赖 ui.theme / ui.utils / sort_utils / customtkinter / tkinter，
不依赖 legacy_app 的任何全局名 → 朝 readmes ① 的解耦目标前进。

主题自洽：Listbox 等 tk 原生控件创建时读单值 THEME["panel"] 取当前色，并经 _native 登记
bg="panel" 等角色；切主题时 theme.retheme_native 遍历同一 NATIVE_WIDGETS 列表翻色，
与 legacy 行为一致（ui.theme.THEME 与 legacy.THEME 为同一 dict 对象）。
"""

import customtkinter as ctk

from tkinter import Listbox, EXTENDED

from sort_utils import SORT_MODE_LABELS

from ..theme import T, THEME, native as _native
from ..utils import disp_font as _disp_font


def build_left_panel(app):
    """构建左侧图片列表面板。app = 主窗口 App 实例。

    写入 app 的属性（与 legacy 原方法完全相同）：
        app._sort_label_to_mode, app.image_listbox, app.status_label
    读取 app 的属性/方法：
        app._panel, app.main_paned, app.left_w, app.ui_small, app.ui_font,
        app.list_font, app.sort_var, app.on_sort_mode_change, app.on_select_image,
        app.on_remove_image, app.on_clear_all_images, app.on_edit_current_data
    """
    panel = app._panel(app.main_paned)
    app.main_paned.add(panel, width=app.left_w, minsize=240, stretch="never")

    head = ctk.CTkFrame(panel, fg_color="transparent")
    head.pack(fill="x", padx=12, pady=(12, 2))
    ctk.CTkLabel(
        head, text="图片列表", font=_disp_font(15, True), text_color=T("text"),
    ).pack(side="left")

    sort_row = ctk.CTkFrame(panel, fg_color="transparent")
    sort_row.pack(fill="x", padx=12, pady=(0, 6))
    ctk.CTkLabel(
        sort_row, text="排序", text_color=T("text_mid"), font=app.ui_small,
    ).pack(side="left")

    labels = [lbl for _, lbl in SORT_MODE_LABELS]
    app._sort_label_to_mode = {lbl: mode for mode, lbl in SORT_MODE_LABELS}
    ctk.CTkOptionMenu(
        sort_row, values=labels, variable=app.sort_var, width=160,
        font=app.ui_font, command=app.on_sort_mode_change,
    ).pack(side="left", padx=(6, 0))

    app.image_listbox = _native(
        Listbox(
            panel, selectmode=EXTENDED,
            bg=THEME["panel"], fg=THEME["text"],
            selectbackground=THEME["sel"], selectforeground=THEME["text"],
            highlightthickness=0, borderwidth=0, activestyle="none",
            font=app.list_font,
        ),
        bg="panel", fg="text", selectbackground="sel", selectforeground="text",
    )
    app.image_listbox.pack(fill="both", expand=True, padx=10, pady=4)
    app.image_listbox.bind("<<ListboxSelect>>", app.on_select_image)

    ctk.CTkButton(
        panel, text="移除选中图片",
        fg_color=T("panel"), text_color=T("text_mid"), hover_color=T("panel3"),
        font=app.ui_font, command=app.on_remove_image,
    ).pack(fill="x", padx=10, pady=(0, 4))

    ctk.CTkButton(
        panel, text="清空全部图片",
        fg_color=T("panel"), text_color=T("danger"), hover_color=T("danger_bg"),
        font=app.ui_font, command=app.on_clear_all_images,
    ).pack(fill="x", padx=10, pady=(0, 4))

    ctk.CTkButton(
        panel, text="编辑当前图片数据…",
        fg_color=T("panel3"), text_color=T("text"), hover_color=T("border2"),
        font=app.ui_font, command=app.on_edit_current_data,
    ).pack(fill="x", padx=10, pady=(0, 10))

    app.status_label = ctk.CTkLabel(
        panel, text="尚未加载图片",
        wraplength=max(120, app.left_w - 30),
        justify="left", text_color=T("text_mid"), font=app.ui_small,
    )
    app.status_label.pack(anchor="w", padx=12, pady=(0, 10))

    def _sync_left_wraplength(event):
        app.left_w = event.width
        app.status_label.configure(wraplength=max(120, event.width - 30))

    panel.bind("<Configure>", _sync_left_wraplength, add="+")