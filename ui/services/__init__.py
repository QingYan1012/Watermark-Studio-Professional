# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - services 包。

当前包含：

- geometry：几何工具
- warp：透视变换
- autodetect：自动透视识别
- edge_snap：边缘吸附 / 撑框 / 精修
"""

from .geometry import (
    point_seg_dist,
    proj_t,
    solve3x3,
)

from .warp import (
    warp_corners,
    warp_scaled,
    warp_triangle,
)

from .autodetect import (
    HAS_CV,
    autodetect_corners,
    autodetect_cv,
    autodetect_v3,
    center_fallback,
)

from .edge_snap import (
    bend_refine_edge_points,
    build_edges,
    refine_box_edges,
    scan_box,
    snap_point,
)


__all__ = [
    "point_seg_dist",
    "proj_t",
    "solve3x3",
    "warp_corners",
    "warp_scaled",
    "warp_triangle",
    "HAS_CV",
    "autodetect_corners",
    "autodetect_cv",
    "autodetect_v3",
    "center_fallback",
    "bend_refine_edge_points",
    "build_edges",
    "refine_box_edges",
    "scan_box",
    "snap_point",
]