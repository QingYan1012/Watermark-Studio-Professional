# -*- coding: utf-8 -*-
"""底栏构建（从 legacy App._build_bottom_bar 物理搬迁，第44轮；第53轮加文件名规则插入变量）。

逐行 self->app 改名，行为与 legacy 等价。第53轮在“导出文件名规则”输入框旁加“插入变量”
下拉，与文字内容那处同源（system_vars 系统变量 + 数据表字段），选中即插入规则框光标处——
让 {图片序号}/{文件名} 等在文件名规则里也“可发现、点一下就有”，不用记中文花括号语法。
"""
import customtkinter as ctk

from tkinter import StringVar

from ..theme import T


def build_bottom_bar(app):
    # 弹性网格：左区(规则+提示)可压缩，右区(导出)固定靠右，窄窗口下绝不重叠
    bar = ctk.CTkFrame(app, height=64, corner_radius=10, fg_color=T("panel"),
                       border_width=1, border_color=T("border"))
    bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(5, 8))
    app._bottom_bar = bar
    bar.grid_columnconfigure(0, weight=1)
    bar.grid_columnconfigure(1, weight=0)
    left = ctk.CTkFrame(bar, fg_color="transparent")
    left.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=8)
    ctk.CTkLabel(left, text="导出文件名规则", text_color=T("text_mid"), font=app.ui_font).pack(side="left", padx=(0, 4))
    _rename_entry = ctk.CTkEntry(left, textvariable=app.rename_var, width=220, font=app.ui_font)
    _rename_entry.pack(side="left", padx=2)

    # 【第53轮】文件名规则插入变量：选中即插入规则输入框光标处。
    try:
        from ..services.system_vars import known_system_vars
        _sys_names = ["{%s}" % n for n in known_system_vars()]
    except Exception:
        _sys_names = []
    _field_names = ["{%s}" % c for c in (getattr(app, "_data_columns", None) or [])]
    _var_options = ["插入变量…"] + _sys_names + _field_names
    _insert_var = StringVar(value="插入变量…")

    def on_insert_var(v):
        if v and v != "插入变量…":
            try:
                _rename_entry.insert("insert", v)
            except Exception:
                pass
        _insert_var.set("插入变量…")

    ctk.CTkOptionMenu(left, values=_var_options, variable=_insert_var, width=100,
                      font=app.ui_font, command=on_insert_var).pack(side="left", padx=(4, 0))

    app.output_dir_label = ctk.CTkLabel(left, text="  （用 {字段名} 引用表格列，留空沿用原文件名）",
                                        text_color=T("text_dim"), font=app.ui_small)
    app.output_dir_label.pack(side="left", padx=(6, 0))
    right = ctk.CTkFrame(bar, fg_color="transparent")
    right.grid(row=0, column=1, sticky="e", padx=8, pady=8)
    app.btn_output_dir = ctk.CTkButton(right, text="选择输出目录", width=100, fg_color=T("panel3"),
                                       text_color=T("text"), hover_color=T("border2"),
                                       font=app.ui_font, command=app.on_choose_output_dir)
    app.btn_output_dir.pack(side="left", padx=4)
    app.progress = ctk.CTkProgressBar(right, width=140, progress_color=T("accent"), fg_color=T("panel3"))
    app.progress.set(0)
    app.progress.pack(side="left", padx=8)
    app.btn_batch_export = ctk.CTkButton(right, text="批量导出全部", width=120, fg_color=T("ok"),
                                         hover_color=T("ok_hover"), text_color="white",
                                         font=app.ui_font_b, command=app.on_batch_export)
    app.btn_batch_export.pack(side="left", padx=4)
    app.btn_export_current = ctk.CTkButton(right, text="导出当前", width=84, fg_color=T("panel3"),
                                           text_color=T("text"), hover_color=T("border2"),
                                           font=app.ui_font, command=app.on_export_current)
    app.btn_export_current.pack(side="left", padx=4)