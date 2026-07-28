# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 配置中心（readmes ⑥ 配置统一管理）。

定位：把散落在 constants / logging_setup / font_manager / library / legacy 主题读写 /
performance_patch 开关里的「路径 + 偏好 + 默认值」收口成单一来源。

设计原则（纯增量、零回归）：
- 路径用【纯函数】：pref_dir() / theme_path() / welcome_flag_path() / log_file_path() /
  font_cache_path() / library_dir_path() / meta_path()。纯计算 + lru_cache，import 期零 IO、
  零副作用。“拼路径”与“确保目录存在”是两件事：这些函数只拼路径，需要写盘的调用方自行 ensure。
- 偏好用【兼容 API】：load_theme_pref / save_theme_pref 与 legacy 的 _load/_save_theme_pref
  使用【同一个 theme.json、同一种 {"mode": ...} 格式】。本模块写盘是【原子写】（.tmp + os.replace）。
- 开关默认值用【登记表 PERF_DEFAULTS】+ 类型化助手 env_bool / env_int / env_str。
  ★ 过渡态声明：performance_patch / bridge 当前仍内联各自默认值（保持已验证行为零回归）；
  PERF_DEFAULTS 是“规范登记”，待 performance_patch 重构时删内联、以本表为准。
- 版本升级：config_meta.json 带 schema；load 时 schema 不匹配走 _migrate 钩子（本轮空实现 +
  记日志，预留真实迁移）。

接入进度：
- 第22轮：logging_setup 改从本模块取日志目录/路径。
- 第25轮：font_manager / library 改从本模块取 font_cache / library 路径。
- 第26轮：performance_patch 用桥接把主题偏好读写覆盖成本模块 API（原子写 + mode 校验）。
- 第27轮：ui/constants 的三个路径常量改从本模块取 → 路径/偏好/常量三线全部统一，⑥ 闭环。

回退：本模块 import 期零副作用；即便整体不可用，各调用方的 try 回退保证功能照常。
"""

import functools
import json
import logging
import os
import threading
import time


_log = logging.getLogger("ws.config")


# ----------------------------------------------------------------------
# 文件名 / 目录名常量（单一来源；整个项目仅此一处出现这些字面量）
# ----------------------------------------------------------------------
APP_DIR_NAME = ".watermark_studio"
THEME_FILENAME = "theme.json"
WELCOME_FILENAME = ".welcomed"          # 【第27轮】首次帮助窗标记
LOG_FILENAME = "wsp.log"
FONT_CACHE_FILENAME = "font_cache.json"
LIBRARY_DIRNAME = "library"
META_FILENAME = "config_meta.json"

# 配置元数据 schema 版本。字段结构变化时 +1，并在 _migrate 里补迁移逻辑。
SCHEMA_VERSION = 1


# ----------------------------------------------------------------------
# 开关默认值登记表（规范来源；过渡态，见模块 docstring）
# ----------------------------------------------------------------------
PERF_DEFAULTS = {
    # 总开关 / 各修复开关（bool 语义：未设置=启用，"0"=关闭）
    "WATERMARK_PERF": True,
    "WS_PERF_SMOOTH": True,
    "WS_PERF_ASYNC_PREVIEW": True,
    "WS_PERF_PREFETCH": True,
    "WS_PERF_UNDO_OBSERVE": True,
    "WS_PERF_LIGHT_THEME": True,
    "WS_PERF_THEME_PREF": True,
    "WS_PERF_SVC_LOG": True,
    "WS_NEW_PERSPECTIVE": True,
    "WS_REFACTOR_BRIDGE": True,
    # 数值调参（int）
    "WS_PREVIEW_SETTLE": 1900,
    "WS_PIXEL_PERFECT": 6000,
    "WS_DOT_STEP": 26,
    # 字符串（str）
    "WS_LOG_LEVEL": "INFO",
}


# ----------------------------------------------------------------------
# 路径纯函数（lru_cache；os.path.expanduser 依赖 HOME，运行期不变，缓存安全）
# ----------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def home_dir():
    return os.path.expanduser("~")


@functools.lru_cache(maxsize=None)
def pref_dir():
    """偏好根目录 ~/.watermark_studio（只拼路径，不创建）。"""
    return os.path.join(home_dir(), APP_DIR_NAME)


@functools.lru_cache(maxsize=None)
def theme_path():
    return os.path.join(pref_dir(), THEME_FILENAME)


@functools.lru_cache(maxsize=None)
def welcome_flag_path():
    """【第27轮】首次帮助窗标记路径（只拼路径，不创建）。"""
    return os.path.join(pref_dir(), WELCOME_FILENAME)


@functools.lru_cache(maxsize=None)
def log_dir():
    """日志目录（与偏好根目录相同；只拼路径，不创建）。"""
    return pref_dir()


@functools.lru_cache(maxsize=None)
def log_file_path():
    return os.path.join(log_dir(), LOG_FILENAME)


@functools.lru_cache(maxsize=None)
def font_cache_path():
    return os.path.join(pref_dir(), FONT_CACHE_FILENAME)


@functools.lru_cache(maxsize=None)
def library_dir_path():
    """水印库目录（只拼路径，不创建；现有 library.library_dir 会 makedirs，迁移时由调用方 ensure）。"""
    return os.path.join(pref_dir(), LIBRARY_DIRNAME)


@functools.lru_cache(maxsize=None)
def meta_path():
    return os.path.join(pref_dir(), META_FILENAME)


# ----------------------------------------------------------------------
# 环境变量助手（类型化；未设置时回退 PERF_DEFAULTS 登记值，再回退调用方 default）
# ----------------------------------------------------------------------
def _default_for(name, default, want_type):
    """调用方未传 default 时，用 PERF_DEFAULTS 登记值（按类型安全转换）。"""
    if default is not None:
        return default
    reg = PERF_DEFAULTS.get(name)
    if reg is None:
        return (True if want_type is bool else 0 if want_type is int else "")
    if want_type is bool:
        return reg if isinstance(reg, bool) else bool(reg)
    if want_type is int:
        return reg if isinstance(reg, int) else int(reg)
    return reg if isinstance(reg, str) else str(reg)


def env_bool(name, default=None):
    """读布尔开关。设置时："0/false/no/off/空" → False，其余 → True；未设置 → 登记默认。"""
    raw = os.environ.get(name)
    if raw is None:
        return bool(_default_for(name, default, bool))
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def env_int(name, default=None):
    """读整数调参。设置但无法解析时记 warning 并回退默认（不抛）。"""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return int(_default_for(name, default, int))
    try:
        return int(raw)
    except Exception:
        _log.warning("环境变量 %s=%r 不是整数，回退默认", name, raw)
        return int(_default_for(name, default, int))


def env_str(name, default=None):
    """读字符串调参。"""
    raw = os.environ.get(name)
    if raw is None:
        return str(_default_for(name, default, str))
    return raw.strip()


# ----------------------------------------------------------------------
# 通用原子 JSON 读写（异常保护；写盘 = .tmp + os.replace，防半截损坏）
# ----------------------------------------------------------------------
def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except FileNotFoundError:
        return default
    except Exception:
        _log.debug("读取 JSON 失败 path=%s（按默认处理）", path, exc_info=True)
        return default


def _save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        _log.warning("写入 JSON 失败 path=%s", path, exc_info=True)
        return False


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ----------------------------------------------------------------------
# Config 单例
# ----------------------------------------------------------------------
class Config:
    """配置中心实例。持有 schema + 元数据 + 路径/偏好/开关的统一入口。"""

    def __init__(self):
        self.schema = SCHEMA_VERSION
        self.meta = self._load_meta()
        self._migrate_if_needed()
        self._touch_meta()
        _log.info(
            "配置中心就绪 pref=%s schema=%d meta=%s",
            pref_dir(), self.schema, meta_path(),
        )

    # ---- 路径转发（面向对象用法；与模块函数等价） ----
    @property
    def pref_dir(self):
        return pref_dir()

    @property
    def theme_path(self):
        return theme_path()

    @property
    def welcome_flag_path(self):           # 【第27轮】
        return welcome_flag_path()

    @property
    def log_dir(self):
        return log_dir()

    @property
    def log_file_path(self):
        return log_file_path()

    @property
    def font_cache_path(self):
        return font_cache_path()

    @property
    def library_dir(self):
        return library_dir_path()

    # ---- 主题偏好（与 legacy 同文件同格式，原子写） ----
    def load_theme_pref(self, default="light"):
        data = _load_json(theme_path(), {})
        mode = data.get("mode", default)
        return mode if mode in ("light", "dark") else default

    def save_theme_pref(self, mode):
        data = _load_json(theme_path(), {})
        data["mode"] = mode
        return _save_json(theme_path(), data)

    # ---- 元数据 + 版本迁移 ----
    def _load_meta(self):
        return _load_json(meta_path(), {})

    def _migrate_if_needed(self):
        old = self.meta.get("schema", 0)
        try:
            old = int(old)
        except Exception:
            old = 0

        if old == SCHEMA_VERSION:
            return

        if old == 0:
            _log.info("配置元数据初始化（schema %d）", SCHEMA_VERSION)
        else:
            _log.info("配置 schema 升级 %d -> %d，执行迁移", old, SCHEMA_VERSION)

        self.meta = self._migrate(self.meta, old, SCHEMA_VERSION)
        self.meta["schema"] = SCHEMA_VERSION

    def _migrate(self, data, old_schema, new_schema):
        """版本迁移钩子。本轮无字段需迁移，原样返回 + 记 debug。"""
        _log.debug("配置迁移 %d -> %d：无字段需转换", old_schema, new_schema)
        return data

    def _touch_meta(self):
        self.meta.setdefault("created", _now_iso())
        self.meta["last_run"] = _now_iso()
        self.meta["schema"] = SCHEMA_VERSION
        _save_json(meta_path(), self.meta)


# ----------------------------------------------------------------------
# 单例访问（double-check 加锁；构造有写盘副作用，保证只构造一次）
# ----------------------------------------------------------------------
_CONFIG = None
_CONFIG_LOCK = threading.Lock()


def get_config():
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    with _CONFIG_LOCK:
        if _CONFIG is None:
            _CONFIG = Config()
    return _CONFIG


# ----------------------------------------------------------------------
# 偏好便捷函数（无需显式拿单例；转发 get_config）
# ----------------------------------------------------------------------
def load_theme_pref(default="light"):
    return get_config().load_theme_pref(default)


def save_theme_pref(mode):
    return get_config().save_theme_pref(mode)