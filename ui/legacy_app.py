# -- coding: utf-8 --
"""
水印标注工坊 - 主界面（v7：双态颜色架构 + 标尺 + 自适应 + 透视加粗）

本轮根因级改动：
- 双态颜色架构：所有 CTk 控件创建时用 T(role)=(亮,暗) 元组，切换主题只调
  set_appearance_mode，CTk 自动翻色，【不销毁重建、不闪、不重渲染水印】；
  tk 原生控件(Canvas/Listbox/PanedWindow)登记到 _NATIVE_WIDGETS，切换时统一翻色；
  画布 PIL 氛围层(点阵/阴影/标尺/选中框)用单值 THEME，切换时重画一次。
  → 切换主题从“整窗重建+整画布重渲染(卡+闪)”变为“翻开关+一次画布重绘(近乎瞬时)”。
- 画布标尺：上方+左侧固定标尺，显示原图像素刻度，随缩放/滚动同步，刻度疏密自适应。
- 工具栏紧凑 + 底栏弹性网格 + minsize 提升 → 未最大化不重叠/不丢按钮。
- 透视裁剪：矫正线加粗、锚点放大加描边、四周留白加大(防贴边裁切)。
- 静止补帧渲染封顶 3200→2200 → 最大化重绘更快；导出始终原图全清，不受影响。
- 字号固定逻辑像素(不乘 scale)：CTk 已按系统 DPI 缩放字号，手动乘会双重放大→字过大/截断。
保留：亮/暗记忆、首次 4 步引导(grid 对齐)、双击 1:1↔适应、拖拽 canvasx、匹配实时预估+智能默认、
导入/导出后台线程+toast、缩放 scale≤1 不上采样+交互封顶+停手两阶段。
"""
import os
import re
import json
import math
import threading
import customtkinter as ctk
import tkinter as tk
from tkinter import (
    Canvas, Listbox, Scrollbar, END, SINGLE, EXTENDED, filedialog, colorchooser, messagebox, StringVar, Menu
)
from PIL import Image, ImageTk, ImageDraw, ImageFilter
from font_manager import FontManager
from model import Template, TextElement, ImageElement, ShapeElement
from renderer import (
    render_template, get_element_bbox, get_image_resize_handle, safe_format,
    template_unresolved_fields
)
from data_import import load_table, match_rows_to_images, diagnose_filename_mismatch
from sort_utils import sort_entries, SORT_MODE_LABELS
import library

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
HANDLE = 5
RESIZE_HANDLE = 6
DOT_STEP = 22
RULER = 22                       # 标尺厚度（像素）
MAX_PREVIEW_INTERACT = 2000      # 交互中预览长边封顶
MAX_PREVIEW_SETTLE = 2200        # 静止补帧长边封顶（导出仍原图，不受影响）
PIXEL_PERFECT_CAP = 6000
PIXEL_PERFECT_CAP_INTERACT = 4000
ZOOM_MIN, ZOOM_MAX = 0.3, 4.0
_PREF_DIR = os.path.join(os.path.expanduser("~"), ".watermark_studio")
_THEME_PATH = os.path.join(_PREF_DIR, "theme.json")
_WELCOME_FLAG = os.path.join(_PREF_DIR, ".welcomed")

# ============================================================ 主题
THEMES = {
    "light": {
        "bg": "#f5f6f8", "panel": "#ffffff", "panel2": "#fafbfc", "panel3": "#f0f2f5",
        "border": "#e6e8eb", "border2": "#d6dae0", "canvas": "#eceef1",
        "dot": (208, 214, 222, 255), "photo_shadow": (31, 35, 41, 64),
        "text": "#1f2329", "text_mid": "#4e5560", "text_dim": "#767d87",
        "accent": "#3370ff", "accent_h": "#2860e1", "accent_bg": "#e8f0fe", "sel": "#e8f0fe",
        "purple": "#7b61ff", "purple_bg": "#f1eeff",
        "ok": "#2faa55", "ok_hover": "#27924a", "danger": "#d54941", "danger_bg": "#fdecea",
        "warn": "#e08a0c", "crop_canvas": "#e9ebef", "ruler": "#f3f4f6",
    },
    "dark": {
        "bg": "#15171c", "panel": "#1d2027", "panel2": "#232730", "panel3": "#2b303b",
        "border": "#2a2f3a", "border2": "#3a4150", "canvas": "#101217",
        "dot": (64, 72, 86, 255), "photo_shadow": (0, 0, 0, 170),
        "text": "#e7e9ee", "text_mid": "#b3b9c4", "text_dim": "#828a98",
        "accent": "#4dabff", "accent_h": "#6cbcff", "accent_bg": "#1f3a5c", "sel": "#21344d",
        "purple": "#9b7bff", "purple_bg": "#2a2342",
        "ok": "#34b35a", "ok_hover": "#2a9249", "danger": "#e0635c", "danger_bg": "#3a2322",
        "warn": "#f0b440", "crop_canvas": "#14171d", "ruler": "#1a1d24",
    },
}
THEME = dict(THEMES["light"])     # 单值，供 PIL 画布层读取；切换时 in-place 更新
ACCENT = THEME["accent"]


def _apply_theme(mode):
    global ACCENT
    THEME.clear()
    THEME.update(THEMES[mode])
    ACCENT = THEME["accent"]


def T(role):
    """双态颜色元组：CTk 控件用它做 fg/text/border 等，set_appearance_mode 时自动翻色。"""
    return (THEMES["light"][role], THEMES["dark"][role])


# tk 原生控件不支持双态元组，登记在此，切换时统一翻色
_NATIVE_WIDGETS = []


def _native(w, **roles):
    """登记一个 tk 原生控件的主题角色，如 _native(canvas, bg="canvas")。"""
    _NATIVE_WIDGETS.append((w, roles))
    return w


def _retheme_native():
    for w, roles in _NATIVE_WIDGETS:
        try:
            w.configure(**{k: THEME[v] for k, v in roles.items()})
        except Exception:
            pass


def _disp_font(size, bold=False):
    return ("Bahnschrift SemiBold" if bold else "Bahnschrift", size)


def _nice_step(raw):
    if raw <= 0:
        return 1
    p = 10 ** math.floor(math.log10(raw))
    f = raw / p
    n = 1 if f < 1.5 else 2 if f < 3 else 5 if f < 7 else 10
    return n * p


def sanitize_filename(name):
    name = re.sub(r'[\/:*?"<>|]', "_", name)
    return name.strip() or "output"


class ImageEntry:
    def __init__(self, path):
        self.path = path
        self.data = {}
        self.pil_image = None


# ============================================================ 可搜索下拉框
class SearchableCombobox(ctk.CTkFrame):
    _open_instance = None
    _MAX_VISIBLE_ROWS = 7

    def __init__(self, master, values=None, command=None, width=260, list_font=None, **kwargs):
        super().__init__(master, fg_color="transparent", width=width)
        self._all_values = list(values or [])
        self._command = command
        self._listbox = None
        self._list_font = list_font
        self._expanded = False
        self.var = StringVar(value=self._all_values[0] if self._all_values else "")
        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width, **kwargs)
        self.entry.pack(fill="x")
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<FocusIn>", lambda e: self._expand(filter_text=""))
        self.entry.bind("<Button-1>", lambda e: self._expand(filter_text=""))
        self.entry.bind("<Down>", lambda e: self._focus_list())
        self.entry.bind("<Escape>", lambda e: self._collapse())
        self.entry.bind("<FocusOut>", lambda e: self.after(120, self._maybe_collapse))
        self._drop_frame = ctk.CTkFrame(self, fg_color=T("panel"), border_width=1, border_color=T("accent"))
        list_wrap = ctk.CTkFrame(self._drop_frame, fg_color="transparent")
        list_wrap.pack(fill="both", expand=True, padx=1, pady=1)
        list_wrap.grid_rowconfigure(0, weight=1)
        list_wrap.grid_columnconfigure(0, weight=1)
        self._listbox = _native(Listbox(list_wrap, bg=THEME["panel"], fg=THEME["text"],
                                        selectbackground=THEME["sel"], selectforeground=THEME["text"],
                                        highlightthickness=0, borderwidth=0, activestyle="none",
                                        exportselection=False, font=self._list_font),
                                bg="panel", fg="text", selectbackground="sel", selectforeground="text")
        self._listbox.grid(row=0, column=0, sticky="nsew")
        list_scroll = Scrollbar(list_wrap, orient="vertical", command=self._listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self._listbox.configure(yscrollcommand=list_scroll.set)
        self._listbox.bind("<<ListboxSelect>>", self._on_pick)
        self._listbox.bind("<Return>", self._on_pick)

        def _wheel_scroll(e):
            self._listbox.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        def _wheel_up(_e):
            self._listbox.yview_scroll(-1, "units")
            return "break"

        def _wheel_down(_e):
            self._listbox.yview_scroll(1, "units")
            return "break"

        self._listbox.bind("<MouseWheel>", _wheel_scroll)
        self._listbox.bind("<Button-4>", _wheel_up)
        self._listbox.bind("<Button-5>", _wheel_down)
        self._listbox.bind("<FocusOut>", lambda e: self.after(120, self._maybe_collapse))
        for w in (list_wrap, self._drop_frame):
            w.bind("<MouseWheel>", _wheel_scroll, add="+")
            w.bind("<Button-4>", _wheel_up, add="+")
            w.bind("<Button-5>", _wheel_down, add="+")
        self.bind("<Destroy>", self._on_self_destroy, add="+")

    def set_values(self, values):
        self._all_values = list(values or [])
        if self._expanded:
            self._expand(filter_text=self.var.get())

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)

    def _on_key(self, event):
        if event.keysym in ("Down", "Up", "Return", "Escape"):
            return
        self._expand(filter_text=self.var.get())

    def _filtered(self, filter_text=""):
        if not filter_text:
            return self._all_values
        f = filter_text.lower()
        starts = [v for v in self._all_values if v.lower().startswith(f)]
        contains = [v for v in self._all_values if f in v.lower() and v not in starts]
        return starts + contains

    def _expand(self, filter_text=None):
        if SearchableCombobox._open_instance is not None and SearchableCombobox._open_instance is not self:
            SearchableCombobox._open_instance._collapse()
        SearchableCombobox._open_instance = self
        items = self._filtered(self.var.get() if filter_text is None else filter_text)
        self._listbox.delete(0, END)
        for v in items:
            self._listbox.insert(END, v)
        if items:
            self._listbox.selection_clear(0, END)
            self._listbox.selection_set(0)
        self._listbox.configure(height=min(self._MAX_VISIBLE_ROWS, max(1, len(items))))
        if not self._expanded:
            self._drop_frame.pack(fill="x", pady=(2, 0))
            self._expanded = True

    def _focus_list(self):
        self._expand(filter_text=self.var.get())
        if self._listbox.size():
            self._listbox.focus_set()
            self._listbox.selection_set(0)

    def _on_pick(self, _event=None):
        if not self._listbox.curselection():
            return
        value = self._listbox.get(self._listbox.curselection()[0])
        self.var.set(value)
        self._collapse()
        if self._command:
            self._command(value)
        self.entry.focus_set()

    def _maybe_collapse(self):
        try:
            focused = self.focus_get()
        except Exception:
            focused = None
        if focused not in (self._listbox, self.entry):
            self._collapse()

    def _collapse(self):
        if self._expanded:
            self._drop_frame.pack_forget()
            self._expanded = False
        if SearchableCombobox._open_instance is self:
            SearchableCombobox._open_instance = None

    _close_popup = _collapse

    def _on_self_destroy(self, _event=None):
        if SearchableCombobox._open_instance is self:
            SearchableCombobox._open_instance = None


# ============================================================ 透视裁剪弹窗
def _solve3x3(m, rhs):
    def det3(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det3(m)
    if abs(d) < 1e-9:
        return None
    x = []
    for col in range(3):
        mi = [row[:] for row in m]
        for r in range(3):
            mi[r][col] = rhs[r]
        x.append(det3(mi) / d)
    return x


class PerspectiveCropDialog(ctk.CTkToplevel):
    def __init__(self, parent, pil_image, on_apply_callback):
        super().__init__(parent)
        self.title("📐 多锚点透视裁剪矫正")
        self.geometry("1040x740")
        self.configure(fg_color=T("bg"))
        self.grab_set()
        self.pil_image = pil_image.copy()
        self.on_apply_callback = on_apply_callback
        self.orig_w, self.orig_h = self.pil_image.size
        self.corners_rel = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]
        self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
        self.active_handle = None
        self._disp_cache = None
        self._dotgrid_cache = None
        self._busy = False
        self._build_ui()
        self.after(50, self._draw_canvas)

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = _native(Canvas(self, bg=THEME["crop_canvas"], highlightthickness=0, bd=0),
                              bg="crop_canvas")
        self.canvas.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=10, pady=(10, 5))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<Configure>", lambda e: self._draw_canvas())
        btn_bar = ctk.CTkFrame(self, fg_color=T("panel"), corner_radius=10,
                               border_width=1, border_color=T("border"))
        btn_bar.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(5, 10))
        ctk.CTkLabel(btn_bar,
                     text="提示：拖拽 4 个角点定基准矩形；双击边线可新增控制点、拖拽自由调整、右键删除，用于修正弯曲边缘。",
                     text_color=T("text_dim"), wraplength=560, justify="left",
                     font=("Microsoft YaHei", 12)).pack(side="left", padx=12)
        self.btn_apply_temp = ctk.CTkButton(btn_bar, text="暂存到内存预览", width=120,
                                            fg_color=T("ok"), hover_color=T("ok_hover"),
                                            text_color="white", command=self._apply_temp)
        self.btn_apply_temp.pack(side="right", padx=6, pady=8)
        self.btn_save_file = ctk.CTkButton(btn_bar, text="另存为新文件…", width=120,
                                           fg_color=T("accent"), hover_color=T("accent_h"),
                                           text_color="white", command=self._save_to_file)
        self.btn_save_file.pack(side="right", padx=6)
        self.btn_cancel = ctk.CTkButton(btn_bar, text="取消", width=80, fg_color=T("panel"),
                                        text_color=T("text_mid"), hover_color=T("panel3"),
                                        command=self.destroy)
        self.btn_cancel.pack(side="right", padx=6)
        self.busy_label = ctk.CTkLabel(btn_bar, text="", text_color=T("accent"))
        self.busy_label.pack(side="right", padx=10)

    def _get_disp_meta(self):
        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())
        # 留白加大到 64（每边 32），让角点手柄不贴边被裁切（“框选显示不全”的根因之一）
        scale = min((cw - 64) / self.orig_w, (ch - 64) / self.orig_h, 1.0)
        dw = round(self.orig_w * scale)
        dh = round(self.orig_h * scale)
        ox = (cw - dw) // 2
        oy = (ch - dh) // 2
        return dw, dh, ox, oy, scale

    @staticmethod
    def _rel_to_screen(rel, dw, dh, ox, oy):
        return (ox + rel[0] * dw, oy + rel[1] * dh)

    @staticmethod
    def _project_t(rel_pt, c0_rel, c1_rel):
        cx, cy = c1_rel[0] - c0_rel[0], c1_rel[1] - c0_rel[1]
        length_sq = cx * cx + cy * cy
        if length_sq < 1e-12:
            return 0.0
        t = ((rel_pt[0] - c0_rel[0]) * cx + (rel_pt[1] - c0_rel[1]) * cy) / length_sq
        return max(0.0, min(1.0, t))

    def _edge_order(self, edge_i):
        c0, c1 = self.corners_rel[edge_i], self.corners_rel[(edge_i + 1) % 4]
        pts = self.edge_points_rel[edge_i]
        return sorted(range(len(pts)), key=lambda k: self._project_t(pts[k], c0, c1))

    def _ensure_dotgrid(self, cw, ch):
        if self._dotgrid_cache and self._dotgrid_cache["size"] == (cw, ch):
            return self._dotgrid_cache["img"]
        img = Image.new("RGBA", (max(1, cw), max(1, ch)), (0, 0, 0, 0))
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
        self._dotgrid_cache = {"size": (cw, ch), "img": tkimg}
        return tkimg

    def _draw_anchor_dot(self, px, py, active=False):
        # 锚点放大 + 暗外描边 + 白芯 + 粗蓝边，亮暗背景皆醒目
        r = 12 if not active else 14
        self.canvas.create_oval(px - r - 3, py - r - 3, px + r + 3, py + r + 3, fill="#1f2329", outline="", tags="anchor")
        self.canvas.create_oval(px - r, py - r, px + r, py + r, fill="#ffffff", outline=ACCENT, width=4, tags="anchor")
        cr = 4
        self.canvas.create_oval(px - cr, py - cr, px + cr, py + cr,
                                fill=(THEME["accent_h"] if active else ACCENT), outline="", tags="anchor")

    def _draw_anchor_square(self, mx, my, active=False):
        r = 7
        self.canvas.create_rectangle(mx - r - 2, my - r - 2, mx + r + 2, my + r + 2, fill="#1f2329", outline="", tags="anchor")
        self.canvas.create_rectangle(mx - r, my - r, mx + r, my + r,
                                     fill=(ACCENT if active else "#ffffff"), outline=ACCENT, width=3, tags="anchor")

    def _draw_canvas(self):
        self.canvas.delete("all")
        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())
        self.canvas.create_image(0, 0, anchor="nw", image=self._ensure_dotgrid(cw, ch))
        dw, dh, ox, oy, _scale = self._get_disp_meta()
        size = (max(1, dw), max(1, dh))
        if self._disp_cache is not None and self._disp_cache["size"] == size:
            self.tk_img = self._disp_cache["img"]
        else:
            res_img = self.pil_image.resize(size, Image.BILINEAR)
            self.tk_img = ImageTk.PhotoImage(res_img)
            self._disp_cache = {"size": size, "img": self.tk_img}
        self.canvas.create_rectangle(ox + 3, oy + 5, ox + dw + 3, oy + dh + 7, fill="#c4cad2", outline="", tags="photo")
        self.canvas.create_rectangle(ox - 1, oy - 1, ox + dw + 1, oy + dh + 1, outline=THEME["border2"], width=1, tags="photo")
        self.canvas.create_image(ox, oy, anchor="nw", image=self.tk_img, tags="photo")
        corners_screen = [self._rel_to_screen(p, dw, dh, ox, oy) for p in self.corners_rel]
        for i in range(4):
            order = self._edge_order(i)
            chain = [corners_screen[i]]
            chain += [self._rel_to_screen(self.edge_points_rel[i][k], dw, dh, ox, oy) for k in order]
            chain.append(corners_screen[(i + 1) % 4])
            for j in range(len(chain) - 1):
                x1, y1 = chain[j]
                x2, y2 = chain[j + 1]
                # 矫正线加粗到 3、虚线更连贯，解决“线太细”
                self.canvas.create_line(x1, y1, x2, y2, fill=ACCENT, width=3, dash=(8, 4), tags="anchor")
            for k in order:
                mx, my = self._rel_to_screen(self.edge_points_rel[i][k], dw, dh, ox, oy)
                self._draw_anchor_square(mx, my, active=(self.active_handle == ("edge", i, k)))
        for i, (px, py) in enumerate(corners_screen):
            self._draw_anchor_dot(px, py, active=(self.active_handle == ("corner", i)))

    def _on_press(self, event):
        dw, dh, ox, oy, _scale = self._get_disp_meta()
        corners_screen = [self._rel_to_screen(p, dw, dh, ox, oy) for p in self.corners_rel]
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
        rx = max(0.0, min(1.0, (event.x - ox) / dw))
        ry = max(0.0, min(1.0, (event.y - oy) / dh))
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
        corners_screen = [self._rel_to_screen(p, dw, dh, ox, oy) for p in self.corners_rel]
        best_edge, best_dist = None, 20.0
        for i in range(4):
            order = self._edge_order(i)
            chain = [corners_screen[i]]
            chain += [self._rel_to_screen(self.edge_points_rel[i][k], dw, dh, ox, oy) for k in order]
            chain.append(corners_screen[(i + 1) % 4])
            for j in range(len(chain) - 1):
                dist = self._point_seg_dist(event.x, event.y, chain[j], chain[j + 1])
                if dist < best_dist:
                    best_dist, best_edge = dist, i
        if best_edge is None:
            return
        rx = max(0.0, min(1.0, (event.x - ox) / dw))
        ry = max(0.0, min(1.0, (event.y - oy) / dh))
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

    @staticmethod
    def _point_seg_dist(px, py, p1, p2):
        x1, y1 = p1
        x2, y2 = p2
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-9:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
        nx, ny = x1 + t * dx, y1 + t * dy
        return math.hypot(px - nx, py - ny)

    def _build_mesh(self):
        corners_px = [(rx * self.orig_w, ry * self.orig_h) for rx, ry in self.corners_rel]
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = corners_px
        w1 = math.hypot(x1 - x0, y1 - y0)
        w2 = math.hypot(x2 - x3, y2 - y3)
        max_w = max(2, round(max(w1, w2)))
        h1 = math.hypot(x3 - x0, y3 - y0)
        h2 = math.hypot(x2 - x1, y2 - y1)
        max_h = max(2, round(max(h1, h2)))
        dst_corners = [(0, 0), (max_w, 0), (max_w, max_h), (0, max_h)]
        perimeter_src, perimeter_dst = [], []
        for i in range(4):
            perimeter_src.append(corners_px[i])
            perimeter_dst.append(dst_corners[i])
            c0_rel, c1_rel = self.corners_rel[i], self.corners_rel[(edge_i + 1) % 4] if False else self.corners_rel[(i + 1) % 4]
            d0, d1 = dst_corners[i], dst_corners[(i + 1) % 4]
            for k in self._edge_order(i):
                rel_pt = self.edge_points_rel[i][k]
                t = self._project_t(rel_pt, c0_rel, c1_rel)
                perimeter_src.append((rel_pt[0] * self.orig_w, rel_pt[1] * self.orig_h))
                perimeter_dst.append((d0[0] + t * (d1[0] - d0[0]), d0[1] + t * (d1[1] - d0[1])))
        return perimeter_src, perimeter_dst, max_w, max_h

    @staticmethod
    def _warp_triangle(src_img, dst_img, tri_src, tri_dst):
        xs = [p[0] for p in tri_dst]
        ys = [p[1] for p in tri_dst]
        x_min = max(0, int(math.floor(min(xs))))
        y_min = max(0, int(math.floor(min(ys))))
        x_max = min(dst_img.width, int(math.ceil(max(xs))) + 1)
        y_max = min(dst_img.height, int(math.ceil(max(ys))) + 1)
        bw, bh = x_max - x_min, y_max - y_min
        if bw <= 0 or bh <= 0:
            return
        m = [[tri_dst[0][0], tri_dst[0][1], 1],
             [tri_dst[1][0], tri_dst[1][1], 1],
             [tri_dst[2][0], tri_dst[2][1], 1]]
        abc = _solve3x3(m, [p[0] for p in tri_src])
        defc = _solve3x3(m, [p[1] for p in tri_src])
        if abc is None or defc is None:
            return
        a, b, c = abc
        d, e, f = defc
        coeffs = (a, b, c + a * x_min + b * y_min, d, e, f + d * x_min + e * y_min)
        patch = src_img.transform((bw, bh), Image.AFFINE, coeffs, resample=Image.BICUBIC)
        mask = Image.new("L", (bw, bh), 0)
        local_tri = [(x - x_min, y - y_min) for x, y in tri_dst]
        ImageDraw.Draw(mask).polygon(local_tri, fill=255, outline=255)
        dst_img.paste(patch, (x_min, y_min), mask)

    def _do_transform(self):
        perimeter_src, perimeter_dst, max_w, max_h = self._build_mesh()
        n = len(perimeter_src)
        centroid_src = (sum(p[0] for p in perimeter_src) / n, sum(p[1] for p in perimeter_src) / n)
        centroid_dst = (sum(p[0] for p in perimeter_dst) / n, sum(p[1] for p in perimeter_dst) / n)
        src_rgba = self.pil_image.convert("RGBA")
        out = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))
        for k in range(n):
            k2 = (k + 1) % n
            tri_src = (centroid_src, perimeter_src[k], perimeter_src[k2])
            tri_dst = (centroid_dst, perimeter_dst[k], perimeter_dst[k2])
            self._warp_triangle(src_rgba, out, tri_src, tri_dst)
        if self.pil_image.mode != "RGBA":
            bg = Image.new("RGB", out.size, (0, 0, 0))
            bg.paste(out, (0, 0), out)
            return bg
        return out

    def _set_busy(self, busy, text=""):
        self._busy = busy
        self.busy_label.configure(text=text)
        state = "disabled" if busy else "normal"
        for btn in (self.btn_apply_temp, self.btn_save_file, self.btn_cancel):
            btn.configure(state=state)

    def _run_transform_async(self, on_done):
        if self._busy:
            return
        self._set_busy(True, "正在生成结果，请稍候…")

        def worker():
            try:
                warped = self._do_transform()
                error = None
            except Exception as exc:
                warped, error = None, exc
            self.after(0, lambda: self._finish_transform_async(warped, error, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_transform_async(self, warped, error, on_done):
        self._set_busy(False)
        if error is not None or warped is None:
            messagebox.showerror("错误", f"透视变换失败：{error}" if error else "透视变换失败")
            return
        on_done(warped)

    def _apply_temp(self):
        def done(warped):
            self.on_apply_callback(warped)
            self.destroy()
        self._run_transform_async(done)

    def _save_to_file(self):
        out_path = filedialog.asksaveasfilename(
            title="保存透视裁剪图片", defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("所有文件", "*.*")])
        if not out_path:
            return

        def done(warped):
            warped.save(out_path, quality=95)
            messagebox.showinfo("完成", f"已成功保存至：\n{out_path}")
            self.on_apply_callback(warped)
            self.destroy()
        self._run_transform_async(done)


# ============================================================ 主窗口
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.theme_mode = self._load_theme_pref()
        _apply_theme(self.theme_mode)
        ctk.set_appearance_mode(self.theme_mode)
        self.configure(fg_color=T("bg"))
        self.title("水印标注工坊 · Watermark Studio")
        if os.path.exists("app.ico"):
            try:
                self.iconbitmap("app.ico")
            except Exception:
                pass
        self.font_manager = FontManager()
        self.template = Template.default()
        self.images = []
        self.sort_mode = "natural"
        self.current_index = None
        self.selected_elem_id = None
        self.drag_state = None
        self._tk_preview_img = None
        self._render_boxes = []
        self._preview_meta = None
        self._data_columns = []
        self._preview_cache = None
        self._dotgrid_cache = None
        self._shadow_cache = None
        self.canvas_zoom = 1.0
        self._pixel_perfect = False
        self._zoom_interacting = False
        self._zoom_settle_job = None
        self._quality_settle_id = None
        self._resize_interacting = False
        self._resize_settle_id = None
        self._pending_zoom_focus = None
        self._canvas_drag_start = None
        self._redraw_after_id = None
        self._live_attr_vars = {}
        self._exporting = False
        self._importing = False
        self._toast_label = None
        self._toast_frame = None
        self._toast_after = None
        self._crop_dialog = None
        self._toolbar = None
        self._bottom_bar = None
        self.main_paned = None
        self.ruler_top = None
        self.ruler_left = None
        self.ruler_corner = None
        self.sort_var = StringVar(value=SORT_MODE_LABELS[0][1])
        self.rename_var = StringVar(value="{钻孔编号}-{箱数}箱 {孔深起(m)}-{孔深止(m)}m")
        self.output_dir_var = StringVar(value="")
        self._setup_responsive_geometry()
        self.list_font, self.menu_font, self.ui_font, self.ui_font_b, self.ui_small = self._compute_scaled_fonts()
        self._build_layout()
        self.font_manager.scan_async(on_done=self._on_fonts_scanned)
        self._refresh_element_list()
        self._select_element(self.template.elements[-1].id if self.template.elements else None)
        self.bind_all("<Button-1>", self._on_global_click, add="+")
        self.bind("<Deactivate>", self._on_app_deactivate)
        self.bind("<Unmap>", self._on_app_deactivate)
        self.bind("<Configure>", self._on_app_configure)
        if not os.path.exists(_WELCOME_FLAG):
            self.after(700, self._show_help)

    def _compute_scaled_fonts(self):
        # 字号 = 12 × 系统缩放：CTk 控件按缩放放大，但传入字号不自动放大，故必须自乘。
        # 基数 12 与 CTk 默认字体逐像素同比例 → 不乘会“过小”、基数 13 会“过大”，12 正中。
        try:
            scale = ctk.ScalingTracker.get_widget_scaling(self)
        except Exception:
            scale = 1.0
        scale = max(1.0, min(2.5, scale))
        yahui = "Microsoft YaHei"
        n = max(11, round(12 * scale))
        ns = max(10, round(11 * scale))
        return ((yahui, n), (yahui, n), (yahui, n), (yahui, n, "bold"), (yahui, ns))

    def _load_theme_pref(self):
        try:
            with open(_THEME_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("mode", "light")
        except Exception:
            return "light"

    def _save_theme_pref(self, mode):
        try:
            os.makedirs(_PREF_DIR, exist_ok=True)
            with open(_THEME_PATH, "w", encoding="utf-8") as f:
                json.dump({"mode": mode}, f)
        except Exception:
            pass

    def toggle_theme(self):
        """切换亮/暗：幂等重建（_build_layout 先销毁旧外壳，不叠加→不空白）。
        恢复逻辑内联，不依赖 _restore_view（v7 无此方法，旧补丁调它会崩）。"""
        new_mode = "dark" if self.theme_mode == "light" else "light"
        self.theme_mode = new_mode
        _apply_theme(new_mode)
        ctk.set_appearance_mode(new_mode)
        if SearchableCombobox._open_instance is not None:
            SearchableCombobox._open_instance._close_popup()
        if self._crop_dialog is not None:
            try:
                self._crop_dialog.destroy()
            except Exception:
                pass
            self._crop_dialog = None
        self._dotgrid_cache = None
        self._shadow_cache = None
        self._preview_cache = None
        self._toast_label = None
        self._toast_frame = None
        self._build_layout()
        cur = self.images[self.current_index].path if (self.current_index is not None and self.images) else None
        self._apply_sort(keep_selection_path=cur)
        self._refresh_element_list()
        self._select_element(self.selected_elem_id)
        if hasattr(self, "canvas_zoom_label"):
            self.canvas_zoom_label.configure(text="1:1" if self._pixel_perfect else f"{round(self.canvas_zoom * 100)}%")
        self._redraw_canvas()
        self._save_theme_pref(new_mode)

    def _show_help(self):
        try:
            os.makedirs(_PREF_DIR, exist_ok=True)
            with open(_WELCOME_FLAG, "w", encoding="utf-8") as f:
                f.write("1")
        except Exception:
            pass
        win = ctk.CTkToplevel(self)
        win.title("使用帮助 · 4 步上手")
        win.geometry("560x600")
        win.configure(fg_color=T("bg"))
        win.grab_set()
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)
        wrap_labels = []
        head = ctk.CTkFrame(win, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 6))
        ctk.CTkLabel(head, text="水印标注工坊 · 快速上手", font=_disp_font(18, True),
                     text_color=T("text")).pack(anchor="w")
        d0 = ctk.CTkLabel(head, text="给岩心箱 / 探槽照片批量加水印标注，按表格自动填字段、按规则批量导出。",
                          text_color=T("text_mid"), justify="left", font=self.ui_font)
        d0.pack(anchor="w", pady=(2, 0))
        wrap_labels.append(d0)
        body = ctk.CTkScrollableFrame(win, fg_color=T("panel2"))
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(6, 12))
        body.grid_columnconfigure(0, weight=1)
        steps = [
            ("① 导入照片", "点左上『打开图片』选多张，或『打开文件夹』整目录导入。左侧列表默认按文件名自然排序（1箱、2箱…10箱）。"),
            ("② 摆好水印", "右侧『元素列表』选中元素，在中间画布上直接拖动定位、拖右下角手柄缩放；右侧属性面板改文字/字体/字号/颜色/阴影。文字里用 {钻孔编号} {箱数} {孔深起} {孔深止} 这类占位符。"),
            ("③ 导入数据表", "点『导入数据表』选 Excel/CSV，每行对应一张图。弹窗会实时显示『预计匹配 X / N 张』——为 0 时改选『按顺序对应』即可。"),
            ("④ 批量导出", "底部填『导出文件名规则』（同样支持 {字段名}），点右下绿色『批量导出全部』，按规则重命名导出，重名自动加序号。"),
        ]
        r = 0
        for title, desc in steps:
            card = ctk.CTkFrame(body, fg_color=T("panel"), corner_radius=8,
                                border_width=1, border_color=T("border"))
            card.grid(row=r, column=0, sticky="ew", pady=5)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=title, font=self.ui_font_b, text_color=T("accent"),
                         anchor="w").grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
            dl = ctk.CTkLabel(card, text=desc, text_color=T("text_mid"), justify="left",
                              anchor="w", font=self.ui_font)
            dl.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
            wrap_labels.append(dl)
            r += 1
        tips = ctk.CTkFrame(body, fg_color="transparent")
        tips.grid(row=r, column=0, sticky="ew", pady=(6, 4))
        tips.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tips, text="小技巧", font=self.ui_font_b, text_color=T("text"),
                     anchor="w").grid(row=0, column=0, sticky="ew")
        tr = 1
        for t in ["· 画布滚轮缩放、中键/空白拖动平移；双击在『1:1 实际像素』与适应窗口间切换；上方/左侧标尺显示原图像素。",
                  "· 右键元素可复制/置顶/置底/删除；右键空白可在此新增元素或透视裁剪。",
                  "· 『★ 水印库』把调好的排版存起来，下次一键套用；『保存/加载模板』存成 .json。",
                  "· 右上角 ☀/🌙 切换亮/暗主题，瞬时切换并自动记住。"]:
            tl = ctk.CTkLabel(tips, text=t, text_color=T("text_dim"), justify="left",
                              anchor="w", font=self.ui_small)
            tl.grid(row=tr, column=0, sticky="ew", pady=1)
            wrap_labels.append(tl)
            tr += 1
        ctk.CTkButton(win, text="知道了", width=120, fg_color=T("accent"),
                      hover_color=T("accent_h"), text_color="white",
                      command=win.destroy).grid(row=2, column=0, pady=(0, 16))

        def _reflow(_e=None):
            wl = max(220, win.winfo_width() - 80)
            for lb in wrap_labels:
                try:
                    lb.configure(wraplength=wl)
                except Exception:
                    pass
        _reflow()
        win.bind("<Configure>", _reflow)

    def _on_app_deactivate(self, event):
        if event.widget is not self:
            return
        if SearchableCombobox._open_instance is not None:
            SearchableCombobox._open_instance._close_popup()

    def _on_app_configure(self, event):
        if event.widget is not self:
            return
        size = (event.width, event.height)
        if getattr(self, "_last_app_size", None) == size:
            return
        self._last_app_size = size
        if SearchableCombobox._open_instance is not None:
            SearchableCombobox._open_instance._close_popup()

    def _on_global_click(self, event):
        inst = SearchableCombobox._open_instance
        if inst is None:
            return
        w = event.widget
        try:
            if w is inst.entry or w is inst or w is inst._listbox:
                return
            if str(w).startswith(str(inst) + "."):
                return
        except Exception:
            pass
        inst._collapse()

    def _setup_responsive_geometry(self):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = max(1280, min(int(sw * 0.86), 1680))
        h = max(760, min(int(sh * 0.86), 1000))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(1380, 760)   # 提到能容纳紧凑工具栏的宽度，未最大化也不重叠
        self.left_w = max(250, min(340, int(w * 0.20)))
        self.right_w = max(300, min(440, int(w * 0.26)))

    def _build_layout(self):
        # 幂等：先销毁旧外壳，避免重建时新旧控件叠在同一 grid 格导致空白
        for _attr in ("_toolbar", "main_paned", "_bottom_bar"):
            _w = getattr(self, _attr, None)
            if _w is not None:
                try:
                    _w.destroy()
                except Exception:
                    pass
                setattr(self, _attr, None)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_toolbar()
        self.main_paned = _native(tk.PanedWindow(self, orient="horizontal", sashwidth=5, sashrelief="flat",
                                                 bg=THEME["border"], bd=0, opaqueresize=True,
                                                 sashcursor="sb_h_double_arrow"), bg="border")
        self.main_paned.grid(row=1, column=0, sticky="nsew", padx=8, pady=0)
        self._build_left_panel()
        self._build_canvas()
        self._build_right_panel()
        self._build_bottom_bar()

    def _panel(self, master):
        return ctk.CTkFrame(master, corner_radius=10, fg_color=T("panel"),
                            border_width=1, border_color=T("border"))

    def _tb_btn(self, bar, text, cmd, kind="ghost", width=78):
        palette = {
            "ghost":  dict(fg_color=T("panel"), hover_color=T("panel3"), text_color=T("text_mid")),
            "accent": dict(fg_color=T("accent_bg"), hover_color=T("accent_bg"), text_color=T("accent_h")),
            "ok":     dict(fg_color=T("ok"), hover_color=T("ok_hover"), text_color="white"),
            "danger": dict(fg_color=T("panel"), hover_color=T("danger_bg"), text_color=T("danger")),
            "purple": dict(fg_color=T("panel"), hover_color=T("purple_bg"), text_color=T("purple")),
        }[kind]
        b = ctk.CTkButton(bar, text=text, command=cmd, width=width, height=30,
                          corner_radius=7, font=self.ui_font, **palette)
        b.pack(side="left", padx=1, pady=6)
        return b

    def _tb_sep(self, bar):
        ctk.CTkFrame(bar, width=1, height=20, fg_color=T("border2")).pack(side="left", fill="y", padx=4, pady=6)

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self, height=46, corner_radius=10, fg_color=T("panel"),
                           border_width=1, border_color=T("border"))
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 5))
        self._toolbar = bar
        self._theme_btn = ctk.CTkButton(bar, text=self._theme_btn_text(), width=72, height=30,
                                        corner_radius=7, fg_color=T("panel"),
                                        hover_color=T("panel3"), text_color=T("text_mid"),
                                        font=self.ui_font, command=self.toggle_theme)
        self._theme_btn.pack(side="right", padx=3, pady=6)
        ctk.CTkButton(bar, text="？ 帮助", width=64, height=30, corner_radius=7,
                      fg_color=T("panel"), hover_color=T("panel3"),
                      text_color=T("text_mid"), font=self.ui_font,
                      command=self._show_help).pack(side="right", padx=2, pady=6)
        self._tb_sep(bar)
        self._tb_btn(bar, "打开图片", self.on_open_images, width=72)
        self._tb_btn(bar, "打开文件夹", self.on_open_folder, width=78)
        self._tb_btn(bar, "导入数据表", self.on_import_table, width=80)
        self._tb_sep(bar)
        self._tb_btn(bar, "加载模板", self.on_load_template, width=72)
        self._tb_btn(bar, "保存模板", self.on_save_template, width=72)
        self._tb_btn(bar, "★ 水印库", self.on_open_library, kind="purple", width=76)
        self._tb_sep(bar)
        self._tb_btn(bar, "📐 透视", self.on_perspective_crop, kind="accent", width=70)
        self._tb_btn(bar, "↻顺90", lambda: self.on_rotate_image(270), width=54)
        self._tb_btn(bar, "↺逆90", lambda: self.on_rotate_image(90), width=54)
        self._tb_btn(bar, "⇆水平", lambda: self.on_flip_image("horizontal"), width=54)
        self._tb_btn(bar, "⥯垂直", lambda: self.on_flip_image("vertical"), width=54)
        self._tb_sep(bar)
        self._tb_btn(bar, "+文字", self.on_add_text, width=54)
        self._tb_btn(bar, "+图标", self.on_add_image_elem, width=54)
        self._tb_btn(bar, "+形状", self.on_add_shape_elem, width=54)
        self._tb_btn(bar, "删除", self.on_delete_element, kind="danger", width=54)

    def _theme_btn_text(self):
        return "☀ 亮色" if self.theme_mode == "dark" else "🌙 暗色"

    def _build_left_panel(self):
        panel = self._panel(self.main_paned)
        self.main_paned.add(panel, width=self.left_w, minsize=240, stretch="never")
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(12, 2))
        ctk.CTkLabel(head, text="图片列表", font=_disp_font(15, True), text_color=T("text")).pack(side="left")
        sort_row = ctk.CTkFrame(panel, fg_color="transparent")
        sort_row.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(sort_row, text="排序", text_color=T("text_mid"), font=self.ui_small).pack(side="left")
        labels = [lbl for _, lbl in SORT_MODE_LABELS]
        self._sort_label_to_mode = {lbl: mode for mode, lbl in SORT_MODE_LABELS}
        ctk.CTkOptionMenu(sort_row, values=labels, variable=self.sort_var, width=160,
                          font=self.ui_font, command=self.on_sort_mode_change).pack(side="left", padx=(6, 0))
        self.image_listbox = _native(Listbox(panel, selectmode=EXTENDED, bg=THEME["panel"], fg=THEME["text"],
                                             selectbackground=THEME["sel"], selectforeground=THEME["text"],
                                             highlightthickness=0, borderwidth=0, activestyle="none",
                                             font=self.list_font),
                                     bg="panel", fg="text", selectbackground="sel", selectforeground="text")
        self.image_listbox.pack(fill="both", expand=True, padx=10, pady=4)
        self.image_listbox.bind("<<ListboxSelect>>", self.on_select_image)
        ctk.CTkButton(panel, text="移除选中图片", fg_color=T("panel"), text_color=T("text_mid"),
                      hover_color=T("panel3"), font=self.ui_font,
                      command=self.on_remove_image).pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(panel, text="清空全部图片", fg_color=T("panel"), text_color=T("danger"),
                      hover_color=T("danger_bg"), font=self.ui_font,
                      command=self.on_clear_all_images).pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(panel, text="编辑当前图片数据…", fg_color=T("panel3"), text_color=T("text"),
                      hover_color=T("border2"), font=self.ui_font,
                      command=self.on_edit_current_data).pack(fill="x", padx=10, pady=(0, 10))
        self.status_label = ctk.CTkLabel(panel, text="尚未加载图片", wraplength=max(120, self.left_w - 30),
                                         justify="left", text_color=T("text_mid"), font=self.ui_small)
        self.status_label.pack(anchor="w", padx=12, pady=(0, 10))

        def _sync_left_wraplength(event):
            self.left_w = event.width
            self.status_label.configure(wraplength=max(120, event.width - 30))
        panel.bind("<Configure>", _sync_left_wraplength, add="+")

    def _build_canvas(self):
        wrap = self._panel(self.main_paned)
        self.main_paned.add(wrap, minsize=300, stretch="always")
        for r in (0, 1):
            wrap.grid_rowconfigure(r, weight=0)
        wrap.grid_rowconfigure(1, weight=1)
        wrap.grid_columnconfigure(1, weight=1)
        # 标尺布局：角块(0,0) 上标尺(0,1) 左标尺(1,0) 主画布(1,1)
        self.ruler_corner = _native(Canvas(wrap, width=RULER, height=RULER, bg=THEME["ruler"],
                                           highlightthickness=0, bd=0), bg="ruler")
        self.ruler_corner.grid(row=0, column=0, sticky="nsew")
        self.ruler_top = _native(Canvas(wrap, height=RULER, bg=THEME["ruler"], highlightthickness=0, bd=0), bg="ruler")
        self.ruler_top.grid(row=0, column=1, sticky="ew")
        self.ruler_left = _native(Canvas(wrap, width=RULER, bg=THEME["ruler"], highlightthickness=0, bd=0), bg="ruler")
        self.ruler_left.grid(row=1, column=0, sticky="ns")
        self.canvas = _native(Canvas(wrap, bg=THEME["canvas"], highlightthickness=0, bd=0), bg="canvas")
        self.canvas.grid(row=1, column=1, sticky="nsew")
        vbar = Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        vbar.grid(row=1, column=2, sticky="ns")
        hbar = Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        hbar.grid(row=2, column=1, sticky="ew")

        def _xscroll(*a):
            hbar.set(*a)
            try:
                self.ruler_top.xview_moveto(float(a[0]))
            except Exception:
                pass

        def _yscroll(*a):
            vbar.set(*a)
            try:
                self.ruler_left.yview_moveto(float(a[0]))
            except Exception:
                pass
        self.canvas.configure(xscrollcommand=_xscroll, yscrollcommand=_yscroll)
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Button-3>", self.on_canvas_right_click)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_canvas_zoom)
        self.canvas.bind("<Button-4>", self._on_canvas_zoom)
        self.canvas.bind("<Button-5>", self._on_canvas_zoom)
        self.canvas.bind("<ButtonPress-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self._resize_after_id = None
        self.canvas_zoom_label = ctk.CTkLabel(self.canvas, text="100%", fg_color=T("panel"),
                                              text_color=T("accent"), corner_radius=6,
                                              font=_disp_font(12, True))
        self.canvas_zoom_label.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)
        self.canvas_tip_label = ctk.CTkLabel(
            wrap, text="提示：滚轮缩放；中键/空白拖动平移；双击在 1:1 与适应窗口间切换；上/左标尺显示原图像素。拖动元素调位置，选中后拖右下角手柄缩放。",
            text_color=T("text_mid"), wraplength=900, justify="left", font=self.ui_small)
        self.canvas_tip_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=6, pady=(3, 0))
        self.canvas_warning_label = ctk.CTkLabel(
            wrap, text="", text_color=T("warn"), anchor="w", justify="left", wraplength=900, font=self.ui_small)
        self.canvas_warning_label.grid(row=4, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 3))

        def _sync_hint_wraplength(event):
            wl = max(200, event.width - 16)
            self.canvas_tip_label.configure(wraplength=wl)
            self.canvas_warning_label.configure(wraplength=wl)
        wrap.bind("<Configure>", _sync_hint_wraplength, add="+")

    def _build_right_panel(self):
        panel = self._panel(self.main_paned)
        self.main_paned.add(panel, width=self.right_w, minsize=280, stretch="never")
        ctk.CTkLabel(panel, text="元素列表", font=_disp_font(15, True), text_color=T("text")).pack(anchor="w", padx=12, pady=(12, 2))
        self.elem_listbox = _native(Listbox(panel, selectmode=SINGLE, height=6, bg=THEME["panel"], fg=THEME["text"],
                                            selectbackground=THEME["sel"], selectforeground=THEME["text"],
                                            highlightthickness=0, borderwidth=0, activestyle="none",
                                            font=self.list_font),
                                    bg="panel", fg="text", selectbackground="sel", selectforeground="text")
        self.elem_listbox.pack(fill="x", padx=10, pady=(0, 8))
        self.elem_listbox.bind("<<ListboxSelect>>", self.on_select_element_from_list)
        self.elem_listbox.bind("<Button-3>", self.on_elem_list_right_click)
        self.prop_container = ctk.CTkScrollableFrame(panel, label_text="属性",
                                                     fg_color=T("panel2"), label_fg_color=T("panel2"),
                                                     label_text_color=T("text"), label_font=_disp_font(13, True))
        self.prop_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def _dismiss_popup(_e=None):
            if SearchableCombobox._open_instance is not None:
                SearchableCombobox._open_instance._close_popup()
        self._prop_canvas_last_width = None

        def _dismiss_popup_on_canvas_resize(event):
            if self._prop_canvas_last_width == event.width:
                return
            self._prop_canvas_last_width = event.width
            _dismiss_popup()
        try:
            self.prop_container._parent_canvas.bind("<MouseWheel>", _dismiss_popup, add="+")
            self.prop_container._parent_canvas.bind("<Button-4>", _dismiss_popup, add="+")
            self.prop_container._parent_canvas.bind("<Button-5>", _dismiss_popup, add="+")
            self.prop_container._parent_canvas.bind("<Configure>", _dismiss_popup_on_canvas_resize, add="+")
        except Exception:
            pass

        def _sync_right_w(event):
            self.right_w = event.width
        panel.bind("<Configure>", _sync_right_w, add="+")

    def _build_bottom_bar(self):
        # 弹性网格：左区(规则+提示)可压缩，右区(导出)固定靠右，窄窗口下绝不重叠
        bar = ctk.CTkFrame(self, height=64, corner_radius=10, fg_color=T("panel"),
                           border_width=1, border_color=T("border"))
        bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(5, 8))
        self._bottom_bar = bar
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_columnconfigure(1, weight=0)
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=8)
        ctk.CTkLabel(left, text="导出文件名规则", text_color=T("text_mid"), font=self.ui_font).pack(side="left", padx=(0, 4))
        ctk.CTkEntry(left, textvariable=self.rename_var, width=260, font=self.ui_font).pack(side="left", padx=2)
        self.output_dir_label = ctk.CTkLabel(left, text="  （用 {字段名} 引用表格列，留空沿用原文件名）",
                                             text_color=T("text_dim"), font=self.ui_small)
        self.output_dir_label.pack(side="left", padx=(6, 0))
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e", padx=8, pady=8)
        self.btn_output_dir = ctk.CTkButton(right, text="选择输出目录", width=100, fg_color=T("panel3"),
                                            text_color=T("text"), hover_color=T("border2"),
                                            font=self.ui_font, command=self.on_choose_output_dir)
        self.btn_output_dir.pack(side="left", padx=4)
        self.progress = ctk.CTkProgressBar(right, width=140, progress_color=T("accent"), fg_color=T("panel3"))
        self.progress.set(0)
        self.progress.pack(side="left", padx=8)
        self.btn_batch_export = ctk.CTkButton(right, text="批量导出全部", width=120, fg_color=T("ok"),
                                              hover_color=T("ok_hover"), text_color="white",
                                              font=self.ui_font_b, command=self.on_batch_export)
        self.btn_batch_export.pack(side="left", padx=4)
        self.btn_export_current = ctk.CTkButton(right, text="导出当前", width=84, fg_color=T("panel3"),
                                                text_color=T("text"), hover_color=T("border2"),
                                                font=self.ui_font, command=self.on_export_current)
        self.btn_export_current.pack(side="left", padx=4)

    def _show_toast(self, text, color=None):
        if self._toast_label is None:
            frame = ctk.CTkFrame(self.canvas, fg_color="#1f2329", corner_radius=8, border_width=0)
            lbl = ctk.CTkLabel(frame, text="", text_color="white", fg_color="transparent", font=_disp_font(12, True))
            lbl.pack(padx=14, pady=7)
            self._toast_frame = frame
            self._toast_label = lbl
        self._toast_label.configure(text=text)
        self._toast_frame.place(relx=1.0, rely=1.0, anchor="se", x=-12, y=-40)
        if self._toast_after:
            self.after_cancel(self._toast_after)
        self._toast_after = self.after(2600, self._hide_toast)

    def _hide_toast(self):
        self._toast_after = None
        if self._toast_frame is not None:
            self._toast_frame.place_forget()

    def _on_fonts_scanned(self, names):
        self.after(0, self._refresh_property_panel)

    def on_open_images(self):
        paths = filedialog.askopenfilenames(
            title="选择照片",
            filetypes=[("图片文件", " ".join(f"*{e}" for e in IMAGE_EXTS)), ("所有文件", "*.*")])
        if paths:
            self._add_images(paths)

    def on_open_folder(self):
        folder = filedialog.askdirectory(title="选择照片所在文件夹")
        if not folder:
            return
        paths = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXTS)]
        if not paths:
            messagebox.showinfo("提示", "该文件夹下没有找到图片文件。")
            return
        self._add_images(paths)

    def _add_images(self, paths):
        current_path = self.images[self.current_index].path if self.current_index is not None else None
        for p in paths:
            self.images.append(ImageEntry(p))
        self._apply_sort(keep_selection_path=current_path or (paths[0] if paths else None))

    def on_sort_mode_change(self, label):
        self.sort_mode = self._sort_label_to_mode.get(label, "natural")
        current_path = self.images[self.current_index].path if self.current_index is not None else None
        self._apply_sort(keep_selection_path=current_path)

    def _apply_sort(self, keep_selection_path=None):
        self.images = sort_entries(self.images, mode=self.sort_mode)
        self.image_listbox.delete(0, END)
        new_idx = 0
        for i, e in enumerate(self.images):
            self.image_listbox.insert(END, os.path.basename(e.path))
            if keep_selection_path and e.path == keep_selection_path:
                new_idx = i
        self.status_label.configure(text=f"共 {len(self.images)} 张图片")
        if self.images:
            self.image_listbox.selection_clear(0, END)
            self.image_listbox.selection_set(new_idx)
            self.image_listbox.see(new_idx)
            self._load_current(new_idx)
        else:
            self.current_index = None
            self.canvas.delete("all")
            self._draw_rulers()

    def on_remove_image(self):
        sel = self.image_listbox.curselection()
        if not sel:
            return
        indices = sorted(list(sel), reverse=True)
        for idx in indices:
            self.image_listbox.delete(idx)
            del self.images[idx]
        self.status_label.configure(text=f"共 {len(self.images)} 张图片")
        if self.images:
            new_idx = min(indices[-1], len(self.images) - 1)
            self.image_listbox.selection_set(new_idx)
            self._load_current(new_idx)
        else:
            self.current_index = None
            self._preview_cache = None
            self.canvas.delete("all")
            self._draw_rulers()

    def on_clear_all_images(self):
        if not self.images:
            return
        if messagebox.askyesno("确认清空", "确定要清空图片列表中的所有照片吗？"):
            self.images.clear()
            self.image_listbox.delete(0, END)
            self.current_index = None
            self._preview_cache = None
            self.status_label.configure(text="尚未加载图片")
            self.canvas.delete("all")
            self._draw_rulers()

    def on_select_image(self, _event=None):
        sel = self.image_listbox.curselection()
        if sel:
            self._load_current(sel[0])

    def _load_current(self, idx):
        self.current_index = idx
        entry = self.images[idx]
        if entry.pil_image is None:
            try:
                entry.pil_image = Image.open(entry.path).convert("RGB")
            except Exception as e:
                messagebox.showerror("打开失败", f"无法打开图片：\n{entry.path}\n{e}")
                return
        self._redraw_canvas()

    def on_edit_current_data(self):
        if self.current_index is None:
            messagebox.showinfo("提示", "请先在左侧选择一张图片。")
            return
        entry = self.images[self.current_index]
        keys = set(entry.data.keys())
        for elem in self.template.elements:
            if elem.type == "text":
                keys.update(re.findall(r"\{([^{}]+)\}", elem.content))
        keys = sorted(keys)
        if not keys:
            messagebox.showinfo("提示", "当前文字元素里没有 {字段名} 占位符，且未导入表格数据。")
            return
        win = ctk.CTkToplevel(self)
        win.title(f"编辑数据 - {os.path.basename(entry.path)}")
        win.geometry("360x" + str(80 + 40 * len(keys)))
        win.configure(fg_color=T("bg"))
        win.grab_set()
        vars_map = {}
        for i, k in enumerate(keys):
            ctk.CTkLabel(win, text=k, width=100, anchor="w", font=self.ui_font).grid(row=i, column=0, padx=10, pady=6, sticky="w")
            v = StringVar(value=entry.data.get(k, ""))
            ctk.CTkEntry(win, textvariable=v, width=200, font=self.ui_font).grid(row=i, column=1, padx=10, pady=6)
            vars_map[k] = v

        def save_and_close():
            for k, v in vars_map.items():
                entry.data[k] = v.get()
            win.destroy()
            self._redraw_canvas()
        ctk.CTkButton(win, text="保存", fg_color=T("accent"), hover_color=T("accent_h"),
                      text_color="white", font=self.ui_font,
                      command=save_and_close).grid(row=len(keys), column=0, columnspan=2, pady=10)

    def on_import_table(self):
        if self._importing:
            return
        path = filedialog.askopenfilename(
            title="选择数据表",
            filetypes=[("Excel/CSV", "*.xlsx *.xls *.xlsm *.csv"), ("所有文件", "*.*")])
        if not path:
            return
        self._importing = True
        self.status_label.configure(text="正在读取数据表…")

        def worker():
            try:
                columns, rows = load_table(path)
                err = None
            except Exception as exc:
                columns, rows, err = None, None, exc
            self.after(0, lambda: self._finish_import(columns, rows, err))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_import(self, columns, rows, err):
        self._importing = False
        if err is not None:
            self.status_label.configure(text=f"共 {len(self.images)} 张图片")
            messagebox.showerror("读取失败", str(err))
            return
        if not rows:
            self.status_label.configure(text=f"共 {len(self.images)} 张图片")
            messagebox.showinfo("提示", "表格里没有数据行。")
            return
        self._data_columns = columns
        self._show_match_dialog(columns, rows)

    def _count_match(self, rows, filename_col):
        paths = [e.path for e in self.images]
        if not paths:
            return 0
        mapping = match_rows_to_images(rows, paths, filename_column=filename_col)
        return sum(1 for d in mapping.values() if d)

    def _show_match_dialog(self, columns, rows):
        win = ctk.CTkToplevel(self)
        win.title("数据与图片匹配方式")
        win.geometry("420x260")
        win.configure(fg_color=T("bg"))
        win.grab_set()
        n_img = len(self.images)
        ctk.CTkLabel(win, text=f"读取到 {len(rows)} 行数据 · {len(columns)} 列；当前图片 {n_img} 张。",
                     text_color=T("text_mid"), font=self.ui_font).pack(padx=16, pady=(16, 8), anchor="w")
        ctk.CTkLabel(win, text="选择匹配方式：", text_color=T("text"), font=self.ui_font).pack(padx=16, anchor="w")
        options = ["(按顺序对应)"] + columns
        perfect = None
        if n_img > 0:
            for c in columns:
                if self._count_match(rows, c) >= n_img:
                    perfect = c
                    break
        var = StringVar(value=perfect or options[0])
        ctk.CTkOptionMenu(win, values=options, variable=var, width=300, font=self.ui_font,
                          command=lambda _v: _update_estimate()).pack(padx=16, pady=8, anchor="w")
        est_label = ctk.CTkLabel(win, text="", text_color=T("accent"), font=_disp_font(12, True))
        est_label.pack(padx=16, anchor="w")
        hint_label = ctk.CTkLabel(win, text="", text_color=T("text_dim"), wraplength=380, justify="left", font=self.ui_small)
        hint_label.pack(padx=16, pady=(2, 0), anchor="w")

        def _update_estimate():
            col = var.get()
            filename_col = None if col == options[0] else col
            cnt = self._count_match(rows, filename_col)
            est_label.configure(text=f"按当前方式预计可匹配 {cnt} / {n_img} 张")
            if filename_col and cnt < max(1, int(n_img * 0.3)):
                hint_label.configure(text="匹配数偏低：表格该列的值与图片文件名对不上，可改选「按顺序对应」。")
            else:
                hint_label.configure(text="")
        _update_estimate()

        def confirm():
            col = var.get()
            filename_col = None if col == options[0] else col
            image_paths = [e.path for e in self.images]
            mapping = match_rows_to_images(rows, image_paths, filename_column=filename_col)
            matched = 0
            for e in self.images:
                data = mapping.get(e.path, {})
                if data:
                    matched += 1
                e.data.update(data)
            win.destroy()
            self.status_label.configure(text=f"共 {len(self.images)} 张图片，已匹配数据 {matched} 张")
            self._redraw_canvas()
            self._show_toast(f"已匹配 {matched} 张数据", ACCENT)
            if filename_col and matched < max(1, len(self.images) * 0.3):
                excel_samples, image_samples = diagnose_filename_mismatch(rows, image_paths, filename_col)
                lines = ["按「%s」列匹配到的很少（%d / %d 张），对比一下实际内容：" % (filename_col, matched, len(self.images)), ""]
                lines.append("表格里「%s」列的值：" % filename_col)
                lines += [f"  {v}" for v in excel_samples] or ["  (空)"]
                lines.append("")
                lines.append("当前图片列表里的实际文件名：")
                lines += [f"  {v}" for v in image_samples] or ["  (无图片)"]
                lines.append("")
                lines.append("请对照检查：大小写、全角/半角符号、扩展名、多余空格；或改选「按顺序对应」。")
                messagebox.showwarning("按文件名匹配数偏低", "\n".join(lines))
        ctk.CTkButton(win, text="确定导入", fg_color=T("accent"), hover_color=T("accent_h"),
                      text_color="white", width=120, font=self.ui_font, command=confirm).pack(pady=14)

    def on_load_template(self):
        path = filedialog.askopenfilename(title="加载模板", filetypes=[("模板文件", "*.json")])
        if not path:
            return
        try:
            self.template = Template.load(path)
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return
        self._refresh_element_list()
        self._select_element(self.template.elements[0].id if self.template.elements else None)
        self._redraw_canvas()

    def on_save_template(self):
        path = filedialog.asksaveasfilename(title="保存模板", defaultextension=".json", filetypes=[("模板文件", "*.json")])
        if not path:
            return
        try:
            self.template.save(path)
        except Exception as e:
            messagebox.showerror("保存失败", str(e))

    def on_open_library(self):
        win = ctk.CTkToplevel(self)
        win.title("水印库")
        win.geometry("460x480")
        win.configure(fg_color=T("bg"))
        win.grab_set()
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 6))
        ctk.CTkLabel(top, text="把常用的水印排版存起来，随时一键套用到当前工程。",
                     text_color=T("text_dim"), wraplength=420, justify="left", font=self.ui_font).pack(anchor="w")
        save_row = ctk.CTkFrame(win, fg_color="transparent")
        save_row.pack(fill="x", padx=14, pady=(0, 10))
        name_var = StringVar(value=self.template.name or "我的水印")
        ctk.CTkEntry(save_row, textvariable=name_var, width=240, font=self.ui_font).pack(side="left")

        def do_save():
            saved_path = library.save_preset(self.template, name_var.get())
            messagebox.showinfo("已保存", f"当前模板已存入水印库：\n{os.path.basename(saved_path)}")
            refresh_list()
        ctk.CTkButton(save_row, text="将当前模板存入库", command=do_save, width=160,
                      fg_color=T("purple"), hover_color="#6950e0", text_color="white", font=self.ui_font).pack(side="left", padx=8)
        list_frame = ctk.CTkScrollableFrame(win, label_text="已保存的水印", fg_color=T("panel2"),
                                            label_fg_color=T("panel2"), label_text_color=T("text"))
        list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        def refresh_list():
            for w in list_frame.winfo_children():
                w.destroy()
            presets = library.list_presets()
            if not presets:
                ctk.CTkLabel(list_frame, text="水印库还是空的，先调好一套排版，点上方按钮存进来吧。",
                             text_color=T("text_dim"), wraplength=380, justify="left", font=self.ui_font).pack(pady=16)
                return
            for display_name, path, _ts in presets:
                row = ctk.CTkFrame(list_frame, fg_color=T("panel"), corner_radius=8,
                                   border_width=1, border_color=T("border"))
                row.pack(fill="x", pady=4)
                ctk.CTkLabel(row, text=display_name, anchor="w", text_color=T("text"),
                             font=self.ui_font).pack(side="left", padx=10, pady=8, fill="x", expand=True)

                def apply_it(p=path):
                    try:
                        self.template = library.load_preset(p)
                    except Exception as e:
                        messagebox.showerror("应用失败", str(e))
                        return
                    self._refresh_element_list()
                    self._select_element(self.template.elements[0].id if self.template.elements else None)
                    self._redraw_canvas()
                    win.destroy()

                def delete_it(p=path):
                    if messagebox.askyesno("删除", "确定从水印库删除这一项吗？"):
                        library.delete_preset(p)
                        refresh_list()
                ctk.CTkButton(row, text="应用", width=58, fg_color=T("accent_bg"), text_color=T("accent_h"),
                              hover_color=T("accent_bg"), font=self.ui_font, command=apply_it).pack(side="left", padx=4)
                ctk.CTkButton(row, text="删除", width=58, fg_color=T("panel"), text_color=T("danger"),
                              hover_color=T("danger_bg"), font=self.ui_font, command=delete_it).pack(side="left", padx=(0, 8))
        refresh_list()

    def on_add_text(self):
        elem = self.template.add(TextElement(content="新文字{字段名}", name="文字"))
        self._refresh_element_list()
        self._select_element(elem.id)
        self._redraw_canvas()

    def on_add_image_elem(self):
        path = filedialog.askopenfilename(title="选择图标/色块图片(PNG推荐)",
                                          filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        elem = self.template.add(ImageElement(path=path or "", name="图标"))
        self._refresh_element_list()
        self._select_element(elem.id)
        self._redraw_canvas()

    def on_add_shape_elem(self):
        elem = self.template.add(ShapeElement(shape="rect", name="形状"))
        self._refresh_element_list()
        self._select_element(elem.id)
        self._redraw_canvas()

    def on_delete_element(self):
        if not self.selected_elem_id:
            return
        self.template.remove(self.selected_elem_id)
        self.selected_elem_id = None
        self._refresh_element_list()
        self._redraw_canvas()

    def on_duplicate_element(self, elem_id=None):
        elem_id = elem_id or self.selected_elem_id
        src = self.template.find(elem_id)
        if src is None:
            return
        import copy
        import uuid
        clone = copy.deepcopy(src)
        clone.id = uuid.uuid4().hex[:8]
        clone.x = min(1.0, clone.x + 0.02)
        clone.y = min(1.0, clone.y + 0.02)
        self.template.elements.append(clone)
        self._refresh_element_list()
        self._select_element(clone.id)
        self._redraw_canvas()

    def _refresh_element_list(self):
        self.elem_listbox.delete(0, END)
        type_labels = {"text": "文字", "image": "图标", "shape": "形状"}
        shape_labels = {"rect": "矩形", "ellipse": "圆/椭圆", "triangle": "三角形"}
        for e in self.template.elements:
            mode_tag = ""
            if e.type == "text" and getattr(e, "mode", "single") != "single":
                mode_tag = "·" + ("平铺" if e.mode == "tile" else "对角")
            elif e.type == "shape":
                mode_tag = "·" + shape_labels.get(getattr(e, "shape", "rect"), "")
            label = f"[{type_labels.get(e.type, e.type)}{mode_tag}] {e.name}"
            self.elem_listbox.insert(END, label)

    def on_select_element_from_list(self, _event=None):
        sel = self.elem_listbox.curselection()
        if not sel:
            return
        elem = self.template.elements[sel[0]]
        self._select_element(elem.id)

    def _select_element(self, elem_id):
        self.selected_elem_id = elem_id
        if elem_id:
            for i, e in enumerate(self.template.elements):
                if e.id == elem_id:
                    self.elem_listbox.selection_clear(0, END)
                    self.elem_listbox.selection_set(i)
                    break
        self._refresh_property_panel()
        self._redraw_canvas()

    def _refresh_property_panel(self):
        if SearchableCombobox._open_instance is not None:
            SearchableCombobox._open_instance._close_popup()
        self._live_attr_vars = {}
        for w in self.prop_container.winfo_children():
            w.destroy()
        elem = self.template.find(self.selected_elem_id) if self.selected_elem_id else None
        if elem is None:
            ctk.CTkLabel(self.prop_container, text="未选中元素", text_color=T("text_dim"), font=self.ui_font).pack(pady=20)
            return

        def label(text):
            ctk.CTkLabel(self.prop_container, text=text, anchor="w", justify="left",
                         wraplength=max(140, self.right_w - 45),
                         text_color=T("text_mid"), font=self.ui_font).pack(fill="x", pady=(8, 0))

        if elem.type == "text":
            label("水印模式")
            mode_labels = {"single": "单个（可拖拽定位）", "tile": "平铺满图", "diagonal": "单条对角线"}
            mode_rev = {v: k for k, v in mode_labels.items()}
            mode_var = StringVar(value=mode_labels.get(elem.mode, mode_labels["single"]))

            def on_mode_change(v):
                elem.mode = mode_rev.get(v, "single")
                self._redraw_canvas()
                self._refresh_property_panel()
            ctk.CTkOptionMenu(self.prop_container, values=list(mode_labels.values()), variable=mode_var,
                              font=self.ui_font, command=on_mode_change).pack(fill="x", pady=2)
            label("文字内容（支持 {字段名} 占位符）")
            box = ctk.CTkTextbox(self.prop_container, height=90, font=self.ui_font)
            box.pack(fill="x", pady=2)
            box.insert("1.0", elem.content)

            def on_content_change(_e=None):
                elem.content = box.get("1.0", "end-1c")
                self._redraw_canvas()
            box.bind("<KeyRelease>", on_content_change)
            if self._data_columns:
                hint = "可用字段：" + "、".join("{%s}" % c for c in self._data_columns)
                ctk.CTkLabel(self.prop_container, text=hint, text_color=T("text_dim"),
                             wraplength=max(140, self.right_w - 45), justify="left", font=self.ui_small).pack(fill="x")
            if elem.mode == "single":
                label("对齐方式")
                align_labels = {"left": "左对齐", "center": "居中", "right": "右对齐"}
                align_rev = {v: k for k, v in align_labels.items()}
                align_var = StringVar(value=align_labels.get(elem.align, "左对齐"))

                def on_align_change(v):
                    elem.align = align_rev.get(v, "left")
                    self._redraw_canvas()
                ctk.CTkOptionMenu(self.prop_container, values=list(align_labels.values()), variable=align_var,
                                  font=self.ui_font, command=on_align_change).pack(fill="x", pady=2)
            label("字体（可打字搜索，支持滚轮翻页）")
            font_names = self.font_manager.family_names() or ["微软雅黑", "黑体", "宋体"]
            resolved = self.font_manager.resolve(elem.font_family)
            if resolved and resolved != elem.font_family:
                elem.font_family = resolved
            font_missing = elem.font_family and resolved is None
            combo = SearchableCombobox(self.prop_container, values=font_names, list_font=self.list_font,
                                       command=lambda v: (setattr(elem, "font_family", v), self._redraw_canvas()))
            if resolved:
                combo.set(resolved)
            elif elem.font_family:
                combo.set(elem.font_family)
            else:
                combo.set(font_names[0])
            combo.pack(fill="x", pady=2)
            if font_missing:
                ctk.CTkLabel(self.prop_container,
                             text=f"⚠ 本机未找到字体「{elem.font_family}」，导出时会回退为默认字体，请重新选择",
                             text_color=T("warn"), wraplength=max(140, self.right_w - 45),
                             justify="left", font=self.ui_small).pack(fill="x", pady=(2, 4))
            label("字号（相对当前预览图高度比例）")
            size_var = StringVar(value=str(round(elem.font_size_rel * 1000)))

            def on_size_change(_e=None):
                try:
                    elem.font_size_rel = max(1, float(size_var.get())) / 1000.0
                except ValueError:
                    pass
                self._redraw_canvas()
            size_entry = ctk.CTkEntry(self.prop_container, textvariable=size_var, font=self.ui_font)
            size_entry.pack(fill="x", pady=2)
            size_entry.bind("<KeyRelease>", on_size_change)
            self._add_slider_row("字间距(像素)", elem, "letter_spacing", 0, 50)
            self._add_slider_row("行间距(像素)", elem, "line_spacing", 0, 50)

            def pick_color():
                rgb, hexcode = colorchooser.askcolor(color=elem.color, title="选择文字颜色")
                if hexcode:
                    elem.color = hexcode
                    self._redraw_canvas()
                    self._refresh_property_panel()
            ctk.CTkButton(self.prop_container, text=f"文字颜色 {elem.color}", command=pick_color,
                          fg_color=elem.color, text_color=self._contrast_color(elem.color), font=self.ui_font).pack(fill="x", pady=(8, 2))
            bold_var = ctk.BooleanVar(value=elem.bold)

            def on_bold_toggle():
                elem.bold = bold_var.get()
                self._redraw_canvas()
            ctk.CTkCheckBox(self.prop_container, text="加粗", variable=bold_var, font=self.ui_font, command=on_bold_toggle).pack(anchor="w", pady=(6, 2))
            stroke_var = ctk.BooleanVar(value=getattr(elem, "stroke_enabled", False))

            def on_stroke_toggle():
                elem.stroke_enabled = stroke_var.get()
                self._redraw_canvas()
            ctk.CTkCheckBox(self.prop_container, text="启用描边", variable=stroke_var, font=self.ui_font, command=on_stroke_toggle).pack(anchor="w", pady=(10, 2))

            def pick_stroke_color():
                rgb, hexcode = colorchooser.askcolor(color=elem.stroke_color, title="选择描边颜色")
                if hexcode:
                    elem.stroke_color = hexcode
                    self._redraw_canvas()
                    self._refresh_property_panel()
            ctk.CTkButton(self.prop_container, text=f"描边颜色 {elem.stroke_color}", command=pick_stroke_color,
                          fg_color=elem.stroke_color, text_color=self._contrast_color(elem.stroke_color), font=self.ui_font).pack(fill="x", pady=2)
            self._add_slider_row("描边宽度(像素)", elem, "stroke_width", 0, 10)
            shadow_var = ctk.BooleanVar(value=elem.shadow_enabled)

            def on_shadow_toggle():
                elem.shadow_enabled = shadow_var.get()
                self._redraw_canvas()
            ctk.CTkCheckBox(self.prop_container, text="启用阴影", variable=shadow_var, font=self.ui_font, command=on_shadow_toggle).pack(anchor="w", pady=(10, 2))

            def pick_shadow_color():
                rgb, hexcode = colorchooser.askcolor(color=elem.shadow_color, title="选择阴影颜色")
                if hexcode:
                    elem.shadow_color = hexcode
                    self._redraw_canvas()
                    self._refresh_property_panel()
            ctk.CTkButton(self.prop_container, text=f"阴影颜色 {elem.shadow_color}", command=pick_shadow_color,
                          fg_color=elem.shadow_color, text_color=self._contrast_color(elem.shadow_color), font=self.ui_font).pack(fill="x", pady=2)
            self._add_numeric_row("阴影X偏移", elem, "shadow_offset", 0, is_offset=True)
            self._add_numeric_row("阴影Y偏移", elem, "shadow_offset", 1, is_offset=True)
            self._add_slider_row("阴影模糊半径", elem, "shadow_blur", 0, 20)
            self._add_slider_row("阴影不透明度", elem, "shadow_opacity", 0.0, 1.0)
            if elem.mode in ("tile", "diagonal"):
                label("旋转角度（度）")
                self._add_float_entry(elem, "tile_angle", -180.0, 180.0)
            if elem.mode == "tile":
                label("水平间距")
                self._add_float_entry(elem, "tile_spacing_x", 0.0, 1.0)
                label("垂直间距")
                self._add_float_entry(elem, "tile_spacing_y", 0.0, 1.0)
        elif elem.type == "image":
            label("图片路径")
            path_var = StringVar(value=elem.path)
            path_entry = ctk.CTkEntry(self.prop_container, textvariable=path_var, font=self.ui_font)
            path_entry.pack(fill="x", pady=2)

            def browse():
                p = filedialog.askopenfilename(title="选择图标/色块图片",
                                               filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
                if p:
                    elem.path = p
                    path_var.set(p)
                    self._redraw_canvas()
            ctk.CTkButton(self.prop_container, text="浏览…", fg_color=T("panel3"), text_color=T("text"),
                          hover_color=T("border2"), font=self.ui_font, command=browse).pack(fill="x", pady=2)
            label("宽度比例（0~1）")
            self._add_float_entry(elem, "w_rel", 0.001, 1.0)
            label("高度比例（0~1）")
            self._add_float_entry(elem, "h_rel", 0.001, 1.0)
            label("不透明度")
            self._add_slider_row("不透明度", elem, "opacity", 0.0, 1.0)
        elif elem.type == "shape":
            label("形状")
            shape_labels = {"rect": "矩形/圆角矩形", "ellipse": "圆 / 椭圆", "triangle": "三角形"}
            shape_rev = {v: k for k, v in shape_labels.items()}
            shape_var = StringVar(value=shape_labels.get(elem.shape, "矩形/圆角矩形"))

            def on_shape_change(v):
                elem.shape = shape_rev.get(v, "rect")
                self._redraw_canvas()
                self._refresh_property_panel()
            ctk.CTkOptionMenu(self.prop_container, values=list(shape_labels.values()), variable=shape_var,
                              font=self.ui_font, command=on_shape_change).pack(fill="x", pady=2)

            def pick_fill_color():
                rgb, hexcode = colorchooser.askcolor(color=elem.fill_color, title="选择填充颜色")
                if hexcode:
                    elem.fill_color = hexcode
                    self._redraw_canvas()
                    self._refresh_property_panel()
            ctk.CTkButton(self.prop_container, text=f"填充颜色 {elem.fill_color}", command=pick_fill_color,
                          fg_color=elem.fill_color, text_color=self._contrast_color(elem.fill_color), font=self.ui_font).pack(fill="x", pady=(8, 2))
            self._add_slider_row("填充不透明度", elem, "fill_opacity", 0.0, 1.0)
            if elem.shape == "rect":
                self._add_slider_row("圆角半径(像素)", elem, "corner_radius", 0, 200)
            stroke_var = ctk.BooleanVar(value=getattr(elem, "stroke_enabled", False))

            def on_stroke_toggle():
                elem.stroke_enabled = stroke_var.get()
                self._redraw_canvas()
            ctk.CTkCheckBox(self.prop_container, text="启用描边", variable=stroke_var, font=self.ui_font, command=on_stroke_toggle).pack(anchor="w", pady=(10, 2))

            def pick_stroke_color():
                rgb, hexcode = colorchooser.askcolor(color=elem.stroke_color, title="选择描边颜色")
                if hexcode:
                    elem.stroke_color = hexcode
                    self._redraw_canvas()
                    self._refresh_property_panel()
            ctk.CTkButton(self.prop_container, text=f"描边颜色 {elem.stroke_color}", command=pick_stroke_color,
                          fg_color=elem.stroke_color, text_color=self._contrast_color(elem.stroke_color), font=self.ui_font).pack(fill="x", pady=2)
            self._add_slider_row("描边宽度(像素)", elem, "stroke_width", 0, 20)
            shadow_var = ctk.BooleanVar(value=getattr(elem, "shadow_enabled", False))

            def on_shadow_toggle():
                elem.shadow_enabled = shadow_var.get()
                self._redraw_canvas()
            ctk.CTkCheckBox(self.prop_container, text="启用阴影", variable=shadow_var, font=self.ui_font, command=on_shadow_toggle).pack(anchor="w", pady=(10, 2))

            def pick_shadow_color():
                rgb, hexcode = colorchooser.askcolor(color=elem.shadow_color, title="选择阴影颜色")
                if hexcode:
                    elem.shadow_color = hexcode
                    self._redraw_canvas()
                    self._refresh_property_panel()
            ctk.CTkButton(self.prop_container, text=f"阴影颜色 {elem.shadow_color}", command=pick_shadow_color,
                          fg_color=elem.shadow_color, text_color=self._contrast_color(elem.shadow_color), font=self.ui_font).pack(fill="x", pady=2)
            self._add_numeric_row("阴影X偏移", elem, "shadow_offset", 0, is_offset=True)
            self._add_numeric_row("阴影Y偏移", elem, "shadow_offset", 1, is_offset=True)
            self._add_slider_row("阴影模糊半径", elem, "shadow_blur", 0, 20)
            self._add_slider_row("阴影不透明度", elem, "shadow_opacity", 0.0, 1.0)
            label("旋转角度（度）")
            self._add_float_entry(elem, "rotation", -180.0, 180.0)
            label("宽度比例（0~1）")
            self._add_float_entry(elem, "w_rel", 0.001, 1.0)
            label("高度比例（0~1）")
            self._add_float_entry(elem, "h_rel", 0.001, 1.0)
        label("位置 X（0~1）")
        self._add_float_entry(elem, "x", 0.0, 1.0)
        label("位置 Y（0~1）")
        self._add_float_entry(elem, "y", 0.0, 1.0)

    def _contrast_color(self, hexcolor):
        try:
            hexcolor = hexcolor.lstrip("#")
            r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
            return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 150 else "#FFFFFF"
        except Exception:
            return "#FFFFFF"

    def _add_float_entry(self, elem, attr, lo, hi):
        var = StringVar(value=str(round(getattr(elem, attr), 4)))
        self._live_attr_vars[attr] = var

        def on_change(_e=None):
            try:
                val = max(lo, min(hi, float(var.get())))
                setattr(elem, attr, val)
                self._redraw_canvas()
            except ValueError:
                pass
        entry = ctk.CTkEntry(self.prop_container, textvariable=var, font=self.ui_font)
        entry.pack(fill="x", pady=2)
        entry.bind("<KeyRelease>", on_change)

    def _sync_live_var(self, attr, val):
        v = self._live_attr_vars.get(attr)
        if v is not None:
            v.set(str(round(val, 4)))

    def _add_numeric_row(self, text, elem, attr, index, is_offset=False):
        ctk.CTkLabel(self.prop_container, text=text, anchor="w", justify="left",
                     wraplength=max(140, self.right_w - 45),
                     text_color=T("text_mid"), font=self.ui_font).pack(fill="x", pady=(6, 0))
        current = getattr(elem, attr)
        var = StringVar(value=str(current[index] if is_offset else current))

        def on_change(_e=None):
            try:
                val = float(var.get())
                if is_offset:
                    lst = list(getattr(elem, attr))
                    lst[index] = val
                    setattr(elem, attr, tuple(lst))
                else:
                    setattr(elem, attr, val)
                self._redraw_canvas()
            except ValueError:
                pass
        entry = ctk.CTkEntry(self.prop_container, textvariable=var, font=self.ui_font)
        entry.pack(fill="x", pady=2)
        entry.bind("<KeyRelease>", on_change)

    def _add_slider_row(self, text, elem, attr, lo, hi):
        ctk.CTkLabel(self.prop_container, text=f"{text}：{getattr(elem, attr)}", anchor="w", justify="left",
                     wraplength=max(140, self.right_w - 45),
                     text_color=T("text_mid"), font=self.ui_font).pack(fill="x", pady=(6, 0))
        lbl = self.prop_container.winfo_children()[-1]

        def on_move(v):
            setattr(elem, attr, v if isinstance(getattr(elem, attr), float) else int(v))
            lbl.configure(text=f"{text}：{round(getattr(elem, attr), 2)}")
            self._request_redraw()
        slider = ctk.CTkSlider(self.prop_container, from_=lo, to=hi, command=on_move,
                               progress_color=T("accent"), button_color=T("accent"), button_hover_color=T("accent_h"))
        slider.set(getattr(elem, attr))
        slider.pack(fill="x", pady=2)

    def _is_interacting(self):
        return bool(self.drag_state) or getattr(self, "_zoom_interacting", False) \
            or getattr(self, "_resize_interacting", False)

    def _request_redraw(self):
        if self._redraw_after_id is None:
            self._redraw_after_id = self.after(1, self._flush_redraw)

    def _flush_redraw(self):
        self._redraw_after_id = None
        self._redraw_canvas()

    def _on_canvas_resize(self, _event):
        self._resize_interacting = True
        self._preview_cache = None
        self._dotgrid_cache = None
        self._shadow_cache = None
        if self._resize_after_id:
            self.after_cancel(self._resize_after_id)
        self._resize_after_id = self.after(30, self._redraw_canvas)
        if self._resize_settle_id:
            self.after_cancel(self._resize_settle_id)
        self._resize_settle_id = self.after(220, self._resize_settle)

    def _resize_settle(self):
        self._resize_settle_id = None
        self._resize_interacting = False
        self._preview_cache = None
        self._redraw_canvas()

    def _on_canvas_double_click(self, event):
        if self._render_boxes:
            cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            for _elem_id, (x0, y0, x1, y1) in self._render_boxes:
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    return
        if self._pixel_perfect:
            self._fit_canvas()
        else:
            self._zoom_pixel_perfect()

    def _on_canvas_zoom(self, event):
        if self.current_index is None:
            return
        if self._pixel_perfect:
            self._pixel_perfect = False
        if getattr(event, "num", None) == 4:
            factor = 1.08
        elif getattr(event, "num", None) == 5:
            factor = 1 / 1.08
        else:
            steps = max(1, min(4, round(abs(event.delta) / 120)))
            factor = 1.08 ** steps if event.delta > 0 else (1 / 1.08) ** steps
        old_zoom = self.canvas_zoom
        self.canvas_zoom = max(ZOOM_MIN, min(ZOOM_MAX, self.canvas_zoom * factor))
        if abs(self.canvas_zoom - old_zoom) < 1e-6:
            return
        self.canvas_zoom_label.configure(text=f"{round(self.canvas_zoom * 100)}%")
        if self._preview_meta is not None:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            pw, ph, off_x, off_y = self._preview_meta
            rel_x = (cx - off_x) / pw if pw else 0.5
            rel_y = (cy - off_y) / ph if ph else 0.5
            self._pending_zoom_focus = (rel_x, rel_y, event.x, event.y)
        self._preview_cache = None
        self._zoom_interacting = True
        if self._zoom_settle_job is not None:
            self.after_cancel(self._zoom_settle_job)
        if self._quality_settle_id is not None:
            self.after_cancel(self._quality_settle_id)
            self._quality_settle_id = None
        self._zoom_settle_job = self.after(180, self._zoom_settle)
        self._request_redraw()

    def _zoom_settle(self):
        self._zoom_settle_job = None
        self._zoom_interacting = True
        self._redraw_canvas()
        if self._quality_settle_id is not None:
            self.after_cancel(self._quality_settle_id)
        self._quality_settle_id = self.after(120, self._quality_settle_finalize)

    def _quality_settle_finalize(self):
        self._quality_settle_id = None
        self._zoom_interacting = False
        self._preview_cache = None
        self._redraw_canvas()

    def _fit_canvas(self):
        self.canvas_zoom = 1.0
        self._pixel_perfect = False
        self._preview_cache = None
        if hasattr(self, "canvas_zoom_label"):
            self.canvas_zoom_label.configure(text="100%")
        self._redraw_canvas()

    def _zoom_pixel_perfect(self):
        self._pixel_perfect = not self._pixel_perfect
        self._preview_cache = None
        if hasattr(self, "canvas_zoom_label"):
            self.canvas_zoom_label.configure(text="1:1" if self._pixel_perfect else f"{round(self.canvas_zoom * 100)}%")
        self._redraw_canvas()

    def on_perspective_crop(self):
        if self.current_index is None:
            messagebox.showinfo("提示", "请先在左侧选择一张图片。")
            return
        entry = self.images[self.current_index]
        if entry.pil_image is None:
            try:
                entry.pil_image = Image.open(entry.path).convert("RGB")
            except Exception as e:
                messagebox.showerror("打开图片失败", str(e))
                return

        def _on_crop_applied(warped_img):
            entry.pil_image = warped_img
            self._preview_cache = None
            self._crop_dialog = None
            self._redraw_canvas()
        self._crop_dialog = PerspectiveCropDialog(self, entry.pil_image, _on_crop_applied)

    def on_rotate_image(self, angle):
        if self.current_index is None:
            messagebox.showinfo("提示", "请先在左侧选择一张图片。")
            return
        entry = self.images[self.current_index]
        if entry.pil_image is None:
            try:
                entry.pil_image = Image.open(entry.path).convert("RGB")
            except Exception as e:
                messagebox.showerror("旋转失败", str(e))
            return
        entry.pil_image = entry.pil_image.rotate(angle, expand=True)
        self._preview_cache = None
        self._redraw_canvas()

    def on_flip_image(self, mode):
        if self.current_index is None:
            messagebox.showinfo("提示", "请先在左侧选择一张图片。")
            return
        entry = self.images[self.current_index]
        if entry.pil_image is None:
            try:
                entry.pil_image = Image.open(entry.path).convert("RGB")
            except Exception as e:
                messagebox.showerror("翻转失败", str(e))
            return
        if mode == "horizontal":
            entry.pil_image = entry.pil_image.transpose(Image.FLIP_LEFT_RIGHT)
        elif mode == "vertical":
            entry.pil_image = entry.pil_image.transpose(Image.FLIP_TOP_BOTTOM)
        self._preview_cache = None
        self._redraw_canvas()

    def _current_preview_source(self):
        if self.current_index is None or not self.images:
            self._preview_cache = None
            return None, None, {}
        entry = self.images[self.current_index]
        if entry.pil_image is None:
            return None, None, {}
        w, h = entry.pil_image.size
        if self._pixel_perfect:
            scale = 1.0
            cap = PIXEL_PERFECT_CAP_INTERACT if self._is_interacting() else PIXEL_PERFECT_CAP
            if max(w, h) * scale > cap:
                scale = cap / max(w, h)
        else:
            avail_w = max(100, self.canvas.winfo_width() - 24)
            avail_h = max(100, self.canvas.winfo_height() - 24)
            fit_scale = min(avail_w / w, avail_h / h, 1.0)
            scale = max(0.02, fit_scale * self.canvas_zoom)
            scale = min(scale, 1.0)
            max_long = MAX_PREVIEW_INTERACT if self._is_interacting() else MAX_PREVIEW_SETTLE
            long_edge = max(w, h) * scale
            if long_edge > max_long:
                scale *= max_long / long_edge
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        cache = self._preview_cache
        if (cache is not None and cache.get("index") == self.current_index
                and cache.get("size") == size and cache.get("source") is entry.pil_image):
            small = cache["img"]
        else:
            resample = Image.BILINEAR if self._is_interacting() else Image.LANCZOS
            small = entry.pil_image.resize(size, resample)
            self._preview_cache = {"index": self.current_index, "size": size,
                                   "img": small, "source": entry.pil_image}
        return small, size, entry.data

    def _ensure_dotgrid(self, cw, ch):
        if self._dotgrid_cache and self._dotgrid_cache["size"] == (cw, ch):
            return self._dotgrid_cache["img"]
        img = Image.new("RGBA", (max(1, cw), max(1, ch)), (0, 0, 0, 0))
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
        self._dotgrid_cache = {"size": (cw, ch), "img": tkimg}
        return tkimg

    def _ensure_shadow(self, size):
        if self._shadow_cache and self._shadow_cache["size"] == size:
            return self._shadow_cache["img"], self._shadow_cache["pad"]
        pad = 16
        w, h = size
        sh = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(sh)
        d.rounded_rectangle([pad - 1, pad - 1, pad + w + 1, pad + h + 1], radius=2, fill=THEME["photo_shadow"])
        sh = sh.filter(ImageFilter.GaussianBlur(7))
        tkimg = ImageTk.PhotoImage(sh)
        self._shadow_cache = {"size": size, "img": tkimg, "pad": pad}
        return tkimg, pad

    def _draw_rulers(self):
        """画布上/左标尺：显示原图像素刻度，随缩放/滚动同步，刻度疏密自适应。"""
        if self.ruler_top is None or self.ruler_left is None:
            return
        self.ruler_top.delete("all")
        self.ruler_left.delete("all")
        if self._preview_meta is None or self.current_index is None:
            return
        entry = self.images[self.current_index]
        if entry.pil_image is None:
            return
        orig_w, orig_h = entry.pil_image.size
        pw, ph, off_x, off_y = self._preview_meta
        sx_per_orig = pw / orig_w if orig_w else 0
        sy_per_orig = ph / orig_h if orig_h else 0
        # 标尺滚动区与主画布同宽/高，刻度用主画布坐标，靠 xview/yview 同步对齐
        try:
            sr = self.canvas.cget("scrollregion").split()
            scroll_w = float(sr[2]) if len(sr) >= 3 else pw + off_x
            scroll_h = float(sr[3]) if len(sr) >= 4 else ph + off_y
        except Exception:
            scroll_w, scroll_h = pw + off_x, ph + off_y
        self.ruler_top.configure(scrollregion=(0, 0, max(scroll_w, 1), RULER))
        self.ruler_left.configure(scrollregion=(0, 0, RULER, max(scroll_h, 1)))
        tick_col = THEME["text_dim"]
        txt_col = THEME["text_mid"]
        font = ("Bahnschrift", 9)
        # 上标尺（X，原图像素）
        if sx_per_orig > 0:
            step = _nice_step(70 / sx_per_orig)
            ox = 0.0
            while ox <= orig_w:
                x = off_x + ox * sx_per_orig
                major = (round(ox / step) % 1 == 0)
                self.ruler_top.create_line(x, RULER, x, RULER - (8 if major else 4), fill=tick_col, width=1)
                if major:
                    self.ruler_top.create_text(x + 2, 2, anchor="nw", text=str(int(round(ox))),
                                               fill=txt_col, font=font)
                ox += step
        # 左标尺（Y，原图像素）
        if sy_per_orig > 0:
            step = _nice_step(70 / sy_per_orig)
            oy = 0.0
            while oy <= orig_h:
                y = off_y + oy * sy_per_orig
                major = (round(oy / step) % 1 == 0)
                self.ruler_left.create_line(RULER, y, RULER - (8 if major else 4), y, fill=tick_col, width=1)
                if major:
                    self.ruler_left.create_text(RULER - 2, y, anchor="e", text=str(int(round(oy))),
                                                fill=txt_col, font=("Bahnschrift", 8))
                oy += step

    def _draw_selection(self, elem, canvas_bbox, size):
        cx0, cy0, cx1, cy1 = canvas_bbox
        self.canvas.create_rectangle(cx0 - 1, cy0 - 1, cx1 + 1, cy1 + 1, outline=ACCENT, width=2, tags="sel")
        corners = [(cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1)]
        for px, py in corners:
            self.canvas.create_rectangle(px - HANDLE - 1, py - HANDLE - 1, px + HANDLE + 1, py + HANDLE + 1,
                                         fill="#1f2329", outline="", tags="sel")
            self.canvas.create_rectangle(px - HANDLE, py - HANDLE, px + HANDLE, py + HANDLE,
                                         fill="white", outline=ACCENT, width=2, tags="sel")
        mids = [((cx0 + cx1) / 2, cy0), (cx1, (cy0 + cy1) / 2), ((cx0 + cx1) / 2, cy1), (cx0, (cy0 + cy1) / 2)]
        for mx, my in mids:
            self.canvas.create_rectangle(mx - 3 - 1, my - 3 - 1, mx + 3 + 1, my + 3 + 1, fill="#1f2329", outline="", tags="sel")
            self.canvas.create_rectangle(mx - 3, my - 3, mx + 3, my + 3, fill="white", outline=ACCENT, width=2, tags="sel")
        if elem.type in ("image", "shape"):
            hx, hy = get_image_resize_handle(elem, size)
            pw, ph, offset_x, offset_y = self._preview_meta
            hx, hy = hx + offset_x, hy + offset_y
            self.canvas.create_rectangle(hx - RESIZE_HANDLE - 1, hy - RESIZE_HANDLE - 1,
                                         hx + RESIZE_HANDLE + 1, hy + RESIZE_HANDLE + 1, fill="#1f2329", outline="", tags="sel")
            self.canvas.create_rectangle(hx - RESIZE_HANDLE, hy - RESIZE_HANDLE,
                                         hx + RESIZE_HANDLE, hy + RESIZE_HANDLE, fill="white", outline=ACCENT, width=2, tags="sel")

    def _redraw_canvas(self):
        self.canvas.delete("all")
        cw = max(200, self.canvas.winfo_width())
        ch = max(120, self.canvas.winfo_height())
        self.canvas.create_image(0, 0, anchor="nw", image=self._ensure_dotgrid(cw, ch), tags="bg")
        small, size, data = self._current_preview_source()
        if small is None:
            self.canvas.create_text(cw // 2, ch // 2 - 30, anchor="center", fill=THEME["text_dim"],
                                    text="还没有照片", font=_disp_font(16, True))
            self.canvas.create_text(
                cw // 2, ch // 2 + 6, anchor="center", fill=THEME["text_mid"], font=self.ui_font,
                text="① 点左上『打开图片 / 打开文件夹』导入照片\n"
                     "② 在右侧调水印，或直接拖动画布上的文字 / 图标\n"
                     "③ 点『导入数据表』批量填充 {字段}\n"
                     "④ 点右下绿色『批量导出全部』")
            self.canvas.configure(scrollregion=(0, 0, cw, ch))
            if hasattr(self, "canvas_warning_label"):
                self.canvas_warning_label.configure(text="")
            self._draw_rulers()
            return
        rendered = render_template(small, self.template, data=data, font_manager=self.font_manager,
                                   fast=self._is_interacting())
        self._tk_preview_img = ImageTk.PhotoImage(rendered)
        cw = max(size[0], self.canvas.winfo_width())
        ch = max(size[1], self.canvas.winfo_height())
        offset_x = max(0, (cw - size[0]) // 2)
        offset_y = max(0, (ch - size[1]) // 2)
        self._preview_meta = (size[0], size[1], offset_x, offset_y)
        self.canvas.configure(scrollregion=(0, 0, cw, ch))
        if self._pending_zoom_focus is not None:
            rel_x, rel_y, ex, ey = self._pending_zoom_focus
            self._pending_zoom_focus = None
            target_cx = rel_x * size[0] + offset_x
            target_cy = rel_y * size[1] + offset_y
            view_left = target_cx - ex
            view_top = target_cy - ey
            if cw > 0:
                self.canvas.xview_moveto(max(0.0, min(1.0, view_left / cw)))
            if ch > 0:
                self.canvas.yview_moveto(max(0.0, min(1.0, view_top / ch)))
        shadow_img, pad = self._ensure_shadow(size)
        self.canvas.create_image(offset_x - pad, offset_y - pad + 4, anchor="nw", image=shadow_img, tags="photo")
        self.canvas.create_rectangle(offset_x - 1, offset_y - 1, offset_x + size[0] + 1, offset_y + size[1] + 1,
                                     outline=THEME["border2"], width=1, tags="photo")
        self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self._tk_preview_img, tags="photo")
        missing = template_unresolved_fields(self.template, data)
        if missing:
            parts = ["{}：{}".format(name, "、".join("{%s}" % f for f in fields)) for name, fields in missing.items()]
            self.canvas_warning_label.configure(text="⚠ 未匹配字段：" + "；".join(parts))
        else:
            self.canvas_warning_label.configure(text="")
        self._render_boxes = []
        for elem in self.template.elements:
            bbox = get_element_bbox(elem, size, data=data, font_manager=self.font_manager)
            x0, y0, x1, y1 = bbox
            canvas_bbox = (x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y)
            self._render_boxes.append((elem.id, canvas_bbox))
            if elem.id == self.selected_elem_id:
                self._draw_selection(elem, canvas_bbox, size)
        self._draw_rulers()

    def _hit_resize_handle(self, event):
        elem = self.template.find(self.selected_elem_id) if self.selected_elem_id else None
        if elem is None or elem.type not in ("image", "shape") or self._preview_meta is None:
            return None
        pw, ph, offset_x, offset_y = self._preview_meta
        hx, hy = get_image_resize_handle(elem, (pw, ph))
        hx, hy = hx + offset_x, hy + offset_y
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if abs(cx - hx) <= RESIZE_HANDLE + 4 and abs(cy - hy) <= RESIZE_HANDLE + 4:
            return elem
        return None

    def on_canvas_press(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        resize_elem = self._hit_resize_handle(event)
        if resize_elem is not None:
            self._canvas_drag_start = None  # 命中手柄：清平移标记
            self.drag_state = {"mode": "resize", "elem_id": resize_elem.id}
            return
        for elem_id, (x0, y0, x1, y1) in reversed(self._render_boxes):
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                self._canvas_drag_start = None  # 命中元素：清平移标记
                self._select_element(elem_id)
                self.drag_state = {"mode": "move", "elem_id": elem_id,
                                   "off_x": cx - x0, "off_y": cy - y0}
                return
        self.canvas.scan_mark(event.x, event.y)
        self._canvas_drag_start = (event.x, event.y)
        self.drag_state = None

    def on_canvas_drag(self, event):
        # 元素拖拽/缩放【优先】：只要 press 设了 drag_state，就无条件走元素逻辑，
        # 绝不被平移画布的 _canvas_drag_start 抢走。这是“拖不动”的根因修复——
        # 旧逻辑先判 _canvas_drag_start，点过一次空白后该标记残留，拖元素全变平移。
        if self.drag_state and self._preview_meta is not None:
            pw, ph, offset_x, offset_y = self._preview_meta
            elem = self.template.find(self.drag_state["elem_id"])
            if elem is not None:
                cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
                if self.drag_state["mode"] == "resize":
                    x0, y0, _x1, _y1 = get_element_bbox(elem, (pw, ph))
                    x0 += offset_x
                    y0 += offset_y
                    new_w = max(6, cx - x0)
                    new_h = max(6, cy - y0)
                    elem.w_rel = max(0.001, min(1.0, new_w / pw))
                    elem.h_rel = max(0.001, min(1.0, new_h / ph))
                    self._sync_live_var("w_rel", elem.w_rel)
                    self._sync_live_var("h_rel", elem.h_rel)
                    self._request_redraw()
                    return
                off_x = self.drag_state["off_x"]
                off_y = self.drag_state["off_y"]
                new_x0 = cx - off_x - offset_x
                new_y0 = cy - off_y - offset_y
                elem.x = max(0.0, min(1.0, new_x0 / pw))
                elem.y = max(0.0, min(1.0, new_y0 / ph))
                self._sync_live_var("x", elem.x)
                self._sync_live_var("y", elem.y)
                self._request_redraw()
                return
        # 没在拖元素时，才是平移画布
        if self._canvas_drag_start is not None:
            self.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_canvas_release(self, _event):
        self._canvas_drag_start = None
        was_dragging = bool(self.drag_state)
        self.drag_state = None
        if was_dragging:
            self._redraw_canvas()

    def _build_element_menu(self, elem_id):
        elem = self.template.find(elem_id)
        menu = Menu(self, tearoff=0, bg=THEME["panel"], fg=THEME["text"],
                    activebackground=THEME["sel"], activeforeground=THEME["text"], font=self.menu_font)
        menu.add_command(label=f"选中：{elem.name}", state="disabled")
        menu.add_separator()
        menu.add_command(label="复制该元素", command=lambda: self.on_duplicate_element(elem_id))
        menu.add_command(label="置于最顶层", command=lambda: self._move_element_z(elem_id, +999))
        menu.add_command(label="置于最底层", command=lambda: self._move_element_z(elem_id, -999))
        menu.add_command(label="上移一层", command=lambda: self._move_element_z(elem_id, +1))
        menu.add_command(label="下移一层", command=lambda: self._move_element_z(elem_id, -1))
        menu.add_separator()
        menu.add_command(label="删除该元素", command=lambda: self._delete_by_id(elem_id))
        return menu

    def on_elem_list_right_click(self, event):
        if not self.template.elements:
            return
        idx = self.elem_listbox.nearest(event.y)
        idx = max(0, min(len(self.template.elements) - 1, idx))
        elem = self.template.elements[idx]
        self._select_element(elem.id)
        self._build_element_menu(elem.id).tk_popup(event.x_root, event.y_root)

    def on_canvas_right_click(self, event):
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        clicked_elem_id = None
        for elem_id, (x0, y0, x1, y1) in reversed(self._render_boxes):
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                clicked_elem_id = elem_id
                break
        if clicked_elem_id:
            self._select_element(clicked_elem_id)
            self._build_element_menu(clicked_elem_id).tk_popup(event.x_root, event.y_root)
        else:
            menu = Menu(self, tearoff=0, bg=THEME["panel"], fg=THEME["text"],
                        activebackground=THEME["sel"], activeforeground=THEME["text"], font=self.menu_font)
            menu.add_command(label="适应窗口大小（重置缩放）", command=self._fit_canvas)
            pp_text = "退出 1:1（回到适应窗口）" if self._pixel_perfect else "1:1 实际像素（查看真实清晰度）"
            menu.add_command(label=pp_text, command=self._zoom_pixel_perfect)
            menu.add_separator()
            menu.add_command(label="📐 透视裁剪矫正…", command=self.on_perspective_crop)
            menu.add_command(label="↻ 顺时针旋转90°", command=lambda: self.on_rotate_image(270))
            menu.add_command(label="↺ 逆时针旋转90°", command=lambda: self.on_rotate_image(90))
            menu.add_command(label="⇆ 水平翻转", command=lambda: self.on_flip_image("horizontal"))
            menu.add_command(label="⥯ 垂直翻转", command=lambda: self.on_flip_image("vertical"))
            menu.add_separator()
            menu.add_command(label="在此添加文字元素", command=lambda: self._add_element_at(event, "text"))
            menu.add_command(label="在此添加图标元素", command=lambda: self._add_element_at(event, "image"))
            menu.add_command(label="在此添加形状元素", command=lambda: self._add_element_at(event, "shape"))
            menu.tk_popup(event.x_root, event.y_root)

    def _move_element_z(self, elem_id, delta):
        self.template.move_z(elem_id, delta)
        self._refresh_element_list()
        self._redraw_canvas()

    def _delete_by_id(self, elem_id):
        self.template.remove(elem_id)
        if self.selected_elem_id == elem_id:
            self.selected_elem_id = None
        self._refresh_element_list()
        self._redraw_canvas()

    def _add_element_at(self, event, kind):
        if self._preview_meta is None:
            return
        pw, ph, offset_x, offset_y = self._preview_meta
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        rel_x = max(0.0, min(1.0, (cx - offset_x) / pw))
        rel_y = max(0.0, min(1.0, (cy - offset_y) / ph))
        if kind == "text":
            elem = self.template.add(TextElement(content="新文字{字段名}", name="文字", x=rel_x, y=rel_y))
        elif kind == "shape":
            elem = self.template.add(ShapeElement(shape="rect", name="形状", x=rel_x, y=rel_y))
        else:
            path = filedialog.askopenfilename(title="选择图标/色块图片(PNG推荐)",
                                              filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
            elem = self.template.add(ImageElement(path=path or "", name="图标", x=rel_x, y=rel_y))
        self._refresh_element_list()
        self._select_element(elem.id)
        self._redraw_canvas()

    def on_choose_output_dir(self):
        d = filedialog.askdirectory(title="选择批量导出的输出目录")
        if d:
            self.output_dir_var.set(d)

    def _build_output_name(self, entry, pattern):
        pattern = (pattern or "").strip()
        base, ext = os.path.splitext(os.path.basename(entry.path))
        if not pattern:
            return f"{base}{ext}"
        name = safe_format(pattern, entry.data)
        name = sanitize_filename(name)
        return f"{name}{ext}"

    def on_export_current(self):
        if self.current_index is None:
            messagebox.showinfo("提示", "请先选择一张图片。")
            return
        entry = self.images[self.current_index]
        out_path = filedialog.asksaveasfilename(
            title="导出当前图片",
            initialfile=self._build_output_name(entry, self.rename_var.get()),
            defaultextension=os.path.splitext(entry.path)[1])
        if not out_path:
            return
        try:
            full = render_template(entry.pil_image, self.template, data=entry.data,
                                   font_manager=self.font_manager, layer_cache=False)
            full.save(out_path, quality=95)
            self._show_toast("已导出当前图片")
            messagebox.showinfo("完成", f"已导出：\n{out_path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def on_batch_export(self):
        if self._exporting:
            return
        if not self.images:
            messagebox.showinfo("提示", "请先加载图片。")
            return
        out_dir = self.output_dir_var.get()
        if not out_dir:
            first_dir = os.path.dirname(self.images[0].path)
            out_dir = os.path.join(first_dir, "output")
        os.makedirs(out_dir, exist_ok=True)
        pattern = self.rename_var.get()
        snapshot = [(e.path, dict(e.data)) for e in self.images]
        total = len(snapshot)
        self._exporting = True
        self.btn_batch_export.configure(state="disabled")
        self.btn_export_current.configure(state="disabled")
        self.progress.set(0)

        def worker():
            errors = []
            unresolved_counts = {}
            tmpl = self.template
            for i, (path, data) in enumerate(snapshot):
                try:
                    img = Image.open(path).convert("RGB")
                    for fields in template_unresolved_fields(tmpl, data).values():
                        for f in fields:
                            unresolved_counts[f] = unresolved_counts.get(f, 0) + 1
                    rendered = render_template(img, tmpl, data=data,
                                               font_manager=self.font_manager, layer_cache=False)
                    base, ext = os.path.splitext(os.path.basename(path))
                    if pattern.strip():
                        out_name = sanitize_filename(safe_format(pattern, data)) + ext
                    else:
                        out_name = base + ext
                    out_path = os.path.join(out_dir, out_name)
                    stem, ex = os.path.splitext(out_path)
                    n = 1
                    while os.path.exists(out_path):
                        out_path = f"{stem}_{n}{ex}"
                        n += 1
                    rendered.save(out_path, quality=95)
                except Exception as e:
                    errors.append(f"{os.path.basename(path)}: {e}")
                self.after(0, lambda p=(i + 1) / total: self.progress.set(p))
            self.after(0, lambda: self._finish_batch(total, errors, unresolved_counts, out_dir))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_batch(self, total, errors, unresolved_counts, out_dir):
        self._exporting = False
        self.btn_batch_export.configure(state="normal")
        self.btn_export_current.configure(state="normal")
        self.progress.set(1.0)
        warn_text = ""
        if unresolved_counts:
            detail = "、".join(f"{{{k}}}（{v}张）" for k, v in sorted(unresolved_counts.items(), key=lambda kv: -kv[1]))
            warn_text = ("\n\n⚠ 提醒：部分占位符未匹配表格数据：\n" + detail)
        if errors:
            messagebox.showwarning("部分失败", f"成功 {total - len(errors)} / {total}，失败：\n" + "\n".join(errors[:10]) + warn_text)
            self._show_toast(f"导出完成（{total - len(errors)}/{total}）")
        elif warn_text:
            messagebox.showwarning("完成（有提醒）", f"已全部导出到：\n{out_dir}" + warn_text)
            self._show_toast(f"已导出 {total} 张")
        else:
            messagebox.showinfo("完成", f"已全部导出到：\n{out_dir}")
            self._show_toast(f"已导出 {total} 张")


def run():
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


# === DRAG_PATCH_V1 ===
# 类外覆盖：运行时用干净版本盖掉拖拽/重绘/字号相关方法，抹平历史叠加差异。
# 坐标统一 canvasx/canvasy；drag 判定倒置；重绘无守卫；press 选中延迟一帧防事件链断裂。
def _p_hit_resize(self, event):
    elem = self.template.find(self.selected_elem_id) if self.selected_elem_id else None
    if elem is None or elem.type not in ("image", "shape") or self._preview_meta is None:
        return None
    pw, ph, offset_x, offset_y = self._preview_meta
    hx, hy = get_image_resize_handle(elem, (pw, ph))
    hx, hy = hx + offset_x, hy + offset_y
    cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
    if abs(cx - hx) <= 10 and abs(cy - hy) <= 10:
        return elem
    return None

def _p_press(self, event):
    cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
    relem = _p_hit_resize(self, event)
    if relem is not None:
        self._canvas_drag_start = None
        self.drag_state = {"mode": "resize", "elem_id": relem.id}
        return
    for elem_id, (x0, y0, x1, y1) in reversed(self._render_boxes):
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            self._canvas_drag_start = None
            self.drag_state = {"mode": "move", "elem_id": elem_id,
                               "off_x": cx - x0, "off_y": cy - y0}
            # 关键：选中+刷新属性面板推迟一帧，避免在 press 回调里重建右侧控件
            # 打断“按下→拖动”的 B1-Motion 事件链（“选中框在却拖不动”的根因之一）
            self.after(0, lambda eid=elem_id: self._select_element(eid))
            return
    self.canvas.scan_mark(event.x, event.y)
    self._canvas_drag_start = (event.x, event.y)
    self.drag_state = None

def _p_drag(self, event):
    if self.drag_state and self._preview_meta is not None:
        pw, ph, offset_x, offset_y = self._preview_meta
        elem = self.template.find(self.drag_state["elem_id"])
        if elem is not None:
            _rd = getattr(self, "_request_redraw", None) or getattr(self, "_redraw_canvas", lambda: None)
            _lv = getattr(self, "_sync_live_var", lambda *a, **k: None)
            cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            if self.drag_state["mode"] == "resize":
                x0, y0, _x1, _y1 = get_element_bbox(elem, (pw, ph))
                x0 += offset_x; y0 += offset_y
                elem.w_rel = max(0.001, min(1.0, max(6, cx - x0) / pw))
                elem.h_rel = max(0.001, min(1.0, max(6, cy - y0) / ph))
                _lv("w_rel", elem.w_rel); _lv("h_rel", elem.h_rel)
                _rd(); return
            off_x, off_y = self.drag_state["off_x"], self.drag_state["off_y"]
            elem.x = max(0.0, min(1.0, (cx - off_x - offset_x) / pw))
            elem.y = max(0.0, min(1.0, (cy - off_y - offset_y) / ph))
            _lv("x", elem.x); _lv("y", elem.y)
            _rd(); return
    if self._canvas_drag_start is not None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

def _p_release(self, event=None):
    self._canvas_drag_start = None
    was = bool(self.drag_state)
    self.drag_state = None
    if was:
        try:
            self._refresh_property_panel()
        except Exception:
            pass
        self._redraw_canvas()

def _p_request_redraw(self):
    # 无任何 _suppress_redraw 守卫：拖拽重绘绝不被拦截
    if self._redraw_after_id is None:
        self._redraw_after_id = self.after(1, self._flush_redraw)

def _p_on_resize(self, _event):
    self._resize_interacting = True
    self._preview_cache = None
    if getattr(self, "_dotgrid_cache", None) is not None:
        self._dotgrid_cache = None
    if getattr(self, "_shadow_cache", None) is not None:
        self._shadow_cache = None
    if getattr(self, "_resize_after_id", None):
        self.after_cancel(self._resize_after_id)
    self._resize_after_id = self.after(30, self._redraw_canvas)
    if getattr(self, "_resize_settle_id", None):
        self.after_cancel(self._resize_settle_id)
    self._resize_settle_id = self.after(220, self._resize_settle)

def _p_fonts(self):
    # 字号收小并封顶：基数 11、缩放封顶 1.25，高 DPI 屏不再爆字
    try:
        scale = ctk.ScalingTracker.get_widget_scaling(self)
    except Exception:
        scale = 1.0
    scale = max(1.0, min(1.25, scale))
    y = "Microsoft YaHei"
    n = max(11, round(11 * scale))
    ns = max(10, round(10 * scale))
    return ((y, n), (y, n), (y, n), (y, n, "bold"), (y, ns))

App._hit_resize_handle = _p_hit_resize
App.on_canvas_press = _p_press
App.on_canvas_drag = _p_drag
App.on_canvas_release = _p_release
App._request_redraw = _p_request_redraw
App._on_canvas_resize = _p_on_resize
App._compute_scaled_fonts = _p_fonts
# === /DRAG_PATCH_V1 ===




# === RECT_CROP_PATCH_V1 ===
# 矩形裁剪：自包含对话框 + 装饰器注入工具栏按钮。不修改 ui.py 主体任何方法体。

class RectCropDialog(ctk.CTkToplevel):
    """矩形裁剪工具：拖选框 / 移选框 / 8 手柄改大小 / 锁比例 / 实时像素读数。
    选框外网格遮罩压暗、选框内三分法参考线，专业修图软件的视觉规格。
    底图按画布尺寸缓存，遮罩用 tk 原生 stipple（非每帧 PIL 合成），拖拽跟手不卡。"""

    _RATIOS = ["自由", "原图", "1:1", "4:3", "3:4", "16:9", "9:16"]

    def __init__(self, parent, pil_image, on_apply_callback):
        super().__init__(parent)
        self.title("✂ 矩形裁剪")
        self.geometry("1000x700")
        self.configure(fg_color=T("bg"))
        self.grab_set()
        self.pil_image = pil_image.copy()
        self.on_apply_callback = on_apply_callback
        self.orig_w, self.orig_h = self.pil_image.size
        self.crop_rel = [0.10, 0.10, 0.90, 0.90]   # 相对原图 0~1 的选区
        self.mode = None                            # None/new/move/手柄名
        self._anchor = None
        self._disp_cache = None
        self.lock_var = tk.BooleanVar(value=False)
        self.ratio_var = tk.StringVar(value="自由")
        self._build_ui()
        self.after(50, self._draw_canvas)

    def _build_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.canvas = Canvas(self, bg=THEME["canvas"], highlightthickness=0, bd=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=10, pady=(10, 5))
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", lambda e: self._draw_canvas())
        bar = ctk.CTkFrame(self, fg_color=T("panel"), corner_radius=10,
                           border_width=1, border_color=T("border"))
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(5, 10))
        ctk.CTkCheckBox(bar, text="锁定比例", variable=self.lock_var, font=("Microsoft YaHei", 12),
                        command=self._draw_canvas).pack(side="left", padx=(12, 6), pady=8)
        ctk.CTkOptionMenu(bar, values=self._RATIOS, variable=self.ratio_var, width=90,
                          font=("Microsoft YaHei", 12), command=self._on_ratio_change).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="全选", width=60, fg_color=T("panel3"), text_color=T("text"),
                      hover_color=T("border2"), font=("Microsoft YaHei", 12),
                      command=self._select_all).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="清除", width=60, fg_color=T("panel3"), text_color=T("text"),
                      hover_color=T("border2"), font=("Microsoft YaHei", 12),
                      command=self._clear).pack(side="left", padx=4)
        self.readout = ctk.CTkLabel(bar, text="", text_color=T("accent"), font=_disp_font(12, True))
        self.readout.pack(side="left", padx=12)
        ctk.CTkButton(bar, text="暂存到内存预览", width=120, fg_color=T("ok"), hover_color=T("ok_hover"),
                      text_color="white", command=self._apply_temp).pack(side="right", padx=6, pady=8)
        ctk.CTkButton(bar, text="另存为新文件…", width=120, fg_color=T("accent"), hover_color=T("accent_h"),
                      text_color="white", command=self._save_to_file).pack(side="right", padx=6)
        ctk.CTkButton(bar, text="取消", width=70, fg_color=T("panel"), text_color=T("text_mid"),
                      hover_color=T("panel3"), command=self.destroy).pack(side="right", padx=6)

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
        # 以宽为基准调高，使选区宽高比等于目标（在显示像素空间衡量比例）
        dw, dh, _ox, _oy, _s = self._get_disp_meta()
        target = ratio * (dh / dw) if dw and dh else ratio   # 换算到 rel 空间的目标 w/h
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
        dw, dh = round(self.orig_w * scale), round(self.orig_h * scale)
        return dw, dh, (cw - dw) // 2, (ch - dh) // 2, scale

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
        return {"nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0), "e": (x1, my),
                "se": (x1, y1), "s": (mx, y1), "sw": (x0, y1), "w": (x0, my)}

    def _ensure_disp(self, dw, dh):
        size = (max(1, dw), max(1, dh))
        if self._disp_cache and self._disp_cache["size"] == size:
            return self._disp_cache["img"]
        img = ImageTk.PhotoImage(self.pil_image.resize(size, Image.BILINEAR))
        self._disp_cache = {"size": size, "img": img}
        return img

    def _draw_canvas(self):
        self.canvas.delete("all")
        cw = max(100, self.canvas.winfo_width())
        ch = max(100, self.canvas.winfo_height())
        dw, dh, ox, oy, _s = self._get_disp_meta()
        self.canvas.create_image(ox, oy, anchor="nw", image=self._ensure_disp(dw, dh))
        x0, y0, x1, y1 = self._sel_screen()
        # 选框外网格遮罩（4 矩形，tk 原生 stipple，零成本跟手）
        mask_kw = dict(fill="#000000", outline="", stipple="gray50")
        self.canvas.create_rectangle(0, 0, cw, y0, **mask_kw)
        self.canvas.create_rectangle(0, y1, cw, ch, **mask_kw)
        self.canvas.create_rectangle(0, y0, x0, y1, **mask_kw)
        self.canvas.create_rectangle(x1, y0, cw, y1, **mask_kw)
        # 选框边线
        self.canvas.create_rectangle(x0, y0, x1, y1, outline=ACCENT, width=2)
        # 三分法参考线
        for f in (1 / 3, 2 / 3):
            self.canvas.create_line(x0 + (x1 - x0) * f, y0, x0 + (x1 - x0) * f, y1,
                                    fill=THEME["accent"], width=1, dash=(3, 3))
            self.canvas.create_line(x0, y0 + (y1 - y0) * f, x1, y0 + (y1 - y0) * f,
                                    fill=THEME["accent"], width=1, dash=(3, 3))
        # 8 手柄（白芯蓝边，与主画布选中态同语言）
        for hx, hy in self._handles().values():
            self.canvas.create_rectangle(hx - 6, hy - 6, hx + 6, hy + 6, fill="#1f2329", outline="")
            self.canvas.create_rectangle(hx - 5, hy - 5, hx + 5, hy + 5, fill="white", outline=ACCENT, width=2)
        # 像素读数（带底条，自适应亮暗）
        w_px = (self.crop_rel[2] - self.crop_rel[0]) * self.orig_w
        h_px = (self.crop_rel[3] - self.crop_rel[1]) * self.orig_h
        ratio = (w_px / h_px) if h_px > 0 else 0
        txt = f"{int(round(w_px))} × {int(round(h_px))} px   ·   {ratio:.2f}"
        self.readout.configure(text=txt)
        tx, ty = (x0 + x1) / 2, min(y1 + 16, ch - 12)
        tw = len(txt) * 3.6 + 16
        self.canvas.create_rectangle(tx - tw, ty - 11, tx + tw, ty + 11, fill=THEME["panel"], outline=THEME["border"])
        self.canvas.create_text(tx, ty, text=txt, fill=THEME["text"], font=_disp_font(11, True))

    def _hit_handle(self, ex, ey):
        for name, (hx, hy) in self._handles().items():
            if abs(ex - hx) <= 8 and abs(ey - hy) <= 8:
                return name
        return None

    def _on_press(self, event):
        h = self._hit_handle(event.x, event.y)
        if h:
            self.mode, self._anchor = h, None
            return
        x0, y0, x1, y1 = self._sel_screen()
        if x0 <= event.x <= x1 and y0 <= event.y <= y1:
            self.mode, self._anchor = "move", (event.x, event.y, list(self.crop_rel))
            return
        dw, dh, ox, oy, _s = self._get_disp_meta()
        rx, ry = self._screen_to_rel(event.x, event.y, dw, dh, ox, oy)
        self.mode, self._anchor = "new", (rx, ry)
        self.crop_rel = [rx, ry, rx, ry]

    def _on_drag(self, event):
        if not self.mode:
            return
        dw, dh, ox, oy, _s = self._get_disp_meta()
        rx, ry = self._screen_to_rel(event.x, event.y, dw, dh, ox, oy)
        if self.mode == "new":
            ax, ay = self._anchor
            self.crop_rel = [min(ax, rx), min(ay, ry), max(ax, rx), max(ay, ry)]
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
        self.mode, self._anchor = None, None
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
            title="保存裁剪图片", defaultextension=".jpg",
            filetypes=[("JPEG", "*.jpg"), ("PNG", "*.png"), ("所有文件", "*.*")])
        if not out_path:
            return
        self._crop_image().save(out_path, quality=95)
        messagebox.showinfo("完成", f"已成功保存至：\n{out_path}")
        self.on_apply_callback(self._crop_image())
        self.destroy()


def _rc_on_rect_crop(self):
    """矩形裁剪入口：裁当前图，结果写回 entry.pil_image 并重绘预览。"""
    if self.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。")
        return
    entry = self.images[self.current_index]
    if entry.pil_image is None:
        try:
            entry.pil_image = Image.open(entry.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("打开图片失败", str(e))
            return

    def _apply(cropped):
        entry.pil_image = cropped
        self._preview_cache = None
        self._redraw_canvas()
    RectCropDialog(self, entry.pil_image, _apply)


# 装饰器：包装 _build_layout，先调原方法，再注入裁剪按钮 + 补一句画布提示。
# 原工具栏/原提示一字不丢；每次重建（含主题切换）都对应一个新 bar，注入一次正好。
_rc_orig_build_layout = App._build_layout

def _rc_wrapped_build_layout(self):
    _rc_orig_build_layout(self)
    tb = getattr(self, "_toolbar", None)
    if tb is not None:
        try:
            ctk.CTkButton(tb, text="✂ 裁剪", width=64, height=30, corner_radius=7,
                          font=self.ui_font, fg_color=T("accent_bg"), hover_color=T("accent_bg"),
                          text_color=T("accent_h"), command=self.on_rect_crop).pack(side="left", padx=1, pady=6)
        except Exception:
            pass
    tip = getattr(self, "canvas_tip_label", None)
    if tip is not None:
        try:
            cur = tip.cget("text")
            if "✂" not in cur:
                tip.configure(text=cur + " 『✂ 裁剪』可矩形裁切当前图。")
        except Exception:
            pass

App._build_layout = _rc_wrapped_build_layout
App.on_rect_crop = _rc_on_rect_crop
# === /RECT_CROP_PATCH_V1 ===


# === RIGHTCLICK_PATCH_V2 ===
import traceback as _rc2_tb

def _rc2_log(msg):
    try:
        d = os.path.join(os.path.expanduser("~"), ".watermark_studio")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "rightclick.log"), "a", encoding="utf-8") as f:
            import time as _rc2_t
            f.write(f"[{_rc2_t.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def _rc2_menu_kwargs(self):
    kw = dict(tearoff=0, bg=THEME["panel"], fg=THEME["text"],
              activebackground=THEME["sel"], activeforeground=THEME["text"])
    mf = getattr(self, "menu_font", None)
    if mf:
        kw["font"] = mf
    return kw

def _rc2_build_element_menu(self, elem_id):
    elem = self.template.find(elem_id)
    menu = Menu(self, **_rc2_menu_kwargs(self))
    menu.add_command(label=("选中：" + (elem.name if elem else "")), state="disabled")
    menu.add_separator()
    menu.add_command(label="复制该元素", command=lambda: getattr(self, "on_duplicate_element", lambda *a: None)(elem_id))
    menu.add_command(label="置于最顶层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, +999))
    menu.add_command(label="置于最底层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, -999))
    menu.add_command(label="上移一层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, +1))
    menu.add_command(label="下移一层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, -1))
    menu.add_separator()
    menu.add_command(label="删除该元素", command=lambda: getattr(self, "_delete_by_id", lambda *a: None)(elem_id))
    return menu

def _rc2_on_canvas_right_click(self, event):
    # 入口日志：确认右键到底有没有进到这个函数（闭包绑定是否生效）
    _rc2_log(f"canvas_right_click ENTER boxes={len(getattr(self, '_render_boxes', []))} "
             f"zoom={getattr(self, 'canvas_zoom', '?')} pixel_perfect={getattr(self, '_pixel_perfect', '?')}")
    try:
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        clicked = None
        for elem_id, (x0, y0, x1, y1) in reversed(self._render_boxes):
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                clicked = elem_id
                break
        if clicked:
            self._select_element(clicked)
            self._rc2_build_element_menu(clicked).tk_popup(event.x_root, event.y_root)
            _rc2_log("canvas_right_click -> element menu popped")
            return
        menu = Menu(self, **_rc2_menu_kwargs(self))
        menu.add_command(label="适应窗口大小（重置缩放）", command=lambda: getattr(self, "_fit_canvas", lambda: None)())
        pp = getattr(self, "_pixel_perfect", False)
        menu.add_command(label=("退出 1:1（回到适应窗口）" if pp else "1:1 实际像素（查看真实清晰度）"),
                         command=lambda: getattr(self, "_zoom_pixel_perfect", lambda: None)())
        menu.add_separator()
        menu.add_command(label="📐 透视裁剪矫正…", command=lambda: getattr(self, "on_perspective_crop", lambda: None)())
        menu.add_command(label="✂ 矩形裁剪…", command=lambda: getattr(self, "on_rect_crop", lambda: None)())
        menu.add_command(label="↻ 顺时针旋转90°", command=lambda: getattr(self, "on_rotate_image", lambda *a: None)(270))
        menu.add_command(label="↺ 逆时针旋转90°", command=lambda: getattr(self, "on_rotate_image", lambda *a: None)(90))
        menu.add_command(label="⇆ 水平翻转", command=lambda: getattr(self, "on_flip_image", lambda *a: None)("horizontal"))
        menu.add_command(label="⥯ 垂直翻转", command=lambda: getattr(self, "on_flip_image", lambda *a: None)("vertical"))
        menu.add_separator()
        menu.add_command(label="在此添加文字元素", command=lambda: self._rc2_add_at(event, "text"))
        menu.add_command(label="在此添加图标元素", command=lambda: self._rc2_add_at(event, "image"))
        menu.add_command(label="在此添加形状元素", command=lambda: self._rc2_add_at(event, "shape"))
        menu.tk_popup(event.x_root, event.y_root)
        _rc2_log("canvas_right_click -> blank menu popped")
    except Exception:
        _rc2_log("canvas_right_click EXCEPTION:\n" + _rc2_tb.format_exc())

def _rc2_on_elem_list_right_click(self, event):
    _rc2_log(f"elem_list_right_click ENTER nelems={len(self.template.elements)}")
    try:
        if not self.template.elements:
            return
        idx = self.elem_listbox.nearest(event.y)
        idx = max(0, min(len(self.template.elements) - 1, idx))
        elem = self.template.elements[idx]
        self._select_element(elem.id)
        self._rc2_build_element_menu(elem.id).tk_popup(event.x_root, event.y_root)
        _rc2_log("elem_list_right_click -> menu popped")
    except Exception:
        _rc2_log("elem_list_right_click EXCEPTION:\n" + _rc2_tb.format_exc())

def _rc2_add_at(self, event, kind):
    if self._preview_meta is None:
        return
    pw, ph, offset_x, offset_y = self._preview_meta
    cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
    rel_x = max(0.0, min(1.0, (cx - offset_x) / pw))
    rel_y = max(0.0, min(1.0, (cy - offset_y) / ph))
    if kind == "text":
        elem = self.template.add(TextElement(content="新文字{字段名}", name="文字", x=rel_x, y=rel_y))
    elif kind == "shape":
        elem = self.template.add(ShapeElement(shape="rect", name="形状", x=rel_x, y=rel_y))
    else:
        path = filedialog.askopenfilename(title="选择图标/色块图片(PNG推荐)",
                                          filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        elem = self.template.add(ImageElement(path=path or "", name="图标", x=rel_x, y=rel_y))
    getattr(self, "_refresh_element_list", lambda: None)()
    self._select_element(elem.id)

# ---- 透视裁剪：加选区外压暗遮罩 + 线加粗 + 实时像素读数 ----
def _pc_draw_canvas(self):
    self.canvas.delete("all")
    cw = max(100, self.canvas.winfo_width())
    ch = max(100, self.canvas.winfo_height())
    # 点阵背景
    try:
        self.canvas.create_image(0, 0, anchor="nw", image=self._ensure_dotgrid(cw, ch))
    except Exception:
        pass
    dw, dh, ox, oy, _scale = self._get_disp_meta()
    size = (max(1, dw), max(1, dh))
    if self._disp_cache is not None and self._disp_cache["size"] == size:
        self.tk_img = self._disp_cache["img"]
    else:
        self.tk_img = ImageTk.PhotoImage(self.pil_image.resize(size, Image.BILINEAR))
        self._disp_cache = {"size": size, "img": self.tk_img}
    self.canvas.create_image(ox, oy, anchor="nw", image=self.tk_img)
    corners_screen = [self._rel_to_screen(p, dw, dh, ox, oy) for p in self.corners_rel]
    # 选区外压暗遮罩：在【显示尺寸】(cw,ch) 上用 PIL 挖洞，绝不碰原图 → 拖拽跟手
    try:
        msk = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        md = ImageDraw.Draw(msk)
        md.rectangle([0, 0, cw, ch], fill=(0, 0, 0, 150))
        md.polygon([tuple(map(int, p)) for p in corners_screen], fill=(0, 0, 0, 0))
        self._pc_mask_img = ImageTk.PhotoImage(msk)   # 保活，防 GC 致空白
        self.canvas.create_image(0, 0, anchor="nw", image=self._pc_mask_img)
    except Exception:
        pass
    # 边线（加粗到 3、虚线更连贯）+ 边控制点
    for i in range(4):
        order = self._edge_order(i)
        chain = [corners_screen[i]]
        chain += [self._rel_to_screen(self.edge_points_rel[i][k], dw, dh, ox, oy) for k in order]
        chain.append(corners_screen[(i + 1) % 4])
        for j in range(len(chain) - 1):
            x1, y1 = chain[j]; x2, y2 = chain[j + 1]
            self.canvas.create_line(x1, y1, x2, y2, fill=ACCENT, width=3, dash=(8, 4), tags="anchor")
        for k in order:
            mx, my = self._rel_to_screen(self.edge_points_rel[i][k], dw, dh, ox, oy)
            self._draw_anchor_square(mx, my, active=(self.active_handle == ("edge", i, k)))
    # 角点
    for i, (px, py) in enumerate(corners_screen):
        self._draw_anchor_dot(px, py, active=(self.active_handle == ("corner", i)))
    # 实时像素读数（取对边平均，轻量，不算 mesh）
    try:
        cpx = [(rx * self.orig_w, ry * self.orig_h) for rx, ry in self.corners_rel]
        w_px = 0.5 * (math.hypot(cpx[1][0] - cpx[0][0], cpx[1][1] - cpx[0][1]) +
                      math.hypot(cpx[2][0] - cpx[3][0], cpx[2][1] - cpx[3][1]))
        h_px = 0.5 * (math.hypot(cpx[3][0] - cpx[0][0], cpx[3][1] - cpx[0][1]) +
                      math.hypot(cpx[2][0] - cpx[1][0], cpx[2][1] - cpx[1][1]))
        txt = "基准框 ≈ %d × %d px" % (int(round(w_px)), int(round(h_px)))
        tcx = sum(p[0] for p in corners_screen) / 4
        tcy = max(14, min(p[1] for p in corners_screen) - 14)
        tw = len(txt) * 3.6 + 14
        self.canvas.create_rectangle(tcx - tw, tcy - 11, tcx + tw, tcy + 11,
                                     fill=THEME["panel"], outline=THEME["border"])
        self.canvas.create_text(tcx, tcy, text=txt, fill=THEME["text"], font=("Bahnschrift", 11))
    except Exception:
        pass

# 类级覆盖（兜底）
App._build_element_menu = _rc2_build_element_menu
App.on_canvas_right_click = _rc2_on_canvas_right_click
App.on_elem_list_right_click = _rc2_on_elem_list_right_click
App._rc2_add_at = _rc2_add_at
try:
    PerspectiveCropDialog._draw_canvas = _pc_draw_canvas
except Exception as _e:
    _rc2_log("cover PerspectiveCropDialog._draw_canvas fail: %r" % _e)

# 关键：build 后用【闭包】绑定右键到 overlay 函数本体，绕开实例属性遮蔽。
# 这是前几轮失败的根因——bind self.方法 可能绑到被遮蔽的旧实例方法。
def _rc2_bind(self):
    try:
        self.canvas.bind("<Button-3>", lambda e, s=self: _rc2_on_canvas_right_click(s, e))
    except Exception as ex:
        _rc2_log("bind canvas <Button-3> fail: %r" % ex)
    try:
        self.elem_listbox.bind("<Button-3>", lambda e, s=self: _rc2_on_elem_list_right_click(s, e))
    except Exception as ex:
        _rc2_log("bind elem_listbox <Button-3> fail: %r" % ex)

_rc2_orig_build = App._build_layout
def _rc2_wrapped_build(self):
    _rc2_orig_build(self)
    _rc2_bind(self)
App._build_layout = _rc2_wrapped_build
# === /RIGHTCLICK_PATCH_V2 ===


# === RULER_SAFE_PATCH_V1 ===
_rc_orig_draw_rulers = App._draw_rulers
def _rc_safe_draw_rulers(self):
    try:
        _rc_orig_draw_rulers(self)
    except Exception:
        for _c in (getattr(self, "ruler_top", None), getattr(self, "ruler_left", None)):
            try:
                if _c is not None:
                    _c.delete("all")
            except Exception:
                pass
App._draw_rulers = _rc_safe_draw_rulers
# === /RULER_SAFE_PATCH_V1 ===


# === RIGHTCLICK_PATCH_V3 ===
import traceback as _rc3_tb
def _rc3_log(msg):
    try:
        d = os.path.join(os.path.expanduser("~"), ".watermark_studio")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "rightclick.log"), "a", encoding="utf-8") as f:
            import time as _t
            f.write("[%s] %s\n" % (_t.strftime("%H:%M:%S"), msg))
    except Exception:
        pass

def _rc3_menu_kw(self):
    kw = dict(tearoff=0, bg=THEME["panel"], fg=THEME["text"],
              activebackground=THEME["sel"], activeforeground=THEME["text"])
    mf = getattr(self, "menu_font", None)
    if mf:
        kw["font"] = mf
    return kw

def _rc2_build_element_menu(self, elem_id):
    elem = self.template.find(elem_id)
    menu = Menu(self, **_rc3_menu_kw(self))
    menu.add_command(label=("选中：" + (elem.name if elem else "")), state="disabled")
    menu.add_separator()
    menu.add_command(label="复制该元素", command=lambda: getattr(self, "on_duplicate_element", lambda *a: None)(elem_id))
    menu.add_command(label="置于最顶层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, +999))
    menu.add_command(label="置于最底层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, -999))
    menu.add_command(label="上移一层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, +1))
    menu.add_command(label="下移一层", command=lambda: getattr(self, "_move_element_z", lambda *a: None)(elem_id, -1))
    menu.add_separator()
    menu.add_command(label="删除该元素", command=lambda: getattr(self, "_delete_by_id", lambda *a: None)(elem_id))
    return menu

def _rc2_on_canvas_right_click(self, event):
    _rc3_log("canvas_right_click ENTER boxes=%d" % len(getattr(self, "_render_boxes", [])))
    try:
        cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        clicked = None
        for elem_id, (x0, y0, x1, y1) in reversed(self._render_boxes):
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                clicked = elem_id
                break
        if clicked:
            self._select_element(clicked)
            _rc2_build_element_menu(self, clicked).tk_popup(event.x_root, event.y_root)  # 模块级直调
            _rc3_log("canvas_right_click -> element menu popped")
            return
        menu = Menu(self, **_rc3_menu_kw(self))
        menu.add_command(label="适应窗口大小（重置缩放）", command=lambda: getattr(self, "_fit_canvas", lambda: None)())
        pp = getattr(self, "_pixel_perfect", False)
        menu.add_command(label=("退出 1:1（回到适应窗口）" if pp else "1:1 实际像素（查看真实清晰度）"),
                         command=lambda: getattr(self, "_zoom_pixel_perfect", lambda: None)())
        menu.add_separator()
        menu.add_command(label="📐 透视裁剪矫正…", command=lambda: getattr(self, "on_perspective_crop", lambda: None)())
        menu.add_command(label="✂ 矩形裁剪…", command=lambda: getattr(self, "on_rect_crop", lambda: None)())
        menu.add_command(label="↻ 顺时针旋转90°", command=lambda: getattr(self, "on_rotate_image", lambda *a: None)(270))
        menu.add_command(label="↺ 逆时针旋转90°", command=lambda: getattr(self, "on_rotate_image", lambda *a: None)(90))
        menu.add_command(label="⇆ 水平翻转", command=lambda: getattr(self, "on_flip_image", lambda *a: None)("horizontal"))
        menu.add_command(label="⥯ 垂直翻转", command=lambda: getattr(self, "on_flip_image", lambda *a: None)("vertical"))
        menu.add_separator()
        menu.add_command(label="在此添加文字元素", command=lambda: _rc2_add_at(self, event, "text"))
        menu.add_command(label="在此添加图标元素", command=lambda: _rc2_add_at(self, event, "image"))
        menu.add_command(label="在此添加形状元素", command=lambda: _rc2_add_at(self, event, "shape"))
        menu.tk_popup(event.x_root, event.y_root)
        _rc3_log("canvas_right_click -> blank menu popped")
    except Exception:
        _rc3_log("canvas_right_click EXCEPTION:\n" + _rc3_tb.format_exc())

def _rc2_on_elem_list_right_click(self, event):
    _rc3_log("elem_list_right_click ENTER nelems=%d" % len(self.template.elements))
    try:
        if not self.template.elements:
            return
        idx = self.elem_listbox.nearest(event.y)
        idx = max(0, min(len(self.template.elements) - 1, idx))
        elem = self.template.elements[idx]
        self._select_element(elem.id)
        _rc2_build_element_menu(self, elem.id).tk_popup(event.x_root, event.y_root)  # 模块级直调
        _rc3_log("elem_list_right_click -> menu popped")
    except Exception:
        _rc3_log("elem_list_right_click EXCEPTION:\n" + _rc3_tb.format_exc())

def _rc2_add_at(self, event, kind):
    if self._preview_meta is None:
        return
    pw, ph, offset_x, offset_y = self._preview_meta
    cx, cy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
    rel_x = max(0.0, min(1.0, (cx - offset_x) / pw))
    rel_y = max(0.0, min(1.0, (cy - offset_y) / ph))
    if kind == "text":
        elem = self.template.add(TextElement(content="新文字{字段名}", name="文字", x=rel_x, y=rel_y))
    elif kind == "shape":
        elem = self.template.add(ShapeElement(shape="rect", name="形状", x=rel_x, y=rel_y))
    else:
        path = filedialog.askopenfilename(title="选择图标/色块图片(PNG推荐)",
                                          filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
        elem = self.template.add(ImageElement(path=path or "", name="图标", x=rel_x, y=rel_y))
    getattr(self, "_refresh_element_list", lambda: None)()
    self._select_element(elem.id)
# === /RIGHTCLICK_PATCH_V3 ===



# === UNDO_PATCH_V1 ===
# 统一撤销：以 _redraw_canvas 为唯一观测点，对模板指纹做 350ms 防抖，
# 把“一次连续操作”(拖一整段/滑杆拖一路/连打一串字/加删/加载模板)压成一个撤销点。
# 零侵入主体：不改动任何散落回调。Ctrl+Z 恢复；焦点在文本框时让给文本自身的撤销。
def _un_snap(self):
    try:
        return self.template.to_dict()
    except Exception:
        return None

def _un_push(self, d):
    if d is None:
        return
    st = getattr(self, "_undo_stack", None)
    if st is None:
        st = []
        self._undo_stack = st
    st.append(d)
    if len(st) > 60:
        del st[:len(st) - 60]

def _un_observe(self):
    if getattr(self, "_undo_in_progress", False):
        return
    cur = _un_snap(self)
    if cur is None:
        return
    last = getattr(self, "_undo_last", None)
    if last is None:
        self._undo_last = cur          # 首次：记基线，不 push
        return
    if cur == last:
        return                          # 未变
    if getattr(self, "_undo_pending_before", None) is None:
        self._undo_pending_before = last   # “变化开始前的稳定态”，连续变化期间只设一次
    self._undo_last = cur
    t = getattr(self, "_undo_timer", None)
    if t:
        try:
            self.after_cancel(t)
        except Exception:
            pass
    self._undo_timer = self.after(350, self._un_commit)

def _un_commit(self):
    self._undo_timer = None
    before = getattr(self, "_undo_pending_before", None)
    if before is not None:
        _un_push(self, before)
        self._undo_pending_before = None

def _un_do(self, event=None):
    try:
        w = self.focus_get()
    except Exception:
        w = None
    if isinstance(w, (tk.Entry, tk.Text)):   # 文本框内：让给控件自己的文本撤销
        return
    t = getattr(self, "_undo_timer", None)
    if t:
        try:
            self.after_cancel(t)
        except Exception:
            pass
        self._undo_timer = None
    pending = getattr(self, "_undo_pending_before", None)
    st = getattr(self, "_undo_stack", None) or []
    if pending is not None:                  # 丢弃当前未完成的连续编辑
        target = pending
        self._undo_pending_before = None
    elif st:
        target = st.pop()
    else:
        return "break"
    self._undo_in_progress = True
    try:
        self.template = Template.from_dict(target)
        self._undo_last = target
        self._refresh_element_list()
        self._select_element(self.selected_elem_id)
    finally:
        self._undo_in_progress = False
    return "break"

_un_orig_redraw = App._redraw_canvas
def _un_wrapped_redraw(self):
    _un_orig_redraw(self)
    try:
        _un_observe(self)
    except Exception:
        pass
App._redraw_canvas = _un_wrapped_redraw

_un_orig_build = App._build_layout
def _un_wrapped_build(self):
    _un_orig_build(self)
    if not getattr(self, "_undo_bound", False):
        try:
            self.bind_all("<Control-z>", self._un_do)
            self.bind_all("<Control-Z>", self._un_do)
            self._undo_bound = True
        except Exception:
            pass
App._build_layout = _un_wrapped_build
# === /UNDO_PATCH_V1 ===


# === PERSP_SNAP_PATCH_V1 ===
from PIL import ImageFilter as _pc_IF

def _pc_ensure_edges(self):
    """在显示尺寸上算边缘强度图并缓存；窗口尺寸不变则 O(1) 命中跳过。
    预模糊压碎石高频、FIND_EDGES 提边、再模糊让边变粗→吸附宽容。全 C 滤镜，快。"""
    cache = getattr(self, "_edges_cache", None)
    try:
        dw, dh, ox, oy, _s = self._get_disp_meta()
    except Exception:
        return
    if dw < 8 or dh < 8:
        return
    key = (dw, dh)
    if cache is not None and cache.get("key") == key:
        return
    try:
        small = self.pil_image.resize((dw, dh), Image.BILINEAR)
        g = small.convert("L")
        g = g.filter(_pc_IF.GaussianBlur(2))
        g = g.filter(_pc_IF.FIND_EDGES).convert("L")
        g = g.filter(_pc_IF.GaussianBlur(1))
        flat = list(g.getdata())
        emax = g.getextrema()[1]
        self._edges_cache = {"key": key, "flat": flat, "w": dw, "h": dh, "emax": int(emax)}
    except Exception:
        self._edges_cache = None

def _pc_snap(self, lx, ly):
    """在 (lx,ly) 的半径窗口内，返回距离最近且强度超阈值的边缘像素；找不到则原样返回。
    lx,ly 为相对显示图左上的坐标（与 edges 图同坐标系）。"""
    cache = getattr(self, "_edges_cache", None)
    if not cache:
        return lx, ly
    flat = cache["flat"]; w = cache["w"]; h = cache["h"]; emax = cache["emax"]
    thresh = max(20, int(emax * 0.30))
    R = int(getattr(self, "snap_radius", 22))
    lxi, lyi = int(lx), int(ly)
    x0 = max(0, lxi - R); x1 = min(w, lxi + R + 1)
    y0 = max(0, lyi - R); y1 = min(h, lyi + R + 1)
    best = None; bd = 1 << 30
    for yy in range(y0, y1):
        row = yy * w; dy = yy - lyi; dy2 = dy * dy
        for xx in range(x0, x1):
            if flat[row + xx] > thresh:
                dx = xx - lxi; d = dx * dx + dy2
                if d < bd:
                    bd = d; best = (xx, yy)
    return best if best is not None else (lx, ly)

# 包装 _on_drag：调用原逻辑前，把 event 坐标修正为吸附后的坐标（零抄写原拖拽逻辑）。
# tkinter.Event 属性可赋值，故原 _on_drag 读到的就是吸附后的位置。
_pc_orig_drag = PerspectiveCropDialog._on_drag
def _pc_new_drag(self, event):
    if (getattr(self, "snap_var", None) is not None and self.snap_var.get()
            and getattr(self, "active_handle", None) is not None):
        try:
            _pc_ensure_edges(self)
            dw, dh, ox, oy, _s = self._get_disp_meta()
            nlx, nly = _pc_snap(self, event.x - ox, event.y - oy)
            event.x = int(nlx + ox); event.y = int(nly + oy)
        except Exception:
            pass
    _pc_orig_drag(self, event)
PerspectiveCropDialog._on_drag = _pc_new_drag

# 包装 _draw_canvas：画完后顺带确保边缘缓存就绪（尺寸未变则跳过）。
_pc_orig_draw = PerspectiveCropDialog._draw_canvas
def _pc_new_draw(self, *args, **kwargs):
    _pc_orig_draw(self, *args, **kwargs)
    try:
        if getattr(self, "snap_var", None) is not None and self.snap_var.get():
            _pc_ensure_edges(self)
    except Exception:
        pass
PerspectiveCropDialog._draw_canvas = _pc_new_draw

# 包装 _build_ui：调原方法后，追加一行“吸附边缘”控制条（开关 + 半径滑块）。
_pc_orig_build = PerspectiveCropDialog._build_ui
def _pc_new_build(self):
    _pc_orig_build(self)
    try:
        self.snap_var = tk.BooleanVar(value=True)
        self.snap_radius = 22
        bar2 = ctk.CTkFrame(self, fg_color=T("panel"), corner_radius=10,
                            border_width=1, border_color=T("border"))
        bar2.grid(row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkCheckBox(bar2, text="吸附边缘（拖动角点/控制点时自动贴到最近的强边缘）",
                        variable=self.snap_var, font=("Microsoft YaHei", 12),
                        fg_color=T("accent"), hover_color=T("accent_h")).pack(side="left", padx=(12, 8), pady=7)
        ctk.CTkLabel(bar2, text="吸附半径", text_color=T("text_mid"),
                     font=("Microsoft YaHei", 11)).pack(side="left", padx=(4, 2))
        _rvar = tk.IntVar(value=22)
        def _on_r(v):
            try:
                self.snap_radius = int(float(v))
            except Exception:
                pass
        ctk.CTkSlider(bar2, from_=8, to=48, number_of_steps=40, variable=_rvar, command=_on_r,
                      width=130, progress_color=T("accent"), button_color=T("accent")).pack(side="left", padx=2)
        ctk.CTkLabel(bar2, text="  关闭可自由放置；半径越大越易吸到稍远的边。",
                     text_color=T("text_dim"), font=("Microsoft YaHei", 11)).pack(side="left", padx=6)
    except Exception:
        pass
PerspectiveCropDialog._build_ui = _pc_new_build
# === /PERSP_SNAP_PATCH_V1 ===


# === AUTOPERSP_PATCH_V1 ===
from PIL import ImageFilter as _ap_IF

# ---------- 零依赖自动检测：游程扫描找箱体四条主边 ----------
def _autodetect_corners(pil_image):
    """返回 corners_rel([[x,y]*4]: TL,TR,BR,BL) 或 None(失手回退)。
    小图上 GaussianBlur 压碎石 + FIND_EDGES 提边 + MaxFilter 膨胀连通，
    二值化后扫“贯穿行/列的长连续边缘游程”定位上下左右四条边。
    对正拍/俯拍岩心箱有效；严重歪斜失手时返回 None，由调用方回退。"""
    try:
        w0, h0 = pil_image.size
        LONG = 480
        sc = LONG / max(w0, h0)
        sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
        g = pil_image.resize((sw, sh), Image.BILINEAR).convert("L")
        g = g.filter(_ap_IF.GaussianBlur(2))
        e = g.filter(_ap_IF.FIND_EDGES).convert("L")
        e = e.filter(_ap_IF.MaxFilter(3))
        ext = e.getextrema()[1]
        thr = max(18, int(ext * 0.32))
        data = list(e.getdata())
        min_h = sw * 0.32
        min_v = sh * 0.32

        def row_run(y):
            best = 0; cur = 0
            for x in range(sw):
                if data[y * sw + x] >= thr:
                    cur += 1
                    if cur > best:
                        best = cur
                else:
                    cur = 0
            return best

        def col_run(x):
            best = 0; cur = 0
            for y in range(sh):
                if data[y * sw + x] >= thr:
                    cur += 1
                    if cur > best:
                        best = cur
                else:
                    cur = 0
            return best

        top = bot = left = right = None
        for y in range(0, sh // 2):
            if row_run(y) >= min_h:
                top = y; break
        for y in range(sh - 1, sh // 2, -1):
            if row_run(y) >= min_h:
                bot = y; break
        for x in range(0, sw // 2):
            if col_run(x) >= min_v:
                left = x; break
        for x in range(sw - 1, sw // 2, -1):
            if col_run(x) >= min_v:
                right = x; break
        if None in (top, bot, left, right) or right <= left or bot <= top:
            return None
        pad = 0.01
        lx = max(0.0, left / sw - pad); rx = min(1.0, right / sw + pad)
        ty = max(0.0, top / sh - pad); by = min(1.0, bot / sh + pad)
        return [[lx, ty], [rx, ty], [rx, by], [lx, by]]
    except Exception:
        return None

# ---------- 中分辨率 warp：复用原 _do_transform，临时换尺寸字段 ----------
def _do_transform_scaled(self, long_edge):
    """在 long_edge 长边上 warp（预览用，快）；原图不大时直接原图 warp。
    同步主线程调用，与后台原图 warp 不重叠（顺序执行），无 race。"""
    w0, h0 = self.pil_image.size
    sc = long_edge / max(w0, h0)
    if sc >= 1.0:
        return self._do_transform()
    sw, sh = max(2, round(w0 * sc)), max(2, round(h0 * sc))
    small = self.pil_image.resize((sw, sh), Image.BILINEAR)
    op, ow, oh = self.pil_image, self.orig_w, self.orig_h
    self.pil_image, self.orig_w, self.orig_h = small, sw, sh
    try:
        return self._do_transform()
    finally:
        self.pil_image, self.orig_w, self.orig_h = op, ow, oh

# ---------- 包装 _apply_temp：同步中清即时预览 + 后台全清无感替换 ----------
_ap_orig_apply_temp = PerspectiveCropDialog._apply_temp
def _ap_new_apply_temp(self):
    cb = self.on_apply_callback
    preview = None
    try:
        preview = _do_transform_scaled(self, 2200)   # 同步：中清，瞬时反馈
    except Exception:
        preview = None
    if preview is not None:
        try:
            cb(preview, False)                        # 两阶段：预览，非最终
        except TypeError:
            try: cb(preview)
            except Exception: pass
        except Exception:
            pass

    def done(warped):                                 # 后台：原图全清，无感替换
        try:
            cb(warped, True)
        except TypeError:
            try: cb(warped)
            except Exception: pass
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass
    self._run_transform_async(done)
PerspectiveCropDialog._apply_temp = _ap_new_apply_temp

# ---------- 包装 __init__：支持 initial_corners 预填 ----------
_ap_orig_init = PerspectiveCropDialog.__init__
def _ap_new_init(self, parent, pil_image, on_apply_callback, initial_corners=None):
    _ap_orig_init(self, parent, pil_image, on_apply_callback)
    if initial_corners:
        try:
            cs = [[max(0.0, min(1.0, float(c[0]))), max(0.0, min(1.0, float(c[1])))]
                  for c in initial_corners]
            if len(cs) == 4:
                self.corners_rel = cs
                self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
        except Exception:
            pass
PerspectiveCropDialog.__init__ = _ap_new_init

# ---------- 弹窗内“自动识别角点”按钮 ----------
def _ap_do_autodetect(self):
    cs = _autodetect_corners(self.pil_image)
    if cs is None:
        try:
            messagebox.showinfo("自动识别", "未检测到规整的箱体边框（可能箱子较歪或对比弱），请手动拖角点，可配合『吸附边缘』微调。")
        except Exception:
            pass
        return
    self.corners_rel = cs
    self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
    self._draw_canvas()

_ap_orig_build_ui = PerspectiveCropDialog._build_ui
def _ap_new_build_ui(self):
    _ap_orig_build_ui(self)
    try:
        bar3 = ctk.CTkFrame(self, fg_color=T("panel"), corner_radius=10,
                            border_width=1, border_color=T("border"))
        bar3.grid(row=3, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkButton(bar3, text="🤖 自动识别角点", width=140,
                      fg_color=T("accent_bg"), hover_color=T("accent_bg"),
                      text_color=T("accent_h"), font=("Microsoft YaHei", 12),
                      command=lambda: _ap_do_autodetect(self)).pack(side="left", padx=12, pady=7)
        ctk.CTkLabel(bar3, text="用边缘检测自动定位箱体四边并填入；失手时框不动，请手动拖角点 + 吸附微调。",
                     text_color=T("text_dim"), font=("Microsoft YaHei", 11)).pack(side="left", padx=6)
    except Exception:
        pass
PerspectiveCropDialog._build_ui = _ap_new_build_ui

# ---------- 主窗口：on_perspective_crop 支持双参数回调 + 预填 ----------
def _ap_on_perspective_crop(self, initial_corners=None):
    if self.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。")
        return
    entry = self.images[self.current_index]
    if entry.pil_image is None:
        try:
            entry.pil_image = Image.open(entry.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("打开图片失败", str(e))
            return

    def _on_crop_applied(warped_img, is_final=True):
        entry.pil_image = warped_img
        self._preview_cache = None
        self._redraw_canvas()
    PerspectiveCropDialog(self, entry.pil_image, _on_crop_applied, initial_corners=initial_corners)
App.on_perspective_crop = _ap_on_perspective_crop

# ---------- 主窗口：工具栏“🤖 自动透视”= 检测 + 打开弹窗预填 ----------
def _ap_auto_perspective(self):
    if self.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。")
        return
    entry = self.images[self.current_index]
    if entry.pil_image is None:
        try:
            entry.pil_image = Image.open(entry.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("打开图片失败", str(e))
            return
    cs = _autodetect_corners(entry.pil_image)
    if cs is None:
        messagebox.showinfo("自动识别", "未检测到规整边框，已打开透视窗口，请手动拖角点（可配合『吸附边缘』）。")
        self.on_perspective_crop(initial_corners=None)
    else:
        self.on_perspective_crop(initial_corners=cs)
App._auto_perspective = _ap_auto_perspective

# 包装 _build_layout：工具栏注入 🤖 自动透视（链式，兼容裁剪/撤销装饰器）
_ap_orig_build_layout = App._build_layout
def _ap_wrapped_build_layout(self):
    _ap_orig_build_layout(self)
    tb = getattr(self, "_toolbar", None)
    if tb is not None and not getattr(self, "_ap_btn_added", False):
        try:
            ctk.CTkButton(tb, text="🤖 自动透视", width=92, height=30, corner_radius=7,
                          font=self.ui_font, fg_color=T("accent_bg"), hover_color=T("accent_bg"),
                          text_color=T("accent_h"), command=self._auto_perspective).pack(side="left", padx=1, pady=6)
            self._ap_btn_added = True
        except Exception:
            pass
App._build_layout = _ap_wrapped_build_layout
# === /AUTOPERSP_PATCH_V1 ===


# === AUTODETECT_V3 ===
# 覆盖式重定义：本块在文件末尾，def 同名覆盖 V2/AUTOPERSP 的旧实现；
# _ap_do_autodetect / _ap_auto_perspective 用全局名调用，运行时解析到本新版。
from PIL import ImageFilter as _ad3_IF
import math as _ad3_math

def _autodetect_corners(pil_image):
    """边缘投影 + 相邻峰对(=一格) + 评分。返回 corners_rel(TL,TR,BR,BL) 或 None。
    竖排多格：行峰排序后相邻对=上/中/下格，靠‘垂直居中’选中格，结构上杜绝跨格大框；
    单格铺满：行/列各一对相邻峰=整格，唯一候选直接胜出。
    阈值用内部92%区域峰值，贴边强边不污染；NMS 合并金属框双边缘。"""
    try:
        w0, h0 = pil_image.size
        LONG = 420
        sc = LONG / max(w0, h0)
        sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
        g = pil_image.resize((sw, sh), Image.BILINEAR).convert("L")
        g = g.filter(_ad3_IF.GaussianBlur(max(2, round(min(sw, sh) * 0.02))))   # 糊掉碎石
        e = g.filter(_ad3_IF.FIND_EDGES).convert("L")
        e = e.filter(_ad3_IF.GaussianBlur(max(1, round(min(sw, sh) * 0.006))))
        data = list(e.getdata())
        rowp = [0.0] * sh
        for y in range(sh):
            s = 0; row = y * sw
            for x in range(sw):
                s += data[row + x]
            rowp[y] = s / sw
        colp = [0.0] * sw
        for x in range(sw):
            s = 0
            for y in range(sh):
                s += data[y * sw + x]
            colp[x] = s / sh

        def smooth(a, k=5):
            n = len(a); out = [0.0] * n; h = k // 2
            for i in range(n):
                lo = max(0, i - h); hi = min(n, i + h + 1)
                out[i] = sum(a[lo:hi]) / (hi - lo)
            return out
        rowp = smooth(rowp, 5); colp = smooth(colp, 5)

        def peaks(a, thr, ex_lo, ex_hi, min_d):
            """局部极大>thr 的峰，NMS(按强度贪心, 抑制距离<min_d)，按位置排序返回(s,i,f)。"""
            n = len(a); cand = []
            for i in range(1, n - 1):
                if a[i] >= a[i - 1] and a[i] >= a[i + 1] and a[i] >= thr:
                    f = i / (n - 1)
                    if ex_lo is not None and (f < ex_lo or f > ex_hi):
                        continue
                    cand.append((a[i], i, f))
            cand.sort(reverse=True)
            kept = []
            for s, i, f in cand:
                if all(abs(i - j) > min_d for _, j, _ in kept):
                    kept.append((s, i, f))
            kept.sort(key=lambda t: t[2])
            return kept

        def find_axis(a, ex_lo, ex_hi):
            """内部鲁棒阈值找峰；不够则降阈值再扫一次。返回归一化强度峰列表[(s,f)]。"""
            lo = max(1, int(len(a) * 0.04)); hi = max(lo + 1, int(len(a) * 0.96))
            inner = a[lo:hi] or a
            imx = max(inner) or 1.0
            pk = peaks(a, imx * 0.25, ex_lo, ex_hi, max(3, int(len(a) * 0.05)))
            if len(pk) < 2:
                pk = peaks(a, imx * 0.15, ex_lo, ex_hi, max(3, int(len(a) * 0.05)))
            return [(min(1.0, s / imx), f) for s, i, f in pk], imx

        # 行：排除贴边3%峰(防图顶/底伪边引入跨格大框)
        H, _ = find_axis(rowp, 0.03, 0.97)
        if len(H) < 2:
            return None                      # 行无结构→回退手动
        # 列：允许贴边(单格铺满左右框常贴边)；不足则兜底图边
        V, _ = find_axis(colp, None, None)
        if len(V) < 2:
            V = [(0.5, 0.0), (0.5, 1.0)]

        # 相邻峰对 = 一格 的上下/左右边候选（结构先验，跨格组合不生成）
        H_pairs = [(H[k], H[k + 1]) for k in range(len(H) - 1)]
        V_pairs = [(V[k], V[k + 1]) for k in range(len(V) - 1)]

        best = None; bscore = -1.0
        for ha, hb in H_pairs:
            t, b = ha[1], hb[1]; hgt = b - t
            if hgt < 0.12 or hgt > 0.95:     # 仅挡金属框厚度级极薄假格
                continue
            for va, vb in V_pairs:
                l, r = va[1], vb[1]; wdt = r - l
                if wdt < 0.40 or wdt > 1.0:
                    continue
                se = (ha[0] + hb[0] + va[0] + vb[0]) * 0.25
                cy = (t + b) * 0.5; cx = (l + r) * 0.5
                s_center = max(0.0, 1.0 - abs(cy - 0.5) * 1.2 - abs(cx - 0.5) * 0.4)
                ar = wdt / hgt
                s_ar = _ad3_math.exp(-((ar - 2.0) / 1.3) ** 2)     # 单格宽:高≈2 软偏好
                s_area = min(1.0, (wdt * hgt) / 0.25)
                score = se * (0.4 + 0.6 * s_center) * (0.5 + 0.5 * s_ar) * s_area
                if score > bscore:
                    bscore = score; best = (l, t, r, b)
        if best is None or bscore < 0.01:
            return None
        l, t, r, b = best
        pad = 0.005
        return [[max(0.0, l - pad), max(0.0, t - pad)], [min(1.0, r + pad), max(0.0, t - pad)],
                [min(1.0, r + pad), min(1.0, b + pad)], [max(0.0, l - pad), min(1.0, b + pad)]]
    except Exception:
        return None
# === /AUTODETECT_V3 ===


# === AUTOPERSP_DIRECT_V1 ===
# 软依赖：装 cv2 用轮廓法(全自动/方向自适应/扛斜拍)，没装退回 Pillow 投影(v3)。
try:
    import cv2 as _ad_cv
    import numpy as _ad_np
    HAS_CV = True
except Exception:
    _ad_cv = None; _ad_np = None; HAS_CV = False

_autodetect_v3_impl = _autodetect_corners   # 捕获当前全局名(=V3 投影版)，作回退

def _order_pts(pts):
    pts = _ad_np.array(pts, dtype=float)
    s = pts.sum(axis=1); d = _ad_np.diff(pts, axis=1).ravel()   # d = y - x
    tl = pts[_ad_np.argmin(s)]; br = pts[_ad_np.argmax(s)]
    tr = pts[_ad_np.argmin(d)]; bl = pts[_ad_np.argmax(d)]
    return _ad_np.array([tl, tr, br, bl], dtype=float)          # TL,TR,BR,BL

def _autodetect_cv(pil_image):
    """轮廓法：斜拍/正拍/横竖排通吃。返回 corners_rel 或 None。"""
    try:
        w0, h0 = pil_image.size
        LONG = 640
        sc = LONG / max(w0, h0); sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
        arr = _ad_np.array(pil_image.resize((sw, sh), Image.BILINEAR).convert("RGB"))
        gray = _ad_cv.cvtColor(arr, _ad_cv.COLOR_RGB2GRAY)
        gray = _ad_cv.bilateralFilter(gray, 9, 75, 75)          # 保边去碎石
        edges = _ad_cv.Canny(gray, 30, 120)
        k = _ad_cv.getStructuringElement(_ad_cv.MORPH_RECT, (5, 5))
        edges = _ad_cv.morphologyEx(edges, _ad_cv.MORPH_CLOSE, k, iterations=2)
        cnts, _ = _ad_cv.findContours(edges, _ad_cv.RETR_LIST, _ad_cv.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=_ad_cv.contourArea, reverse=True)
        area_img = float(sw * sh)
        cands = []
        for c in cnts[:40]:
            ca = _ad_cv.contourArea(c); fr = ca / area_img
            if fr < 0.06 or fr > 0.92:
                continue
            rect = _ad_cv.minAreaRect(c); box = _ad_cv.boxPoints(rect)
            rect_area = float(rect[1][0] * rect[1][1]) or 1.0
            rectw = ca / rect_area                               # 矩形度，越接近1越规整
            cands.append((fr, box.astype(float), rectw))
            peri = _ad_cv.arcLength(c, True)
            approx = _ad_cv.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4 and _ad_cv.isContourConvex(approx):
                cands.append((fr, approx.reshape(4, 2).astype(float), 1.0))
        if not cands:
            return None
        best = None; bscore = -1.0
        for fr, pts, rectw in cands:
            pts = _order_pts(pts)
            cx = pts[:, 0].mean() / sw; cy = pts[:, 1].mean() / sh
            s_center = max(0.0, 1.0 - abs(cy - 0.5) * 1.2 - abs(cx - 0.5) * 0.4)
            wt = _ad_np.linalg.norm(pts[1] - pts[0]); wb = _ad_np.linalg.norm(pts[2] - pts[3])
            hl = _ad_np.linalg.norm(pts[3] - pts[0]); hr = _ad_np.linalg.norm(pts[2] - pts[1])
            W = (wt + wb) * 0.5 / sw; H = (hl + hr) * 0.5 / sh
            ar = (W / H) if H > 0 else 0.0; ar2 = max(ar, 1.0 / ar) if ar > 0 else 0.0
            s_ar = _ad_math.exp(-((ar2 - 2.0) / 1.0) ** 2)        # 方向无关：横格竖格长:短≈2 都满分
            s_area = min(1.0, fr / 0.20)
            s_size = _ad_math.exp(-((fr - 0.35) / 0.25) ** 2) * 0.5 + 0.5   # 单格面积偏好(软)
            rw = 1.0 if rectw < 1.2 else max(0.2, 1.0 - (rectw - 1.2))      # 不规则轮廓降权
            score = (0.5 + 0.5 * s_center) * (0.5 + 0.5 * s_ar) * s_area * s_size * rw
            if score > bscore:
                bscore = score; best = pts
        if best is None or bscore < 0.01:
            return None
        rel = (best / _ad_np.array([sw, sh], dtype=float)).tolist()
        return [[rel[0][0], rel[0][1]], [rel[1][0], rel[1][1]],
                [rel[2][0], rel[2][1]], [rel[3][0], rel[3][1]]]
    except Exception:
        return None

def _autodetect_corners(pil_image):
    """dispatcher：装 cv2 优先轮廓法，失手再试 v3 投影；没 cv2 直接 v3。"""
    if HAS_CV:
        r = _autodetect_cv(pil_image)
        if r is not None:
            return r
    return _autodetect_v3_impl(pil_image)

# ---------- 纯函数 warp（供一键暂存，不依赖弹窗 UI） ----------
def _proj_t(rel_pt, c0, c1):
    cx, cy = c1[0] - c0[0], c1[1] - c0[1]; L = cx * cx + cy * cy
    if L < 1e-12:
        return 0.0
    t = ((rel_pt[0] - c0[0]) * cx + (rel_pt[1] - c0[1]) * cy) / L
    return max(0.0, min(1.0, t))

def _warp_tri(src_img, dst_img, tri_src, tri_dst):
    xs = [p[0] for p in tri_dst]; ys = [p[1] for p in tri_dst]
    x_min = max(0, int(_ad_math.floor(min(xs)))); y_min = max(0, int(_ad_math.floor(min(ys))))
    x_max = min(dst_img.width, int(_ad_math.ceil(max(xs))) + 1)
    y_max = min(dst_img.height, int(_ad_math.ceil(max(ys))) + 1)
    bw, bh = x_max - x_min, y_max - y_min
    if bw <= 0 or bh <= 0:
        return
    m = [[tri_dst[0][0], tri_dst[0][1], 1], [tri_dst[1][0], tri_dst[1][1], 1], [tri_dst[2][0], tri_dst[2][1], 1]]
    abc = _solve3x3(m, [p[0] for p in tri_src]); defc = _solve3x3(m, [p[1] for p in tri_src])
    if abc is None or defc is None:
        return
    a, b, c = abc; d, e, f = defc
    coeffs = (a, b, c + a * x_min + b * y_min, d, e, f + d * x_min + e * y_min)
    patch = src_img.transform((bw, bh), Image.AFFINE, coeffs, resample=Image.BICUBIC)
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).polygon([(x - x_min, y - y_min) for x, y in tri_dst], fill=255, outline=255)
    dst_img.paste(patch, (x_min, y_min), mask)

def _warp_corners(pil_image, corners_rel, edge_points_rel=None):
    edge_points_rel = edge_points_rel or {0: [], 1: [], 2: [], 3: []}
    ow, oh = pil_image.size
    cpx = [(rx * ow, ry * oh) for rx, ry in corners_rel]
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = cpx
    mw = max(2, round(max(_ad_math.hypot(x1 - x0, y1 - y0), _ad_math.hypot(x2 - x3, y2 - y3))))
    mh = max(2, round(max(_ad_math.hypot(x3 - x0, y3 - y0), _ad_math.hypot(x2 - x1, y2 - y1))))
    dst = [(0, 0), (mw, 0), (mw, mh), (0, mh)]
    psrc, pdst = [], []
    for i in range(4):
        psrc.append(cpx[i]); pdst.append(dst[i])
        c0, c1 = corners_rel[i], corners_rel[(i + 1) % 4]; d0, d1 = dst[i], dst[(i + 1) % 4]
        pts = edge_points_rel.get(i, [])
        order = sorted(range(len(pts)), key=lambda k: _proj_t(pts[k], c0, c1))
        for kk in order:
            t = _proj_t(pts[kk], c0, c1)
            psrc.append((pts[kk][0] * ow, pts[kk][1] * oh))
            pdst.append((d0[0] + t * (d1[0] - d0[0]), d0[1] + t * (d1[1] - d0[1])))
    n = len(psrc)
    cs = (sum(p[0] for p in psrc) / n, sum(p[1] for p in psrc) / n)
    cd = (sum(p[0] for p in pdst) / n, sum(p[1] for p in pdst) / n)
    src = pil_image.convert("RGBA"); out = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    for k in range(n):
        k2 = (k + 1) % n
        _warp_tri(src, out, (cs, psrc[k], psrc[k2]), (cd, pdst[k], pdst[k2]))
    if pil_image.mode != "RGBA":
        bg = Image.new("RGB", out.size, (0, 0, 0)); bg.paste(out, (0, 0), out); return bg
    return out

def _warp_scaled(pil_image, corners_rel, long_edge):
    w0, h0 = pil_image.size; sc = long_edge / max(w0, h0)
    if sc >= 1.0:
        return _warp_corners(pil_image, corners_rel)
    small = pil_image.resize((max(2, round(w0 * sc)), max(2, round(h0 * sc))), Image.BILINEAR)
    return _warp_corners(small, corners_rel)

# ---------- 一键直接暂存：检测成功不弹窗，两阶段；失败才开弹窗 ----------
def _ap_auto_perspective(self):
    if self.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。"); return
    entry = self.images[self.current_index]
    if entry.pil_image is None:
        try:
            entry.pil_image = Image.open(entry.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("打开图片失败", str(e)); return
    pil = entry.pil_image
    corners = _autodetect_corners(pil)
    if corners is None:
        messagebox.showinfo("自动识别", "未检测到规整边框（可能箱子较歪/对比弱），已打开透视窗口，请手动拖角点（可配合『吸附边缘』）。")
        self.on_perspective_crop(initial_corners=None)
        return
    preview = None
    try:
        preview = _warp_scaled(pil, corners, 2200)
    except Exception:
        preview = None
    pid = id(preview) if preview is not None else None
    if preview is not None:
        entry.pil_image = preview
        self._preview_cache = None
        self._redraw_canvas()
        getattr(self, "_show_toast", lambda *a, **k: None)("已自动透视矫正（高清版后台生成中…）")

    def worker():
        full = None
        try:
            full = _warp_corners(pil, corners)
        except Exception:
            full = None
        if full is not None:
            self.after(0, lambda: _commit_full(self, entry, full, pid))
    threading.Thread(target=worker, daemon=True).start()

def _commit_full(self, entry, full, pid):
    # 仅当 entry 当前图仍是中清 preview(用户没在期间裁剪/旋转/换图)才替换，避免覆盖人工操作
    if pid is not None and id(entry.pil_image) != pid:
        return
    entry.pil_image = full
    self._preview_cache = None
    self._redraw_canvas()

App._auto_perspective = _ap_auto_perspective
# === /AUTOPERSP_DIRECT_V1 ===


# === AUTODETECT_V5 ===
# 末尾重定义：覆盖 DIRECT 块的 _autodetect_cv / _autodetect_corners / _ap_do_autodetect /
# _ap_auto_perspective。dispatcher 与弹窗 lambda 用全局名调用，运行时解析到本 V5 版。
def _autodetect_cv(pil_image):
    """轮廓法(扛斜拍/横竖排)。自适应 Canny + 形态学 + 多档四边形 + minAreaRect 斜框；
    评分只用 居中×面积×填充率，无长宽比先验(横排竖格/竖排横格比例相反, 先验必毒一边)。"""
    if not HAS_CV:
        return None
    try:
        w0, h0 = pil_image.size
        LONG = 640
        sc = LONG / max(w0, h0); sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
        arr = _ad_np.array(pil_image.resize((sw, sh), Image.BILINEAR).convert("RGB"))
        gray = _ad_cv.cvtColor(arr, _ad_cv.COLOR_RGB2GRAY)
        gray = _ad_cv.bilateralFilter(gray, 11, 100, 100)        # 保边压碎石
        med = float(_ad_np.median(gray))                          # 自适应 Canny 阈值
        lo = int(max(0, 0.5 * med)); hi = int(min(255, 1.3 * med))
        edges = _ad_cv.Canny(gray, lo, hi)
        kc = _ad_cv.getStructuringElement(_ad_cv.MORPH_RECT, (7, 7))
        edges = _ad_cv.morphologyEx(edges, _ad_cv.MORPH_CLOSE, kc, iterations=2)  # 连框线
        ko = _ad_cv.getStructuringElement(_ad_cv.MORPH_RECT, (3, 3))
        edges = _ad_cv.morphologyEx(edges, _ad_cv.MORPH_OPEN, ko, iterations=1)   # 削碎石毛刺
        cnts, _ = _ad_cv.findContours(edges, _ad_cv.RETR_LIST, _ad_cv.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=_ad_cv.contourArea, reverse=True)
        area_img = float(sw * sh); cands = []
        for c in cnts[:50]:
            ca = _ad_cv.contourArea(c); fr = ca / area_img
            if fr < 0.05 or fr > 0.93:
                continue
            rect = _ad_cv.minAreaRect(c); box = _ad_cv.boxPoints(rect)
            ra = float(rect[1][0] * rect[1][1]) or 1.0; fill = ca / ra   # 填充率: 矩形≈1, 凹/散块<1
            peri = _ad_cv.arcLength(c, True); quad = None
            for eps in (0.02, 0.03, 0.015, 0.04, 0.01):                  # 多档逼四边形
                ap = _ad_cv.approxPolyDP(c, eps * peri, True)
                if len(ap) == 4 and _ad_cv.isContourConvex(ap):
                    quad = ap.reshape(4, 2).astype(float); break
            if quad is not None:
                cands.append((fr, quad, fill))
            cands.append((fr, box.astype(float), fill))                  # 旋转外接矩形=斜框兜底
        if not cands:
            return None
        best = None; bs = -1.0
        for fr, pts, fill in cands:
            pts = _order_pts(pts)
            cx = pts[:, 0].mean() / sw; cy = pts[:, 1].mean() / sh
            s_center = max(0.0, 1.0 - abs(cy - 0.5) * 1.3 - abs(cx - 0.5) * 0.5)
            s_area = min(1.0, fr / 0.18)
            s_rect = max(0.0, min(1.0, fill))
            score = (0.4 + 0.6 * s_center) * s_area * (0.3 + 0.7 * s_rect)   # 无 ar 偏好
            if fr > 0.85:
                score *= 0.3                                              # 仅压整图大框
            if score > bs:
                bs = score; best = pts
        if best is None or bs < 0.01:
            return None
        rel = (best / _ad_np.array([sw, sh], dtype=float)).tolist()
        return [[rel[0][0], rel[0][1]], [rel[1][0], rel[1][1]],
                [rel[2][0], rel[2][1]], [rel[3][0], rel[3][1]]]
    except Exception:
        return None

def _autodetect_corners(pil_image):
    r = _autodetect_cv(pil_image)        # 装 cv 优先(扛斜拍)
    if r is not None:
        return r
    return _autodetect_v3_impl(pil_image)  # 回退 v4 投影(正拍横竖排)

def _center_fallback(pil_image):
    """cv+投影都无把握时的起点框: 中心 62%, 比整图默认框更接近目标, 配合吸附拖两下即成。"""
    return [[0.19, 0.19], [0.81, 0.19], [0.81, 0.81], [0.19, 0.81]]

def _ap_do_autodetect(self):
    """弹窗内『自动识别角点』: 永不死胡同, 无把握时填中心框而非弹废话框。"""
    cs = _autodetect_corners(self.pil_image)
    if cs is None:
        cs = _center_fallback(self.pil_image)
    self.corners_rel = cs
    self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
    self._draw_canvas()

def _ap_auto_perspective(self):
    """工具栏『自动透视』: 成功→两阶段直接暂存不弹窗; 无把握→开弹窗预填中心框(不直接暂存粗估计)。"""
    if self.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。"); return
    entry = self.images[self.current_index]
    if entry.pil_image is None:
        try:
            entry.pil_image = Image.open(entry.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("打开图片失败", str(e)); return
    pil = entry.pil_image
    corners = _autodetect_corners(pil)
    if corners is None:
        self.on_perspective_crop(initial_corners=_center_fallback(pil))   # 进弹窗核对+吸附
        return
    preview = None
    try:
        preview = _warp_scaled(pil, corners, 2200)
    except Exception:
        preview = None
    pid = id(preview) if preview is not None else None
    if preview is not None:
        entry.pil_image = preview
        self._preview_cache = None
        self._redraw_canvas()
        getattr(self, "_show_toast", lambda *a, **k: None)("已自动透视矫正（高清版后台生成中…）")

    def worker():
        full = None
        try:
            full = _warp_corners(pil, corners)
        except Exception:
            full = None
        if full is not None:
            self.after(0, lambda: _commit_full(self, entry, full, pid))
    threading.Thread(target=worker, daemon=True).start()

App._auto_perspective = _ap_auto_perspective
# === /AUTODETECT_V5 ===


# === AUTODETECT_V6 ===
from PIL import ImageFilter as _v6_IF

def _v6_build_edges(pil_image, long_edge=800):
    """等比缩到 long_edge 建边缘图；rel 坐标与显示尺寸无关，故工具栏/弹窗可共用。"""
    w0, h0 = pil_image.size
    sc = long_edge / max(w0, h0)
    sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
    g = pil_image.resize((sw, sh), Image.BILINEAR).convert("L").filter(_v6_IF.GaussianBlur(2))
    e = g.filter(_v6_IF.FIND_EDGES).convert("L").filter(_v6_IF.GaussianBlur(1))
    return list(e.getdata()), sw, sh, int(e.getextrema()[1])

def _v6_scan_box(pil_image, cx_rel, cy_rel):
    """从种子向四边十字扫描最近强边，撑成 rel 四角。返回 (box, real_count) 或 (None,0)。
    band 容忍斜档条；real=真正扫到强边的方向数(<2 视为边缘图失效)。"""
    try:
        flat, w, h, emax = _v6_build_edges(pil_image)
    except Exception:
        return None, 0
    thr = max(20, int(emax * 0.30))
    sx = int(cx_rel * w); sy = int(cy_rel * h)
    bx = max(3, int(w * 0.08)); by = max(3, int(h * 0.08))
    def row_hit(y):
        lo = max(0, sx - bx); hi = min(w, sx + bx + 1); r = y * w
        for x in range(lo, hi):
            if flat[r + x] > thr:
                return True
        return False
    def col_hit(x):
        lo = max(0, sy - by); hi = min(h, sy + by + 1)
        for y in range(lo, hi):
            if flat[y * w + x] > thr:
                return True
        return False
    top = None
    for y in range(sy - 1, -1, -1):
        if row_hit(y):
            top = y; break
    bot = None
    for y in range(sy + 1, h):
        if row_hit(y):
            bot = y; break
    left = None
    for x in range(sx - 1, -1, -1):
        if col_hit(x):
            left = x; break
    right = None
    for x in range(sx + 1, w):
        if col_hit(x):
            right = x; break
    real = (top is not None) + (bot is not None) + (left is not None) + (right is not None)
    if real < 2:
        return None, 0
    top = top if top is not None else 0
    bot = bot if bot is not None else h - 1
    left = left if left is not None else 0
    right = right if right is not None else w - 1
    if right <= left or bot <= top:
        return None, 0
    l, t, r, b = left / w, top / h, right / w, bot / h
    return [[l, t], [r, t], [r, b], [l, b]], real

def _ap_do_autodetect(self):
    """弹窗内『自动识别角点』：以当前框中心为种子撑框=精修当前框。
    默认整图框的中心≈画面中心，撑出来通常是中间格 → 对‘没动过的框’也显著有效。"""
    try:
        cx = (self.corners_rel[0][0] + self.corners_rel[2][0]) * 0.5
        cy = (self.corners_rel[0][1] + self.corners_rel[2][1]) * 0.5
    except Exception:
        cx = cy = 0.5
    box, real = _v6_scan_box(self.pil_image, cx, cy)
    if box is None:
        return                              # 边缘图无强边(极罕见)：不动当前框，避免重置用户已拖好的框
    self.corners_rel = box
    self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
    self._draw_canvas()

def _ap_auto_perspective_v6(self):
    """工具栏『自动透视』：画面中心种子撑框 → 开弹窗预填确认(不直存, 防批量存错)。
    撑框一定改变框(整图/中心 → 贴边小框)，故不再‘没效果’；斜拍为轴对齐近似，弹窗内用吸附+四角精修。"""
    if self.current_index is None:
        messagebox.showinfo("提示", "请先在左侧选择一张图片。"); return
    entry = self.images[self.current_index]
    if entry.pil_image is None:
        try:
            entry.pil_image = Image.open(entry.path).convert("RGB")
        except Exception as e:
            messagebox.showerror("打开图片失败", str(e)); return
    box, real = _v6_scan_box(entry.pil_image, 0.5, 0.5)
    if box is None:
        box = [[0.19, 0.19], [0.81, 0.19], [0.81, 0.81], [0.19, 0.81]]   # 边缘失效兜底
    try:
        self.on_perspective_crop(initial_corners=box)
    except TypeError:
        self.on_perspective_crop()

App._auto_perspective = _ap_auto_perspective_v6
# === /AUTODETECT_V6 ===


# === FINALIZE_AUTODETECT_V1 ===
# 定稿：覆盖 V6 的 _v6_scan_box 与 _ap_do_autodetect，堵“假整图框”+ 统一诚实占位。
# 不新增检测算法；_v6_build_edges 仍用 V6 的实现（全局名运行时解析）。
def _v6_scan_box(pil_image, cx_rel, cy_rel):
    """种子十字扫边 + 面积合理性校验。返回 (box, real) 或 (None,0)。
    面积>0.80(假整图) 或 <0.05(假小框) 一律 None，交外层给中心占位。"""
    try:
        flat, w, h, emax = _v6_build_edges(pil_image)
    except Exception:
        return None, 0
    thr = max(20, int(emax * 0.30))
    sx = int(cx_rel * w); sy = int(cy_rel * h)
    bx = max(3, int(w * 0.08)); by = max(3, int(h * 0.08))
    def row_hit(y):
        lo = max(0, sx - bx); hi = min(w, sx + bx + 1); r = y * w
        for x in range(lo, hi):
            if flat[r + x] > thr:
                return True
        return False
    def col_hit(x):
        lo = max(0, sy - by); hi = min(h, sy + by + 1)
        for y in range(lo, hi):
            if flat[y * w + x] > thr:
                return True
        return False
    top = None
    for y in range(sy - 1, -1, -1):
        if row_hit(y):
            top = y; break
    bot = None
    for y in range(sy + 1, h):
        if row_hit(y):
            bot = y; break
    left = None
    for x in range(sx - 1, -1, -1):
        if col_hit(x):
            left = x; break
    right = None
    for x in range(sx + 1, w):
        if col_hit(x):
            right = x; break
    real = (top is not None) + (bot is not None) + (left is not None) + (right is not None)
    if real < 2:
        return None, 0
    top = top if top is not None else 0
    bot = bot if bot is not None else h - 1
    left = left if left is not None else 0
    right = right if right is not None else w - 1
    if right <= left or bot <= top:
        return None, 0
    l, t, r, b = left / w, top / h, right / w, bot / h
    # 止损：拦截假整图框/假小框——这是“看起来识别了其实没对上”的根源
    area = (r - l) * (b - t)
    if area > 0.80 or area < 0.05:
        return None, 0
    return [[l, t], [r, t], [r, b], [l, b]], real

def _ap_do_autodetect(self):
    """弹窗内『自动识别角点』：种子=当前框中心撑框；没把握时给诚实中心占位(不再不动)。"""
    try:
        cx = (self.corners_rel[0][0] + self.corners_rel[2][0]) * 0.5
        cy = (self.corners_rel[0][1] + self.corners_rel[2][1]) * 0.5
    except Exception:
        cx = cy = 0.5
    box, real = _v6_scan_box(self.pil_image, cx, cy)
    if box is None:
        box = [[0.19, 0.19], [0.81, 0.19], [0.81, 0.81], [0.19, 0.81]]   # 诚实中心占位
    self.corners_rel = box
    self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
    self._draw_canvas()
# === /FINALIZE_AUTODETECT_V1 ===


# === REFINEBATCH_V1 ===
# ---- 路1：四边吸附精修 ----
def _pc_refine_build_edges(pil, long_edge=800):
    """固定长边建边缘图(与弹窗显示尺寸解耦, 纯函数)。rel<->像素用此图 w,h 换算。"""
    w0, h0 = pil.size; sc = long_edge / max(w0, h0)
    sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
    g = pil.resize((sw, sh), Image.BILINEAR).convert("L").filter(_rb_IF.GaussianBlur(2))
    e = g.filter(_rb_IF.FIND_EDGES).convert("L").filter(_rb_IF.GaussianBlur(1))
    return list(e.getdata()), sw, sh, int(e.getextrema()[1])

def _pc_refine_edges(self):
    """把当前框四边各自贴到邻域内最近强边。搜不到更强边则该边保持(幂等, 不抖)。
    轴对齐精修：斜拍给近似外接起点, 四角精修交给吸附+手拖(弹窗内可见, 不静默存错)。"""
    try:
        flat, w, h, emax = _pc_refine_build_edges(self.pil_image, 800)
    except Exception:
        return
    thr = max(20, int(emax * 0.30))
    cs = self.corners_rel
    l = min(cs[0][0], cs[3][0]); r = max(cs[1][0], cs[2][0])
    t = min(cs[0][1], cs[1][1]); b = max(cs[2][1], cs[3][1])
    lx, rx = int(l * w), int(r * w)
    R = max(4, int(0.12 * h))
    def row_str(yy):
        if yy < 0 or yy >= h:
            return 0
        row = yy * w; lo = max(0, lx); hi = min(w, rx + 1); c = 0
        for x in range(lo, hi):
            if flat[row + x] > thr:
                c += 1
        return c
    ty2 = int(t * h); by2 = int(b * h)
    def col_str(xx):
        if xx < 0 or xx >= w:
            return 0
        lo = max(0, ty2); hi = min(h, by2 + 1); c = 0
        for y in range(lo, hi):
            if flat[y * w + xx] > thr:
                c += 1
        return c
    min_w = max(3, int((rx - lx) * 0.12)); min_h = max(3, int((by2 - ty2) * 0.12))
    # 上边
    ty = int(t * h); best = ty; bs = row_str(ty)
    for yy in range(max(0, ty - R), min(h, ty + R + 1)):
        s = row_str(yy)
        if s > bs:
            bs = s; best = yy
    if bs >= min_w and bs > row_str(ty) * 1.05:
        t = best / h
    # 下边
    by = int(b * h); best = by; bs = row_str(by)
    for yy in range(max(0, by - R), min(h, by + R + 1)):
        s = row_str(yy)
        if s > bs:
            bs = s; best = yy
    if bs >= min_w and bs > row_str(by) * 1.05:
        b = best / h
    ty2 = int(t * h); by2 = int(b * h); min_h = max(3, int((by2 - ty2) * 0.12))
    # 左边
    lxx = int(l * w); best = lxx; bs = col_str(lxx)
    for xx in range(max(0, lxx - R), min(w, lxx + R + 1)):
        s = col_str(xx)
        if s > bs:
            bs = s; best = xx
    if bs >= min_h and bs > col_str(lxx) * 1.05:
        l = best / w
    # 右边
    rxx = int(r * w); best = rxx; bs = col_str(rxx)
    for xx in range(max(0, rxx - R), min(w, rxx + R + 1)):
        s = col_str(xx)
        if s > bs:
            bs = s; best = xx
    if bs >= min_h and bs > col_str(rxx) * 1.05:
        r = best / w
    l = max(0.0, min(1.0, l)); r = max(0.0, min(1.0, r))
    t = max(0.0, min(1.0, t)); b = max(0.0, min(1.0, b))
    if r - l < 0.05 or b - t < 0.05:
        return
    self.corners_rel = [[l, t], [r, t], [r, b], [l, b]]
    self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}
    self._draw_canvas()

_rb_orig_pc_build = PerspectiveCropDialog._build_ui
def _rb_pc_build(self):
    _rb_orig_pc_build(self)
    try:
        bar = ctk.CTkFrame(self, fg_color=T("panel"), corner_radius=10,
                           border_width=1, border_color=T("border"))
        bar.grid(row=4, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkButton(bar, text="⚡ 四边吸附精修", width=132, fg_color=T("accent_bg"),
                      hover_color=T("accent_bg"), text_color=T("accent_h"),
                      font=("Microsoft YaHei", 12),
                      command=lambda: _pc_refine_edges(self)).pack(side="left", padx=12, pady=7)
        ctk.CTkLabel(bar, text="把当前框四条边各自贴到最近的强边：正拍/微斜一键卡准；"
                               "斜拍/变形箱请配合『吸附边缘』拖四角收尾。",
                     text_color=T("text_dim"), font=("Microsoft YaHei", 11)).pack(side="left", padx=6)
    except Exception:
        pass
PerspectiveCropDialog._build_ui = _rb_pc_build

# ---- 路2：已编辑判定 + 导出知情 + 解耦说明 ----
def _bend_build_edges(pil, long_edge=800):
    w0, h0 = pil.size; sc = long_edge / max(w0, h0)
    sw, sh = max(8, round(w0 * sc)), max(8, round(h0 * sc))
    g = pil.resize((sw, sh), Image.BILINEAR).convert("L").filter(_bs_IF.GaussianBlur(2))
    e = g.filter(_bs_IF.FIND_EDGES).convert("L").filter(_bs_IF.GaussianBlur(1))
    return list(e.getdata()), sw, sh, int(e.getextrema()[1])

def _bend_snap(flat, w, h, emax, lx, ly, R):
    thr = max(20, int(emax * 0.30))
    x0, x1 = max(0, int(lx) - R), min(w, int(lx) + R + 1)
    y0, y1 = max(0, int(ly) - R), min(h, int(ly) + R + 1)
    best, bd = None, 1 << 30
    for yy in range(y0, y1):
        row = yy * w; dy = yy - ly; dy2 = dy * dy
        for xx in range(x0, x1):
            if flat[row + xx] > thr:
                dx = xx - lx; d = dx * dx + dy2
                if d < bd:
                    bd, best = d, (xx, yy)
    return best if best is not None else (lx, ly)

def _bend_refine(self):
    """沿四边各撒 _BEND_K 种子(在当前角点连线上等分)，各自吸到最近强边，写 edge_points_rel。
    吸附后的点偏离弦=表达弯曲；warp 的 _project_t 会取其在弦上的进度，源位置用吸附点→边跟着弯。"""
    try:
        flat, w, h, emax = _bend_build_edges(self.pil_image, 800)
    except Exception:
        return
    dw, dh, ox, oy, _s = self._get_disp_meta()
    R = max(6, int(min(dw, dh) * 0.03))
    new_edges = {0: [], 1: [], 2: [], 3: []}
    for i in range(4):
        ax, ay = self.corners_rel[i]; bx, by = self.corners_rel[(i + 1) % 4]
        for j in range(1, _BEND_K + 1):
            t = j / (_BEND_K + 1)
            rx, ry = ax + (bx - ax) * t, ay + (by - ay) * t
            lx, ly = ox + rx * dw, oy + ry * dh
            nlx, nly = _bend_snap(flat, w, h, emax, lx, ly, R)
            nrx = max(0.0, min(1.0, (nlx - ox) / dw)) if dw else rx
            nry = max(0.0, min(1.0, (nly - oy) / dh)) if dh else ry
            new_edges[i].append([nrx, nry])
    self.edge_points_rel = new_edges
    self._draw_canvas()

_bs_orig_build = PerspectiveCropDialog._build_ui
def _bs_build(self):
    _bs_orig_build(self)
    try:
        bar = ctk.CTkFrame(self, fg_color=T("panel"), corner_radius=10,
                           border_width=1, border_color=T("border"))
        bar.grid(row=5, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 8))
        ctk.CTkButton(bar, text="⚡ 边线吸附(修弯曲)", width=150, fg_color=T("accent_bg"),
                      hover_color=T("accent_bg"), text_color=T("accent_h"),
                      font=("Microsoft YaHei", 12),
                      command=lambda: _bend_refine(self)).pack(side="left", padx=12, pady=7)
        ctk.CTkLabel(bar, text="沿四边撒点并吸到强边缘，描出弯曲/变形边(覆盖已有边控制点)；"
                               "直边自动等同无修正。配合角点拖拽+吸附即可不靠模型修好变形箱。",
                     text_color=T("text_dim"), font=("Microsoft YaHei", 11)).pack(side="left", padx=6)
    except Exception:
        pass
PerspectiveCropDialog._build_ui = _bs_build
# === /BENDSNAP_V1 ===

