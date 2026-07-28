# -*- coding: utf-8 -*-
"""边角归位 · 最终确定版。

为什么单独成文件、且必须在 performance_patch 之后 import（见 main.py）：
performance_patch 的边角逻辑经多轮调整已不可信；本文件作为“最后覆盖者”，用一套
对称、确定、不猜像素的规则一次盖掉它，无需关任何开关、无需改 performance_patch。

两个独立病根（对着 legacy 源码 + 主题表确认，非猜截图）：
  病1 黑角/黑边：面板是 CTkFrame，父却是 tk.PanedWindow；CTk 画圆角时圆角外切角
      要填“父色”，tk 父无 CTk 色 → 兜底填黑。与主题/边框色无关 → 调颜色治不了。
  病2 暗色亮框/亮线：legacy border 暗色 #2a2f3a 比深 panel #1d2027 亮；PanedWindow.bg
      =border 又比窗口底亮 → 暗色描边与拖拽条发亮。
  两病根因不同，一套颜色值无法同治 → 这是前几轮横跳的数学必然。

对称正解（亮暗各取所需、结构相同）：
  (1) 面板/顶栏/底栏 corner_radius=0：无圆角 → 无外切角 → 无黑兜底（根治病1）。
  (2) 三者 border 用跨角色元组 (light_border, dark_bg)，border_width 仍 1：
      亮=浅灰勾边(比白深→清晰)，暗=窗口底(比深 panel 深→暗勾边不发亮，根治病2)。
  (3) PanedWindow 底色改窗口底 bg，并把它的登记角色 border→bg：圆角缺口与拖拽条
      融进窗口底，亮暗皆“消失”；切主题时 _retheme_native 按 bg 翻色，自洽。
  (4) 恢复 THEMES["light"]["bg"] 为原始 #f5f6f8（撤销历史补偿；单值 THEME 在
      App.__init__ 的 _apply_theme 里重算，无需手动同步）。

结果：亮=白直角面板+浅灰勾边浮浅灰底；暗=深直角面板+近黑勾边浮近黑底。
两态对称，无黑角、无亮框、无亮线。
回退：删掉 main.py 里 `import ui.edge_fix` 那一行，即回到 performance_patch 旧边角逻辑。
若你坚持要圆角：现有布局下面板圆角必带黑角，需把 PanedWindow 换 CTk 分割容器（大改，另议）。
"""
import logging

_log = logging.getLogger("ws.edge_fix")


def _find_app():
    import sys
    m = sys.modules.get("ui")
    if m is not None and getattr(m, "App", None) is not None:
        return m, m.App
    m = sys.modules.get("ui.legacy_app")
    if m is not None and getattr(m, "App", None) is not None:
        return m, m.App
    for mn, mo in list(sys.modules.items()):
        if mn.startswith("watermark_studio_legacy_ui") and getattr(mo, "App", None) is not None:
            return mo, mo.App
    return None, None


def install():
    mod, App = _find_app()
    if App is None:
        _log.warning("edge_fix: 找不到 App，跳过")
        return False
    legacy = mod
    TH = getattr(legacy, "THEMES", None)
    T = getattr(legacy, "T", None)
    THEME = getattr(legacy, "THEME", None)
    if not (TH and callable(T) and THEME is not None):
        _log.warning("edge_fix: 主题表不可用，跳过")
        return False

    try:
        import customtkinter as ctk
    except Exception:
        _log.warning("edge_fix: customtkinter 不可用，跳过")
        return False

    # 跨角色勾边：亮浅灰 / 暗窗口底（比深 panel 深 → 暗勾边不发亮）
    try:
        EDGE = (TH["light"]["border"], TH["dark"]["bg"])
    except Exception:
        _log.exception("edge_fix: 取跨角色边色失败")
        return False

    # (4) 恢复亮色窗口底原始值（若曾被历史补偿改过）
    try:
        TH["light"]["bg"] = "#f5f6f8"
    except Exception:
        pass

    # (1)+(2) 面板：直角 + 跨角色勾边
    if hasattr(App, "_panel"):
        orig_panel = App._panel

        def _panel(self, master):
            try:
                return ctk.CTkFrame(
                    master, corner_radius=0, fg_color=T("panel"),
                    border_width=1, border_color=EDGE,
                )
            except Exception:
                return orig_panel(self, master)

        App._panel = _panel

    # (1)+(2) 顶栏/底栏：orig 后改直角 + 跨角色勾边
    def _restyle(frame):
        if frame is None:
            return
        try:
            frame.configure(corner_radius=0, border_width=1, border_color=EDGE)
        except Exception:
            pass

    if hasattr(App, "_build_toolbar"):
        _ot = App._build_toolbar

        def _bt(self):
            _ot(self)
            _restyle(getattr(self, "_toolbar", None))

        App._build_toolbar = _bt

    if hasattr(App, "_build_bottom_bar"):
        _ob = App._build_bottom_bar

        def _bb(self):
            _ob(self)
            _restyle(getattr(self, "_bottom_bar", None))

        App._build_bottom_bar = _bb

    # (3) PanedWindow 底色=窗口底 + 登记角色 border→bg（切主题时翻成 bg）
    if hasattr(App, "_build_layout"):
        _ol = App._build_layout

        def _bl(self):
            _ol(self)
            mp = getattr(self, "main_paned", None)
            if mp is None:
                return
            try:
                mp.configure(bg=THEME.get("bg"))
            except Exception:
                pass
            try:
                NW = getattr(legacy, "_NATIVE_WIDGETS", None)
                if NW is not None:
                    for _w, _roles in NW:
                        if _w is mp and isinstance(_roles, dict):
                            _roles["bg"] = "bg"
            except Exception:
                pass

        App._build_layout = _bl

    _log.info("edge_fix: 边角归位已安装（直角 + 跨角色勾边 + 拖拽条=窗口底）")
    return True


install()