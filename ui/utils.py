# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - UI 工具函数模块。

从旧 ui.py 中抽离出的通用工具函数。
"""

import math
import re


def disp_font(size, bold=False):
    """
    返回显示字体元组。

    旧 ui.py 中大量使用 Bahnschrift / Bahnschrift SemiBold。
    """
    return ("Bahnschrift SemiBold" if bold else "Bahnschrift", size)


def nice_step(raw):
    """
    计算标尺刻度的“好看步长”。

    例如：
        73  -> 100
        42  -> 50
        21  -> 20
        8   -> 10
    """
    if raw <= 0:
        return 1

    p = 10 ** math.floor(math.log10(raw))
    f = raw / p

    if f < 1.5:
        n = 1
    elif f < 3:
        n = 2
    elif f < 7:
        n = 5
    else:
        n = 10

    return n * p


def sanitize_filename(name):
    """
    清理文件名中的非法字符。
    """
    name = re.sub(r'[/:*?"<>|]', "_", name)
    return name.strip() or "output"