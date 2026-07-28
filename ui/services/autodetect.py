# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 自动透视识别服务。

从旧 ui.py 的多个补丁中抽离：

- AUTOPERSP_PATCH_V1
- AUTODETECT_V3
- AUTOPERSP_DIRECT_V1
- AUTODETECT_V5
- AUTODETECT_V6
- FINALIZE_AUTODETECT_V1

当前最终策略：

1. 如果安装了 cv2 / numpy，优先使用轮廓法 autodetect_cv。
2. 如果 cv2 失手或未安装，回退到投影峰法 autodetect_v3。
3. 如果仍无把握，由调用方使用 center_fallback。
"""

import math

from PIL import (
    Image,
    ImageFilter,
)


try:
    import cv2
    import numpy as np

    HAS_CV = True
except Exception:
    cv2 = None
    np = None
    HAS_CV = False


def _order_points(pts):
    """
    将四个点排序为：

        TL, TR, BR, BL

    需要 numpy。
    """
    pts = np.array(pts, dtype=float)

    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]

    tr = pts[np.argmin(d)]
    bl = pts[np.argmax(d)]

    return np.array([tl, tr, br, bl], dtype=float)


def autodetect_v3(pil_image):
    """
    投影峰法。

    适合正拍、俯拍、横竖排岩心箱。
    返回 corners_rel 或 None。
    """
    try:
        w0, h0 = pil_image.size

        LONG = 420
        sc = LONG / max(w0, h0)

        sw = max(8, round(w0 * sc))
        sh = max(8, round(h0 * sc))

        g = pil_image.resize((sw, sh), Image.BILINEAR).convert("L")
        g = g.filter(ImageFilter.GaussianBlur(max(2, round(min(sw, sh) * 0.02))))

        e = g.filter(ImageFilter.FIND_EDGES).convert("L")
        e = e.filter(ImageFilter.GaussianBlur(max(1, round(min(sw, sh) * 0.006))))

        data = list(e.getdata())

        rowp = [0.0] * sh

        for y in range(sh):
            s = 0
            row = y * sw

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
            n = len(a)
            out = [0.0] * n
            h = k // 2

            for i in range(n):
                lo = max(0, i - h)
                hi = min(n, i + h + 1)
                out[i] = sum(a[lo:hi]) / (hi - lo)

            return out

        rowp = smooth(rowp, 5)
        colp = smooth(colp, 5)

        def peaks(a, thr, ex_lo, ex_hi, min_d):
            n = len(a)
            cand = []

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
            lo = max(1, int(len(a) * 0.04))
            hi = max(lo + 1, int(len(a) * 0.96))

            inner = a[lo:hi] or a
            imx = max(inner) or 1.0

            pk = peaks(
                a,
                imx * 0.25,
                ex_lo,
                ex_hi,
                max(3, int(len(a) * 0.05)),
            )

            if len(pk) < 2:
                pk = peaks(
                    a,
                    imx * 0.15,
                    ex_lo,
                    ex_hi,
                    max(3, int(len(a) * 0.05)),
                )

            return [(min(1.0, s / imx), f) for s, i, f in pk], imx

        H, _ = find_axis(rowp, 0.03, 0.97)

        if len(H) < 2:
            return None

        V, _ = find_axis(colp, None, None)

        if len(V) < 2:
            V = [(0.5, 0.0), (0.5, 1.0)]

        H_pairs = [(H[k], H[k + 1]) for k in range(len(H) - 1)]
        V_pairs = [(V[k], V[k + 1]) for k in range(len(V) - 1)]

        best = None
        bscore = -1.0

        for ha, hb in H_pairs:
            t, b = ha[1], hb[1]
            hgt = b - t

            if hgt < 0.12 or hgt > 0.95:
                continue

            for va, vb in V_pairs:
                l, r = va[1], vb[1]
                wdt = r - l

                if wdt < 0.40 or wdt > 1.0:
                    continue

                se = (ha[0] + hb[0] + va[0] + vb[0]) * 0.25

                cy = (t + b) * 0.5
                cx = (l + r) * 0.5

                s_center = max(
                    0.0,
                    1.0 - abs(cy - 0.5) * 1.2 - abs(cx - 0.5) * 0.4,
                )

                ar = wdt / hgt

                s_ar = math.exp(-((ar - 2.0) / 1.3) ** 2)

                s_area = min(1.0, (wdt * hgt) / 0.25)

                score = se * (0.4 + 0.6 * s_center) * (0.5 + 0.5 * s_ar) * s_area

                if score > bscore:
                    bscore = score
                    best = (l, t, r, b)

        if best is None or bscore < 0.01:
            return None

        l, t, r, b = best

        pad = 0.005

        return [
            [max(0.0, l - pad), max(0.0, t - pad)],
            [min(1.0, r + pad), max(0.0, t - pad)],
            [min(1.0, r + pad), min(1.0, b + pad)],
            [max(0.0, l - pad), min(1.0, b + pad)],
        ]

    except Exception:
        return None


def autodetect_cv(pil_image):
    """
    OpenCV 轮廓法。

    适合斜拍、横竖排、复杂背景。
    返回 corners_rel 或 None。
    """
    if not HAS_CV:
        return None

    try:
        w0, h0 = pil_image.size

        LONG = 640
        sc = LONG / max(w0, h0)

        sw = max(8, round(w0 * sc))
        sh = max(8, round(h0 * sc))

        arr = np.array(pil_image.resize((sw, sh), Image.BILINEAR).convert("RGB"))

        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        gray = cv2.bilateralFilter(gray, 11, 100, 100)

        med = float(np.median(gray))

        lo = int(max(0, 0.5 * med))
        hi = int(min(255, 1.3 * med))

        edges = cv2.Canny(gray, lo, hi)

        kc = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kc, iterations=2)

        ko = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edges = cv2.morphologyEx(edges, cv2.MORPH_OPEN, ko, iterations=1)

        cnts, _ = cv2.findContours(
            edges,
            cv2.RETR_LIST,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        cnts = sorted(cnts, key=cv2.contourArea, reverse=True)

        area_img = float(sw * sh)
        cands = []

        for c in cnts[:50]:
            ca = cv2.contourArea(c)
            fr = ca / area_img

            if fr < 0.05 or fr > 0.93:
                continue

            rect = cv2.minAreaRect(c)
            box = cv2.boxPoints(rect)

            ra = float(rect[1][0] * rect[1][1]) or 1.0
            fill = ca / ra

            peri = cv2.arcLength(c, True)
            quad = None

            for eps in (0.02, 0.03, 0.015, 0.04, 0.01):
                ap = cv2.approxPolyDP(c, eps * peri, True)

                if len(ap) == 4 and cv2.isContourConvex(ap):
                    quad = ap.reshape(4, 2).astype(float)
                    break

            if quad is not None:
                cands.append((fr, quad, fill))

            cands.append((fr, box.astype(float), fill))

        if not cands:
            return None

        best = None
        bs = -1.0

        for fr, pts, fill in cands:
            pts = _order_points(pts)

            cx = pts[:, 0].mean() / sw
            cy = pts[:, 1].mean() / sh

            s_center = max(
                0.0,
                1.0 - abs(cy - 0.5) * 1.3 - abs(cx - 0.5) * 0.5,
            )

            s_area = min(1.0, fr / 0.18)
            s_rect = max(0.0, min(1.0, fill))

            score = (0.4 + 0.6 * s_center) * s_area * (0.3 + 0.7 * s_rect)

            if fr > 0.85:
                score *= 0.3

            if score > bs:
                bs = score
                best = pts

        if best is None or bs < 0.01:
            return None

        rel = (best / np.array([sw, sh], dtype=float)).tolist()

        return [
            [rel[0][0], rel[0][1]],
            [rel[1][0], rel[1][1]],
            [rel[2][0], rel[2][1]],
            [rel[3][0], rel[3][1]],
        ]

    except Exception:
        return None


def autodetect_corners(pil_image):
    """
    自动识别四角 dispatcher。

    优先 cv2 轮廓法，失手再回退投影峰法。
    """
    if HAS_CV:
        r = autodetect_cv(pil_image)

        if r is not None:
            return r

    return autodetect_v3(pil_image)


def center_fallback(pil_image=None):
    """
    无把握时的中心占位框。

    比整图默认框更接近目标，可配合吸附和手动拖拽完成精修。
    """
    return [
        [0.19, 0.19],
        [0.81, 0.19],
        [0.81, 0.81],
        [0.19, 0.81],
    ]