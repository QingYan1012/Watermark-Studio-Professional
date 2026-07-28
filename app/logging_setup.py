# -*- coding: utf-8 -*-
"""
Watermark Studio Professional - 统一日志系统。

纯增量、零回归：
- root logger = 控制台 handler（默认 INFO，可由环境变量 WS_LOG_LEVEL 调整）
              + 落盘 RotatingFileHandler（日志目录/wsp.log，2MB × 3 滚动，
                DEBUG 全量，带时间戳/文件名/行号）。
- sys.excepthook：主线程未捕获异常写入日志。
- threading.excepthook：后台线程未捕获异常写入日志。

本轮（第22轮）改动：日志目录/路径改从 app.config 取（配置中心单一来源），
并带 try 回退——app.config 不可用时退回硬编码路径，日志照常工作，绝不阻塞。

用法：
    from app.logging_setup import setup_logging, get_logger

    setup_logging()                 # 程序启动时调一次（幂等）
    log = get_logger("ws.perf")     # 任意模块拿一个带名字的 logger

幂等：setup_logging 多次调用只挂一次 handler。
惰性：get_logger 在尚未 setup 时会自动 setup 一次，保证“永远可用、不丢日志”。
健壮：日志目录/文件创建失败时，仅文件 handler 缺失，控制台仍工作，绝不抛异常。

回退：
    set WS_LOG_LEVEL=WARNING        # 控制台只看警告以上（文件仍 DEBUG 全量）
"""

import logging
import logging.handlers
import os
import sys
import threading


_INITIALIZED = False


# ----------------------------------------------------------------------
# 路径来源：优先配置中心；不可用时回退硬编码（与 config 计算结果一致）。
# 注意：此处【不】在 import 期创建目录，目录创建留给 setup_logging。
# ----------------------------------------------------------------------
try:
    from .config import log_dir as _cfg_log_dir, log_file_path as _cfg_log_file
    _HAS_CONFIG = True
except Exception:
    _HAS_CONFIG = False

    def _cfg_log_dir():
        return os.path.join(os.path.expanduser("~"), ".watermark_studio")

    def _cfg_log_file():
        return os.path.join(_cfg_log_dir(), "wsp.log")


def _level_from_env():
    raw = os.environ.get("WS_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def _install_excepthooks():
    """挂全局兜底钩子。失败不影响日志主功能。"""
    try:
        _orig_sys = sys.excepthook

        def _sys_hook(exc_type, exc, tb):
            if issubclass(exc_type, KeyboardInterrupt):
                _orig_sys(exc_type, exc, tb)
                return
            logging.getLogger("ws.fatal").error(
                "未捕获异常", exc_info=(exc_type, exc, tb)
            )

        sys.excepthook = _sys_hook
    except Exception:
        pass

    try:
        def _thread_hook(args):
            logging.getLogger("ws.thread").error(
                "后台线程未捕获异常 thread=%s",
                getattr(args, "thread", None),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        threading.excepthook = _thread_hook
    except Exception:
        pass


def setup_logging():
    """
    初始化日志系统。幂等：重复调用只挂一次 handler。

    返回 root logger。
    """
    global _INITIALIZED

    if _INITIALIZED:
        return logging.getLogger()

    _INITIALIZED = True

    console_level = _level_from_env()

    # 从配置中心取路径（回退已在 _cfg_* 内处理）
    try:
        log_dir = _cfg_log_dir()
        log_path = _cfg_log_file()
    except Exception:
        log_dir = os.path.join(os.path.expanduser("~"), ".watermark_studio")
        log_path = os.path.join(log_dir, "wsp.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    for h in list(root.handlers):
        try:
            root.removeHandler(h)
        except Exception:
            pass

    fmt_console = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(console_level)
    ch.setFormatter(fmt_console)
    root.addHandler(ch)

    file_ok = False
    try:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        ))
        root.addHandler(fh)
        file_ok = True
    except Exception:
        pass

    _install_excepthooks()

    root.info(
        "日志系统已初始化 console=%s file=%s config=%s -> %s",
        logging.getLevelName(console_level),
        "on" if file_ok else "off",
        "on" if _HAS_CONFIG else "off",
        log_path if file_ok else "(disabled)",
    )

    return root


def get_logger(name):
    """
    返回带名字的 logger。

    若尚未 setup_logging，则惰性初始化一次，保证：
    - 任何模块在任何时机调用都不会丢日志到文件；
    - 即使调用早于 main.py 的显式 setup（例如某些 import 期活动），也能落盘。
    """
    if not _INITIALIZED:
        try:
            setup_logging()
        except Exception:
            pass
    return logging.getLogger(name)


def log_path():
    """返回日志文件路径（供界面/诊断展示）。带 config 回退。"""
    try:
        return _cfg_log_file()
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".watermark_studio", "wsp.log")