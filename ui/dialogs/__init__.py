# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - UI dialogs 包。

当前包含：

- RectCropDialog：矩形裁剪对话框
- show_help：帮助窗口
- edit_current_data：编辑当前图片数据窗口
- show_match_dialog：数据匹配窗口
- open_library：水印库窗口
- PerspectiveCropDialog：新版透视裁剪对话框（可选启用）
"""

from .rect_crop_dialog import RectCropDialog

from .help_dialog import show_help
from .edit_data_dialog import edit_current_data
from .match_dialog import show_match_dialog
from .library_dialog import open_library


try:
    from .perspective_crop_dialog import PerspectiveCropDialog
except Exception:
    PerspectiveCropDialog = None


__all__ = [
    "RectCropDialog",
    "show_help",
    "edit_current_data",
    "show_match_dialog",
    "open_library",
    "PerspectiveCropDialog",
]