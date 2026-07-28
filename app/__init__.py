# -*- coding: utf-8 -*-
"""
app 包：应用级基础设施（日志、配置、路径等）。

当前仅含日志系统（app/logging_setup.py）。
后续配置统一（app/config.py）、路径管理（app/paths.py）等会逐步落在这里。

本包为纯增量：即便整个 app 包缺失，主程序仍应能启动（调用方均用 try/except 保护）。
"""