# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 数据匹配窗口。

从旧 ui.py 的 App._show_match_dialog 中抽离（第 9 轮），bridge 注入后成为主线弹窗，
legacy 的旧 _show_match_dialog 被实质架空。

本轮（第24轮）：改调 match_rows_to_images_detail，拿到 exact/fuzzy 拆分，
在“精确 0 但 fuzzy>0”时用强调色显式说明智能匹配救场，把第23轮的智能兜底从
“黑盒数字变化”变成“看得懂、信得过”。旧 match_rows_to_images 仍被 confirm 用于
拿最终 mapping（行为不变），此处 confirm 改调 detail 仅为顺带取 fuzzy 计数。
"""

import customtkinter as ctk

from tkinter import (
    StringVar,
    messagebox,
)

from data_import import (
    diagnose_filename_mismatch,
    match_rows_to_images,
    match_rows_to_images_detail,
)

from .. import theme as _theme
from ..theme import T
from ..utils import disp_font


def _match_stats(app, rows, filename_col):
    """返回 match_rows_to_images_detail 的 stats（含 exact/fuzzy/total/mode）。
    无图时返回全 0，避免弹窗在空列表下越界。"""
    paths = [e.path for e in app.images]
    if not paths:
        return {"exact": 0, "fuzzy": 0, "total": 0, "mode": "filename" if filename_col else "order"}

    _mapping, stats = match_rows_to_images_detail(
        rows,
        paths,
        filename_column=filename_col,
    )
    return stats


def show_match_dialog(app, columns, rows):
    """
    显示数据与图片匹配方式选择窗口。

    参数：
        app: 主窗口 App 实例
        columns: 表格列名列表
        rows: 表格数据行列表
    """
    win = ctk.CTkToplevel(app)
    win.title("数据与图片匹配方式")
    win.geometry("420x280")
    win.configure(fg_color=T("bg"))
    win.grab_set()

    n_img = len(app.images)

    ctk.CTkLabel(
        win,
        text=f"读取到 {len(rows)} 行数据 · {len(columns)} 列；当前图片 {n_img} 张。",
        text_color=T("text_mid"),
        font=app.ui_font,
    ).pack(padx=16, pady=(16, 8), anchor="w")

    ctk.CTkLabel(
        win,
        text="选择匹配方式：",
        text_color=T("text"),
        font=app.ui_font,
    ).pack(padx=16, anchor="w")

    options = ["(按顺序对应)"] + columns

    # 智能默认：哪一列的“总匹配数”能覆盖全部图片，就默认选它
    perfect = None

    if n_img > 0:
        for c in columns:
            if _match_stats(app, rows, c)["total"] >= n_img:
                perfect = c
                break

    var = StringVar(value=perfect or options[0])

    ctk.CTkOptionMenu(
        win,
        values=options,
        variable=var,
        width=300,
        font=app.ui_font,
        command=lambda _v: _update_estimate(),
    ).pack(padx=16, pady=8, anchor="w")

    est_label = ctk.CTkLabel(
        win,
        text="",
        text_color=T("accent"),
        font=disp_font(12, True),
    )

    est_label.pack(padx=16, anchor="w")

    hint_label = ctk.CTkLabel(
        win,
        text="",
        text_color=T("text_dim"),
        wraplength=380,
        justify="left",
        font=app.ui_small,
    )

    hint_label.pack(padx=16, pady=(2, 0), anchor="w")

    def _update_estimate():
        col = var.get()
        filename_col = None if col == options[0] else col

        stats = _match_stats(app, rows, filename_col)
        cnt = stats["total"]
        exact = stats["exact"]
        fuzzy = stats["fuzzy"]

        est_label.configure(text=f"按当前方式预计可匹配 {cnt} / {n_img} 张")

        if filename_col and exact == 0 and fuzzy > 0:
            # 精确全失败、靠智能兜底救场：显式说明，强调色，让用户看懂“为什么有数”
            hint_label.configure(
                text=(
                    f"精确匹配 0 张，已按「编号+尾部」智能匹配 {fuzzy} 张"
                    f"（图片带孔号前缀、表格不带时自动生效）。"
                ),
                text_color=_theme.ACCENT,
            )
        elif filename_col and cnt < max(1, int(n_img * 0.3)):
            hint_label.configure(
                text="匹配数偏低：表格该列的值与图片文件名对不上，可改选「按顺序对应」。",
                text_color=T("text_dim"),
            )
        else:
            hint_label.configure(text="", text_color=T("text_dim"))

    _update_estimate()

    def confirm():
        col = var.get()
        filename_col = None if col == options[0] else col

        image_paths = [e.path for e in app.images]

        mapping, stats = match_rows_to_images_detail(
            rows,
            image_paths,
            filename_column=filename_col,
        )

        matched = 0

        for e in app.images:
            data = mapping.get(e.path, {})

            if data:
                matched += 1

            e.data.update(data)

        win.destroy()

        app.status_label.configure(
            text=f"共 {len(app.images)} 张图片，已匹配数据 {matched} 张"
        )

        app._redraw_canvas()

        fuzzy = stats.get("fuzzy", 0)
        toast_txt = f"已匹配 {matched} 张数据"
        if fuzzy > 0:
            toast_txt += f"（含智能匹配 {fuzzy} 张）"

        try:
            app._show_toast(toast_txt, _theme.ACCENT)
        except Exception:
            pass

        # 注意：fuzzy 把 matched 拉高后，此条件自然不触发——正是我们想要的
        # （智能匹配已成功，不该再弹“匹配数偏低”的吓人警告）。
        if filename_col and matched < max(1, len(app.images) * 0.3):
            excel_samples, image_samples = diagnose_filename_mismatch(
                rows,
                image_paths,
                filename_col,
            )

            lines = [
                "按「%s」列匹配到的很少（%d / %d 张），对比一下实际内容："
                % (filename_col, matched, len(app.images)),
                "",
            ]

            lines.append("表格里「%s」列的值：" % filename_col)
            lines += [f"  {v}" for v in excel_samples] or ["  (空)"]

            lines.append("")
            lines.append("当前图片列表里的实际文件名：")
            lines += [f"  {v}" for v in image_samples] or ["  (无图片)"]

            lines.append("")
            lines.append(
                "请对照检查：大小写、全角/半角符号、扩展名、多余空格；或改选「按顺序对应」。"
            )

            messagebox.showwarning("按文件名匹配数偏低", "\n".join(lines))

    ctk.CTkButton(
        win,
        text="确定导入",
        fg_color=T("accent"),
        hover_color=T("accent_h"),
        text_color="white",
        width=120,
        font=app.ui_font,
        command=confirm,
    ).pack(pady=14)