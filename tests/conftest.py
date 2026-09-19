# -*- coding: utf-8 -*-
"""测试夹具：一个**真实**的假 CDP 服务器。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

刻意不用 monkeypatch 换掉 `websockets.connect`：那样测不到 JSON 组包、
`id` 匹配、事件插播跳过、超时这些真正容易写错的地方。这里起真的 HTTP
端点 + 真的 WebSocket 服务端，让整条链路跑通。

**为什么是两个端口。** 真实 CDP 在同一个端口上既提供 ``GET /json`` 又接受
WebSocket 升级，但 Windows 不允许两个 socket 绑同一端口（没有
SO_REUSEPORT）。所以夹具起两个服务器，并通过 :attr:`CDPConfig.ws_url`
显式指定 WebSocket 地址——这个字段在真实场景里也有用（SSH 端口转发时
调试端口对外暴露的地址与内部不一致）。
"""
from __future__ import annotations

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from netease_cdp.config import CDPConfig  # noqa: E402

EvalHandler = Callable[[str], Any]


def _free_port() -> int:
    """让内核挑一个空闲端口。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _listen_socket() -> socket.socket:
    """返回一个**仍处于监听状态**的 socket。

    比「先问内核要个端口号、关掉、再让别人绑」可靠：那中间有个窗口，
    在 Windows 上很容易被别的进程抢走（实测会随机 EADDRINUSE）。
    直接把这个 socket 交给 ``websockets.serve(sock=...)`` 就没有窗口了。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(8)
    return s


class FakeCDP:
    """极简 CDP 服务器：HTTP ``/json`` + WebSocket 求值端。"""

    def __init__(
        self,
        handler: EvalHandler | None = None,
        *,
        target_url: str = "https://music.163.com/#/discover",
        target_title: str = "网易云音乐",
        target_type: str = "page",
        with_ws: bool = True,
        delay_sec: float = 0.0,
        raise_on_eval: str = "",
        omit_id: bool = False,
        insert_event: bool = True,
    ) -> None:
        self.handler = handler or (lambda _expr: True)
        self.target_url = target_url
        self.target_title = target_title
        self.target_type = target_type
        self.with_ws = with_ws
        self.delay_sec = delay_sec
        self.raise_on_eval = raise_on_eval
        self.omit_id = omit_id
        self.insert_event = insert_event

        self.expressions: list[str] = []
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._ws_thread: threading.Thread | None = None
        self._ws_ready = threading.Event()
        self._ws_stop = threading.Event()
        self._ws_sock: socket.socket | None = None
        self._server: Any = None
        #: HTTP ``/json`` 端口
        self.port = 0
        #: WebSocket 端口（与 HTTP 不同，见模块 docstring）
        self.ws_port = 0

    # -- 生命周期 -------------------------------------------------------

    def start(self) -> "FakeCDP":
        # 端口先占好再启动：否则客户端可能抢在 bind 之前来连（竞态）
        self.port = _free_port()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), self._handler_class())
        self._httpd.daemon_threads = True
        self._http_thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True, name="fake-cdp-http"
        )
        self._http_thread.start()

        if self.with_ws:
            self._ws_sock = _listen_socket()
            self.ws_port = int(self._ws_sock.getsockname()[1])
            self._ws_thread = threading.Thread(
                target=self._serve_ws, daemon=True, name="fake-cdp-ws"
            )
            self._ws_thread.start()
            if not self._ws_ready.wait(timeout=5):
                raise RuntimeError("假 CDP WebSocket 服务器启动超时")
        return self

    def stop(self) -> None:
        self._ws_stop.set()
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._http_thread is not None:
            self._http_thread.join(timeout=3)
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=3)
        if self._ws_sock is not None:
            try:
                self._ws_sock.close()
            except OSError:
                pass
            self._ws_sock = None

    def __enter__(self) -> "FakeCDP":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- HTTP /json -----------------------------------------------------

    def ws_url(self) -> str:
        """WebSocket 调试地址。"""
        return f"ws://127.0.0.1:{self.ws_port}/devtools/page/FAKE"

    def target_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": "FAKE-TARGET",
            "type": self.target_type,
            "title": self.target_title,
            "url": self.target_url,
        }
        if self.with_ws:
            out["webSocketDebuggerUrl"] = self.ws_url()
        return out

    def _handler_class(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/") not in ("/json", "/json/list"):
                    self.send_error(404)
                    return
                body = json.dumps([outer.target_dict()], ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass  # 静音

        return Handler

    # -- WebSocket ------------------------------------------------------

    def _reply_for(self, expression: str) -> dict[str, Any]:
        if self.delay_sec:
            import time

            time.sleep(self.delay_sec)
        with self._lock:
            self.expressions.append(expression)
        if self.raise_on_eval:
            return self._exception(self.raise_on_eval)
        try:
            value = self.handler(expression)
        except Exception as exc:  # handler 自己炸了 → 当成页面异常
            return self._exception(f"{type(exc).__name__}: {exc}")
        return {"result": {"result": {"type": "object", "value": value}}}

    @staticmethod
    def _exception(description: str) -> dict[str, Any]:
        return {
            "result": {
                "exceptionDetails": {
                    "text": "Uncaught",
                    "exception": {"description": description},
                }
            }
        }

    def _serve_ws(self) -> None:
        from websockets.sync.server import serve

        outer = self

        def connection(ws) -> None:
            for raw in ws:
                outer._on_message(ws, raw)

        # 直接把已监听的 socket 交出去：不再有「端口号与绑定之间」的竞态。
        # sync 版 Server 只有 serve_forever()/shutdown()（没有 asyncio 版的
        # poll_interval），退出靠 shutdown()。
        with serve(connection, sock=outer._ws_sock, close_timeout=1) as server:
            outer._server = server
            outer._ws_ready.set()
            try:
                server.serve_forever()
            except Exception:
                pass

    def _on_message(self, ws: Any, raw: Any) -> None:
        if isinstance(raw, bytes):
            return
        try:
            msg = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(msg, dict) or msg.get("method") != "Runtime.evaluate":
            return
        expr = str((msg.get("params") or {}).get("expression") or "")
        # 先插播一条事件通知，验证客户端会跳过非目标 id 的消息
        if self.insert_event:
            ws.send(json.dumps({"method": "Runtime.consoleAPICalled", "params": {}}))
        reply = self._reply_for(expr)
        if not self.omit_id:
            reply["id"] = msg.get("id")
        ws.send(json.dumps(reply, ensure_ascii=False))

    # -- 断言辅助 -------------------------------------------------------

    def saw(self, needle: str) -> bool:
        with self._lock:
            return any(needle in e for e in self.expressions)

    def last(self) -> str:
        with self._lock:
            return self.expressions[-1] if self.expressions else ""


@pytest.fixture
def fake_cdp() -> Any:
    """起一个假 CDP 服务器，测完自动关。"""
    servers: list[FakeCDP] = []

    def factory(**kwargs: Any) -> FakeCDP:
        srv = FakeCDP(**kwargs).start()
        servers.append(srv)
        return srv

    yield factory
    for srv in servers:
        srv.stop()


@pytest.fixture
def cfg_for() -> Any:
    """按假服务器端口造配置。

    显式给 ``ws_url``，因为夹具的 HTTP 与 WebSocket 不在同一端口上。
    """

    def factory(srv: FakeCDP, **kw: Any) -> CDPConfig:
        kw.setdefault("timeout", 3.0)
        if srv.with_ws:
            kw.setdefault("ws_url", srv.ws_url())
        return CDPConfig(port=srv.port, **kw)

    return factory
