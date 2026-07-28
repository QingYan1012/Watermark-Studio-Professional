# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - UI 常量模块。

从旧 ui.py 中抽离出的基础常量。
当前阶段通过 ui/bridge.py 注入回 ui/legacy_app.py，
后续会逐步让新模块直接依赖这里，而不是依赖 legacy_app。

本轮（第27轮）改动：三个路径常量 _PREF_DIR / _THEME_PATH / _WELCOME_FLAG 收口到
配置中心 app/config.py 的纯函数，带 try 回退（app 包不可用时退回硬编码，值与 config
完全相同）。至此整个项目里 "~/.watermark_studio" 字面量只剩 app/config.py 一处定义，
readmes ⑥ 配置统一管理的路径/偏好/常量三线全部统一。
"""

import os


IMAGE_EXTS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
)

HANDLE = 5
RESIZE_HANDLE = 6

DOT_STEP = 22
RULER = 22

MAX_PREVIEW_INTERACT = 2000
MAX_PREVIEW_SETTLE = 2200

PIXEL_PERFECT_CAP = 6000
PIXEL_PERFECT_CAP_INTERACT = 4000

ZOOM_MIN = 0.3
ZOOM_MAX = 4.0


# ----------------------------------------------------------------------
# 【第27轮】路径常量收口到配置中心。
# 优先用 app/config.py 的纯函数；import 失败（app 包缺失/损坏）时回退硬编码，
# 回退值与 config 计算结果逐字符相同，保证 legacy 拿到的路径不漂移。
# 注意：这些纯函数为 lru_cache，此处调用不产生任何 IO 副作用。
# ----------------------------------------------------------------------
try:
    from app.config import (
        pref_dir as _cfg_pref_dir,
        theme_path as _cfg_theme_path,
        welcome_flag_path as _cfg_welcome_path,
    )
    _PREF_DIR = _cfg_pref_dir()
    _THEME_PATH = _cfg_theme_path()
    _WELCOME_FLAG = _cfg_welcome_path()
except Exception:
    _PREF_DIR = os.path.join(os.path.expanduser("~"), ".watermark_studio")
    _THEME_PATH = os.path.join(_PREF_DIR, "theme.json")
    _WELCOME_FLAG = os.path.join(_PREF_DIR, ".welcomed")


ALL = (
    "IMAGE_EXTS",
    "HANDLE",
    "RESIZE_HANDLE",
    "DOT_STEP",
    "RULER",
    "MAX_PREVIEW_INTERACT",
    "MAX_PREVIEW_SETTLE",
    "PIXEL_PERFECT_CAP",
    "PIXEL_PERFECT_CAP_INTERACT",
    "ZOOM_MIN",
    "ZOOM_MAX",
    "_PREF_DIR",
    "_THEME_PATH",
    "_WELCOME_FLAG",
)