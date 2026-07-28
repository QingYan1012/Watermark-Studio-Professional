# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 几何工具服务。

从旧 ui.py 透视裁剪相关补丁中抽离出的纯几何函数。
"""

import math


def solve3x3(m, rhs):
    """
    解 3x3 线性方程组。

    参数：
        m: 3x3 矩阵
        rhs: 长度 3 的右端向量

    返回：
        [x, y, z]

    如果矩阵接近奇异，返回 None。
    """

    def det3(a):
        return (
            a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0])
        )

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


def proj_t(rel_pt, c0, c1):
    """
    计算 rel_pt 在 c0 -> c1 线段上的投影进度 t。

    返回值范围：
        0.0 ~ 1.0
    """
    cx = c1[0] - c0[0]
    cy = c1[1] - c0[1]

    length_sq = cx * cx + cy * cy

    if length_sq < 1e-12:
        return 0.0

    t = ((rel_pt[0] - c0[0]) * cx + (rel_pt[1] - c0[1]) * cy) / length_sq

    return max(0.0, min(1.0, t))


def point_seg_dist(px, py, p1, p2):
    """
    计算点 (px, py) 到线段 p1-p2 的最短距离。
    """
    x1, y1 = p1
    x2, y2 = p2

    dx = x2 - x1
    dy = y2 - y1

    length_sq = dx * dx + dy * dy

    if length_sq < 1e-9:
        return math.hypot(px - x1, py - y1)

    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))

    nx = x1 + t * dx
    ny = y1 + t * dy

    return math.hypot(px - nx, py - ny)