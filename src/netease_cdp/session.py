# -*- coding: utf-8 -*-
"""CDP 会话层：目标发现 + Runtime.evaluate。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

只负责「把一段 JS 送进页面并取回值」，不含任何业务语义。
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from .config import CDPConfig
from .errors import CDPTimeout, CDPUnavailable, ScriptError


def fetch_targets(cfg: CDPConfig, *, timeout: float | None = None) -> list[dict[str, Any]]:
    """读取 ``/json`` 的目标列表。

    :raises CDPUnavailable: 端口不通或返回的不是数组
    """
    url = cfg.http_endpoint
    try:
        with urlopen(url, timeout=float(timeout or cfg.timeout)) as resp:
            raw = resp.read()
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise CDPUnavailable(
            f"连不上 CDP 端口 {cfg.port}（{url}）：{exc}。"
            f"网易云需要以 --remote-debugging-port={cfg.port} 启动。"
        ) from exc
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CDPUnavailable(f"{url} 返回的不是合法 JSON：{exc}") from exc
    if not isinstance(data, list):
        raise CDPUnavailable(f"{url} 返回 {type(data).__name__}，期望数组")
    return [t for t in data if isinstance(t, dict)]


def pick_page_target(
    targets: list[dict[str, Any]], cfg: CDPConfig
) -> dict[str, Any]:
    """从目标列表里挑出网易云那个 page。

    两轮筛选：先按 :attr:`CDPConfig.url_hints` 认 URL，都认不出来再退到
    第一个有 ``webSocketDebuggerUrl`` 的 page（可被
    ``allow_url_fallback=False`` 关掉）。
    """
    pages = [
        t
        for t in targets
        if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]
    if not pages:
        raise CDPUnavailable(
            f"CDP 端口 {cfg.port} 上有 {len(targets)} 个目标，但没有可用的 page"
        )
    hints = tuple(h.lower() for h in cfg.url_hints if h)
    if hints:
        for hint in hints:
            for t in pages:
                if hint in str(t.get("url") or "").lower():
                    return t
    if cfg.allow_url_fallback:
        return pages[0]
    raise CDPUnavailable(
        f"端口 {cfg.port} 上没有 URL 命中 {hints} 的页面；"
        f"现有页面：{[str(t.get('url'))[:80] for t in pages]}"
    )


def _check_host(ws_url: str, cfg: CDPConfig) -> None:
    """确认 WebSocket 端点指向本机。

    调试端口连上就等于交出页面控制权，所以默认只允许环回地址。
    ``urlparse`` 会把 IPv6 主机名连方括号一起返回（``[::1]``），
    所以两边都归一化掉方括号再比。
    """
    if cfg.allow_remote_host:
        return
    host = (urlparse(ws_url).hostname or "").lower()
    allowed = {h.strip("[]").lower() for h in cfg.allowed_hosts}
    if host not in allowed:
        raise CDPUnavailable(
            f"拒绝连接到非本机 CDP 端点 {host!r}（允许：{sorted(allowed)}）。"
            f"确认风险后可设 allow_remote_host=True。"
        )


def debugger_url(cfg: CDPConfig) -> str:
    """取当前网易云页面的 WebSocket 调试地址。

    若 :attr:`CDPConfig.ws_url` 非空则直接采用（仍需过本机校验），
    否则读 ``/json`` 自动发现。

    :raises CDPUnavailable: 端口不通 / 没有合适页面 / 端点非本机
    """
    if cfg.ws_url:
        _check_host(cfg.ws_url, cfg)
        return cfg.ws_url
    target = pick_page_target(fetch_targets(cfg), cfg)
    ws_url = str(target["webSocketDebuggerUrl"])
    _check_host(ws_url, cfg)
    return ws_url


def debugger_target(cfg: CDPConfig) -> dict[str, Any]:
    """同 :func:`debugger_url`，但返回完整目标信息（含 title/url），便于诊断。

    走显式 ``ws_url`` 时没有目标元数据，返回一个只含 ``url`` 的最小字典。
    """
    if cfg.ws_url:
        _check_host(cfg.ws_url, cfg)
        return {"type": "page", "url": "", "title": "", "webSocketDebuggerUrl": cfg.ws_url}
    target = pick_page_target(fetch_targets(cfg), cfg)
    _check_host(str(target["webSocketDebuggerUrl"]), cfg)
    return target


def available(cfg: CDPConfig | None = None) -> bool:
    """调试端口是否可用。任何失败都返回 ``False``，不抛异常。"""
    try:
        debugger_url(cfg or CDPConfig())
        return True
    except Exception:
        return False


def _sync_connect(ws_url: str, timeout: float):
    """取同步连接工厂。

    ``websockets`` 15 起把同步客户端放在 ``websockets.sync.client``；
    老版本没有这个模块，回退到 ``websockets.client``（其 ``connect``
    同样接受 ``open_timeout``）。
    """
    try:
        from websockets.sync.client import connect  # type: ignore
    except ImportError:  # websockets < 12
        from websockets.client import connect  # type: ignore

        return connect(ws_url, open_timeout=timeout, close_timeout=1)
    return connect(ws_url, open_timeout=timeout, close_timeout=1)


def evaluate(
    expression: str,
    *,
    cfg: CDPConfig | None = None,
    timeout: float | None = None,
    msg_id: int = 1,
) -> Any:
    """在网易云页面里跑一段 JS，返回其值。

    表达式按 ``returnByValue=True, awaitPromise=True`` 求值，所以返回值
    必须是可 JSON 化的（对象、数组、字符串、数字、布尔、null）。
    ``Runtime.evaluate`` 的顶层不允许 ``return``——用
    :func:`netease_cdp.js.wrap` 包一层。

    :raises CDPUnavailable: 端口不通或页面不存在
    :raises ScriptError: 页面里的 JS 抛异常
    :raises CDPTimeout: 命令已发出但在超时内没有回包
    """
    cfg = cfg or CDPConfig()
    limit = float(timeout or cfg.timeout)
    ws_url = debugger_url(cfg)
    payload = json.dumps(
        {
            "id": int(msg_id),
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }
    )

    try:
        ws = _sync_connect(ws_url, limit)
    except Exception as exc:
        raise CDPUnavailable(f"WebSocket 连接失败（{ws_url}）：{exc}") from exc

    try:
        with ws:
            ws.send(payload)
            deadline = time.time() + limit
            while time.time() < deadline:
                remaining = deadline - time.time()
                try:
                    raw = ws.recv(timeout=max(0.1, remaining))
                except TimeoutError as exc:
                    raise CDPTimeout(f"CDP 指令超时（>{limit:.1f}s）") from exc
                try:
                    msg = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue  # CDP 会插播事件通知，跳过
                if not isinstance(msg, dict) or msg.get("id") != int(msg_id):
                    continue
                result = msg.get("result") or {}
                if result.get("exceptionDetails"):
                    exc_info = result["exceptionDetails"].get("exception") or {}
                    detail = str(
                        exc_info.get("description")
                        or result["exceptionDetails"].get("text")
                        or "CDP 执行异常"
                    )
                    raise ScriptError(detail)
                return (result.get("result") or {}).get("value")
    except (CDPTimeout, ScriptError):
        raise
    except TimeoutError as exc:
        raise CDPTimeout(f"CDP 指令超时（>{limit:.1f}s）") from exc
    except OSError as exc:
        raise CDPUnavailable(f"WebSocket 通信中断：{exc}") from exc
    raise CDPTimeout(f"CDP 指令超时（>{limit:.1f}s，未收到 id={msg_id} 的回包）")


class Session:
    """可复用的会话对象。

    本身不保持长连接——每次 :meth:`evaluate` 重新解析目标并新建 WebSocket。
    这是刻意的：网易云页面重载会换掉 ``webSocketDebuggerUrl``，而桌宠这类
    调用方是低频、突发的（几秒一次），为省一次握手而缓存失效的 URL 不划算。
    """

    def __init__(self, config: CDPConfig | None = None) -> None:
        self.config = config or CDPConfig()

    # -- 目标 -----------------------------------------------------------

    def available(self) -> bool:
        """调试端口是否可用。"""
        return available(self.config)

    def target(self) -> dict[str, Any]:
        """当前网易云页面目标（含 ``title`` / ``url``）。"""
        return debugger_target(self.config)

    def url(self) -> str:
        """当前网易云页面的 WebSocket 调试地址。"""
        return debugger_url(self.config)

    # -- 求值 -----------------------------------------------------------

    def evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        """跑一段 JS 并返回值。"""
        return evaluate(expression, cfg=self.config, timeout=timeout)


__all__ = [
    "Session",
    "available",
    "debugger_target",
    "debugger_url",
    "evaluate",
    "fetch_targets",
    "pick_page_target",
]
