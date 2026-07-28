# -- coding: utf-8 --
"""路3 标点工具 v3：修“最大化不自适应”+“多锚点画不出来”。
数据模型统一存 0~1 相对坐标(点击即换算)，绘制时转屏幕 → 窗口 resize/最大化
重排时点绝不错位，自适应免费拿到；阶段2 逐边画“角点→排序边点→下一角点”折线，
边点=按边着色的同规格圆+边序号，顶栏实时报每边锚点数 → 多锚点视觉成立。
存盘 {image, corners_rel, edge_points_rel, keypoints_fixed} 与软件 mesh 同构，
keypoints_fixed=4角+每边按弧长重采样K点(定长4+4K)备训练。
交互：阶段1 左键点 TL→TR→BR→BL；阶段2 左键点=归最近边、右键撤最后边点、
b 回阶段1 重标角、r 清边点、n/空格 存并跳下一张(跳过已标)、← → 翻页、q 退。
独立运行，不依赖主软件。用法：python label_corners_v3.py <图片文件夹>"""
import os, sys, json, glob, math
import tkinter as tk
from PIL import Image, ImageTk

ORDER = ["TL", "TR", "BR", "BL"]
EDGE_COL = ["#3ea6ff", "#2faa55", "#f0b440", "#9b7bff"]   # 四条边各一色，鲜明可辨
K = 4  # 每边重采样内部点数 → keypoints_fixed 定长 = 4 + 4*K


def _seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L = dx * dx + dy * dy
    if L < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _proj_t(p, a, b):
    cx, cy = b[0] - a[0], b[1] - a[1]
    L = cx * cx + cy * cy
    if L < 1e-12:
        return 0.0
    return max(0.0, min(1.0, ((p[0] - a[0]) * cx + (p[1] - a[1]) * cy) / L))


def _resample_edge(A, user_pts, B, k):
    """沿折线 [A,*user_pts,B] 按累计弧长等距采 k 个内部点(定长, 弯曲保形)。坐标空间无关。"""
    poly = [A] + list(user_pts) + [B]
    seg = [math.hypot(poly[i + 1][0] - poly[i][0], poly[i + 1][1] - poly[i][1])
           for i in range(len(poly) - 1)]
    total = sum(seg)
    if total < 1e-9:
        return [list(A)] * k
    out = []
    for j in range(1, k + 1):
        target = total * j / (k + 1)
        acc = 0.0
        for i, s in enumerate(seg):
            if acc + s >= target - 1e-9:
                f = 0.0 if s < 1e-9 else (target - acc) / s
                out.append([poly[i][0] + f * (poly[i + 1][0] - poly[i][0]),
                            poly[i][1] + f * (poly[i + 1][1] - poly[i][1])])
                break
            acc += s
        else:
            out.append(list(poly[-1]))
    return out


class Labeler:
    def __init__(self, folder):
        self.folder = folder
        self.files = sorted(glob.glob(os.path.join(folder, "*.*")))
        self.files = [f for f in self.files if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))]
        self.idx = 0
        # ★ 统一存相对坐标：resize/最大化时只重算 meta，rel 不变 → 点绝不错位
        self.corners_rel = []
        self.edge_rel = {0: [], 1: [], 2: [], 3: []}
        self.phase = 1
        self.pulse = None          # ('corner',i) 或 ('edge',i) 刚添加的点，脉冲高亮
        self._pulse_job = None
        self._last_size = (0, 0)
        self.root = tk.Tk()
        self.root.title("路3 标点工具 v3（多锚点 · 自适应）")
        self.root.geometry("1280x820")
        self.canvas = tk.Canvas(self.root, bg="#16181d", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Button-3>", self.undo_edge)
        self.canvas.bind("<Configure>", self.on_configure)   # ★ 最大化/resize 自适应
        self.root.bind("<Left>", lambda e: self.go(-1))
        self.root.bind("<Right>", lambda e: self.go(1))
        self.root.bind("n", lambda e: self.save_next())
        self.root.bind("<space>", lambda e: self.save_next())
        self.root.bind("b", lambda e: self.back_to_corners())
        self.root.bind("r", lambda e: self.clear_edges())
        self.root.bind("q", lambda e: self.root.destroy())
        self.tk_img = None
        self.meta = None
        self.pil = None
        self._open_file()

    # ---------- 坐标换算 ----------
    def json_path(self, f):
        return os.path.splitext(f)[0] + ".corners.json"

    def s2r(self, x, y):
        sc, ox, oy = self.meta
        return [(x - ox) / sc / self.pil.width, (y - oy) / sc / self.pil.height]

    def r2s(self, rx, ry):
        sc, ox, oy = self.meta
        return ox + rx * sc * self.pil.width, oy + ry * sc * self.pil.height

    def nearest_edge_rel(self, rel):
        cs = self.corners_rel
        best, bd = 0, 1e18
        for i in range(4):
            d = _seg_dist(rel[0], rel[1], cs[i][0], cs[i][1], cs[(i + 1) % 4][0], cs[(i + 1) % 4][1])
            if d < bd:
                bd, best = d, i
        return best

    # ---------- 文件 / 布局 ----------
    def _open_file(self):
        if self.idx >= len(self.files):
            self.pil = None
            self.corners_rel = []
            self.edge_rel = {0: [], 1: [], 2: [], 3: []}
            self.phase = 1
            self._relayout(force=True)
            return
        self.pil = Image.open(self.files[self.idx]).convert("RGB")
        self.corners_rel = []
        self.edge_rel = {0: [], 1: [], 2: [], 3: []}
        self.phase = 1
        self.pulse = None
        self._relayout(force=True)

    def on_configure(self, _e=None):
        # 只在窗口尺寸真正变化时重排，避免无谓重缩放
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        if (cw, ch) == self._last_size:
            return
        self._last_size = (cw, ch)
        self._relayout(force=True)

    def _relayout(self, force=False):
        """按当前窗口算 meta + 缩放底图 + 重画。rel 不变，故 resize 后点自动归位。"""
        self.canvas.delete("all")
        if self.pil is None:
            self.canvas.create_text(400, 300, fill="#cfd4dc",
                                    text="全部标完，q 退出。", font=("", 16))
            return
        cw = max(50, self.canvas.winfo_width())
        ch = max(50, self.canvas.winfo_height())
        if cw < 50 or ch < 50:
            return
        sc = min((cw - 40) / self.pil.width, (ch - 80) / self.pil.height, 1.0)
        dw, dh = max(1, round(self.pil.width * sc)), max(1, round(self.pil.height * sc))
        ox, oy = (cw - dw) // 2, (ch - dh) // 2
        self.meta = (sc, ox, oy)
        self.tk_img = ImageTk.PhotoImage(self.pil.resize((dw, dh), Image.BILINEAR))
        self.draw()

    # ---------- 绘制 ----------
    def _corner_dot(self, sx, sy, label, active=False):
        """三层角点：外光晕 + 实心橙 + 白边，active 时再套脉冲环。"""
        if active:
            self.canvas.create_oval(sx - 16, sy - 16, sx + 16, sy + 16,
                                    outline="#ffd27a", width=2)
        self.canvas.create_oval(sx - 11, sy - 11, sx + 11, sy + 11,
                                fill=(255, 179, 71, 70), outline="")
        self.canvas.create_oval(sx - 7, sy - 7, sx + 7, sy + 7,
                                fill="#ffb347", outline="white", width=2)
        self.canvas.create_text(sx + 12, sy - 12, anchor="w", fill="#ffd27a",
                                text=label, font=("", 11, "bold"))

    def _edge_dot(self, sx, sy, color, tag, active=False):
        if active:
            self.canvas.create_oval(sx - 13, sy - 13, sx + 13, sy + 13, outline=color, width=2)
        self.canvas.create_oval(sx - 8, sy - 8, sx + 8, sy + 8, fill=(255, 255, 255, 60), outline="")
        self.canvas.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill=color, outline="white", width=2)
        self.canvas.create_text(sx + 10, sy + 9, anchor="w", fill=color, text=tag, font=("", 9))

    def draw(self):
        self.canvas.delete("all")
        if self.meta is None or self.tk_img is None:
            return
        sc, ox, oy = self.meta
        self.canvas.create_image(ox, oy, anchor="nw", image=self.tk_img)
        cs = self.corners_rel
        n_edge = [len(self.edge_rel[i]) for i in range(4)]

        if self.phase == 2 and len(cs) == 4:
            # ★ 逐边折线：角点 → 该边按 t 排序的边点 → 下一角点（多锚点视觉成立的关键）
            for i in range(4):
                order = sorted(range(len(self.edge_rel[i])),
                               key=lambda k: _proj_t(self.edge_rel[i][k], cs[i], cs[(i + 1) % 4]))
                chain = [cs[i]] + [self.edge_rel[i][k] for k in order] + [cs[(i + 1) % 4]]
                cs_ = [self.r2s(*p) for p in chain]
                for j in range(len(cs_) - 1):
                    self.canvas.create_line(cs_[j][0], cs_[j][1], cs_[j + 1][0], cs_[j + 1][1],
                                            fill=EDGE_COL[i], width=2)
                for k in order:
                    sx, sy = self.r2s(*self.edge_rel[i][k])
                    self._edge_dot(sx, sy, EDGE_COL[i], f"e{i}",
                                   active=(self.pulse == ("edge", i)))
        else:
            # 阶段1：按点击顺序连临时线
            for i in range(len(cs)):
                a = self.r2s(*cs[i]); b = self.r2s(*cs[(i + 1) % len(cs)])
                self.canvas.create_line(a[0], a[1], b[0], b[1], fill="#3ea6ff", width=2, dash=(5, 3))

        for i, p in enumerate(cs):
            sx, sy = self.r2s(*p)
            self._corner_dot(sx, sy, ORDER[i], active=(self.pulse == ("corner", i)))

        # 顶栏：阶段色条 + 进度 + 每边锚点数
        self.canvas.create_rectangle(0, 0, self.canvas.winfo_width(), 30,
                                     fill="#1d2128", outline="")
        self.canvas.create_rectangle(0, 0, 6 if self.phase == 1 else 6, 30,
                                     fill=("#ffb347" if self.phase == 1 else "#3ea6ff"))
        f = os.path.basename(self.files[self.idx]) if self.idx < len(self.files) else ""
        done = "  [已标]" if (self.idx < len(self.files) and os.path.exists(self.json_path(self.files[self.idx]))) else ""
        if self.phase == 1:
            mid = f"阶段1：点 4 角 {ORDER}（已 {len(cs)}/4）"
        else:
            mid = (f"阶段2：左键沿弯曲边点控制点(自动归最近边) | 右键撤销  b 重标角  r 清边点  n/空格 存并下一张"
                   f"   ‖ 边锚点 0:{n_edge[0]} 1:{n_edge[1]} 2:{n_edge[2]} 3:{n_edge[3]}")
        self.canvas.create_text(16, 15, anchor="w", fill="#e7e9ee",
                                text=f"{self.idx + 1}/{len(self.files)}  {f}    {mid}{done}    |  ← → 翻页  q 退",
                                font=("", 11))

    def _flash_pulse(self, kind):
        self.pulse = kind
        if self._pulse_job:
            self.root.after_cancel(self._pulse_job)
        self.draw()
        self._pulse_job = self.root.after(420, self._clear_pulse)

    def _clear_pulse(self):
        self.pulse = None
        self._pulse_job = None
        self.draw()

    # ---------- 交互 ----------
    def on_click(self, e):
        if self.meta is None:
            return
        if self.phase == 1:
            if len(self.corners_rel) >= 4:
                return
            self.corners_rel.append(self.s2r(e.x, e.y))
            self._flash_pulse(("corner", len(self.corners_rel) - 1))
            if len(self.corners_rel) == 4:
                self.phase = 2
                self.pulse = None
                self.draw()
        else:
            rel = self.s2r(e.x, e.y)
            ei = self.nearest_edge_rel(rel)
            self.edge_rel[ei].append(rel)
            self._flash_pulse(("edge", ei))

    def undo_edge(self, _e):
        for i in (3, 2, 1, 0):
            if self.edge_rel[i]:
                self.edge_rel[i].pop()
                self.draw()
                return

    def back_to_corners(self):
        self.phase = 1
        self.corners_rel = []
        self.edge_rel = {0: [], 1: [], 2: [], 3: []}
        self.pulse = None
        self.draw()

    def clear_edges(self):
        self.edge_rel = {0: [], 1: [], 2: [], 3: []}
        self.draw()

    # ---------- 存盘 ----------
    def build_payload(self):
        edge_rel = {str(i): [list(p) for p in self.edge_rel[i]] for i in range(4)}
        kp = []
        for i in range(4):
            kp.append(list(self.corners_rel[i]))
            kp += _resample_edge(self.corners_rel[i],
                                 [list(p) for p in self.edge_rel[i]],
                                 self.corners_rel[(i + 1) % 4], K)
        return {"image": os.path.basename(self.files[self.idx]),
                "corners_rel": [list(p) for p in self.corners_rel],
                "edge_points_rel": edge_rel,
                "keypoints_fixed": kp}

    def save_next(self):
        if len(self.corners_rel) != 4:
            return
        with open(self.json_path(self.files[self.idx]), "w", encoding="utf-8") as f:
            json.dump(self.build_payload(), f, ensure_ascii=False, indent=2)
        self.go(1, skip_done=True)

    def go(self, d, skip_done=False):
        self.idx += d
        if skip_done:
            while 0 <= self.idx < len(self.files) and os.path.exists(self.json_path(self.files[self.idx])):
                self.idx += 1
        self.idx = max(0, min(len(self.files), self.idx))
        self._open_file()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    Labeler(sys.argv[1] if len(sys.argv) > 1 else ".").run()