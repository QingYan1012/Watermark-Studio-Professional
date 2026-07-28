# -*- coding: utf-8 -*-
"""
渲染模块：把 Template 里的元素（文字/图标/形状）画到一张图片上。

支持字间距(letter_spacing)、行间距(line_spacing)的渲染控制。

性能模型：

ElementLayerCache：每个元素渲染好的“透明图层”按【像素级外观哈希】缓存。
交互拖拽只改 x/y，外观哈希不变 → 命中缓存 → 直接 alpha_composite 到新位置，
不再重渲染该元素。

缓存键含“渲染像素尺寸 + fast + 替换后文本”，故预览(小) 与导出(原图) 哈希不同
→ 导出自动 miss → 当场全质量重渲染，缓存对导出画质无损。

底图 RGBA 转换结果缓存，每帧只 copy；图标 resize 结果缓存；临时 Draw 单例复用。

交互 fast=True 时：阴影模糊跳过、加粗降级、图标用 BILINEAR；松手后 fast=False 补精细帧。

形状阴影在 fast 时同样跳过（_build_shape_layer 的 shadow_on 含 and not fast），
避免拖拽/缩放带阴影的形状时每帧跑高斯模糊导致的卡顿。
"""

import os
import re
import math
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFilter, ImageFont


PLACEHOLDER_RE = re.compile(r"{([^{}]+)}")
UNIT_SUFFIX_RE = re.compile(r"[（(][^（）()]*[)）]\s*$")


def _normalize_key(k):
    k = str(k).strip()
    k = UNIT_SUFFIX_RE.sub("", k).strip()
    return k.lower()


def safe_format(text, data):
    data = data or {}
    norm_lookup = {}
    built = False

    def _sub(m):
        nonlocal built

        key = m.group(1)

        if key in data and str(data[key]) != "":
            return str(data[key])

        if not built:
            for k, v in data.items():
                norm_lookup.setdefault(_normalize_key(k), v)
            built = True

        hit = norm_lookup.get(_normalize_key(key))
        if hit is not None and str(hit) != "":
            return str(hit)

        return m.group(0)

    return PLACEHOLDER_RE.sub(_sub, text or "")


def find_unresolved_placeholders(text, data):
    rendered = safe_format(text, data)
    seen = []

    for m in PLACEHOLDER_RE.finditer(rendered):
        if m.group(1) not in seen:
            seen.append(m.group(1))

    return seen


def template_unresolved_fields(template, data):
    result = {}

    for elem in getattr(template, "elements", []):
        if getattr(elem, "type", None) != "text":
            continue

        missing = find_unresolved_placeholders(elem.content, data)
        if missing:
            result[elem.name] = missing

    return result


def _hex_to_rgb(hexcolor):
    hexcolor = (hexcolor or "#FFFFFF").lstrip("#")

    if len(hexcolor) != 6:
        hexcolor = "FFFFFF"

    return tuple(int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))


# ---------- 共享临时 Draw（避免每次测量都 new Image+Draw） ----------

_SHARED_DRAW_IMG = None
_SHARED_DRAW = None


def _shared_draw():
    global _SHARED_DRAW_IMG, _SHARED_DRAW

    if _SHARED_DRAW is None:
        _SHARED_DRAW_IMG = Image.new("RGBA", (4, 4))
        _SHARED_DRAW = ImageDraw.Draw(_SHARED_DRAW_IMG)

    return _SHARED_DRAW


# ---------- 字间距/行间距排版：测量与绘制共用一次 layout ----------

def _layout_lines(text, font, spacing, letter_spacing):
    lines = text.split("\n")
    line_widths = []
    line_heights = []

    for line in lines:
        if not line:
            dummy = font.getbbox("A")
            h = (dummy[3] - dummy[1]) if dummy else getattr(font, "size", 12)
            line_widths.append(0)
            line_heights.append(h)
            continue

        w = 0
        h = 0
        last = len(line) - 1

        for i, char in enumerate(line):
            cb = font.getbbox(char)
            ch = (cb[3] - cb[1]) if cb else getattr(font, "size", 12)

            if hasattr(font, "getlength"):
                advance = font.getlength(char)
            else:
                advance = (cb[2] - cb[0]) if cb else 10

            w += advance + (letter_spacing if i < last else 0)

            if ch > h:
                h = ch

        gb = font.getbbox(line)
        if gb:
            gh = gb[3] - gb[1]
            if gh > h:
                h = gh

        line_widths.append(w)
        line_heights.append(h)

    max_w = max(line_widths) if line_widths else 0
    total_h = sum(line_heights) + max(0, len(lines) - 1) * spacing

    return line_widths, line_heights, max_w, total_h


def custom_multiline_text_bbox(
    draw,
    xy,
    text,
    font,
    spacing=4,
    letter_spacing=0,
    stroke_width=0,
    align="left",
):
    letter_spacing = int(letter_spacing or 0)
    spacing = int(spacing if spacing is not None else 4)

    if letter_spacing == 0:
        return draw.multiline_textbbox(
            xy,
            text,
            font=font,
            spacing=spacing,
            stroke_width=stroke_width,
            align=align,
        )

    x_start, y_start = xy
    _, _, max_w, total_h = _layout_lines(text, font, spacing, letter_spacing)

    return (x_start, y_start, x_start + max_w, y_start + total_h)


def custom_draw_multiline_text(
    draw,
    xy,
    text,
    font,
    fill=None,
    spacing=4,
    letter_spacing=0,
    stroke_width=0,
    stroke_fill=None,
    align="left",
):
    letter_spacing = int(letter_spacing or 0)
    spacing = int(spacing if spacing is not None else 4)

    if letter_spacing == 0:
        draw.multiline_text(
            xy,
            text,
            font=font,
            fill=fill,
            spacing=spacing,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            align=align,
        )
        return

    x_start, y_start = xy
    line_widths, line_heights, max_w, _total_h = _layout_lines(
        text,
        font,
        spacing,
        letter_spacing,
    )

    lines = text.split("\n")
    cur_y = y_start

    for i, line in enumerate(lines):
        lw = line_widths[i]
        lh = line_heights[i]

        if align == "center":
            cur_x = x_start + (max_w - lw) / 2
        elif align == "right":
            cur_x = x_start + (max_w - lw)
        else:
            cur_x = x_start

        for char in line:
            draw.text(
                (cur_x, cur_y),
                char,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )

            if hasattr(font, "getlength"):
                advance = font.getlength(char)
            else:
                advance = 10

            cur_x += advance + letter_spacing

        cur_y += lh + spacing


def _text_bbox(text, font, line_spacing=4, letter_spacing=0):
    return custom_multiline_text_bbox(
        _shared_draw(),
        (0, 0),
        text,
        font=font,
        spacing=line_spacing,
        letter_spacing=letter_spacing,
    )


# ---------- 元素级图层缓存 ----------

class ElementLayerCache:
    """
    LRU 缓存：key=像素级外观哈希(tuple) -> 渲染好的透明图层。位置 x/y 不进 key。
    """

    def __init__(self, maxsize=256):
        self._d = OrderedDict()
        self._max = maxsize

    def get(self, key):
        v = self._d.get(key)
        if v is not None:
            self._d.move_to_end(key)
        return v

    def put(self, key, value):
        if key in self._d:
            self._d.move_to_end(key)

        self._d[key] = value

        if len(self._d) > self._max:
            self._d.popitem(last=False)

    def clear(self):
        self._d.clear()


_DEFAULT_LAYER_CACHE = ElementLayerCache()


def _cget(cache, key):
    return cache.get(key) if cache else None


def _cput(cache, key, value):
    if cache:
        cache.put(key, value)


# ---------- 元素 bbox / 手柄 ----------

def get_element_bbox(elem, image_size, data=None, font_manager=None):
    W, H = image_size
    x = round(elem.x * W)
    y = round(elem.y * H)

    if elem.type == "text":
        mode = getattr(elem, "mode", "single")

        if mode in ("tile", "diagonal"):
            r = max(10, round(H * 0.02))
            return (x - r, y - r, x + r, y + r)

        text = safe_format(elem.content, data) or " "
        font_size = max(6, round(elem.font_size_rel * H))

        font = (
            font_manager.get_font(elem.font_family, font_size)
            if font_manager
            else ImageFont.load_default()
        )

        line_spacing = int(getattr(elem, "line_spacing", 4))
        letter_spacing = int(getattr(elem, "letter_spacing", 0))

        bbox = _text_bbox(
            text,
            font,
            line_spacing=line_spacing,
            letter_spacing=letter_spacing,
        )

        sw = int(getattr(elem, "stroke_width", 0)) if getattr(elem, "stroke_enabled", False) else 0

        return (
            x + bbox[0] - sw,
            y + bbox[1] - sw,
            x + bbox[2] + sw,
            y + bbox[3] + sw,
        )

    elif elem.type in ("image", "shape"):
        w = max(1, round(elem.w_rel * W))
        h = max(1, round(elem.h_rel * H))
        return (x, y, x + w, y + h)

    return (x, y, x, y)


def get_image_resize_handle(elem, image_size):
    x0, y0, x1, y1 = get_element_bbox(elem, image_size)
    return (x1, y1)


# ---------- 阴影滤镜 ----------

def _shadow_blur_filter(radius, fast=False):
    return ImageFilter.BoxBlur(radius) if fast else ImageFilter.GaussianBlur(radius)


# ---------- 文字图层（含阴影/描边/加粗） ----------

def _draw_text_with_shadow(layer_size, text, font, elem, align="left", fast=False):
    stroke_width = int(getattr(elem, "stroke_width", 0)) if getattr(elem, "stroke_enabled", False) else 0
    sr, sg, sb = _hex_to_rgb(getattr(elem, "stroke_color", "#000000"))

    line_spacing = int(getattr(elem, "line_spacing", 4))
    letter_spacing = int(getattr(elem, "letter_spacing", 0))

    d = _shared_draw()

    bbox = custom_multiline_text_bbox(
        d,
        (0, 0),
        text,
        font=font,
        align=align,
        stroke_width=stroke_width,
        spacing=line_spacing,
        letter_spacing=letter_spacing,
    )

    shadow_on = bool(getattr(elem, "shadow_enabled", False)) and not fast
    blur = int(getattr(elem, "shadow_blur", 0)) if shadow_on else 0
    shadow_offset = getattr(elem, "shadow_offset", (0, 0))

    pad = max(4, blur + 4 + stroke_width)

    w = bbox[2] - bbox[0] + pad * 2 + abs(int(shadow_offset[0]))
    h = bbox[3] - bbox[1] + pad * 2 + abs(int(shadow_offset[1]))

    layer = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))

    ox, oy = pad - bbox[0], pad - bbox[1]

    if shadow_on:
        shadow_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)

        sx = ox + int(shadow_offset[0])
        sy = oy + int(shadow_offset[1])

        r, g, b = _hex_to_rgb(getattr(elem, "shadow_color", "#000000"))
        alpha = max(0, min(255, round(float(getattr(elem, "shadow_opacity", 0.0)) * 255)))

        custom_draw_multiline_text(
            sd,
            (sx, sy),
            text,
            font=font,
            fill=(r, g, b, alpha),
            align=align,
            spacing=line_spacing,
            letter_spacing=letter_spacing,
        )

        if blur > 0:
            shadow_layer = shadow_layer.filter(_shadow_blur_filter(blur, fast=fast))

        layer.alpha_composite(shadow_layer)

    text_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)

    r, g, b = _hex_to_rgb(elem.color)
    fill = (r, g, b, 255)
    stroke_fill = (sr, sg, sb, 255)

    bold = bool(getattr(elem, "bold", False))

    if bold and not fast:
        passes = ((0, 0), (1, 0), (0, 1), (1, 1))
    elif bold and fast:
        passes = ((0, 0), (1, 1))
    else:
        passes = ((0, 0),)

    for dx, dy in passes:
        custom_draw_multiline_text(
            td,
            (ox + dx, oy + dy),
            text,
            font=font,
            fill=fill,
            align=align,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            spacing=line_spacing,
            letter_spacing=letter_spacing,
        )

    layer.alpha_composite(text_layer)

    return layer, int(ox), int(oy)


def _text_layer_key(elem, text, font_size, fast):
    return (
        "T",
        elem.id,
        text,
        elem.font_family,
        int(font_size),
        elem.color,
        bool(getattr(elem, "bold", False)),
        getattr(elem, "align", "left"),
        int(getattr(elem, "letter_spacing", 0)),
        int(getattr(elem, "line_spacing", 4)),
        bool(getattr(elem, "stroke_enabled", False)),
        getattr(elem, "stroke_color", "#000000"),
        int(getattr(elem, "stroke_width", 0)),
        bool(getattr(elem, "shadow_enabled", False)),
        getattr(elem, "shadow_color", "#000000"),
        tuple(getattr(elem, "shadow_offset", (0, 0))),
        int(getattr(elem, "shadow_blur", 0)),
        round(float(getattr(elem, "shadow_opacity", 0.0)), 3),
        bool(fast),
    )


def render_text_element(base, elem, data, font_manager, fast=False, cache=None):
    text = safe_format(elem.content, data)

    if not text.strip():
        return

    W, H = base.size
    font_size = max(6, round(elem.font_size_rel * H))

    font = (
        font_manager.get_font(elem.font_family, font_size)
        if font_manager
        else ImageFont.load_default()
    )

    mode = getattr(elem, "mode", "single")

    if mode == "single":
        x = round(elem.x * W)
        y = round(elem.y * H)

        key = _text_layer_key(elem, text, font_size, fast)
        hit = _cget(cache, key)

        if hit is not None:
            stamp, ox, oy = hit
        else:
            stamp, ox, oy = _draw_text_with_shadow(
                base.size,
                text,
                font,
                elem,
                align=getattr(elem, "align", "left"),
                fast=fast,
            )
            _cput(cache, key, (stamp, ox, oy))

        base.alpha_composite(stamp, (x - ox, y - oy))
        return

    key = _text_layer_key(elem, text, font_size, fast)
    hit = _cget(cache, key)

    if hit is not None:
        stamp, _ox, _oy = hit
    else:
        stamp, _ox, _oy = _draw_text_with_shadow(
            base.size,
            text,
            font,
            elem,
            align="left",
            fast=fast,
        )
        _cput(cache, key, (stamp, _ox, _oy))

    angle = float(getattr(elem, "tile_angle", 0) or 0)

    if mode == "diagonal" and not angle:
        angle = -math.degrees(math.atan2(H, W))

    if angle:
        stamp = stamp.rotate(
            angle,
            expand=True,
            resample=Image.NEAREST if fast else Image.BICUBIC,
        )

    sw, sh = stamp.size

    if mode == "diagonal":
        cx, cy = round(elem.x * W), round(elem.y * H)
        base.alpha_composite(stamp, (cx - sw // 2, cy - sh // 2))
        return

    spacing_x = max(1, round(getattr(elem, "tile_spacing_x", 0.30) * W)) + sw
    spacing_y = max(1, round(getattr(elem, "tile_spacing_y", 0.18) * H)) + sh

    start_x = round(elem.x * W) % spacing_x - spacing_x
    start_y = round(elem.y * H) % spacing_y - spacing_y

    row = 0
    y = start_y

    while y < H + sh:
        row_offset = (spacing_x // 2) if (row % 2) else 0
        x = start_x - row_offset

        while x < W + sw:
            base.alpha_composite(stamp, (x, y))
            x += spacing_x

        y += spacing_y
        row += 1


# ---------- 形状图层 ----------

def _shape_layer_key(elem, w, h, fast):
    return (
        "S",
        elem.id,
        getattr(elem, "shape", "rect"),
        int(w),
        int(h),
        getattr(elem, "fill_color", "#FFFFFF"),
        round(float(getattr(elem, "fill_opacity", 1.0)), 3),
        bool(getattr(elem, "stroke_enabled", False)),
        getattr(elem, "stroke_color", "#FFFFFF"),
        int(getattr(elem, "stroke_width", 0)),
        int(getattr(elem, "corner_radius", 0)),
        round(float(getattr(elem, "rotation", 0) or 0), 2),
        bool(getattr(elem, "shadow_enabled", False)),
        getattr(elem, "shadow_color", "#000000"),
        tuple(getattr(elem, "shadow_offset", (0, 0))),
        int(getattr(elem, "shadow_blur", 0)),
        round(float(getattr(elem, "shadow_opacity", 0.0)), 3),
        bool(fast),
    )


def render_shape_element(base, elem, fast=False, cache=None):
    W, H = base.size

    x = round(elem.x * W)
    y = round(elem.y * H)
    w = max(1, round(elem.w_rel * W))
    h = max(1, round(elem.h_rel * H))

    key = _shape_layer_key(elem, w, h, fast)
    hit = _cget(cache, key)

    if hit is not None:
        layer, lw, lh = hit
    else:
        layer, lw, lh = _build_shape_layer(elem, w, h, fast)
        _cput(cache, key, (layer, lw, lh))

    paste_x = round(x + w / 2 - lw / 2)
    paste_y = round(y + h / 2 - lh / 2)

    base.alpha_composite(layer, (int(paste_x), int(paste_y)))


def _build_shape_layer(elem, w, h, fast):
    fr, fg, fb = _hex_to_rgb(getattr(elem, "fill_color", "#FFFFFF"))
    falpha = max(0, min(255, round(float(getattr(elem, "fill_opacity", 1.0)) * 255)))

    stroke_enabled = bool(getattr(elem, "stroke_enabled", False))
    stroke_w = int(getattr(elem, "stroke_width", 0)) if stroke_enabled else 0

    sr, sg, sb = _hex_to_rgb(getattr(elem, "stroke_color", "#FFFFFF"))
    outline = (sr, sg, sb, 255) if stroke_w else None

    shape = getattr(elem, "shape", "rect")

    # 交互 fast 时跳过阴影模糊，避免拖拽/缩放带阴影形状时每帧跑高斯模糊造成卡顿
    shadow_on = bool(getattr(elem, "shadow_enabled", False)) and not fast
    shadow_blur = int(getattr(elem, "shadow_blur", 0)) if shadow_on else 0
    shadow_offset = getattr(elem, "shadow_offset", (0, 0)) if shadow_on else (0, 0)

    pad = stroke_w + 2 + shadow_blur + max(
        abs(int(shadow_offset[0])),
        abs(int(shadow_offset[1])),
    )

    def _draw_shape(d, ox, oy, fill, outline_color, outline_w):
        box = [ox, oy, ox + w, oy + h]

        if shape == "ellipse":
            d.ellipse(box, fill=fill, outline=outline_color, width=outline_w)

        elif shape == "triangle":
            pts = [(ox + w / 2, oy), (ox + w, oy + h), (ox, oy + h)]
            d.polygon(pts, fill=fill)

            if outline_w:
                d.line(pts + [pts[0]], fill=outline_color, width=outline_w, joint="curve")

        else:
            radius = max(0, int(getattr(elem, "corner_radius", 0)))

            if radius > 0:
                d.rounded_rectangle(
                    box,
                    radius=min(radius, min(w, h) // 2 or 1),
                    fill=fill,
                    outline=outline_color,
                    width=outline_w,
                )
            else:
                d.rectangle(box, fill=fill, outline=outline_color, width=outline_w)

    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    if shadow_on:
        shadow_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        shd = ImageDraw.Draw(shadow_layer)

        shr, shg, shb = _hex_to_rgb(getattr(elem, "shadow_color", "#000000"))
        shalpha = max(0, min(255, round(float(getattr(elem, "shadow_opacity", 0.0)) * 255)))

        _draw_shape(
            shd,
            pad + int(shadow_offset[0]),
            pad + int(shadow_offset[1]),
            fill=(shr, shg, shb, shalpha),
            outline_color=None,
            outline_w=0,
        )

        if shadow_blur > 0:
            shadow_layer = shadow_layer.filter(_shadow_blur_filter(shadow_blur, fast=fast))

        layer.alpha_composite(shadow_layer)

    d = ImageDraw.Draw(layer)

    _draw_shape(
        d,
        pad,
        pad,
        fill=(fr, fg, fb, falpha),
        outline_color=outline,
        outline_w=stroke_w,
    )

    rotation = float(getattr(elem, "rotation", 0) or 0)

    if rotation:
        layer = layer.rotate(
            -rotation,
            expand=True,
            resample=Image.NEAREST if fast else Image.BICUBIC,
        )

    lw, lh = layer.size

    return layer, lw, lh


# ---------- 图标 ----------

_ICON_SRC_CACHE = {}
_ICON_SRC_MAX = 64


def _load_icon_source(path):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None, 0

    cached = _ICON_SRC_CACHE.get(path)

    if cached is not None and cached[0] == mtime:
        return cached[1], mtime

    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        return None, mtime

    if len(_ICON_SRC_CACHE) >= _ICON_SRC_MAX:
        _ICON_SRC_CACHE.pop(next(iter(_ICON_SRC_CACHE)))

    _ICON_SRC_CACHE[path] = (mtime, img)

    return img, mtime


def _image_layer_key(elem, path, mtime, w, h, fast):
    return (
        "I",
        elem.id,
        path,
        mtime,
        int(w),
        int(h),
        round(float(getattr(elem, "opacity", 1.0)), 3),
        bool(fast),
    )


def render_image_element(base, elem, asset_root=None, fast=False, cache=None):
    if not elem.path:
        return

    path = elem.path

    if asset_root and not os.path.isabs(path):
        path = os.path.join(asset_root, path)

    if not os.path.exists(path):
        return

    W, H = base.size
    w = max(1, round(elem.w_rel * W))
    h = max(1, round(elem.h_rel * H))

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return

    key = _image_layer_key(elem, path, mtime, w, h, fast)
    hit = _cget(cache, key)

    if hit is not None:
        icon = hit
    else:
        src, _src_mtime = _load_icon_source(path)

        if src is None:
            return

        resample = Image.BILINEAR if fast else Image.LANCZOS

        try:
            icon = src.resize((w, h), resample)
        except Exception:
            return

        opacity = float(getattr(elem, "opacity", 1.0))

        if opacity < 1.0:
            a = icon.split()[3].point(
                lambda p, o=opacity: int(p * max(0.0, min(1.0, o)))
            )
            icon.putalpha(a)

        _cput(cache, key, icon)

    x = round(elem.x * W)
    y = round(elem.y * H)

    base.alpha_composite(icon, (x, y))


# ---------- 底图 RGBA 缓存 ----------

_BASE_RGBA_SLOT = [None, None]


def _get_base_rgba(image):
    if _BASE_RGBA_SLOT[0] is image and _BASE_RGBA_SLOT[1] is not None:
        return _BASE_RGBA_SLOT[1]

    rgba = image.convert("RGBA")

    _BASE_RGBA_SLOT[0] = image
    _BASE_RGBA_SLOT[1] = rgba

    return rgba


def render_template(
    image,
    template,
    data=None,
    font_manager=None,
    asset_root=None,
    fast=False,
    layer_cache=None,
):
    """
    fast=True 用于交互实时预览；交互结束后应再用 fast=False 重绘拿最终效果。

    layer_cache：
        None = 模块级默认缓存；
        ElementLayerCache 实例 = 用它；
        False = 禁用缓存。

    导出请传 layer_cache=False，确保与预览缓存隔离、画质逐像素全质量。
    """
    data = data or {}

    if layer_cache is None:
        cache = _DEFAULT_LAYER_CACHE
    elif layer_cache is False:
        cache = None
    else:
        cache = layer_cache

    base = _get_base_rgba(image).copy()

    for elem in template.elements:
        if elem.type == "text":
            render_text_element(base, elem, data, font_manager, fast=fast, cache=cache)
        elif elem.type == "image":
            render_image_element(base, elem, asset_root, fast=fast, cache=cache)
        elif elem.type == "shape":
            render_shape_element(base, elem, fast=fast, cache=cache)

    return base.convert("RGB")