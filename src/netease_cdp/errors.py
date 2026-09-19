# -*- coding: utf-8 -*-
"""异常层次。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations


class NeteaseCDPError(RuntimeError):
    """本库所有异常的基类。

    继承 ``RuntimeError`` 而非 ``Exception``：CDP 失败都是「运行时环境问题」
    （客户端没开、端口没起、页面没加载完），不是调用方写错了代码。
    """


class CDPUnavailable(NeteaseCDPError):
    """连不上调试端口，或端口上没有可用页面。

    绝大多数情况是网易云没有以 ``--remote-debugging-port=<port>`` 启动。
    先试 :meth:`netease_cdp.NeteaseCDP.ensure_ready`。
    """


class CDPTimeout(NeteaseCDPError):
    """命令已发出，但在超时内没等到对应 ``id`` 的回包。"""


class ScriptError(NeteaseCDPError):
    """页面里的 JS 抛异常了（``exceptionDetails`` 非空）。

    通常意味着网易云前端改版，注入的选择器/Redux 结构对不上了。
    """


class ClientNotFound(NeteaseCDPError):
    """找不到 ``cloudmusic.exe``。

    只有 :meth:`netease_cdp.NeteaseCDP.restart_client` 会抛这个——
    其余方法在缺 exe 路径时安静地返回 ``False``。
    """


__all__ = [
    "NeteaseCDPError",
    "CDPUnavailable",
    "CDPTimeout",
    "ScriptError",
    "ClientNotFound",
]
