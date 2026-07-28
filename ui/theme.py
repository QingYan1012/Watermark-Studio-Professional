# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 主题模块。

从旧 ui.py 中抽离出的主题系统。

包含：

- THEMES：亮色/暗色主题定义
- THEME：当前单值主题，供 PIL 画布层读取
- ACCENT：当前强调色
- T(role)：CustomTkinter 双态颜色元组
- native(widget, **roles)：登记 tk 原生控件主题角色
- retheme_native()：切换主题时统一刷新 tk 原生控件
- apply_theme(mode)：应用亮色/暗色主题
"""


THEMES = {
    "light": {
        "bg": "#f5f6f8",
        "panel": "#ffffff",
        "panel2": "#fafbfc",
        "panel3": "#f0f2f5",
        "border": "#e6e8eb",
        "border2": "#d6dae0",
        "canvas": "#eceef1",
        "dot": (208, 214, 222, 255),
        "photo_shadow": (31, 35, 41, 64),
        "text": "#1f2329",
        "text_mid": "#4e5560",
        "text_dim": "#767d87",
        "accent": "#3370ff",
        "accent_h": "#2860e1",
        "accent_bg": "#e8f0fe",
        "sel": "#e8f0fe",
        "purple": "#7b61ff",
        "purple_bg": "#f1eeff",
        "ok": "#2faa55",
        "ok_hover": "#27924a",
        "danger": "#d54941",
        "danger_bg": "#fdecea",
        "warn": "#e08a0c",
        "crop_canvas": "#e9ebef",
        "ruler": "#f3f4f6",
    },
    "dark": {
        "bg": "#15171c",
        "panel": "#1d2027",
        "panel2": "#232730",
        "panel3": "#2b303b",
        "border": "#2a2f3a",
        "border2": "#3a4150",
        "canvas": "#101217",
        "dot": (64, 72, 86, 255),
        "photo_shadow": (0, 0, 0, 170),
        "text": "#e7e9ee",
        "text_mid": "#b3b9c4",
        "text_dim": "#828a98",
        "accent": "#4dabff",
        "accent_h": "#6cbcff",
        "accent_bg": "#1f3a5c",
        "sel": "#21344d",
        "purple": "#9b7bff",
        "purple_bg": "#2a2342",
        "ok": "#34b35a",
        "ok_hover": "#2a9249",
        "danger": "#e0635c",
        "danger_bg": "#3a2322",
        "warn": "#f0b440",
        "crop_canvas": "#14171d",
        "ruler": "#1a1d24",
    },
}


THEME = dict(THEMES["light"])
ACCENT = THEME["accent"]

NATIVE_WIDGETS = []


def apply_theme(mode):
    """
    应用主题。

    mode:
        "light"
        "dark"
    """
    global ACCENT

    THEME.clear()
    THEME.update(THEMES[mode])
    ACCENT = THEME["accent"]


def T(role):
    """
    双态颜色元组。

    CustomTkinter 控件使用它作为 fg_color / text_color / border_color 等，
    切换 appearance mode 时自动翻色。
    """
    return (THEMES["light"][role], THEMES["dark"][role])


def native(widget, **roles):
    """
    登记一个 tk 原生控件的主题角色。

    例如：

        native(canvas, bg="canvas")
    """
    NATIVE_WIDGETS.append((widget, roles))
    return widget


def retheme_native():
    """
    切换主题时统一刷新所有已登记的 tk 原生控件。
    """
    for widget, roles in NATIVE_WIDGETS:
        try:
            widget.configure(**{key: THEME[value] for key, value in roles.items()})
        except Exception:
            pass