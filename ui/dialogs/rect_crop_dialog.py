# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 矩形裁剪对话框。

从旧 ui.py 的 RECT_CROP_PATCH_V1 中抽离出的 RectCropDialog。

功能：

- 拖选框
- 移动选框
- 8 手柄调整大小
- 锁定比例
- 实时像素读数
- 选框外压暗遮罩
- 三分法参考线
- 暂存到内存预览
- 另存为新文件
"""

import customtkinter as ctk
import tkinter as tk

from tkinter import (
    Canvas,
    filedialog,
    messagebox,
)

from PIL import (
    Image,
    ImageTk,
)

from .. import theme as _theme
from ..theme import (
    T,
    THEME,
)
from ..utils import disp_font


class RectCropDialog(ctk.CTkToplevel):
    """
    矩形裁剪工具。

    选框外网格遮罩压暗、选框内三分法参考线。
    底图按画布尺寸缓存，遮罩用 tk 原生 stipple，拖拽跟手。
    """

    _RATIOS = [
        "自由",
        "原图",
        "1:1",
        "4:3",
        "3:4",
        "16:9",
        "9:16",
    ]

    _dialog_version = "v1"

    def __init__(self, parent, pil_image, on_apply_callback):
        super().__init__(parent)

        self.title("✂ 矩形裁剪")
        self.geometry("1000x700")
        self.configure(fg_color=T("bg"))
        self.grab_set()

        self.pil_image = pil_image.copy()
        self.on_apply_callback = on_apply_callback
        self.orig_w, self.orig_h = self.pil_image.size

        # 相对原图 0~1 的选区
        self.crop_rel = [0.10, 0.10, 0.90, 0.90]

        # None / new / move / 手柄名
        self.mode = None
        self._anchor = None
        self._disp_cache = None

        self.lock_var = tk.BooleanVar(value=False)
        self.ratio_var = tk.StringVar(value="自由")

        self._build_ui()

        self.after(50, self._draw_canvas)

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.canvas = Canvas(
            self,
            bg=THEME["canvas"],
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )

        self.canvas.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="nsew",
            padx=10,
            pady=(10, 5),
        )

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", lambda e: self._draw_canvas())

        bar = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            corner_radius=10,
            border_width=1,
            border_color=T("border"),
        )

        bar.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=10,
            pady=(5, 10),
        )

        ctk.CTkCheckBox(
            bar,
            text="锁定比例",
            variable=self.lock_var,
            font=("Microsoft YaHei", 12),
            command=self._draw_canvas,
        ).pack(side="left", padx=(12, 6), pady=8)

        ctk.CTkOptionMenu(
            bar,
            values=self._RATIOS,
            variable=self.ratio_var,
            width=90,
            font=("Microsoft YaHei", 12),
            command=self._on_ratio_change,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            bar,
            text="全选",
            width=60,
            fg_color=T("panel3"),
            text_color=T("text"),
            hover_color=T("border2"),
            font=("Microsoft YaHei", 12),
            command=self._select_all,
        ).pack(side="left", padx=4)

        ctk.CTkButton(
            bar,
            text="清除",
            width=60,
            fg_color=T("panel3"),
            text_color=T("text"),
            hover_color=T("border2"),
            font=("Microsoft YaHei", 12),
            command=self._clear,
        ).pack(side="left", padx=4)

        self.readout = ctk.CTkLabel(
            bar,
            text="",
            text_color=T("accent"),
            font=disp_font(12, True),
        )

        self.readout.pack(side="left", padx=12)

        ctk.CTkButton(
            bar,
            text="暂存到内存预览",
            width=120,
            fg_color=T("ok"),
            hover_color=T("ok_hover"),
            text_color="white",
            command=self._apply_temp,
        ).pack(side="right", padx=6, pady=8)

        ctk.CTkButton(
            bar,
            text="另存为新文件…",
            width=120,
            fg_color=T("accent"),
            hover_color=T("accent_h"),
            text_color="white",
            command=self._save_to_file,
        ).pack(side="right", padx=6)

        ctk.CTkButton(
            bar,
            text="取消",
            width=70,
            fg_color=T("panel"),
            text_color=T("text_mid"),
            hover_color=T("panel3"),
            command=self.destroy,
        ).pack(side="right", padx=6)

    def _on_ratio_change(self, _v):
        self.lock_var.set(self.ratio_var.get() != "自由")
        self._apply_ratio_to_current()
        self._draw_canvas()

    def _ratio_value(self):
        r = self.ratio_var.get()

        if r == "自由" or not self.lock_var.get():
            return None

        if r == "原图":
            return self.orig_w / self.orig_h

        a, b = r.split(":")
        return float(a) / float(b)

    def _apply_ratio_to_current(self):
        ratio = self._ratio_value()

        if ratio is None:
            return

        x0, y0, x1, y1 = self.crop_rel
        w, h = (x1 - x0), (y1 - y0)

        if w <= 0 or h <= 0:
            return

        dw, dh, _ox, _oy, _s = self._get_disp_meta()

        # 换算到 rel 空间的目标 w/h
        target = ratio * (dh / dw) if dw and dh else ratio

        new_h = w / target if target else h
        cy = (y0 + y1) / 2

        y0 = max(0.0, min(1.0, cy - new_h / 2))
        y1 = max(0.0, min(1.0, cy + new_h / 2))

        self.crop_rel = [x0, y0, x1, y1]

    def _select_all(self):
        self.crop_rel = [0.0, 0.0, 1.0, 1.0]
        self._draw_canvas()

    def _clear(self):
        self.crop_rel = [0.45, 0.45, 0.55, 0.55]
        self._draw_canvas()

    def _get_disp_meta(self):
        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        scale = min((cw - 48) / self.orig_w, (ch - 48) / self.orig_h, 1.0)

        dw = round(self.orig_w * scale)
        dh = round(self.orig_h * scale)

        ox = (cw - dw) // 2
        oy = (ch - dh) // 2

        return dw, dh, ox, oy, scale

    def _rel_to_screen(self, rx, ry, dw, dh, ox, oy):
        return ox + rx * dw, oy + ry * dh

    def _screen_to_rel(self, sx, sy, dw, dh, ox, oy):
        rx = (sx - ox) / dw if dw else 0.0
        ry = (sy - oy) / dh if dh else 0.0

        return max(0.0, min(1.0, rx)), max(0.0, min(1.0, ry))

    def _sel_screen(self):
        dw, dh, ox, oy, _s = self._get_disp_meta()

        x0, y0 = self._rel_to_screen(self.crop_rel[0], self.crop_rel[1], dw, dh, ox, oy)
        x1, y1 = self._rel_to_screen(self.crop_rel[2], self.crop_rel[3], dw, dh, ox, oy)

        return x0, y0, x1, y1

    def _handles(self):
        x0, y0, x1, y1 = self._sel_screen()

        mx, my = (x0 + x1) / 2, (y0 + y1) / 2

        return {
            "nw": (x0, y0),
            "n": (mx, y0),
            "ne": (x1, y0),
            "e": (x1, my),
            "se": (x1, y1),
            "s": (mx, y1),
            "sw": (x0, y1),
            "w": (x0, my),
        }

    def _ensure_disp(self, dw, dh):
        size = (max(1, dw), max(1, dh))

        if self._disp_cache and self._disp_cache["size"] == size:
            return self._disp_cache["img"]

        img = ImageTk.PhotoImage(self.pil_image.resize(size, Image.BILINEAR))

        self._disp_cache = {
            "size": size,
            "img": img,
        }

        return img

    def _draw_canvas(self):
        self.canvas.delete("all")

        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())

        dw, dh, ox, oy, _s = self._get_disp_meta()

        self.canvas.create_image(
            ox,
            oy,
            anchor="nw",
            image=self._ensure_disp(dw, dh),
        )

        x0, y0, x1, y1 = self._sel_screen()

        # 选框外网格遮罩
        mask_kw = dict(
            fill="#000000",
            outline="",
            stipple="gray50",
        )

        self.canvas.create_rectangle(0, 0, cw, y0, **mask_kw)
        self.canvas.create_rectangle(0, y1, cw, ch, **mask_kw)
        self.canvas.create_rectangle(0, y0, x0, y1, **mask_kw)
        self.canvas.create_rectangle(x1, y0, cw, y1, **mask_kw)

        accent = _theme.ACCENT

        # 选框边线
        self.canvas.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            outline=accent,
            width=2,
        )

        # 三分法参考线
        for f in (1 / 3, 2 / 3):
            self.canvas.create_line(
                x0 + (x1 - x0) * f,
                y0,
                x0 + (x1 - x0) * f,
                y1,
                fill=THEME["accent"],
                width=1,
                dash=(3, 3),
            )

            self.canvas.create_line(
                x0,
                y0 + (y1 - y0) * f,
                x1,
                y0 + (y1 - y0) * f,
                fill=THEME["accent"],
                width=1,
                dash=(3, 3),
            )

        # 8 手柄
        for hx, hy in self._handles().values():
            self.canvas.create_rectangle(
                hx - 6,
                hy - 6,
                hx + 6,
                hy + 6,
                fill="#1f2329",
                outline="",
            )

            self.canvas.create_rectangle(
                hx - 5,
                hy - 5,
                hx + 5,
                hy + 5,
                fill="white",
                outline=accent,
                width=2,
            )

        # 像素读数
        w_px = (self.crop_rel[2] - self.crop_rel[0]) * self.orig_w
        h_px = (self.crop_rel[3] - self.crop_rel[1]) * self.orig_h

        ratio = (w_px / h_px) if h_px > 0 else 0

        txt = f"{int(round(w_px))} × {int(round(h_px))} px   ·   {ratio:.2f}"

        self.readout.configure(text=txt)

        tx, ty = (x0 + x1) / 2, min(y1 + 16, ch - 12)
        tw = len(txt) * 3.6 + 16

        self.canvas.create_rectangle(
            tx - tw,
            ty - 11,
            tx + tw,
            ty + 11,
            fill=THEME["panel"],
            outline=THEME["border"],
        )

        self.canvas.create_text(
            tx,
            ty,
            text=txt,
            fill=THEME["text"],
            font=disp_font(11, True),
        )

    def _hit_handle(self, ex, ey):
        for name, (hx, hy) in self._handles().items():
            if abs(ex - hx) <= 8 and abs(ey - hy) <= 8:
                return name

        return None

    def _on_press(self, event):
        h = self._hit_handle(event.x, event.y)

        if h:
            self.mode = h
            self._anchor = None
            return

        x0, y0, x1, y1 = self._sel_screen()

        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self.mode = "move"
            self._anchor = (event.x, event.y, list(self.crop_rel))
            return

        dw, dh, ox, oy, _s = self._get_disp_meta()
        rx, ry = self._screen_to_rel(event.x, event.y, dw, dh, ox, oy)

        self.mode = "new"
        self._anchor = (rx, ry)
        self.crop_rel = [rx, ry, rx, ry]

    def _on_drag(self, event):
        if not self.mode:
            return

        dw, dh, ox, oy, _s = self._get_disp_meta()
        rx, ry = self._screen_to_rel(event.x, event.y, dw, dh, ox, oy)

        if self.mode == "new":
            ax, ay = self._anchor
            self.crop_rel = [
                min(ax, rx),
                min(ay, ry),
                max(ax, rx),
                max(ay, ry),
            ]

        elif self.mode == "move":
            sx, sy, old = self._anchor

            dxr = (event.x - sx) / dw if dw else 0.0
            dyr = (event.y - sy) / dh if dh else 0.0

            w, h = old[2] - old[0], old[3] - old[1]

            nx0 = max(0.0, min(1.0 - w, old[0] + dxr))
            ny0 = max(0.0, min(1.0 - h, old[1] + dyr))

            self.crop_rel = [nx0, ny0, nx0 + w, ny0 + h]

        else:
            self._resize_handle(self.mode, rx, ry)

        self._draw_canvas()

    def _resize_handle(self, h, rx, ry):
        x0, y0, x1, y1 = self.crop_rel

        if "w" in h:
            x0 = rx

        if "e" in h:
            x1 = rx

        if "n" in h:
            y0 = ry

        if "s" in h:
            y1 = ry

        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)

        if x1 - x0 < 0.01:
            x1 = x0 + 0.01

        if y1 - y0 < 0.01:
            y1 = y0 + 0.01

        self.crop_rel = [x0, y0, x1, y1]

        if self.lock_var.get():
            self._apply_ratio_to_current()

    def _on_release(self, _event):
        self.mode = None
        self._anchor = None
        self._draw_canvas()

    def _crop_image(self):
        x0 = int(round(self.crop_rel[0] * self.orig_w))
        y0 = int(round(self.crop_rel[1] * self.orig_h))
        x1 = int(round(self.crop_rel[2] * self.orig_w))
        y1 = int(round(self.crop_rel[3] * self.orig_h))

        x0, x1 = max(0, min(x0, x1 - 1)), min(self.orig_w, max(x1, x0 + 1))
        y0, y1 = max(0, min(y0, y1 - 1)), min(self.orig_h, max(y1, y0 + 1))

        return self.pil_image.crop((x0, y0, x1, y1))

    def _apply_temp(self):
        self.on_apply_callback(self._crop_image())
        self.destroy()

    def _save_to_file(self):
        out_path = filedialog.asksaveasfilename(
            title="保存裁剪图片",
            defaultextension=".jpg",
            filetypes=[
                ("JPEG", "*.jpg"),
                ("PNG", "*.png"),
                ("所有文件", "*.*"),
            ],
        )

        if not out_path:
            return

        cropped = self._crop_image()
        cropped.save(out_path, quality=95)

        messagebox.showinfo("完成", f"已成功保存至：\n{out_path}")

        self.on_apply_callback(cropped)
        self.destroy()