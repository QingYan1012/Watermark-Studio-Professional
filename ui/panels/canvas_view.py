# -*- coding: utf-8 -*-
"""画布构建（从 legacy App._build_canvas 物理搬迁，第46轮）。

逐行 self->app 改名，闭包 _xscroll/_yscroll/_sync_hint_wraplength 与两处 lambda 同步
把 self 换成 app，行为与 legacy 993-1058 逐字等价；零“顺手优化”，错的概率压到机械级。
保留全部 self 属性：ruler_corner/ruler_top/ruler_left/canvas/_resize_after_id/
canvas_zoom_label/canvas_tip_label/canvas_warning_label —— 缺一则标尺/缩放标签/空状态
警告/resize 节流失联。

时序安全（由第44轮“Smart Output 下拉仍在”反证：桥接先于 performance_patch 执行）：
桥接版完整自建画布后，performance_patch 的 _install_canvas_interactions_fix 在其后包装，
其 orig(self) 即本桥接版 → 自建 canvas 并 bind 了 zoom/resize → 包装层再 unbind 滚轮、
重绑 Configure 到节流版。故滚轮缩放仍被取消、拖窗口仍节流。若该时序不成立，第4项验证
（滚轮不应缩放）会立刻暴露，属确定性可查错，非渲染猜测。
wrap 走 app._panel（已被直角终结者改直角无描边），tk Canvas 无圆角概念 → 画布区无边角病。
"""
import customtkinter as ctk

from tkinter import Canvas, Scrollbar

from ..theme import T, THEME, native as _native
from ..utils import disp_font as _disp_font
from ..constants import RULER


def build_canvas(app):
    wrap = app._panel(app.main_paned)
    app.main_paned.add(wrap, minsize=300, stretch="always")
    for r in (0, 1):
        wrap.grid_rowconfigure(r, weight=0)
    wrap.grid_rowconfigure(1, weight=1)
    wrap.grid_columnconfigure(1, weight=1)
    # 标尺布局：角块(0,0) 上标尺(0,1) 左标尺(1,0) 主画布(1,1)
    app.ruler_corner = _native(Canvas(wrap, width=RULER, height=RULER, bg=THEME["ruler"],
                                      highlightthickness=0, bd=0), bg="ruler")
    app.ruler_corner.grid(row=0, column=0, sticky="nsew")
    app.ruler_top = _native(Canvas(wrap, height=RULER, bg=THEME["ruler"], highlightthickness=0, bd=0), bg="ruler")
    app.ruler_top.grid(row=0, column=1, sticky="ew")
    app.ruler_left = _native(Canvas(wrap, width=RULER, bg=THEME["ruler"], highlightthickness=0, bd=0), bg="ruler")
    app.ruler_left.grid(row=1, column=0, sticky="ns")
    app.canvas = _native(Canvas(wrap, bg=THEME["canvas"], highlightthickness=0, bd=0), bg="canvas")
    app.canvas.grid(row=1, column=1, sticky="nsew")
    vbar = Scrollbar(wrap, orient="vertical", command=app.canvas.yview)
    vbar.grid(row=1, column=2, sticky="ns")
    hbar = Scrollbar(wrap, orient="horizontal", command=app.canvas.xview)
    hbar.grid(row=2, column=1, sticky="ew")

    def _xscroll(*a):
        hbar.set(*a)
        try:
            app.ruler_top.xview_moveto(float(a[0]))
        except Exception:
            pass

    def _yscroll(*a):
        vbar.set(*a)
        try:
            app.ruler_left.yview_moveto(float(a[0]))
        except Exception:
            pass

    app.canvas.configure(xscrollcommand=_xscroll, yscrollcommand=_yscroll)
    app.canvas.bind("<ButtonPress-1>", app.on_canvas_press)
    app.canvas.bind("<B1-Motion>", app.on_canvas_drag)
    app.canvas.bind("<ButtonRelease-1>", app.on_canvas_release)
    app.canvas.bind("<Button-3>", app.on_canvas_right_click)
    app.canvas.bind("<Configure>", app._on_canvas_resize)
    app.canvas.bind("<MouseWheel>", app._on_canvas_zoom)
    app.canvas.bind("<Button-4>", app._on_canvas_zoom)
    app.canvas.bind("<Button-5>", app._on_canvas_zoom)
    app.canvas.bind("<ButtonPress-2>", lambda e: app.canvas.scan_mark(e.x, e.y))
    app.canvas.bind("<B2-Motion>", lambda e: app.canvas.scan_dragto(e.x, e.y, gain=1))
    app.canvas.bind("<Double-Button-1>", app._on_canvas_double_click)
    app._resize_after_id = None
    app.canvas_zoom_label = ctk.CTkLabel(app.canvas, text="100%", fg_color=T("panel"),
                                         text_color=T("accent"), corner_radius=6,
                                         font=_disp_font(12, True))
    app.canvas_zoom_label.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
    app.canvas_tip_label = ctk.CTkLabel(
        wrap, text="提示：滚轮缩放；中键/空白拖动平移；双击在 1:1 与适应窗口间切换；上/左标尺显示原图像素。拖动元素调位置，选中后拖右下角手柄缩放。",
        text_color=T("text_mid"), wraplength=900, justify="left", font=app.ui_small)
    app.canvas_tip_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(3, 0))
    app.canvas_warning_label = ctk.CTkLabel(
        wrap, text="", text_color=T("warn"), anchor="w", justify="left", wraplength=900, font=app.ui_small)
    app.canvas_warning_label.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 3))

    def _sync_hint_wraplength(event):
        wl = max(200, event.width - 16)
        app.canvas_tip_label.configure(wraplength=wl)
        app.canvas_warning_label.configure(wraplength=wl)

    wrap.bind("<Configure>", _sync_hint_wraplength, add="+")