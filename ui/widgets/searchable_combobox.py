# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 可搜索下拉框（v2 + 第35轮选中即时刷新修复）。

v2 修复：“选择字体后下拉框异常重新弹出”（重开锁定窗口）。
第35轮修复：“选了字体/值后画布或 entry 没即时刷新、要点别处才更新”——
根因是 _on_pick 的 command 虽同步改了数据并重绘，但深处事件回调中，
tkinter 把屏幕刷新推迟到事件循环空闲；选完后强制 update_idletasks() 立即 flush，
并双保险再 _collapse 一次，杜绝下拉残留造成的“看似没选上”。
"""

import traceback

import customtkinter as ctk

from tkinter import (
    END,
    Listbox,
    Scrollbar,
    StringVar,
)

from ..theme import (
    T,
    THEME,
    native,
)


_REOPEN_LOCK_MS = 500


class SearchableCombobox(ctk.CTkFrame):
    _open_instance = None
    _MAX_VISIBLE_ROWS = 7
    _widget_version = "v2"

    def __init__(self, master, values=None, command=None, width=260, list_font=None, **kwargs):
        super().__init__(master, fg_color="transparent", width=width)

        self._all_values = list(values or [])
        self._command = command
        self._listbox = None
        self._list_font = list_font
        self._expanded = False

        self._reopen_locked = False
        self._reopen_unlock_job = None

        self.var = StringVar(value=self._all_values[0] if self._all_values else "")

        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width, **kwargs)
        self.entry.pack(fill="x")

        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<Button-1>", self._on_entry_click)
        self.entry.bind("<Down>", lambda e: self._focus_list())
        self.entry.bind("<Escape>", lambda e: self._collapse())
        self.entry.bind("<FocusOut>", self._on_focus_out)

        self._drop_frame = ctk.CTkFrame(
            self,
            fg_color=T("panel"),
            border_width=1,
            border_color=T("accent"),
        )

        list_wrap = ctk.CTkFrame(self._drop_frame, fg_color="transparent")
        list_wrap.pack(fill="both", expand=True, padx=1, pady=1)

        list_wrap.grid_rowconfigure(0, weight=1)
        list_wrap.grid_columnconfigure(0, weight=1)

        self._listbox = native(
            Listbox(
                list_wrap,
                bg=THEME["panel"],
                fg=THEME["text"],
                selectbackground=THEME["sel"],
                selectforeground=THEME["text"],
                highlightthickness=0,
                borderwidth=0,
                activestyle="none",
                exportselection=False,
                font=self._list_font,
            ),
            bg="panel",
            fg="text",
            selectbackground="sel",
            selectforeground="text",
        )

        self._listbox.grid(row=0, column=0, sticky="nsew")

        list_scroll = Scrollbar(list_wrap, orient="vertical", command=self._listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")

        self._listbox.configure(yscrollcommand=list_scroll.set)

        self._listbox.bind("<<ListboxSelect>>", self._on_pick)
        self._listbox.bind("<Return>", self._on_pick)

        def _wheel_scroll(e):
            self._listbox.yview_scroll(int(-1 * (e.delta / 120)), "units")
            return "break"

        def _wheel_up(_e):
            self._listbox.yview_scroll(-1, "units")
            return "break"

        def _wheel_down(_e):
            self._listbox.yview_scroll(1, "units")
            return "break"

        self._listbox.bind("<MouseWheel>", _wheel_scroll)
        self._listbox.bind("<Button-4>", _wheel_up)
        self._listbox.bind("<Button-5>", _wheel_down)
        self._listbox.bind("<FocusOut>", lambda e: self.after(120, self._maybe_collapse))

        for w in (list_wrap, self._drop_frame):
            w.bind("<MouseWheel>", _wheel_scroll, add="+")
            w.bind("<Button-4>", _wheel_up, add="+")
            w.bind("<Button-5>", _wheel_down, add="+")

        self.bind("<Destroy>", self._on_self_destroy, add="+")

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def set_values(self, values):
        self._all_values = list(values or [])

        if self._expanded:
            self._expand(filter_text=self.var.get())

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)

    # ------------------------------------------------------------------
    # 重开锁定
    # ------------------------------------------------------------------

    def _lock_reopen(self):
        """选中后短暂锁定，防止焦点回归/残留事件自动展开下拉框。"""
        self._reopen_locked = True

        try:
            if self._reopen_unlock_job is not None:
                self.after_cancel(self._reopen_unlock_job)
        except Exception:
            pass

        try:
            self._reopen_unlock_job = self.after(_REOPEN_LOCK_MS, self._unlock_reopen)
        except Exception:
            self._reopen_unlock_job = None

    def _unlock_reopen(self):
        self._reopen_locked = False

        if self._reopen_unlock_job is not None:
            try:
                self.after_cancel(self._reopen_unlock_job)
            except Exception:
                pass

        self._reopen_unlock_job = None

    # ------------------------------------------------------------------
    # 输入框事件
    # ------------------------------------------------------------------

    def _on_focus_in(self, _event=None):
        if self._reopen_locked:
            return

        self._expand(filter_text="")

    def _on_focus_out(self, _event=None):
        # 焦点真正离开后解锁：用户下次再点输入框属于有意操作
        self._unlock_reopen()
        self.after(120, self._maybe_collapse)

    def _on_entry_click(self, _event=None):
        if self._reopen_locked:
            return

        self._expand(filter_text="")

    def _on_key(self, event):
        if event.keysym in ("Down", "Up", "Return", "Escape"):
            return

        # 主动打字视为有意搜索，解锁并过滤
        self._reopen_locked = False
        self._expand(filter_text=self.var.get())

    # ------------------------------------------------------------------
    # 下拉列表
    # ------------------------------------------------------------------

    def _filtered(self, filter_text=""):
        if not filter_text:
            return self._all_values

        f = filter_text.lower()

        starts = [v for v in self._all_values if v.lower().startswith(f)]
        contains = [v for v in self._all_values if f in v.lower() and v not in starts]

        return starts + contains

    def _expand(self, filter_text=None):
        if (
            SearchableCombobox._open_instance is not None
            and SearchableCombobox._open_instance is not self
        ):
            SearchableCombobox._open_instance._collapse()

        SearchableCombobox._open_instance = self

        items = self._filtered(self.var.get() if filter_text is None else filter_text)

        self._listbox.delete(0, END)

        for v in items:
            self._listbox.insert(END, v)

        if items:
            self._listbox.selection_clear(0, END)
            self._listbox.selection_set(0)

        self._listbox.configure(height=min(self._MAX_VISIBLE_ROWS, max(1, len(items))))

        if not self._expanded:
            self._drop_frame.pack(fill="x", pady=(2, 0))
            self._expanded = True

    def _focus_list(self):
        self._reopen_locked = False
        self._expand(filter_text=self.var.get())

        if self._listbox.size():
            self._listbox.focus_set()
            self._listbox.selection_set(0)

    def _on_pick(self, _event=None):
        if not self._listbox.curselection():
            return

        value = self._listbox.get(self._listbox.curselection()[0])

        # 先清选中状态，防止 <<ListboxSelect>> 连续触发导致重复进入
        self._listbox.selection_clear(0, END)

        self.var.set(value)
        self._collapse()

        # 先锁定再执行回调，避免回调内触发事件处理时被穿透
        self._lock_reopen()

        if self._command:
            try:
                self._command(value)
            except Exception:
                traceback.print_exc()

        try:
            self.entry.focus_set()
        except Exception:
            pass

        # 【第35轮修】选完后双保险再关一次下拉 + 强制 flush 屏幕更新，
        # 避免“选了字体/值但画布或 entry 没即时刷新、要点别处才更新”的时序错觉。
        try:
            self._collapse()
        except Exception:
            pass
        try:
            self.winfo_toplevel().update_idletasks()
        except Exception:
            pass

    def _maybe_collapse(self):
        try:
            focused = self.focus_get()
        except Exception:
            focused = None

        if focused not in (self._listbox, self.entry):
            self._collapse()

    def _collapse(self):
        if self._expanded:
            self._drop_frame.pack_forget()
            self._expanded = False

        if SearchableCombobox._open_instance is self:
            SearchableCombobox._open_instance = None

    _close_popup = _collapse

    def _on_self_destroy(self, _event=None):
        if SearchableCombobox._open_instance is self:
            SearchableCombobox._open_instance = None