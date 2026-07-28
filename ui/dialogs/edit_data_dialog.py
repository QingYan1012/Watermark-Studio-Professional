# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 编辑当前图片数据窗口。

从旧 ui.py 的 App.on_edit_current_data 中抽离。
"""

import os
import re

import customtkinter as ctk

from tkinter import (
    StringVar,
    messagebox,
)

from ..theme import T


def edit_current_data(app):
    """
    编辑当前图片的数据字段。

    参数：
        app: 主窗口 App 实例
    """
    if app.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。")
        return

    entry = app.images[app.current_index]

    keys = set(entry.data.keys())

    for elem in app.template.elements:
        if elem.type == "text":
            keys.update(re.findall(r"\{([^{}]+)\}", elem.content))

    keys = sorted(keys)

    if not keys:
        messagebox.showinfo(
            "提示",
            "当前文字元素里没有 {字段名} 占位符，且未导入表格数据。",
        )
        return

    win = ctk.CTkToplevel(app)
    win.title(f"编辑数据 - {os.path.basename(entry.path)}")
    win.geometry("360x" + str(80 + 40 * len(keys)))
    win.configure(fg_color=T("bg"))
    win.grab_set()

    vars_map = {}

    for i, k in enumerate(keys):
        ctk.CTkLabel(
            win,
            text=k,
            width=100,
            anchor="w",
            font=app.ui_font,
        ).grid(row=i, column=0, padx=10, pady=6, sticky="w")

        v = StringVar(value=entry.data.get(k, ""))

        ctk.CTkEntry(
            win,
            textvariable=v,
            width=200,
            font=app.ui_font,
        ).grid(row=i, column=1, padx=10, pady=6)

        vars_map[k] = v

    def save_and_close():
        for k, v in vars_map.items():
            entry.data[k] = v.get()

        win.destroy()
        app._redraw_canvas()

    ctk.CTkButton(
        win,
        text="保存",
        fg_color=T("accent"),
        hover_color=T("accent_h"),
        text_color="white",
        font=app.ui_font,
        command=save_and_close,
    ).grid(row=len(keys), column=0, columnspan=2, pady=10)