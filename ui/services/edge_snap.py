# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 边缘吸附服务。

从旧 ui.py 的多个补丁中抽离：

- PERSP_SNAP_PATCH_V1
- AUTODETECT_V6
- FINALIZE_AUTODETECT_V1
- REFINEBATCH_V1
- BENDSNAP_V1

包含：

- build_edges：建立边缘强度图
- snap_point：在半径窗口内吸附到最近强边
- scan_box：从种子点十字扫描撑框
- refine_box_edges：四边吸附精修
- bend_refine_edge_points：沿四边撒点吸附，生成边控制点
"""

from PIL import (
    Image,
    ImageFilter,
)


def build_edges(pil_image, long_edge=800):
    """
    等比缩放到 long_edge，建立边缘强度图。

    返回：
        flat, w, h, emax

    flat:
        边缘强度一维列表
    w:
        边缘图宽度
    h:
        边缘图高度
    emax:
        边缘强度最大值
    """
    w0, h0 = pil_image.size

    sc = long_edge / max(w0, h0)

    sw = max(8, round(w0 * sc))
    sh = max(8, round(h0 * sc))

    g = pil_image.resize((sw, sh), Image.BILINEAR).convert("L")
    g = g.filter(ImageFilter.GaussianBlur(2))

    e = g.filter(ImageFilter.FIND_EDGES).convert("L")
    e = e.filter(ImageFilter.GaussianBlur(1))

    return list(e.getdata()), sw, sh, int(e.getextrema()[1])


def snap_point(flat, w, h, emax, lx, ly, R):
    """
    在 (lx, ly) 的半径窗口内，返回距离最近且强度超阈值的边缘像素。

    找不到则原样返回 (lx, ly)。
    """
    thr = max(20, int(emax * 0.30))

    x0 = max(0, int(lx) - R)
    x1 = min(w, int(lx) + R + 1)

    y0 = max(0, int(ly) - R)
    y1 = min(h, int(ly) + R + 1)

    best = None
    bd = 1 << 30

    for yy in range(y0, y1):
        row = yy * w
        dy = yy - ly
        dy2 = dy * dy

        for xx in range(x0, x1):
            if flat[row + xx] > thr:
                dx = xx - lx
                d = dx * dx + dy2

                if d < bd:
                    bd = d
                    best = (xx, yy)

    return best if best is not None else (lx, ly)


def scan_box(pil_image, cx_rel, cy_rel, long_edge=800):
    """
    从种子点向四边十字扫描最近强边，撑成 rel 四角。

    返回：
        (box, real_count)

    如果失败：
        (None, 0)

    面积 > 0.80 或 < 0.05 会被视为假框，返回 None。
    """
    try:
        flat, w, h, emax = build_edges(pil_image, long_edge)
    except Exception:
        return None, 0

    thr = max(20, int(emax * 0.30))

    sx = int(cx_rel * w)
    sy = int(cy_rel * h)

    bx = max(3, int(w * 0.08))
    by = max(3, int(h * 0.08))

    def row_hit(y):
        lo = max(0, sx - bx)
        hi = min(w, sx + bx + 1)

        r = y * w

        for x in range(lo, hi):
            if flat[r + x] > thr:
                return True

        return False

    def col_hit(x):
        lo = max(0, sy - by)
        hi = min(h, sy + by + 1)

        for y in range(lo, hi):
            if flat[y * w + x] > thr:
                return True

        return False

    top = None

    for y in range(sy - 1, -1, -1):
        if row_hit(y):
            top = y
            break

    bot = None

    for y in range(sy + 1, h):
        if row_hit(y):
            bot = y
            break

    left = None

    for x in range(sx - 1, -1, -1):
        if col_hit(x):
            left = x
            break

    right = None

    for x in range(sx + 1, w):
        if col_hit(x):
            right = x
            break

    real = (
        (top is not None)
        + (bot is not None)
        + (left is not None)
        + (right is not None)
    )

    if real < 2:
        return None, 0

    top = top if top is not None else 0
    bot = bot if bot is not None else h - 1
    left = left if left is not None else 0
    right = right if right is not None else w - 1

    if right <= left or bot <= top:
        return None, 0

    l = left / w
    t = top / h
    r = right / w
    b = bot / h

    area = (r - l) * (b - t)

    if area > 0.80 or area < 0.05:
        return None, 0

    return [[l, t], [r, t], [r, b], [l, b]], real


def refine_box_edges(pil_image, corners_rel, long_edge=800):
    """
    把当前框四边各自贴到邻域内最近强边。

    返回新的 corners_rel，失败返回 None。
    """
    try:
        flat, w, h, emax = build_edges(pil_image, long_edge)
    except Exception:
        return None

    thr = max(20, int(emax * 0.30))

    cs = corners_rel

    l = min(cs[0][0], cs[3][0])
    r = max(cs[1][0], cs[2][0])

    t = min(cs[0][1], cs[1][1])
    b = max(cs[2][1], cs[3][1])

    lx = int(l * w)
    rx = int(r * w)

    R = max(4, int(0.12 * h))

    def row_str(yy):
        if yy < 0 or yy >= h:
            return 0

        row = yy * w

        lo = max(0, lx)
        hi = min(w, rx + 1)

        c = 0

        for x in range(lo, hi):
            if flat[row + x] > thr:
                c += 1

        return c

    ty2 = int(t * h)
    by2 = int(b * h)

    def col_str(xx):
        if xx < 0 or xx >= w:
            return 0

        lo = max(0, ty2)
        hi = min(h, by2 + 1)

        c = 0

        for y in range(lo, hi):
            if flat[y * w + xx] > thr:
                c += 1

        return c

    min_w = max(3, int((rx - lx) * 0.12))
    min_h = max(3, int((by2 - ty2) * 0.12))

    # 上边
    ty = int(t * h)
    best = ty
    bs = row_str(ty)

    for yy in range(max(0, ty - R), min(h, ty + R + 1)):
        s = row_str(yy)

        if s > bs:
            bs = s
            best = yy

    if bs >= min_w and bs > row_str(ty) * 1.05:
        t = best / h

    # 下边
    by = int(b * h)
    best = by
    bs = row_str(by)

    for yy in range(max(0, by - R), min(h, by + R + 1)):
        s = row_str(yy)

        if s > bs:
            bs = s
            best = yy

    if bs >= min_w and bs > row_str(by) * 1.05:
        b = best / h

    ty2 = int(t * h)
    by2 = int(b * h)

    min_h = max(3, int((by2 - ty2) * 0.12))

    # 左边
    lxx = int(l * w)
    best = lxx
    bs = col_str(lxx)

    for xx in range(max(0, lxx - R), min(w, lxx + R + 1)):
        s = col_str(xx)

        if s > bs:
            bs = s
            best = xx

    if bs >= min_h and bs > col_str(lxx) * 1.05:
        l = best / w

    # 右边
    rxx = int(r * w)
    best = rxx
    bs = col_str(rxx)

    for xx in range(max(0, rxx - R), min(w, rxx + R + 1)):
        s = col_str(xx)

        if s > bs:
            bs = s
            best = xx

    if bs >= min_h and bs > col_str(rxx) * 1.05:
        r = best / w

    l = max(0.0, min(1.0, l))
    r = max(0.0, min(1.0, r))

    t = max(0.0, min(1.0, t))
    b = max(0.0, min(1.0, b))

    if r - l < 0.05 or b - t < 0.05:
        return None

    return [
        [l, t],
        [r, t],
        [r, b],
        [l, b],
    ]


def bend_refine_edge_points(pil_image, corners_rel, k=4, long_edge=800, snap_radius_ratio=0.03):
    """
    沿四边各撒 k 个种子点，各自吸附到最近强边，生成 edge_points_rel。

    返回：
        {
            0: [[x,y], ...],
            1: [[x,y], ...],
            2: [[x,y], ...],
            3: [[x,y], ...],
        }

    坐标为相对原图 0~1。
    """
    try:
        flat, w, h, emax = build_edges(pil_image, long_edge)
    except Exception:
        return {
            0: [],
            1: [],
            2: [],
            3: [],
        }

    R = max(6, int(min(w, h) * snap_radius_ratio))

    new_edges = {
        0: [],
        1: [],
        2: [],
        3: [],
    }

    for i in range(4):
        ax, ay = corners_rel[i]
        bx, by = corners_rel[(i + 1) % 4]

        for j in range(1, k + 1):
            t = j / (k + 1)

            rx = ax + (bx - ax) * t
            ry = ay + (by - ay) * t

            lx = rx * w
            ly = ry * h

            nlx, nly = snap_point(flat, w, h, emax, lx, ly, R)

            nrx = max(0.0, min(1.0, nlx / w)) if w else rx
            nry = max(0.0, min(1.0, nly / h)) if h else ry

            new_edges[i].append([nrx, nry])

    return new_edges