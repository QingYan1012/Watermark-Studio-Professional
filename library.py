# -*- coding: utf-8 -*-
"""
水印库（模板预设库）。

v2 优化：list_presets 按“目录文件签名(文件名+mtime)”缓存解析结果——
只有库内容真正变化时才读取/解析 JSON，重复打开水印库面板几乎零开销。

本轮（第25轮）改动：library_dir() 的路径收口到配置中心 app.config.library_dir_path()，
带 try 回退（app 包不可用时退回硬编码，值与 config 完全一致）。
注意：config.library_dir_path() 是纯函数不建目录，故此处仍 makedirs
（save_preset / list_presets 等调用方依赖目录已存在），行为与原来一字不差。
"""

import os
import re
import json
import time

from model import Template


_LIST_CACHE = {
    "sig": None,
    "items": None,
}


def library_dir():
    # 【第25轮】路径来源收口到配置中心；app 包不可用时回退硬编码（值与 config 完全一致）。
    # config.library_dir_path() 为纯函数、不建目录，故取完后仍 makedirs 保持原行为。
    try:
        from app.config import library_dir_path
        base = library_dir_path()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".watermark_studio", "library")

    os.makedirs(base, exist_ok=True)
    return base


def _dir_signature(d):
    sig = []

    for fname in os.listdir(d):
        if not fname.lower().endswith(".json"):
            continue

        try:
            sig.append((fname, os.path.getmtime(os.path.join(d, fname))))
        except OSError:
            pass

    return tuple(sorted(sig))


def list_presets():
    """
    返回 [(display_name, path, saved_at), ...]，按保存时间倒序。
    """
    d = library_dir()
    sig = _dir_signature(d)

    if _LIST_CACHE["sig"] == sig and _LIST_CACHE["items"] is not None:
        return _LIST_CACHE["items"]

    items = []

    for fname, _mt in sig:
        path = os.path.join(d, fname)
        name = os.path.splitext(fname)[0]

        try:
            with open(path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            saved_at = meta.get("_saved_at", 0)
            display_name = meta.get("_display_name", name)
        except Exception:
            saved_at = 0
            display_name = name

        items.append((display_name, path, saved_at))

    items.sort(key=lambda t: t[2], reverse=True)

    _LIST_CACHE["sig"] = sig
    _LIST_CACHE["items"] = items

    return items


def safe_name(name):
    name = re.sub(r'[/:*?"<>|]', "", str(name)).strip()
    return name or f"预设_{int(time.time())}"


def save_preset(template, display_name):
    display_name = safe_name(display_name)
    path = os.path.join(library_dir(), f"{display_name}.json")

    data = template.to_dict()
    data["_display_name"] = display_name
    data["_saved_at"] = time.time()

    stem, ext = os.path.splitext(path)
    base_path = path
    n = 1

    while os.path.exists(base_path) and n < 999:
        base_path = f"{stem}_{n}{ext}"
        n += 1

    with open(base_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 失效缓存，下次重读
    _LIST_CACHE["sig"] = None
    _LIST_CACHE["items"] = None

    return base_path


def load_preset(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return Template.from_dict(data)


def delete_preset(path):
    try:
        os.remove(path)
        _LIST_CACHE["sig"] = None
        _LIST_CACHE["items"] = None
        return True
    except OSError:
        return False