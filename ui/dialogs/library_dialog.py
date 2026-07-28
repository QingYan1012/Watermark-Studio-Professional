# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 水印库窗口。

从旧 ui.py 的 App.on_open_library 中抽离。
"""

import os

import customtkinter as ctk

from tkinter import (
    StringVar,
    messagebox,
)

import library

from ..theme import T


def open_library(app):
    """
    打开水印库窗口。

    参数：
        app: 主窗口 App 实例
    """
    win = ctk.CTkToplevel(app)
    win.title("水印库")
    win.geometry("460x480")
    win.configure(fg_color=T("bg"))
    win.grab_set()

    top = ctk.CTkFrame(win, fg_color="transparent")
    top.pack(fill="x", padx=14, pady=(14, 6))

    ctk.CTkLabel(
        top,
        text="把常用的水印排版存起来，随时一键套用到当前工程。",
        text_color=T("text_dim"),
        wraplength=420,
        justify="left",
        font=app.ui_font,
    ).pack(anchor="w")

    save_row = ctk.CTkFrame(win, fg_color="transparent")
    save_row.pack(fill="x", padx=14, pady=(0, 10))

    name_var = StringVar(value=app.template.name or "我的水印")

    ctk.CTkEntry(
        save_row,
        textvariable=name_var,
        width=240,
        font=app.ui_font,
    ).pack(side="left")

    def do_save():
        saved_path = library.save_preset(app.template, name_var.get())

        messagebox.showinfo(
            "已保存",
            f"当前模板已存入水印库：\n{os.path.basename(saved_path)}",
        )

        refresh_list()

    ctk.CTkButton(
        save_row,
        text="将当前模板存入库",
        command=do_save,
        width=160,
        fg_color=T("purple"),
        hover_color="#6950e0",
        text_color="white",
        font=app.ui_font,
    ).pack(side="left", padx=8)

    list_frame = ctk.CTkScrollableFrame(
        win,
        label_text="已保存的水印",
        fg_color=T("panel2"),
        label_fg_color=T("panel2"),
        label_text_color=T("text"),
    )

    list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    def refresh_list():
        for w in list_frame.winfo_children():
            w.destroy()

        presets = library.list_presets()

        if not presets:
            ctk.CTkLabel(
                list_frame,
                text="水印库还是空的，先调好一套排版，点上方按钮存进来吧。",
                text_color=T("text_dim"),
                wraplength=380,
                justify="left",
                font=app.ui_font,
            ).pack(pady=16)
            return

        for display_name, path, _ts in presets:
            row = ctk.CTkFrame(
                list_frame,
                fg_color=T("panel"),
                corner_radius=8,
                border_width=1,
                border_color=T("border"),
            )

            row.pack(fill="x", pady=4)

            ctk.CTkLabel(
                row,
                text=display_name,
                anchor="w",
                text_color=T("text"),
                font=app.ui_font,
            ).pack(side="left", padx=10, pady=8, fill="x", expand=True)

            def apply_it(p=path):
                try:
                    app.template = library.load_preset(p)
                except Exception as e:
                    messagebox.showerror("应用失败", str(e))
                    return

                app._refresh_element_list()

                app._select_element(
                    app.template.elements[0].id if app.template.elements else None
                )

                app._redraw_canvas()
                win.destroy()

            def delete_it(p=path):
                if messagebox.askyesno("删除", "确定从水印库删除这一项吗？"):
                    library.delete_preset(p)
                    refresh_list()

            ctk.CTkButton(
                row,
                text="应用",
                width=58,
                fg_color=T("accent_bg"),
                text_color=T("accent_h"),
                hover_color=T("accent_bg"),
                font=app.ui_font,
                command=apply_it,
            ).pack(side="left", padx=4)

            ctk.CTkButton(
                row,
                text="删除",
                width=58,
                fg_color=T("panel"),
                text_color=T("danger"),
                hover_color=T("danger_bg"),
                font=app.ui_font,
                command=delete_it,
            ).pack(side="left", padx=(0, 8))

    refresh_list()