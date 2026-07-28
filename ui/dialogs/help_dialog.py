# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 帮助窗口。

从旧 ui.py 的 App._show_help 中抽离。
"""

import os

import customtkinter as ctk

from ..theme import T
from ..utils import disp_font
from ..constants import (
    _PREF_DIR,
    _WELCOME_FLAG,
)


def show_help(app):
    """
    显示首次进入帮助窗口。

    参数：
        app: 主窗口 App 实例
    """
    try:
        os.makedirs(_PREF_DIR, exist_ok=True)

        with open(_WELCOME_FLAG, "w", encoding="utf-8") as f:
            f.write("1")
    except Exception:
        pass

    win = ctk.CTkToplevel(app)
    win.title("使用帮助 · 4 步上手")
    win.geometry("560x600")
    win.configure(fg_color=T("bg"))
    win.grab_set()

    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(1, weight=1)

    wrap_labels = []

    head = ctk.CTkFrame(win, fg_color="transparent")
    head.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 6))

    ctk.CTkLabel(
        head,
        text="水印标注工坊 · 快速上手",
        font=disp_font(18, True),
        text_color=T("text"),
    ).pack(anchor="w")

    d0 = ctk.CTkLabel(
        head,
        text="给岩心箱 / 探槽照片批量加水印标注，按表格自动填字段、按规则批量导出。",
        text_color=T("text_mid"),
        justify="left",
        font=app.ui_font,
    )

    d0.pack(anchor="w", pady=(2, 0))
    wrap_labels.append(d0)

    body = ctk.CTkScrollableFrame(win, fg_color=T("panel2"))
    body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(6, 12))
    body.grid_columnconfigure(0, weight=1)

    steps = [
        (
            "① 导入照片",
            "点左上『打开图片』选多张，或『打开文件夹』整目录导入。左侧列表默认按文件名自然排序（1箱、2箱…10箱）。",
        ),
        (
            "② 摆好水印",
            "右侧『元素列表』选中元素，在中间画布上直接拖动定位、拖右下角手柄缩放；右侧属性面板改文字/字体/字号/颜色/阴影。文字里用 {钻孔编号} {箱数} {孔深起} {孔深止} 这类占位符。",
        ),
        (
            "③ 导入数据表",
            "点『导入数据表』选 Excel/CSV，每行对应一张图。弹窗会实时显示『预计匹配 X / N 张』——为 0 时改选『按顺序对应』即可。",
        ),
        (
            "④ 批量导出",
            "底部填『导出文件名规则』（同样支持 {字段名}），点右下绿色『批量导出全部』，按规则重命名导出，重名自动加序号。",
        ),
    ]

    r = 0

    for title, desc in steps:
        card = ctk.CTkFrame(
            body,
            fg_color=T("panel"),
            corner_radius=8,
            border_width=1,
            border_color=T("border"),
        )

        card.grid(row=r, column=0, sticky="ew", pady=5)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            card,
            text=title,
            font=app.ui_font_b,
            text_color=T("accent"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))

        dl = ctk.CTkLabel(
            card,
            text=desc,
            text_color=T("text_mid"),
            justify="left",
            anchor="w",
            font=app.ui_font,
        )

        dl.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        wrap_labels.append(dl)

        r += 1

    tips = ctk.CTkFrame(body, fg_color="transparent")
    tips.grid(row=r, column=0, sticky="ew", pady=(6, 4))
    tips.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(
        tips,
        text="小技巧",
        font=app.ui_font_b,
        text_color=T("text"),
        anchor="w",
    ).grid(row=0, column=0, sticky="ew")

    tr = 1

    tip_lines = [
        "· 画布滚轮缩放、中键/空白拖动平移；双击在『1:1 实际像素』与适应窗口间切换；上方/左侧标尺显示原图像素。",
        "· 右键元素可复制/置顶/置底/删除；右键空白可在此新增元素或透视裁剪。",
        "· 『★ 水印库』把调好的排版存起来，下次一键套用；『保存/加载模板』存成 .json。",
        "· 右上角 ☀/🌙 切换亮/暗主题，瞬时切换并自动记住。",
    ]

    for t in tip_lines:
        tl = ctk.CTkLabel(
            tips,
            text=t,
            text_color=T("text_dim"),
            justify="left",
            anchor="w",
            font=app.ui_small,
        )

        tl.grid(row=tr, column=0, sticky="ew", pady=1)
        wrap_labels.append(tl)

        tr += 1

    ctk.CTkButton(
        win,
        text="知道了",
        width=120,
        fg_color=T("accent"),
        hover_color=T("accent_h"),
        text_color="white",
        command=win.destroy,
    ).grid(row=2, column=0, pady=(0, 16))

    def _reflow(_e=None):
        wl = max(220, win.winfo_width() - 80)

        for lb in wrap_labels:
            try:
                lb.configure(wraplength=wl)
            except Exception:
                pass

    _reflow()
    win.bind("<Configure>", _reflow)