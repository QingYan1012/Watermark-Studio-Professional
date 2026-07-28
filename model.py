# -*- coding: utf-8 -*-
"""
模板数据模型。

一个模板(Template) = 若干元素(TextElement / ImageElement / ShapeElement)的列表。
所有位置/尺寸都用【相对坐标 0~1】保存（相对于图片宽高）。
"""

import json
import uuid


class TextElement:
    type = "text"

    def __init__(
        self,
        content="龙山铜多金属矿{钻孔编号}\n\n箱 数：{箱数}箱\n孔 深：{孔深起}-{孔深止}m",
        x=0.28,
        y=0.18,
        font_family="微软雅黑",
        font_size_rel=0.055,
        color="#FFFFFF",
        bold=True,
        stroke_enabled=False,
        stroke_color="#000000",
        stroke_width=2,
        shadow_enabled=True,
        shadow_color="#000000",
        shadow_offset=(2, 3),
        shadow_blur=3,
        shadow_opacity=0.65,
        mode="single",
        tile_spacing_x=0.30,
        tile_spacing_y=0.18,
        tile_angle=0,
        align="left",
        letter_spacing=0,
        line_spacing=4,
        elem_id=None,
        name=None,
    ):
        self.id = elem_id or uuid.uuid4().hex[:8]
        self.name = name or "文字"
        self.content = content
        self.x = float(x)
        self.y = float(y)
        self.font_family = font_family
        self.font_size_rel = float(font_size_rel)
        self.color = color
        self.bold = bool(bold)
        self.stroke_enabled = bool(stroke_enabled)
        self.stroke_color = stroke_color
        self.stroke_width = int(stroke_width)
        self.shadow_enabled = bool(shadow_enabled)
        self.shadow_color = shadow_color
        self.shadow_offset = tuple(shadow_offset)
        self.shadow_blur = int(shadow_blur)
        self.shadow_opacity = float(shadow_opacity)
        self.mode = mode if mode in ("single", "tile", "diagonal") else "single"
        self.tile_spacing_x = float(tile_spacing_x)
        self.tile_spacing_y = float(tile_spacing_y)
        self.tile_angle = float(tile_angle)
        self.align = align if align in ("left", "center", "right") else "left"
        self.letter_spacing = int(letter_spacing)
        self.line_spacing = int(line_spacing)

    def to_dict(self):
        d = dict(self.__dict__)
        d["type"] = self.type
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.pop("type", None)
        elem_id = d.pop("id", None)
        name = d.pop("name", None)
        return cls(elem_id=elem_id, name=name, **d)


class ImageElement:
    type = "image"

    def __init__(
        self,
        path="",
        x=0.06,
        y=0.15,
        w_rel=0.09,
        h_rel=0.11,
        opacity=1.0,
        elem_id=None,
        name=None,
    ):
        self.id = elem_id or uuid.uuid4().hex[:8]
        self.name = name or "图标"
        self.path = path
        self.x = float(x)
        self.y = float(y)
        self.w_rel = float(w_rel)
        self.h_rel = float(h_rel)
        self.opacity = float(opacity)

    def to_dict(self):
        d = dict(self.__dict__)
        d["type"] = self.type
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.pop("type", None)
        elem_id = d.pop("id", None)
        name = d.pop("name", None)
        return cls(elem_id=elem_id, name=name, **d)


class ShapeElement:
    type = "shape"

    def __init__(
        self,
        shape="rect",
        x=0.06,
        y=0.15,
        w_rel=0.12,
        h_rel=0.06,
        fill_color="#E53935",
        fill_opacity=1.0,
        stroke_enabled=False,
        stroke_color="#FFFFFF",
        stroke_width=2,
        corner_radius=0,
        rotation=0,
        shadow_enabled=False,
        shadow_color="#000000",
        shadow_offset=(2, 3),
        shadow_blur=4,
        shadow_opacity=0.6,
        elem_id=None,
        name=None,
    ):
        self.id = elem_id or uuid.uuid4().hex[:8]
        self.name = name or "形状"
        self.shape = shape if shape in ("rect", "ellipse", "triangle") else "rect"
        self.x = float(x)
        self.y = float(y)
        self.w_rel = float(w_rel)
        self.h_rel = float(h_rel)
        self.fill_color = fill_color
        self.fill_opacity = float(fill_opacity)
        self.stroke_enabled = bool(stroke_enabled)
        self.stroke_color = stroke_color
        self.stroke_width = int(stroke_width)
        self.corner_radius = int(corner_radius)
        self.rotation = float(rotation)
        self.shadow_enabled = bool(shadow_enabled)
        self.shadow_color = shadow_color
        self.shadow_offset = tuple(shadow_offset)
        self.shadow_blur = int(shadow_blur)
        self.shadow_opacity = float(shadow_opacity)

    def to_dict(self):
        d = dict(self.__dict__)
        d["type"] = self.type
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        d.pop("type", None)
        elem_id = d.pop("id", None)
        name = d.pop("name", None)
        return cls(elem_id=elem_id, name=name, **d)


class Template:
    def __init__(self, name="未命名模板", elements=None):
        self.name = name
        self.elements = elements if elements is not None else []

    def add(self, element):
        self.elements.append(element)
        return element

    def remove(self, elem_id):
        self.elements = [e for e in self.elements if e.id != elem_id]

    def find(self, elem_id):
        for e in self.elements:
            if e.id == elem_id:
                return e
        return None

    def move_z(self, elem_id, delta):
        idx = next((i for i, e in enumerate(self.elements) if e.id == elem_id), None)
        if idx is None:
            return

        new_idx = max(0, min(len(self.elements) - 1, idx + delta))
        if new_idx != idx:
            self.elements.insert(new_idx, self.elements.pop(idx))

    def to_dict(self):
        return {
            "name": self.name,
            "elements": [e.to_dict() for e in self.elements],
        }

    @classmethod
    def from_dict(cls, d):
        elems = []

        for ed in d.get("elements", []):
            elem_type = ed.get("type")

            if elem_type == "text":
                elems.append(TextElement.from_dict(ed))
            elif elem_type == "image":
                elems.append(ImageElement.from_dict(ed))
            elif elem_type == "shape":
                elems.append(ShapeElement.from_dict(ed))

        return cls(name=d.get("name", "未命名模板"), elements=elems)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def default(cls):
        t = cls(name="岩心箱标注")
        t.add(
            ImageElement(
                path="",
                x=0.06,
                y=0.15,
                w_rel=0.09,
                h_rel=0.11,
                opacity=1.0,
                name="色块/图标",
            )
        )
        t.add(TextElement(name="标注文字"))
        return t