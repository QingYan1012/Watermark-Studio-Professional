# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 透视变换服务。

从旧 ui.py 的 AUTOPERSP_DIRECT_V1 等补丁中抽离出的纯 warp 函数。

包含：

- warp_triangle：单三角形仿射贴图片
- warp_corners：根据四角 + 边控制点做 mesh warp
- warp_scaled：在指定长边上做快速 warp
"""

import math

from PIL import (
    Image,
    ImageDraw,
)

from .geometry import (
    proj_t,
    solve3x3,
)


def warp_triangle(src_img, dst_img, tri_src, tri_dst):
    """
    将 src_img 中的一个三角形仿射变换到 dst_img 中的目标三角形。
    """
    xs = [p[0] for p in tri_dst]
    ys = [p[1] for p in tri_dst]

    x_min = max(0, int(math.floor(min(xs))))
    y_min = max(0, int(math.floor(min(ys))))

    x_max = min(dst_img.width, int(math.ceil(max(xs))) + 1)
    y_max = min(dst_img.height, int(math.ceil(max(ys))) + 1)

    bw = x_max - x_min
    bh = y_max - y_min

    if bw <= 0 or bh <= 0:
        return

    m = [
        [tri_dst[0][0], tri_dst[0][1], 1],
        [tri_dst[1][0], tri_dst[1][1], 1],
        [tri_dst[2][0], tri_dst[2][1], 1],
    ]

    abc = solve3x3(m, [p[0] for p in tri_src])
    defc = solve3x3(m, [p[1] for p in tri_src])

    if abc is None or defc is None:
        return

    a, b, c = abc
    d, e, f = defc

    coeffs = (
        a,
        b,
        c + a * x_min + b * y_min,
        d,
        e,
        f + d * x_min + e * y_min,
    )

    patch = src_img.transform(
        (bw, bh),
        Image.AFFINE,
        coeffs,
        resample=Image.BICUBIC,
    )

    mask = Image.new("L", (bw, bh), 0)

    local_tri = [
        (x - x_min, y - y_min)
        for x, y in tri_dst
    ]

    ImageDraw.Draw(mask).polygon(local_tri, fill=255, outline=255)

    dst_img.paste(patch, (x_min, y_min), mask)


def warp_corners(pil_image, corners_rel, edge_points_rel=None):
    """
    根据四角和边控制点做 mesh warp。

    参数：
        pil_image: PIL.Image
        corners_rel: [[x,y], [x,y], [x,y], [x,y]]，相对坐标 0~1
        edge_points_rel: {0: [...], 1: [...], 2: [...], 3: [...]}

    返回：
        矫正后的 PIL.Image
    """
    edge_points_rel = edge_points_rel or {
        0: [],
        1: [],
        2: [],
        3: [],
    }

    ow, oh = pil_image.size

    corners_px = [
        (rx * ow, ry * oh)
        for rx, ry in corners_rel
    ]

    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = corners_px

    w1 = math.hypot(x1 - x0, y1 - y0)
    w2 = math.hypot(x2 - x3, y2 - y3)
    max_w = max(2, round(max(w1, w2)))

    h1 = math.hypot(x3 - x0, y3 - y0)
    h2 = math.hypot(x2 - x1, y2 - y1)
    max_h = max(2, round(max(h1, h2)))

    dst_corners = [
        (0, 0),
        (max_w, 0),
        (max_w, max_h),
        (0, max_h),
    ]

    perimeter_src = []
    perimeter_dst = []

    for i in range(4):
        perimeter_src.append(corners_px[i])
        perimeter_dst.append(dst_corners[i])

        c0 = corners_rel[i]
        c1 = corners_rel[(i + 1) % 4]

        d0 = dst_corners[i]
        d1 = dst_corners[(i + 1) % 4]

        pts = edge_points_rel.get(i, [])

        order = sorted(
            range(len(pts)),
            key=lambda k: proj_t(pts[k], c0, c1),
        )

        for kk in order:
            t = proj_t(pts[kk], c0, c1)

            perimeter_src.append(
                (
                    pts[kk][0] * ow,
                    pts[kk][1] * oh,
                )
            )

            perimeter_dst.append(
                (
                    d0[0] + t * (d1[0] - d0[0]),
                    d0[1] + t * (d1[1] - d0[1]),
                )
            )

    n = len(perimeter_src)

    centroid_src = (
        sum(p[0] for p in perimeter_src) / n,
        sum(p[1] for p in perimeter_src) / n,
    )

    centroid_dst = (
        sum(p[0] for p in perimeter_dst) / n,
        sum(p[1] for p in perimeter_dst) / n,
    )

    src_rgba = pil_image.convert("RGBA")
    out = Image.new("RGBA", (max_w, max_h), (0, 0, 0, 0))

    for k in range(n):
        k2 = (k + 1) % n

        tri_src = (
            centroid_src,
            perimeter_src[k],
            perimeter_src[k2],
        )

        tri_dst = (
            centroid_dst,
            perimeter_dst[k],
            perimeter_dst[k2],
        )

        warp_triangle(src_rgba, out, tri_src, tri_dst)

    if pil_image.mode != "RGBA":
        bg = Image.new("RGB", out.size, (0, 0, 0))
        bg.paste(out, (0, 0), out)
        return bg

    return out


def warp_scaled(pil_image, corners_rel, long_edge, edge_points_rel=None):
    """
    在指定长边上做快速 warp。

    如果原图长边小于等于 long_edge，则直接原图 warp。
    """
    w0, h0 = pil_image.size

    sc = long_edge / max(w0, h0)

    if sc >= 1.0:
        return warp_corners(pil_image, corners_rel, edge_points_rel)

    small = pil_image.resize(
        (
            max(2, round(w0 * sc)),
            max(2, round(h0 * sc)),
        ),
        Image.BILINEAR,
    )

    return warp_corners(small, corners_rel, edge_points_rel)