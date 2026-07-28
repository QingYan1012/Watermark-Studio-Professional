# -*- coding: utf-8 -*-
"""
字体管理模块。

扫描本机已安装字体 + 程序自带 fonts 目录，建立“家族名 -> 文件路径”映射。

v2 优化：
磁盘缓存（~/.watermark_studio/font_cache.json）：按 路径+mtime+size 校验，
只对新装/变更的字体用 fontTools 解析 name 表，启动二次起接近秒开。

get_font 的 ImageFont 实例缓存加 LRU 上限，避免滑杆连续调字号时无限膨胀。

本轮（第25轮）改动：_CACHE_PATH 收口到配置中心 app.config.font_cache_path()，
带 try 回退（app 包不可用时退回硬编码，值与 config 完全一致）。
font_cache_path() 是 lru_cache 纯函数，import 期零 IO、不触发单例、不写盘。
"""

import os
import sys
import json
import platform
import threading
from collections import OrderedDict

from PIL import ImageFont

try:
    from fontTools.ttLib import TTFont
    HAS_FONTTOOLS = True
except Exception:
    HAS_FONTTOOLS = False


# ----------------------------------------------------------------------
# 【第25轮】字体缓存路径收口到配置中心。
# 优先用 app.config.font_cache_path()；import 失败（app 包缺失/损坏）时回退硬编码，
# 回退值与 config 计算结果逐字符相同，保证路径不漂移。
# 注意：font_cache_path() 为 lru_cache 纯函数，此处调用不产生任何 IO 副作用。
# ----------------------------------------------------------------------
try:
    from app.config import font_cache_path as _cfg_font_cache_path
    _CACHE_PATH = _cfg_font_cache_path()
except Exception:
    _CACHE_PATH = os.path.join(
        os.path.expanduser("~"),
        ".watermark_studio",
        "font_cache.json",
    )

_FONT_LRU_MAX = 512


class FontManager:
    def __init__(self):
        self._map = {}
        self._alias = {}
        self._scanned = False
        self._lock = threading.Lock()
        self._font_cache = OrderedDict()

    # ---------- 磁盘缓存 ----------

    @staticmethod
    def _load_disk_cache():
        try:
            with open(_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_disk_cache(cache):
        try:
            os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
            with open(_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------- 扫描 ----------

    def _font_dirs(self):
        dirs = []
        system = platform.system()

        if system == "Windows":
            windir = os.environ.get("WINDIR", "C:\\Windows")
            dirs.append(os.path.join(windir, "Fonts"))

            local = os.environ.get("LOCALAPPDATA")
            if local:
                dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))

        elif system == "Darwin":
            dirs += [
                "/Library/Fonts",
                "/System/Library/Fonts",
                os.path.expanduser("~/Library/Fonts"),
            ]

        else:
            dirs += [
                "/usr/share/fonts",
                os.path.expanduser("~/.fonts"),
            ]

        try:
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        except Exception:
            base = os.getcwd()

        dirs.append(os.path.join(base, "fonts"))

        return [d for d in dirs if os.path.isdir(d)]

    def _read_family_names(self, path):
        names = []

        if HAS_FONTTOOLS:
            try:
                tt = TTFont(path, fontNumber=0, lazy=True)
                name_table = tt["name"]

                candidates = [
                    (16, 3, 1, 0x804),
                    (1, 3, 1, 0x804),
                    (16, 3, 1, 0x409),
                    (1, 3, 1, 0x409),
                    (1, 1, 0, 0),
                ]

                for name_id, plat, enc, lang in candidates:
                    rec = name_table.getName(name_id, plat, enc, lang)
                    if rec:
                        s = str(rec).strip()
                        if s and s not in names:
                            names.append(s)
            except Exception:
                pass

        if not names:
            names.append(os.path.splitext(os.path.basename(path))[0])

        return names

    def scan(self):
        with self._lock:
            disk = self._load_disk_cache()
            new_disk = {}
            new_map = {}
            new_alias = {}

            exts = (".ttf", ".ttc", ".otf")

            for d in self._font_dirs():
                try:
                    entries = os.listdir(d)
                except Exception:
                    continue

                for fname in entries:
                    if not fname.lower().endswith(exts):
                        continue

                    fpath = os.path.join(d, fname)

                    try:
                        st = os.stat(fpath)
                        mtime = st.st_mtime
                        size = st.st_size
                    except OSError:
                        continue

                    sig = disk.get(fpath)

                    if (
                        isinstance(sig, dict)
                        and sig.get("mtime") == mtime
                        and sig.get("size") == size
                        and isinstance(sig.get("names"), list)
                        and sig["names"]
                    ):
                        names = sig["names"]
                    else:
                        names = self._read_family_names(fpath)

                    new_disk[fpath] = {
                        "mtime": mtime,
                        "size": size,
                        "names": names,
                    }

                    primary = names[0]
                    new_map.setdefault(primary, fpath)

                    for n in names:
                        new_alias.setdefault(n, primary)
                        if n.lower() != n:
                            new_alias.setdefault(n.lower(), primary)

            self._map = new_map
            self._alias = new_alias
            self._scanned = True

            self._save_disk_cache(new_disk)

    def scan_async(self, on_done=None):
        def _run():
            self.scan()
            if on_done:
                on_done(self.family_names())

        threading.Thread(target=_run, daemon=True).start()

    # ---------- 查询 ----------

    def family_names(self):
        return sorted(self._map.keys(), key=lambda s: s.lower())

    def resolve(self, family_name):
        if not family_name:
            return None

        if family_name in self._map:
            return family_name

        if family_name in self._alias:
            return self._alias[family_name]

        return self._alias.get(family_name.lower())

    def path_for(self, family_name):
        if family_name in self._map:
            return self._map[family_name]

        canonical = self.resolve(family_name)
        return self._map.get(canonical) if canonical else None

    def get_font(self, family_name, size):
        size = max(1, int(size))
        key = (family_name, size)

        cached = self._font_cache.get(key)
        if cached is not None:
            self._font_cache.move_to_end(key)
            return cached

        font = None
        path = self.path_for(family_name)

        if path:
            try:
                font = ImageFont.truetype(path, size)
            except Exception:
                font = None

        if font is None:
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None

        if font is not None:
            self._font_cache[key] = font
            if len(self._font_cache) > _FONT_LRU_MAX:
                self._font_cache.popitem(last=False)

        return font