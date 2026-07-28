# -*- coding: utf-8 -*-
"""工具栏构建（从 legacy App._build_toolbar 物理搬迁，第43轮）。

逐行 self->app 改名，行为与 legacy 918-950 逐字等价。
关键：保留 app._toolbar = bar —— RECT_CROP_PATCH(2945)/AUTOPERSP_PATCH(3704) 包装
_build_layout 后靠 getattr(self,"_toolbar") 往 bar 塞『✂裁剪』『🤖自动透视』，
此属性在则包装链不断、按钮不丢。
_tb_sep/_tb_btn 仍走 app 的方法（legacy 辅助方法，未搬），运行时解析正确。
边角参数(corner_radius/border)保留 legacy 原样：直角终结者会在 _build_layout 包装里
orig 后 configure 掉，搬代码不夹带边角修改，职责分离。
"""
import customtkinter as ctk

from ..theme import T


def build_toolbar(app):
    bar = ctk.CTkFrame(app, height=46, corner_radius=10, fg_color=T("panel"),
                       border_width=1, border_color=T("border"))
    bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 5))
    app._toolbar = bar
    app._theme_btn = ctk.CTkButton(bar, text=app._theme_btn_text(), width=72, height=30,
                                   corner_radius=7, fg_color=T("panel"),
                                   hover_color=T("panel3"), text_color=T("text_mid"),
                                   font=app.ui_font, command=app.toggle_theme)
    app._theme_btn.pack(side="right", padx=3, pady=6)
    ctk.CTkButton(bar, text="？ 帮助", width=64, height=30, corner_radius=7,
                  fg_color=T("panel"), hover_color=T("panel3"),
                  text_color=T("text_mid"), font=app.ui_font,
                  command=app._show_help).pack(side="right", padx=2, pady=6)
    app._tb_sep(bar)
    app._tb_btn(bar, "打开图片", app.on_open_images, width=72)
    app._tb_btn(bar, "打开文件夹", app.on_open_folder, width=78)
    app._tb_btn(bar, "导入数据表", app.on_import_table, width=80)
    app._tb_sep(bar)
    app._tb_btn(bar, "加载模板", app.on_load_template, width=72)
    app._tb_btn(bar, "保存模板", app.on_save_template, width=72)
    app._tb_btn(bar, "★ 水印库", app.on_open_library, kind="purple", width=76)
    app._tb_sep(bar)
    app._tb_btn(bar, "📐 透视", app.on_perspective_crop, kind="accent", width=70)
    app._tb_btn(bar, "↻顺90", lambda: app.on_rotate_image(270), width=54)
    app._tb_btn(bar, "↺逆90", lambda: app.on_rotate_image(90), width=54)
    app._tb_btn(bar, "⇆水平", lambda: app.on_flip_image("horizontal"), width=54)
    app._tb_btn(bar, "⥯垂直", lambda: app.on_flip_image("vertical"), width=54)
    app._tb_sep(bar)
    app._tb_btn(bar, "+文字", app.on_add_text, width=54)
    app._tb_btn(bar, "+图标", app.on_add_image_elem, width=54)
    app._tb_btn(bar, "+形状", app.on_add_shape_elem, width=54)
    app._tb_btn(bar, "删除", app.on_delete_element, kind="danger", width=54)