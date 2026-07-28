# -*- coding: utf-8 -*-
"""
图片列表排序工具。

默认的“按文件名排序”如果直接用字符串比较，会把 “第10箱” 排到 “第2箱”
前面（因为 '1' < '2'），顺序看起来很乱。这里提供“自然排序”：把文件名
拆成 [文字][数字][文字][数字]... 的片段，数字片段按数值比较、文字片段
按字符串比较，这样 第1箱 < 第2箱 < … < 第10箱 < 第11箱，符合直觉。

同时暴露几种排序方式，供界面下拉框选择：

natural   ：自然排序（默认，前方文字优先，其后数字按数值大小）
name      ：纯字符串排序（原始文件名排序，作为兜底/对照）
mtime     ：按文件修改时间排序
manual    ：不排序，保持用户手动调整/导入时的顺序
"""

import os
import re


_CHUNK_RE = re.compile(r"(\d+)")


def natural_key(text):
    """
    把字符串拆成 [str, int, str, int, ...] 片段用于自然排序比较。
    """
    parts = _CHUNK_RE.split(text)
    key = []

    for i, p in enumerate(parts):
        if p == "":
            continue

        if i % 2 == 1:
            # 数字片段
            key.append((0, int(p), ""))
        else:
            # 文字片段：优先按文字本身比较（“前方文字优先”）
            key.append((1, 0, p.lower()))

    return key


def sort_entries(entries, mode="natural", path_attr="path"):
    """
    按指定 mode 对 entries（需有 .path 属性的对象列表）排序，返回新列表。
    """
    mode = str(mode or "natural").strip()
    path_attr = str(path_attr or "path").strip()

    if mode == "manual":
        return list(entries)

    if mode == "mtime":
        def mtime_key(e):
            p = getattr(e, path_attr)
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0

        return sorted(entries, key=mtime_key)

    if mode == "name":
        return sorted(
            entries,
            key=lambda e: os.path.basename(getattr(e, path_attr)).lower()
        )

    # natural（默认）
    return sorted(
        entries,
        key=lambda e: natural_key(os.path.basename(getattr(e, path_attr)))
    )


SORT_MODE_LABELS = [
    ("natural", "文件名（自然排序，推荐）"),
    ("name", "文件名（字符排序）"),
    ("mtime", "修改时间"),
    ("manual", "导入/手动顺序"),
]