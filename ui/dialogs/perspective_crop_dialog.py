# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 新版透视裁剪对话框。

基于 ui/services 服务层重写，合并旧 ui.py 中以下补丁能力：

- PerspectiveCropDialog 主类
- PERSP_SNAP_PATCH_V1：吸附边缘
- AUTOPERSP_PATCH_V1：自动识别角点、两阶段暂存
- AUTODETECT_V3 / V5 / V6 / FINALIZE_AUTODETECT_V1：自动识别策略
- REFINEBATCH_V1：四边吸附精修
- BENDSNAP_V1：边线吸附修弯曲
- AUTOPERSP_DIRECT_V1：纯函数 warp

当前通过环境变量可选启用：

    set WS_NEW_PERSPECTIVE=1
    python main.py
"""

import math
import threading
import traceback

import customtkinter as ctk
import tkinter as tk

from tkinter import (
    Canvas,
    filedialog,
    messagebox,
)

from PIL import (
    Image,
    ImageDraw,
    ImageFilter,
    ImageTk,
)

from .. import theme as _theme
from ..theme import (
    T,
    THEME,
    native,
)
from ..constants import DOT_STEP
from ..utils import disp_font

from ..services import (
    autodetect,
    edge_snap,
    geometry,
    warp,
)


_PREVIEW_LONG_EDGE = 2200
_REFINE_LONG_EDGE = 800
_BEND_K = 4


class PerspectiveCropDialog(ctk.CTkToplevel):
    """
    多锚点透视裁剪矫正对话框。
    """

    _dialog_version = "v2-services"

    def __init__(self, parent, pil_image, on_apply_callback, initial_corners=None):
        super().__init__(parent)

        self.title("📐 多锚点透视裁剪矫正")
        self.geometry("1040x740")
        self.configure(fg_color=T("bg"))
        self.grab_set()

        self.pil_image = pil_image.copy()
        self.on_apply_callback = on_apply_callback
        self.orig_w, self.orig_h = self.pil_image.size

        self.corners_rel = [
            [0.1, 0.1],
            [0.9, 0.1],
            [0.9, 0.9],
            [0.1, 0.9],
        ]

        if initial_corners:
            try:
                cs = [
                    [
                        max(0.0, min(1.0, float(c[0]))),
                        max(0.0, min(1.0, float(c[1]))),
                    ]
                    for c in initial_corners
                ]

                if len(cs) == 4:
                    self.corners_rel = cs
            except Exception:
                pass

        self.edge_points_rel = {
            0: [],
            1: [],
            2: [],
            3: [],
        }

        self.active_handle = None

        self._disp_cache = None
        self._dotgrid_cache = None
        self._mask_img = None
        self._display_edges_cache = None

        self._busy = False
        self._status_after = None
        self._busy_buttons = []

        self.snap_var = tk.BooleanVar(value=True)
        self.snap_radius_var = tk.IntVar(value=22)
        self.snap_radius = 22

        self._build_ui()

        self.after(50, self._draw_canvas)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.canvas = native(
            Canvas(
                self,
                bg=THEME["crop_canvas"],
                highlightthickness=0,
                bd=0,
            ),
            bg="crop_canvas",
        )

        self.canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=10,
            pady=(10, 5),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Configure>", lambda e: self._draw_canvas())

        # ------------------------------------------------------------
        # 主按钮栏
        # ------------------------------------------------------------
        btn_bar = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            corner_radius=10,
            border_width=1,
            border_color=T("border"),
        )

        btn_bar.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=10,
            pady=(5, 4),
        )

        ctk.CTkLabel(
            btn_bar,
            text=(
                "提示：拖拽 4 个角点定基准矩形；双击边线可新增控制点、"
                "拖拽自由调整、右键删除，用于修正弯曲边缘。"
            ),
            text_color=T("text_dim"),
            wraplength=560,
            justify="left",
            font=("Microsoft YaHei", 12),
        ).pack(side="left", padx=12)

        self.btn_apply_temp = ctk.CTkButton(
            btn_bar,
            text="暂存到内存预览",
            width=120,
            fg_color=T("ok"),
            hover_color=T("ok_hover"),
            text_color="white",
            command=self._apply_temp,
        )

        self.btn_apply_temp.pack(side="right", padx=6, pady=8)

        self.btn_save_file = ctk.CTkButton(
            btn_bar,
            text="另存为新文件…",
            width=120,
            fg_color=T("accent"),
            hover_color=T("accent_h"),
            text_color="white",
            command=self._save_to_file,
        )

        self.btn_save_file.pack(side="right", padx=6)

        self.btn_cancel = ctk.CTkButton(
            btn_bar,
            text="取消",
            width=80,
            fg_color=T("panel"),
            text_color=T("text_mid"),
            hover_color=T("panel3"),
            command=self.destroy,
        )

        self.btn_cancel.pack(side="right", padx=6)

        self.busy_label = ctk.CTkLabel(
            btn_bar,
            text="",
            text_color=T("accent"),
        )

        self.busy_label.pack(side="right", padx=10)

        self._busy_buttons.extend(
            [
                self.btn_apply_temp,
                self.btn_save_file,
                self.btn_cancel,
            ]
        )

        # ------------------------------------------------------------
        # 吸附边缘栏
        # ------------------------------------------------------------
        snap_bar = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            corner_radius=10,
            border_width=1,
            border_color=T("border"),
        )

        snap_bar.grid(
            row=2,
            column=0,
            sticky="ew",
            padx=10,
            pady=(0, 4),
        )

        ctk.CTkCheckBox(
            snap_bar,
            text="吸附边缘（拖动角点/控制点时自动贴到最近的强边缘）",
            variable=self.snap_var,
            font=("Microsoft YaHei", 12),
            fg_color=T("accent"),
            hover_color=T("accent_h"),
        ).pack(side="left", padx=(12, 8), pady=7)

        ctk.CTkLabel(
            snap_bar,
            text="吸附半径",
            text_color=T("text_mid"),
            font=("Microsoft YaHei", 11),
        ).pack(side="left", padx=(4, 2))

        ctk.CTkSlider(
            snap_bar,
            from_=8,
            to=48,
            number_of_steps=40,
            variable=self.snap_radius_var,
            command=self._on_snap_radius,
            width=130,
            progress_color=T("accent"),
            button_color=T("accent"),
        ).pack(side="left", padx=2)

        ctk.CTkLabel(
            snap_bar,
            text="  关闭可自由放置；半径越大越易吸到稍远的边。",
            text_color=T("text_dim"),
            font=("Microsoft YaHei", 11),
        ).pack(side="left", padx=6)

        # ------------------------------------------------------------
        # 自动识别栏
        # ------------------------------------------------------------
        auto_bar = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            corner_radius=10,
            border_width=1,
            border_color=T("border"),
        )

        auto_bar.grid(
            row=3,
            column=0,
            sticky="ew",
            padx=10,
            pady=(0, 4),
        )

        self.btn_auto = ctk.CTkButton(
            auto_bar,
            text="🤖 自动识别角点",
            width=140,
            fg_color=T("accent_bg"),
            hover_color=T("accent_bg"),
            text_color=T("accent_h"),
            font=("Microsoft YaHei", 12),
            command=self._on_autodetect,
        )

        self.btn_auto.pack(side="left", padx=12, pady=7)

        ctk.CTkLabel(
            auto_bar,
            text="用边缘检测自动定位箱体四边并填入；失手时给中心占位框，请手动拖角点 + 吸附微调。",
            text_color=T("text_dim"),
            font=("Microsoft YaHei", 11),
        ).pack(side="left", padx=6)

        self._busy_buttons.append(self.btn_auto)

        # ------------------------------------------------------------
        # 四边吸附精修栏
        # ------------------------------------------------------------
        refine_bar = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            corner_radius=10,
            border_width=1,
            border_color=T("border"),
        )

        refine_bar.grid(
            row=4,
            column=0,
            sticky="ew",
            padx=10,
            pady=(0, 4),
        )

        self.btn_refine = ctk.CTkButton(
            refine_bar,
            text="⚡ 四边吸附精修",
            width=132,
            fg_color=T("accent_bg"),
            hover_color=T("accent_bg"),
            text_color=T("accent_h"),
            font=("Microsoft YaHei", 12),
            command=self._on_refine_edges,
        )

        self.btn_refine.pack(side="left", padx=12, pady=7)

        ctk.CTkLabel(
            refine_bar,
            text=(
                "把当前框四条边各自贴到最近的强边：正拍/微斜一键卡准；"
                "斜拍/变形箱请配合『吸附边缘』拖四角收尾。"
            ),
            text_color=T("text_dim"),
            font=("Microsoft YaHei", 11),
        ).pack(side="left", padx=6)

        self._busy_buttons.append(self.btn_refine)

        # ------------------------------------------------------------
        # 边线吸附修弯曲栏
        # ------------------------------------------------------------
        bend_bar = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            corner_radius=10,
            border_width=1,
            border_color=T("border"),
        )

        bend_bar.grid(
            row=5,
            column=0,
            sticky="ew",
            padx=10,
            pady=(0, 8),
        )

        self.btn_bend = ctk.CTkButton(
            bend_bar,
            text="⚡ 边线吸附(修弯曲)",
            width=150,
            fg_color=T("accent_bg"),
            hover_color=T("accent_bg"),
            text_color=T("accent_h"),
            font=("Microsoft YaHei", 12),
            command=self._on_bend_refine,
        )

        self.btn_bend.pack(side="left", padx=12, pady=7)

        ctk.CTkLabel(
            bend_bar,
            text=(
                "沿四边撒点并吸到强边缘，描出弯曲/变形边；"
                "直边自动等同无修正。配合角点拖拽 + 吸附即可不靠模型修好变形箱。"
            ),
            text_color=T("text_dim"),
            font=("Microsoft YaHei", 11),
        ).pack(side="left", padx=6)

        self._busy_buttons.append(self.btn_bend)

    # ------------------------------------------------------------------
    # 基础坐标
    # ------------------------------------------------------------------

    def _get_disp_meta(self):
        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        scale = min(
            (cw - 64) / self.orig_w,
            (ch - 64) / self.orig_h,
            1.0,
        )

        dw = round(self.orig_w * scale)
        dh = round(self.orig_h * scale)

        ox = (cw - dw) // 2
        oy = (ch - dh) // 2

        return dw, dh, ox, oy, scale

    @staticmethod
    def _rel_to_screen(rel, dw, dh, ox, oy):
        return (
            ox + rel[0] * dw,
            oy + rel[1] * dh,
        )

    def _edge_order(self, edge_i):
        c0 = self.corners_rel[edge_i]
        c1 = self.corners_rel[(edge_i + 1) % 4]

        pts = self.edge_points_rel[edge_i]

        return sorted(
            range(len(pts)),
            key=lambda k: geometry.proj_t(pts[k], c0, c1),
        )

    # ------------------------------------------------------------------
    # 缓存
    # ------------------------------------------------------------------

    def _ensure_dotgrid(self, cw, ch):
        if self._dotgrid_cache and self._dotgrid_cache["size"] == (cw, ch):
            return self._dotgrid_cache["img"]

        img = Image.new(
            "RGBA",
            (max(1, cw), max(1, ch)),
            (0, 0, 0, 0),
        )

        d = ImageDraw.Draw(img)

        col = THEME["dot"]

        y = DOT_STEP // 2

        while y < ch:
            x = DOT_STEP // 2

            while x < cw:
                d.ellipse([x - 1, y - 1, x + 1, y + 1], fill=col)
                x += DOT_STEP

            y += DOT_STEP

        tkimg = ImageTk.PhotoImage(img)

        self._dotgrid_cache = {
            "size": (cw, ch),
            "img": tkimg,
        }

        return tkimg

    def _ensure_disp(self, dw, dh):
        size = (max(1, dw), max(1, dh))

        if self._disp_cache and self._disp_cache["size"] == size:
            return self._disp_cache["img"]

        img = ImageTk.PhotoImage(
            self.pil_image.resize(size, Image.BILINEAR)
        )

        self._disp_cache = {
            "size": size,
            "img": img,
        }

        return img

    def _ensure_display_edges(self):
        """
        在显示尺寸上建立边缘强度图，用于拖动吸附。
        """
        try:
            dw, dh, ox, oy, _scale = self._get_disp_meta()
        except Exception:
            return None

        if dw < 8 or dh < 8:
            return None

        key = (dw, dh)

        cache = self._display_edges_cache

        if cache is not None and cache.get("key") == key:
            return cache

        try:
            small = self.pil_image.resize((dw, dh), Image.BILINEAR)

            g = small.convert("L")
            g = g.filter(ImageFilter.GaussianBlur(2))

            e = g.filter(ImageFilter.FIND_EDGES).convert("L")
            e = e.filter(ImageFilter.GaussianBlur(1))

            flat = list(e.getdata())
            emax = int(e.getextrema()[1])

            self._display_edges_cache = {
                "key": key,
                "flat": flat,
                "w": dw,
                "h": dh,
                "emax": emax,
            }

            return self._display_edges_cache

        except Exception:
            self._display_edges_cache = None
            return None

    # ------------------------------------------------------------------
    # 绘制
    # ------------------------------------------------------------------

    def _draw_anchor_dot(self, px, py, active=False):
        accent = _theme.ACCENT

        r = 12 if not active else 14

        self.canvas.create_oval(
            px - r - 3,
            py - r - 3,
            px + r + 3,
            py + r + 3,
            fill="#1f2329",
            outline="",
            tags="anchor",
        )

        self.canvas.create_oval(
            px - r,
            py - r,
            px + r,
            py + r,
            fill="#ffffff",
            outline=accent,
            width=4,
            tags="anchor",
        )

        cr = 4

        self.canvas.create_oval(
            px - cr,
            py - cr,
            px + cr,
            py + cr,
            fill=(THEME["accent_h"] if active else accent),
            outline="",
            tags="anchor",
        )

    def _draw_anchor_square(self, mx, my, active=False):
        accent = _theme.ACCENT

        r = 7

        self.canvas.create_rectangle(
            mx - r - 2,
            my - r - 2,
            mx + r + 2,
            my + r + 2,
            fill="#1f2329",
            outline="",
            tags="anchor",
        )

        self.canvas.create_rectangle(
            mx - r,
            my - r,
            mx + r,
            my + r,
            fill=(accent if active else "#ffffff"),
            outline=accent,
            width=3,
            tags="anchor",
        )

    def _draw_canvas(self):
        self.canvas.delete("all")

        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        self.canvas.create_image(
            0,
            0,
            anchor="nw",
            image=self._ensure_dotgrid(cw, ch),
        )

        dw, dh, ox, oy, _scale = self._get_disp_meta()

        self.canvas.create_image(
            ox,
            oy,
            anchor="nw",
            image=self._ensure_disp(dw, dh),
        )

        corners_screen = [
            self._rel_to_screen(p, dw, dh, ox, oy)
            for p in self.corners_rel
        ]

        # 选区外压暗遮罩
        try:
            mask = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            md = ImageDraw.Draw(mask)

            md.rectangle([0, 0, cw, ch], fill=(0, 0, 0, 150))

            md.polygon(
                [tuple(map(int, p)) for p in corners_screen],
                fill=(0, 0, 0, 0),
            )

            self._mask_img = ImageTk.PhotoImage(mask)

            self.canvas.create_image(
                0,
                0,
                anchor="nw",
                image=self._mask_img,
            )

        except Exception:
            pass

        accent = _theme.ACCENT

        # 边线 + 边控制点
        for i in range(4):
            order = self._edge_order(i)

            chain = [corners_screen[i]]

            chain += [
                self._rel_to_screen(
                    self.edge_points_rel[i][k],
                    dw,
                    dh,
                    ox,
                    oy,
                )
                for k in order
            ]

            chain.append(corners_screen[(i + 1) % 4])

            for j in range(len(chain) - 1):
                x1, y1 = chain[j]
                x2, y2 = chain[j + 1]

                self.canvas.create_line(
                    x1,
                    y1,
                    x2,
                    y2,
                    fill=accent,
                    width=3,
                    dash=(8, 4),
                    tags="anchor",
                )

            for k in order:
                mx, my = self._rel_to_screen(
                    self.edge_points_rel[i][k],
                    dw,
                    dh,
                    ox,
                    oy,
                )

                self._draw_anchor_square(
                    mx,
                    my,
                    active=(self.active_handle == ("edge", i, k)),
                )

        # 角点
        for i, (px, py) in enumerate(corners_screen):
            self._draw_anchor_dot(
                px,
                py,
                active=(self.active_handle == ("corner", i)),
            )

        # 实时像素读数
        try:
            cpx = [
                (rx * self.orig_w, ry * self.orig_h)
                for rx, ry in self.corners_rel
            ]

            w_px = 0.5 * (
                math.hypot(cpx[1][0] - cpx[0][0], cpx[1][1] - cpx[0][1])
                + math.hypot(cpx[2][0] - cpx[3][0], cpx[2][1] - cpx[3][1])
            )

            h_px = 0.5 * (
                math.hypot(cpx[3][0] - cpx[0][0], cpx[3][1] - cpx[0][1])
                + math.hypot(cpx[2][0] - cpx[1][0], cpx[2][1] - cpx[1][1])
            )

            txt = "基准框 ≈ %d × %d px" % (
                int(round(w_px)),
                int(round(h_px)),
            )

            tcx = sum(p[0] for p in corners_screen) / 4
            tcy = max(14, min(p[1] for p in corners_screen) - 14)

            tw = len(txt) * 3.6 + 14

            self.canvas.create_rectangle(
                tcx - tw,
                tcy - 11,
                tcx + tw,
                tcy + 11,
                fill=THEME["panel"],
                outline=THEME["border"],
            )

            self.canvas.create_text(
                tcx,
                tcy,
                text=txt,
                fill=THEME["text"],
                font=disp_font(11, True),
            )

        except Exception:
            pass

        # 保持边缘缓存就绪
        try:
            if self.snap_var.get():
                self._ensure_display_edges()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 交互
    # ------------------------------------------------------------------

    def _on_snap_radius(self, v):
        try:
            self.snap_radius = int(float(v))
        except Exception:
            pass

    def _on_press(self, event):
        dw, dh, ox, oy, _scale = self._get_disp_meta()

        corners_screen = [
            self._rel_to_screen(p, dw, dh, ox, oy)
            for p in self.corners_rel
        ]

        for i, (px, py) in enumerate(corners_screen):
            if abs(event.x - px) <= 16 and abs(event.y - py) <= 16:
                self.active_handle = ("corner", i)
                self._draw_canvas()
                return

        for i in range(4):
            for k, pt in enumerate(self.edge_points_rel[i]):
                mx, my = self._rel_to_screen(pt, dw, dh, ox, oy)

                if abs(event.x - mx) <= 12 and abs(event.y - my) <= 12:
                    self.active_handle = ("edge", i, k)
                    self._draw_canvas()
                    return

    def _on_drag(self, event):
        if self.active_handle is None:
            return

        dw, dh, ox, oy, _scale = self._get_disp_meta()

        if dw <= 0 or dh <= 0:
            return

        lx = event.x - ox
        ly = event.y - oy

        if self.snap_var.get():
            cache = self._ensure_display_edges()

            if cache is not None:
                try:
                    nlx, nly = edge_snap.snap_point(
                        cache["flat"],
                        cache["w"],
                        cache["h"],
                        cache["emax"],
                        lx,
                        ly,
                        int(getattr(self, "snap_radius", 22)),
                    )

                    lx, ly = nlx, nly

                except Exception:
                    pass

        rx = max(0.0, min(1.0, lx / dw))
        ry = max(0.0, min(1.0, ly / dh))

        kind = self.active_handle[0]

        if kind == "corner":
            self.corners_rel[self.active_handle[1]] = [rx, ry]

        elif kind == "edge":
            _, edge_i, pt_idx = self.active_handle
            self.edge_points_rel[edge_i][pt_idx] = [rx, ry]

        self._draw_canvas()

    def _on_release(self, _event):
        self.active_handle = None
        self._draw_canvas()

    def _on_double_click(self, event):
        dw, dh, ox, oy, _scale = self._get_disp_meta()

        corners_screen = [
            self._rel_to_screen(p, dw, dh, ox, oy)
            for p in self.corners_rel
        ]

        best_edge = None
        best_dist = 20.0

        for i in range(4):
            order = self._edge_order(i)

            chain = [corners_screen[i]]

            chain += [
                self._rel_to_screen(
                    self.edge_points_rel[i][k],
                    dw,
                    dh,
                    ox,
                    oy,
                )
                for k in order
            ]

            chain.append(corners_screen[(i + 1) % 4])

            for j in range(len(chain) - 1):
                dist = geometry.point_seg_dist(
                    event.x,
                    event.y,
                    chain[j],
                    chain[j + 1],
                )

                if dist < best_dist:
                    best_dist = dist
                    best_edge = i

        if best_edge is None:
            return

        lx = event.x - ox
        ly = event.y - oy

        if self.snap_var.get():
            cache = self._ensure_display_edges()

            if cache is not None:
                try:
                    nlx, nly = edge_snap.snap_point(
                        cache["flat"],
                        cache["w"],
                        cache["h"],
                        cache["emax"],
                        lx,
                        ly,
                        int(getattr(self, "snap_radius", 22)),
                    )

                    lx, ly = nlx, nly

                except Exception:
                    pass

        rx = max(0.0, min(1.0, lx / dw)) if dw else 0.0
        ry = max(0.0, min(1.0, ly / dh)) if dh else 0.0

        self.edge_points_rel[best_edge].append([rx, ry])

        self._draw_canvas()

    def _on_right_click(self, event):
        dw, dh, ox, oy, _scale = self._get_disp_meta()

        for i in range(4):
            for k, pt in enumerate(self.edge_points_rel[i]):
                mx, my = self._rel_to_screen(pt, dw, dh, ox, oy)

                if abs(event.x - mx) <= 12 and abs(event.y - my) <= 12:
                    del self.edge_points_rel[i][k]

                    if self.active_handle == ("edge", i, k):
                        self.active_handle = None

                    self._draw_canvas()
                    return

    # ------------------------------------------------------------------
    # 自动识别 / 精修
    # ------------------------------------------------------------------

    def _on_autodetect(self):
        if self._busy:
            return

        self._set_busy(True, "正在自动识别…")

        def worker():
            cs = None

            try:
                cs = autodetect.autodetect_corners(self.pil_image)
            except Exception:
                cs = None

            self.after(0, lambda: self._finish_autodetect(cs))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_autodetect(self, cs):
        self._set_busy(False)

        if cs is None:
            cs = autodetect.center_fallback()

        self.corners_rel = cs

        self.edge_points_rel = {
            0: [],
            1: [],
            2: [],
            3: [],
        }

        self._draw_canvas()

    def _on_refine_edges(self):
        if self._busy:
            return

        try:
            new_corners = edge_snap.refine_box_edges(
                self.pil_image,
                self.corners_rel,
                long_edge=_REFINE_LONG_EDGE,
            )
        except Exception:
            new_corners = None

        if new_corners is None:
            self._show_status("未找到可吸附的强边")
            return

        self.corners_rel = new_corners

        self.edge_points_rel = {
            0: [],
            1: [],
            2: [],
            3: [],
        }

        self._draw_canvas()
        self._show_status("已完成四边吸附精修")

    def _on_bend_refine(self):
        if self._busy:
            return

        try:
            new_edges = edge_snap.bend_refine_edge_points(
                self.pil_image,
                self.corners_rel,
                k=_BEND_K,
                long_edge=_REFINE_LONG_EDGE,
                snap_radius_ratio=0.03,
            )
        except Exception:
            new_edges = None

        if new_edges is None:
            self._show_status("边线吸附失败")
            return

        self.edge_points_rel = new_edges

        self._draw_canvas()
        self._show_status("已完成边线吸附")

    # ------------------------------------------------------------------
    # 变换 / 导出
    # ------------------------------------------------------------------

    def _do_transform(self):
        return warp.warp_corners(
            self.pil_image,
            self.corners_rel,
            self.edge_points_rel,
        )

    def _do_preview_transform(self):
        return warp.warp_scaled(
            self.pil_image,
            self.corners_rel,
            _PREVIEW_LONG_EDGE,
            self.edge_points_rel,
        )

    def _set_busy(self, busy, text=""):
        self._busy = busy

        self.busy_label.configure(text=text)

        state = "disabled" if busy else "normal"

        for btn in self._busy_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _show_status(self, text):
        self.busy_label.configure(text=text)

        if self._status_after:
            try:
                self.after_cancel(self._status_after)
            except Exception:
                pass

        self._status_after = self.after(
            2600,
            lambda: self.busy_label.configure(text=""),
        )

    def _notify(self, warped, is_final=True):
        try:
            self.on_apply_callback(warped, is_final)
        except TypeError:
            try:
                self.on_apply_callback(warped)
            except Exception:
                traceback.print_exc()
        except Exception:
            traceback.print_exc()

    def _finish_error(self, exc):
        self._set_busy(False)
        messagebox.showerror("错误", f"透视变换失败：{exc}")

    def _apply_temp(self):
        if self._busy:
            return

        self._set_busy(True, "正在生成结果，请稍候…")

        def worker():
            preview = None

            try:
                preview = self._do_preview_transform()
            except Exception:
                preview = None

            if preview is not None:
                self.after(0, lambda: self._notify(preview, False))

            full = None

            try:
                full = self._do_transform()
            except Exception as exc:
                self.after(0, lambda e=exc: self._finish_error(e))
                return

            self.after(0, lambda: self._finish_apply_full(full))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_apply_full(self, full):
        self._set_busy(False)

        self._notify(full, True)

        try:
            self.destroy()
        except Exception:
            pass

    def _save_to_file(self):
        out_path = filedialog.asksaveasfilename(
            title="保存透视裁剪图片",
            defaultextension=".jpg",
            filetypes=[
                ("JPEG", "*.jpg"),
                ("PNG", "*.png"),
                ("所有文件", "*.*"),
            ],
        )

        if not out_path:
            return

        if self._busy:
            return

        self._set_busy(True, "正在生成结果，请稍候…")

        def worker():
            full = None

            try:
                full = self._do_transform()
            except Exception as exc:
                self.after(0, lambda e=exc: self._finish_error(e))
                return

            self.after(0, lambda: self._finish_save(full, out_path))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_save(self, full, out_path):
        self._set_busy(False)

        try:
            full.save(out_path, quality=95)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return

        messagebox.showinfo("完成", f"已成功保存至：\n{out_path}")

        self._notify(full, True)

        try:
            self.destroy()
        except Exception:
            pass