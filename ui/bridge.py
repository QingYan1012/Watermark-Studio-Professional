# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 重构桥接层。

当前阶段 ui/legacy_app.py 仍然是旧 ui.py 的完整代码。
本模块负责把新拆出来的模块注入回 legacy_app，使其逐步使用新模块，
而不需要一次性重写 legacy_app.py。

注入内容包括：

1. ui/constants.py 中的常量
2. ui/theme.py 中的主题系统
3. ui/utils.py 中的工具函数
4. ui/widgets/searchable_combobox.py 中的 SearchableCombobox
5. ui/dialogs/rect_crop_dialog.py 中的 RectCropDialog
6. ui/dialogs 中的帮助 / 编辑数据 / 数据匹配 / 水印库窗口
7. ui/services 服务层挂载到 legacy._ws_services
8.【本轮改】默认启用新版 PerspectiveCropDialog（直接走 services，无 legacy 补丁依赖）；
        设 WS_NEW_PERSPECTIVE=0 可回退旧版透视弹窗。
9. 透视按钮修复：用 ui/services/edge_snap 覆盖旧版 _pc_refine_edges / _bend_refine，
   修复旧版“四边吸附精修 / 边线吸附(修弯曲) 点了没反应”（新版默认时此项为旧版回退保险）。
10. 导出修复：重写 on_batch_export，worker 优先用内存快照 entry.pil_image，
    修复“校正/裁剪/旋转/翻转在批量导出时丢失”（与 performance_patch 等价，互为兜底）。

可通过环境变量关闭桥接：
    set WS_REFACTOR_BRIDGE=0
    python main.py

【本轮改】新版透视弹窗现已默认启用；如需回退旧版：
    set WS_NEW_PERSPECTIVE=0
    python main.py
"""

import os
import sys
import threading

from tkinter import messagebox

from PIL import Image

from . import constants
from . import theme
from . import utils


# ----------------------------------------------------------------------
# 服务层透视精修函数（坐标系正确版本），用于覆盖旧版有 bug 的全局函数。
# 导入失败时降级为 None，对应修复函数会安全 return，不会崩溃。
# ----------------------------------------------------------------------
try:
    from .services.edge_snap import (
        refine_box_edges as _svc_refine,
        bend_refine_edge_points as _svc_bend,
    )
except Exception:
    _svc_refine = None
    _svc_bend = None


# 渲染模块（项目根顶层模块）。bridge 在 legacy_app 之后导入，
# 此时 renderer 必已在 sys.modules；仍用 try 做防御。
try:
    import renderer
except Exception:
    renderer = None


def _find_legacy_module():
    """
    找到真正的旧 UI 模块。

    正常包结构下是：

        ui.legacy_app

    如果使用了兼容入口加载根目录旧 ui.py，则可能是：

        watermark_studio_legacy_ui_single_file
    """
    module = sys.modules.get("ui.legacy_app")

    if module is not None and hasattr(module, "App"):
        return module

    for module_name, module in list(sys.modules.items()):
        if module_name.startswith("watermark_studio_legacy_ui") and hasattr(module, "App"):
            return module

    return None


# ======================================================================
# 修复函数（模块全局；通过 setattr 注入 legacy / App）
# ======================================================================

def _fixed_refine_edges(self):
    """
    旧版『⚡ 四边吸附精修』的修复实现。

    旧实现因缺 _rb_IF 而 NameError 被静默吞掉。
    这里改用 ui/services/edge_snap.refine_box_edges（坐标系自洽）。
    注：新版透视弹窗默认启用后，本函数仅在回退旧版时被调用，作为保险。
    """
    if _svc_refine is None:
        return

    try:
        new_corners = _svc_refine(
            self.pil_image,
            self.corners_rel,
            long_edge=800,
        )
    except Exception:
        new_corners = None

    if new_corners is None:
        return

    self.corners_rel = new_corners
    self.edge_points_rel = {0: [], 1: [], 2: [], 3: []}

    try:
        self._draw_canvas()
    except Exception:
        pass


def _fixed_bend_refine(self):
    """
    旧版『⚡ 边线吸附(修弯曲)』的修复实现。

    旧实现除缺 _bs_IF 外，还混用了『显示坐标 / 800 坐标』导致吸附错位。
    这里改用 ui/services/edge_snap.bend_refine_edge_points（统一 800 坐标 + rel）。
    注：新版透视弹窗默认启用后，本函数仅在回退旧版时被调用，作为保险。
    """
    if _svc_bend is None:
        return

    try:
        new_edges = _svc_bend(
            self.pil_image,
            self.corners_rel,
            k=4,
            long_edge=800,
            snap_radius_ratio=0.03,
        )
    except Exception:
        new_edges = {0: [], 1: [], 2: [], 3: []}

    self.edge_points_rel = new_edges

    try:
        self._draw_canvas()
    except Exception:
        pass


def _count_edited(images):
    """
    统计内存里已被编辑（校正/裁剪/旋转/翻转）的图片数。

    依赖 REFINEBATCH_V1 在 _load_current 里记录的 _orig_loaded_id。
    """
    n = 0

    for e in images:
        oid = getattr(e, "_orig_loaded_id", None)
        pil = getattr(e, "pil_image", None)

        if oid is not None and pil is not None and id(pil) != oid:
            n += 1

    return n


def _fixed_batch_export(self):
    """
    修复版批量导出（与 performance_patch 中等价，互为兜底）。

    关键修正：worker 优先使用内存快照 entry.pil_image，
    仅当为 None 时才回退 Image.open(path)。

    这样校正 / 矩形裁剪 / 旋转 / 翻转等只存在于内存的编辑，
    在批量导出时不再被磁盘原图覆盖。

    同时保留旧 REFINEBATCH 的『部分已编辑』确认弹窗语义。
    """
    if renderer is None:
        try:
            messagebox.showerror("导出失败", "渲染模块未就绪，无法导出。")
        except Exception:
            pass
        return

    if getattr(self, "_exporting", False):
        return

    if not self.images:
        messagebox.showinfo("提示", "请先加载图片。")
        return

    total = len(self.images)
    edited = _count_edited(self.images)
    orig = total - edited

    if total > 0 and 0 < edited < total:
        if not messagebox.askyesno(
            "批量导出确认",
            "共 %d 张：%d 张已编辑（矫正/旋转/翻转/裁剪）、%d 张为原图。\n"
            "将各自加水印导出（已编辑用编辑后图，原图用原图）。\n\n"
            "💡 水印与导出本就批量、与矫正解耦——不矫正也能一键给全部图加水印。\n继续？"
            % (total, edited, orig),
        ):
            return

    out_dir = self.output_dir_var.get()

    if not out_dir:
        first_dir = os.path.dirname(self.images[0].path)
        out_dir = os.path.join(first_dir, "output")

    os.makedirs(out_dir, exist_ok=True)

    pattern = self.rename_var.get()

    # 快照：路径 + 数据 + 当前内存图（可能为 None）
    snapshot = [(e.path, dict(e.data), e.pil_image) for e in self.images]

    self._exporting = True

    try:
        self.btn_batch_export.configure(state="disabled")
        self.btn_export_current.configure(state="disabled")
    except Exception:
        pass

    try:
        self.progress.set(0)
    except Exception:
        pass

    font_manager = self.font_manager
    tmpl = self.template
    after = self.after
    sanitize = utils.sanitize_filename

    def worker():
        errors = []
        unresolved_counts = {}

        for i, (path, data, pil) in enumerate(snapshot):
            try:
                # ★ 关键修正：内存编辑图优先，None 才读磁盘
                if pil is not None:
                    img = pil.convert("RGB")
                else:
                    img = Image.open(path).convert("RGB")

                for fields in renderer.template_unresolved_fields(tmpl, data).values():
                    for f in fields:
                        unresolved_counts[f] = unresolved_counts.get(f, 0) + 1

                rendered = renderer.render_template(
                    img,
                    tmpl,
                    data=data,
                    font_manager=font_manager,
                    layer_cache=False,
                )

                base, ext = os.path.splitext(os.path.basename(path))

                if pattern.strip():
                    out_name = sanitize(renderer.safe_format(pattern, data)) + ext
                else:
                    out_name = base + ext

                out_path = os.path.join(out_dir, out_name)
                stem, ex = os.path.splitext(out_path)

                n = 1
                while os.path.exists(out_path):
                    out_path = "%s_%d%s" % (stem, n, ex)
                    n += 1

                rendered.save(out_path, quality=95)

            except Exception as e:
                errors.append("%s: %s" % (os.path.basename(path), e))

            after(0, lambda p=(i + 1) / total: self.progress.set(p))

        after(
            0,
            lambda: self._finish_batch(total, errors, unresolved_counts, out_dir),
        )

    threading.Thread(target=worker, daemon=True).start()

    try:
        self._show_toast(
            "已提交批量导出：%d 张已编辑 + %d 张原图" % (edited, orig)
        )
    except Exception:
        pass


# ======================================================================
# 桥接安装
# ======================================================================

def install():
    """
    安装桥接。

    返回 True 表示安装成功或已经安装。
    返回 False 表示未安装。
    """
    if os.environ.get("WS_REFACTOR_BRIDGE", "1") == "0":
        return False

    legacy = _find_legacy_module()

    if legacy is None:
        return False

    if getattr(legacy, "_refactor_bridge_installed", False):
        return True

    # ------------------------------------------------------------------
    # 1. 注入常量
    # ------------------------------------------------------------------
    for name in constants.ALL:
        try:
            setattr(legacy, name, getattr(constants, name))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 2. 注入主题系统
    # ------------------------------------------------------------------
    legacy.THEMES = theme.THEMES
    legacy.THEME = theme.THEME
    legacy.ACCENT = theme.ACCENT
    legacy.T = theme.T
    legacy._NATIVE_WIDGETS = theme.NATIVE_WIDGETS
    legacy._native = theme.native
    legacy._retheme_native = theme.retheme_native

    def _apply_theme(mode):
        theme.apply_theme(mode)
        legacy.ACCENT = theme.ACCENT

    legacy._apply_theme = _apply_theme

    # ------------------------------------------------------------------
    # 3. 注入工具函数
    # ------------------------------------------------------------------
    legacy._disp_font = utils.disp_font
    legacy._nice_step = utils.nice_step
    legacy.sanitize_filename = utils.sanitize_filename

    # ------------------------------------------------------------------
    # 4. 注入 SearchableCombobox
    # ------------------------------------------------------------------
    try:
        from .widgets.searchable_combobox import SearchableCombobox

        legacy.SearchableCombobox = SearchableCombobox
    except Exception:
        import traceback

        traceback.print_exc()

    # ------------------------------------------------------------------
    # 5. 注入 RectCropDialog
    # ------------------------------------------------------------------
    try:
        from .dialogs.rect_crop_dialog import RectCropDialog

        legacy.RectCropDialog = RectCropDialog
    except Exception:
        import traceback

        traceback.print_exc()

    # ------------------------------------------------------------------
    # 6. 注入独立对话框
    # ------------------------------------------------------------------
    try:
        from .dialogs import (
            edit_data_dialog,
            help_dialog,
            library_dialog,
            match_dialog,
        )

        def _show_help(self):
            help_dialog.show_help(self)

        def _on_edit_current_data(self):
            edit_data_dialog.edit_current_data(self)

        def _show_match_dialog(self, columns, rows):
            match_dialog.show_match_dialog(self, columns, rows)

        def _on_open_library(self):
            library_dialog.open_library(self)

        legacy.App._show_help = _show_help
        legacy.App.on_edit_current_data = _on_edit_current_data
        legacy.App._show_match_dialog = _show_match_dialog
        legacy.App.on_open_library = _on_open_library

    except Exception:
        import traceback

        traceback.print_exc()

    # ------------------------------------------------------------------
    # 7. 挂载服务层
    # ------------------------------------------------------------------
    try:
        from . import services

        legacy._ws_services = services
    except Exception:
        import traceback

        traceback.print_exc()

    # ------------------------------------------------------------------
    # 8.【本轮改】默认启用新版透视裁剪对话框
    #
    #    旧：if os.environ.get("WS_NEW_PERSPECTIVE", "0") == "1":   （默认旧版）
    #    新：if os.environ.get("WS_NEW_PERSPECTIVE", "1") != "0":   （默认新版）
    #
    #    新版直接调用 ui/services，不依赖 legacy 末尾的
    #    AUTODETECT / REFINEBATCH / BENDSNAP 补丁，是“干净主线”。
    #    若新版模块 import 失败，except 会保留旧版，软件仍可启动（自动回退）。
    #    设 WS_NEW_PERSPECTIVE=0 可显式回退旧版。
    # ------------------------------------------------------------------
    if os.environ.get("WS_NEW_PERSPECTIVE", "1") != "0":
        try:
            from .dialogs.perspective_crop_dialog import PerspectiveCropDialog

            legacy.PerspectiveCropDialog = PerspectiveCropDialog
        except Exception:
            import traceback

            traceback.print_exc()

    # ------------------------------------------------------------------
    # 9. 透视按钮修复（旧版回退保险）
    #
    #    默认新版时，旧弹窗不再被实例化，本项注入的全局函数不会被调用，纯冗余但无害；
    #    回退旧版（WS_NEW_PERSPECTIVE=0）时，本项保证旧弹窗的
    #    四边吸附精修 / 边线吸附 仍可用。
    # ------------------------------------------------------------------
    try:
        from PIL import ImageFilter as _IF

        legacy._rb_IF = _IF
        legacy._bs_IF = _IF
    except Exception:
        pass

    try:
        legacy._pc_refine_edges = _fixed_refine_edges
        legacy._bend_refine = _fixed_bend_refine
    except Exception:
        import traceback

        traceback.print_exc()

    # ------------------------------------------------------------------
    # 10. 导出修复（与 performance_patch 等价，互为兜底）
    # ------------------------------------------------------------------
    try:
        legacy.App.on_batch_export = _fixed_batch_export
    except Exception:
        import traceback

        traceback.print_exc()

    # ------------------------------------------------------------------
    #【本轮新增】安装日志：在控制台一眼确认重构状态，尤其透视弹窗走新版还是旧版
    # ------------------------------------------------------------------
    try:
        pd = getattr(legacy, "PerspectiveCropDialog", None)
        pd_ver = getattr(pd, "_dialog_version", "legacy") if pd is not None else "none"
        pd_mod = getattr(pd, "__module__", "?") if pd is not None else "?"
        new_persp_on = os.environ.get("WS_NEW_PERSPECTIVE", "1") != "0"
        print(
            "[WS-BRIDGE] installed=True new_perspective=%s | "
            "PerspectiveCropDialog=%s @%s"
            % (new_persp_on, pd_ver, pd_mod)
        )
    except Exception:
        pass

    legacy._refactor_bridge_installed = True
    return True