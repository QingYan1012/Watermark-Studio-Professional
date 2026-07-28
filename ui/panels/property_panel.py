# -*- coding: utf-8 -*-
"""属性面板填充逻辑（从 legacy App._refresh_property_panel + 4 辅助 物理搬迁，第47轮）。

搬肉(1544-1778) + 4 辅助(_contrast_color/_add_float_entry/_add_numeric_row/_add_slider_row)，
全部转成模块函数：self->app；辅助方法在模块内直接互调(不走 app)；唯一定义留在 App 上的
_redraw_canvas / _request_redraw 写 app.xxx()，运行时解析（后者还解析到 performance_patch
的节流版，行为一致）。自递归 self._refresh_property_panel() -> refresh_property_panel(app)，
闭包在回调时触发，模块名已绑定，安全。

依赖闭合（取证确认）：4 辅助体内 self 调用仅 _redraw_canvas/_request_redraw(运行时解析,不搬)
+ 互调；无第三层隐藏依赖。外部 import：StringVar/colorchooser/filedialog/SearchableCombobox/T/ctk。
SearchableCombobox 走 ui/widgets，类变量 _open_instance 与主界面共享（右面板轮已验证）。

撤销不断链：属性改值后调 _redraw_canvas，撤销“记录”由 performance_patch 第12轮接管的 observe
在 redraw 后比对模板指纹自动入栈——靠 redraw 副作用，不靠属性面板显式 push，故搬肉不碰撤销逻辑。
上游 _select_element(legacy) 调 self._refresh_property_panel() 运行时解析到桥接覆盖版，不断。
"""
import customtkinter as ctk

from tkinter import StringVar, colorchooser, filedialog

from ..theme import T
from ..widgets.searchable_combobox import SearchableCombobox


def _contrast_color(hexcolor):
    try:
        hexcolor = hexcolor.lstrip("#")
        r, g, b = (int(hexcolor[i:i + 2], 16) for i in (0, 2, 4))
        return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 > 150 else "#FFFFFF"
    except Exception:
        return "#FFFFFF"


def _add_float_entry(app, elem, attr, lo, hi):
    var = StringVar(value=str(round(getattr(elem, attr), 4)))
    app._live_attr_vars[attr] = var

    def on_change(_e=None):
        try:
            val = max(lo, min(hi, float(var.get())))
            setattr(elem, attr, val)
            app._redraw_canvas()
        except ValueError:
            pass

    entry = ctk.CTkEntry(app.prop_container, textvariable=var, font=app.ui_font)
    entry.pack(fill="x", pady=2)
    entry.bind("<KeyRelease>", on_change)


def _add_numeric_row(app, text, elem, attr, index, is_offset=False):
    ctk.CTkLabel(app.prop_container, text=text, anchor="w", justify="left",
                 wraplength=max(140, app.right_w - 45),
                 text_color=T("text_mid"), font=app.ui_font).pack(fill="x", pady=(6, 0))
    current = getattr(elem, attr)
    var = StringVar(value=str(current[index] if is_offset else current))

    def on_change(_e=None):
        try:
            val = float(var.get())
            if is_offset:
                lst = list(getattr(elem, attr))
                lst[index] = val
                setattr(elem, attr, tuple(lst))
            else:
                setattr(elem, attr, val)
            app._redraw_canvas()
        except ValueError:
            pass

    entry = ctk.CTkEntry(app.prop_container, textvariable=var, font=app.ui_font)
    entry.pack(fill="x", pady=2)
    entry.bind("<KeyRelease>", on_change)


def _add_slider_row(app, text, elem, attr, lo, hi):
    ctk.CTkLabel(app.prop_container, text=f"{text}：{getattr(elem, attr)}", anchor="w", justify="left",
                 wraplength=max(140, app.right_w - 45),
                 text_color=T("text_mid"), font=app.ui_font).pack(fill="x", pady=(6, 0))
    lbl = app.prop_container.winfo_children()[-1]

    def on_move(v):
        setattr(elem, attr, v if isinstance(getattr(elem, attr), float) else int(v))
        lbl.configure(text=f"{text}：{round(getattr(elem, attr), 2)}")
        app._request_redraw()

    slider = ctk.CTkSlider(app.prop_container, from_=lo, to=hi, command=on_move,
                           progress_color=T("accent"), button_color=T("accent"), button_hover_color=T("accent_h"))
    slider.set(getattr(elem, attr))
    slider.pack(fill="x", pady=2)


def refresh_property_panel(app):
    if SearchableCombobox._open_instance is not None:
        SearchableCombobox._open_instance._close_popup()
    app._live_attr_vars = {}
    for w in app.prop_container.winfo_children():
        w.destroy()
    elem = app.template.find(app.selected_elem_id) if app.selected_elem_id else None
    if elem is None:
        ctk.CTkLabel(app.prop_container, text="未选中元素", text_color=T("text_dim"), font=app.ui_font).pack(pady=20)
        return

    def label(text):
        ctk.CTkLabel(app.prop_container, text=text, anchor="w", justify="left",
                     wraplength=max(140, app.right_w - 45),
                     text_color=T("text_mid"), font=app.ui_font).pack(fill="x", pady=(8, 0))

    if elem.type == "text":
        label("水印模式")
        mode_labels = {"single": "单个（可拖拽定位）", "tile": "平铺满图", "diagonal": "单条对角线"}
        mode_rev = {v: k for k, v in mode_labels.items()}
        mode_var = StringVar(value=mode_labels.get(elem.mode, mode_labels["single"]))

        def on_mode_change(v):
            elem.mode = mode_rev.get(v, "single")
            app._redraw_canvas()
            refresh_property_panel(app)

        ctk.CTkOptionMenu(app.prop_container, values=list(mode_labels.values()), variable=mode_var,
                          font=app.ui_font, command=on_mode_change).pack(fill="x", pady=2)
        label("文字内容（支持 {字段名} 占位符）")
        box = ctk.CTkTextbox(app.prop_container, height=90, font=app.ui_font)
        box.pack(fill="x", pady=2)
        box.insert("1.0", elem.content)

        def on_content_change(_e=None):
            elem.content = box.get("1.0", "end-1c")
            app._redraw_canvas()

        box.bind("<KeyRelease>", on_content_change)

        # 【第52轮】插入变量：系统变量 + 数据表字段，选中即插入文字光标处。
        # 让系统变量“用得上、可发现”——不用记中文花括号语法、不用手动打，
        # 也顺带列出数据表字段，缓解“不知道该填什么字段”的困惑。
        try:
            from ..services.system_vars import known_system_vars
            _sys_names = ["{%s}" % n for n in known_system_vars()]
        except Exception:
            _sys_names = []
        _field_names = ["{%s}" % c for c in (getattr(app, "_data_columns", None) or [])]
        _var_options = ["插入变量…"] + _sys_names + _field_names
        _insert_var = StringVar(value="插入变量…")

        def on_insert_var(v):
            if v and v != "插入变量…":
                try:
                    box.insert("insert", v)                 # 插到光标处
                    elem.content = box.get("1.0", "end-1c")
                    app._redraw_canvas()
                except Exception:
                    pass
            _insert_var.set("插入变量…")                    # 复位，方便连续插入

        ctk.CTkOptionMenu(app.prop_container, values=_var_options, variable=_insert_var,
                          font=app.ui_font, command=on_insert_var).pack(fill="x", pady=(2, 2))

        box.bind("<KeyRelease>", on_content_change)
        if app._data_columns:
            hint = "可用字段：" + "、".join("{%s}" % c for c in app._data_columns)
            ctk.CTkLabel(app.prop_container, text=hint, text_color=T("text_dim"),
                         wraplength=max(140, app.right_w - 45), justify="left", font=app.ui_small).pack(fill="x")
        if elem.mode == "single":
            label("对齐方式")
            align_labels = {"left": "左对齐", "center": "居中", "right": "右对齐"}
            align_rev = {v: k for k, v in align_labels.items()}
            align_var = StringVar(value=align_labels.get(elem.align, "左对齐"))

            def on_align_change(v):
                elem.align = align_rev.get(v, "left")
                app._redraw_canvas()

            ctk.CTkOptionMenu(app.prop_container, values=list(align_labels.values()), variable=align_var,
                              font=app.ui_font, command=on_align_change).pack(fill="x", pady=2)
        label("字体（可打字搜索，支持滚轮翻页）")
        font_names = app.font_manager.family_names() or ["微软雅黑", "黑体", "宋体"]
        resolved = app.font_manager.resolve(elem.font_family)
        if resolved and resolved != elem.font_family:
            elem.font_family = resolved
        font_missing = elem.font_family and resolved is None
        combo = SearchableCombobox(app.prop_container, values=font_names, list_font=app.list_font,
                                   command=lambda v: (setattr(elem, "font_family", v), app._redraw_canvas()))
        if resolved:
            combo.set(resolved)
        elif elem.font_family:
            combo.set(elem.font_family)
        else:
            combo.set(font_names[0])
        combo.pack(fill="x", pady=2)
        if font_missing:
            ctk.CTkLabel(app.prop_container,
                         text=f"⚠ 本机未找到字体「{elem.font_family}」，导出时会回退为默认字体，请重新选择",
                         text_color=T("warn"), wraplength=max(140, app.right_w - 45),
                         justify="left", font=app.ui_small).pack(fill="x", pady=(2, 4))
        label("字号（相对当前预览图高度比例）")
        size_var = StringVar(value=str(round(elem.font_size_rel * 1000)))

        def on_size_change(_e=None):
            try:
                elem.font_size_rel = max(1, float(size_var.get())) / 1000.0
            except ValueError:
                pass
            app._redraw_canvas()

        size_entry = ctk.CTkEntry(app.prop_container, textvariable=size_var, font=app.ui_font)
        size_entry.pack(fill="x", pady=2)
        size_entry.bind("<KeyRelease>", on_size_change)
        _add_slider_row(app, "字间距(像素)", elem, "letter_spacing", 0, 50)
        _add_slider_row(app, "行间距(像素)", elem, "line_spacing", 0, 50)

        def pick_color():
            rgb, hexcode = colorchooser.askcolor(color=elem.color, title="选择文字颜色")
            if hexcode:
                elem.color = hexcode
                app._redraw_canvas()
                refresh_property_panel(app)

        ctk.CTkButton(app.prop_container, text=f"文字颜色 {elem.color}", command=pick_color,
                      fg_color=elem.color, text_color=_contrast_color(elem.color), font=app.ui_font).pack(fill="x", pady=(8, 2))
        bold_var = ctk.BooleanVar(value=elem.bold)

        def on_bold_toggle():
            elem.bold = bold_var.get()
            app._redraw_canvas()

        ctk.CTkCheckBox(app.prop_container, text="加粗", variable=bold_var, font=app.ui_font, command=on_bold_toggle).pack(anchor="w", pady=(6, 2))
        stroke_var = ctk.BooleanVar(value=getattr(elem, "stroke_enabled", False))

        def on_stroke_toggle():
            elem.stroke_enabled = stroke_var.get()
            app._redraw_canvas()

        ctk.CTkCheckBox(app.prop_container, text="启用描边", variable=stroke_var, font=app.ui_font, command=on_stroke_toggle).pack(anchor="w", pady=(10, 2))

        def pick_stroke_color():
            rgb, hexcode = colorchooser.askcolor(color=elem.stroke_color, title="选择描边颜色")
            if hexcode:
                elem.stroke_color = hexcode
                app._redraw_canvas()
                refresh_property_panel(app)

        ctk.CTkButton(app.prop_container, text=f"描边颜色 {elem.stroke_color}", command=pick_stroke_color,
                      fg_color=elem.stroke_color, text_color=_contrast_color(elem.stroke_color), font=app.ui_font).pack(fill="x", pady=2)
        _add_slider_row(app, "描边宽度(像素)", elem, "stroke_width", 0, 10)
        shadow_var = ctk.BooleanVar(value=elem.shadow_enabled)

        def on_shadow_toggle():
            elem.shadow_enabled = shadow_var.get()
            app._redraw_canvas()

        ctk.CTkCheckBox(app.prop_container, text="启用阴影", variable=shadow_var, font=app.ui_font, command=on_shadow_toggle).pack(anchor="w", pady=(10, 2))

        def pick_shadow_color():
            rgb, hexcode = colorchooser.askcolor(color=elem.shadow_color, title="选择阴影颜色")
            if hexcode:
                elem.shadow_color = hexcode
                app._redraw_canvas()
                refresh_property_panel(app)

        ctk.CTkButton(app.prop_container, text=f"阴影颜色 {elem.shadow_color}", command=pick_shadow_color,
                      fg_color=elem.shadow_color, text_color=_contrast_color(elem.shadow_color), font=app.ui_font).pack(fill="x", pady=2)
        _add_numeric_row(app, "阴影X偏移", elem, "shadow_offset", 0, is_offset=True)
        _add_numeric_row(app, "阴影Y偏移", elem, "shadow_offset", 1, is_offset=True)
        _add_slider_row(app, "阴影模糊半径", elem, "shadow_blur", 0, 20)
        _add_slider_row(app, "阴影不透明度", elem, "shadow_opacity", 0.0, 1.0)
        if elem.mode in ("tile", "diagonal"):
            label("旋转角度（度）")
            _add_float_entry(app, elem, "tile_angle", -180.0, 180.0)
        if elem.mode == "tile":
            label("水平间距")
            _add_float_entry(app, elem, "tile_spacing_x", 0.0, 1.0)
            label("垂直间距")
            _add_float_entry(app, elem, "tile_spacing_y", 0.0, 1.0)
    elif elem.type == "image":
        label("图片路径")
        path_var = StringVar(value=elem.path)
        path_entry = ctk.CTkEntry(app.prop_container, textvariable=path_var, font=app.ui_font)
        path_entry.pack(fill="x", pady=2)

        def browse():
            p = filedialog.askopenfilename(title="选择图标/色块图片",
                                           filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")])
            if p:
                elem.path = p
                path_var.set(p)
                app._redraw_canvas()

        ctk.CTkButton(app.prop_container, text="浏览…", fg_color=T("panel3"), text_color=T("text"),
                      hover_color=T("border2"), font=app.ui_font, command=browse).pack(fill="x", pady=2)
        label("宽度比例（0~1）")
        _add_float_entry(app, elem, "w_rel", 0.001, 1.0)
        label("高度比例（0~1）")
        _add_float_entry(app, elem, "h_rel", 0.001, 1.0)
        label("不透明度")
        _add_slider_row(app, "不透明度", elem, "opacity", 0.0, 1.0)
    elif elem.type == "shape":
        label("形状")
        shape_labels = {"rect": "矩形/圆角矩形", "ellipse": "圆 / 椭圆", "triangle": "三角形"}
        shape_rev = {v: k for k, v in shape_labels.items()}
        shape_var = StringVar(value=shape_labels.get(elem.shape, "矩形/圆角矩形"))

        def on_shape_change(v):
            elem.shape = shape_rev.get(v, "rect")
            app._redraw_canvas()
            refresh_property_panel(app)

        ctk.CTkOptionMenu(app.prop_container, values=list(shape_labels.values()), variable=shape_var,
                          font=app.ui_font, command=on_shape_change).pack(fill="x", pady=2)

        def pick_fill_color():
            rgb, hexcode = colorchooser.askcolor(color=elem.fill_color, title="选择填充颜色")
            if hexcode:
                elem.fill_color = hexcode
                app._redraw_canvas()
                refresh_property_panel(app)

        ctk.CTkButton(app.prop_container, text=f"填充颜色 {elem.fill_color}", command=pick_fill_color,
                      fg_color=elem.fill_color, text_color=_contrast_color(elem.fill_color), font=app.ui_font).pack(fill="x", pady=(8, 2))
        _add_slider_row(app, "填充不透明度", elem, "fill_opacity", 0.0, 1.0)
        if elem.shape == "rect":
            _add_slider_row(app, "圆角半径(像素)", elem, "corner_radius", 0, 200)
        stroke_var = ctk.BooleanVar(value=getattr(elem, "stroke_enabled", False))

        def on_stroke_toggle():
            elem.stroke_enabled = stroke_var.get()
            app._redraw_canvas()

        ctk.CTkCheckBox(app.prop_container, text="启用描边", variable=stroke_var, font=app.ui_font, command=on_stroke_toggle).pack(anchor="w", pady=(10, 2))

        def pick_stroke_color():
            rgb, hexcode = colorchooser.askcolor(color=elem.stroke_color, title="选择描边颜色")
            if hexcode:
                elem.stroke_color = hexcode
                app._redraw_canvas()
                refresh_property_panel(app)

        ctk.CTkButton(app.prop_container, text=f"描边颜色 {elem.stroke_color}", command=pick_stroke_color,
                      fg_color=elem.stroke_color, text_color=_contrast_color(elem.stroke_color), font=app.ui_font).pack(fill="x", pady=2)
        _add_slider_row(app, "描边宽度(像素)", elem, "stroke_width", 0, 20)
        shadow_var = ctk.BooleanVar(value=getattr(elem, "shadow_enabled", False))

        def on_shadow_toggle():
            elem.shadow_enabled = shadow_var.get()
            app._redraw_canvas()

        ctk.CTkCheckBox(app.prop_container, text="启用阴影", variable=shadow_var, font=app.ui_font, command=on_shadow_toggle).pack(anchor="w", pady=(10, 2))

        def pick_shadow_color():
            rgb, hexcode = colorchooser.askcolor(color=elem.shadow_color, title="选择阴影颜色")
            if hexcode:
                elem.shadow_color = hexcode
                app._redraw_canvas()
                refresh_property_panel(app)

        ctk.CTkButton(app.prop_container, text=f"阴影颜色 {elem.shadow_color}", command=pick_shadow_color,
                      fg_color=elem.shadow_color, text_color=_contrast_color(elem.shadow_color), font=app.ui_font).pack(fill="x", pady=2)
        _add_numeric_row(app, "阴影X偏移", elem, "shadow_offset", 0, is_offset=True)
        _add_numeric_row(app, "阴影Y偏移", elem, "shadow_offset", 1, is_offset=True)
        _add_slider_row(app, "阴影模糊半径", elem, "shadow_blur", 0, 20)
        _add_slider_row(app, "阴影不透明度", elem, "shadow_opacity", 0.0, 1.0)
        label("旋转角度（度）")
        _add_float_entry(app, elem, "rotation", -180.0, 180.0)
        label("宽度比例（0~1）")
        _add_float_entry(app, elem, "w_rel", 0.001, 1.0)
        label("高度比例（0~1）")
        _add_float_entry(app, elem, "h_rel", 0.001, 1.0)
    label("位置 X（0~1）")
    _add_float_entry(app, elem, "x", 0.0, 1.0)
    label("位置 Y（0~1）")
    _add_float_entry(app, elem, "y", 0.0, 1.0)