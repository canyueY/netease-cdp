# -*- coding: utf-8 -*-
"""会话层：目标发现、JS 求值、超时与异常。

这些用例跑在**真实** WebSocket 之上（见 conftest 的 FakeCDP），
所以 JSON 组包、id 匹配、事件插播、超时都真的被执行到了。
"""
from __future__ import annotations

import pytest

from netease_cdp import session as S
from netease_cdp.config import CDPConfig
from netease_cdp.errors import CDPTimeout, CDPUnavailable, ScriptError


class TestAvailable:
    def test_true_for_fake_server(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        assert S.available(cfg_for(srv)) is True

    def test_false_when_no_listener(self):
        assert S.available(CDPConfig(port=1, timeout=0.4)) is False

    def test_ws_url_bypasses_json_page_requirement(self, fake_cdp, cfg_for):
        # 显式 ws_url 时不读 /json，所以 /json 里没有 page 也照样可用
        # （SSH 端口转发场景下只能这样）
        srv = fake_cdp(target_type="service_worker")
        assert S.available(cfg_for(srv)) is True

    def test_false_when_json_has_no_page(self, fake_cdp):
        # 不显式给 ws_url，且 /json 里只有 service_worker → 不可用
        srv = fake_cdp(target_type="service_worker")
        cfg = CDPConfig(port=srv.port, timeout=3.0)
        assert S.available(cfg) is False

    def test_false_when_ws_url_given_but_dead(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        cfg = cfg_for(srv, ws_url="ws://127.0.0.1:1/devtools/page/X")
        # 主机校验通过，但连不上 → install 层面为 False
        assert S.debugger_url(cfg) == "ws://127.0.0.1:1/devtools/page/X"
        with pytest.raises(Exception):
            S.evaluate("x", cfg=cfg, timeout=0.5)

    def test_false_when_no_ws_url(self, fake_cdp, cfg_for):
        srv = fake_cdp(with_ws=False)
        assert S.available(cfg_for(srv)) is False


class TestDebuggerUrl:
    def test_resolves(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        url = S.debugger_url(cfg_for(srv))
        assert url.startswith("ws://127.0.0.1:")

    def test_target_exposes_metadata(self, fake_cdp, cfg_for):
        # 显式 ws_url 时元数据只存在于 /json，所以直接验证解析函数
        srv = fake_cdp(target_title="网易云音乐")
        cfg = cfg_for(srv, ws_url="")  # 清掉 ws_url → 走自动发现
        target = S.pick_page_target(S.fetch_targets(cfg), cfg)
        assert target["title"] == "网易云音乐"
        assert "music.163.com" in target["url"]

    def test_debugger_target_minimal_when_ws_url_given(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        t = S.debugger_target(cfg_for(srv))
        assert t["webSocketDebuggerUrl"].startswith("ws://")
        assert t["type"] == "page"

    def test_rejects_remote_host(self):
        # 调试端点等于完全控制权，默认只允许环回地址
        from netease_cdp.config import CDPConfig

        cfg = CDPConfig(ws_url="ws://evil.example:9222/devtools/page/X")
        with pytest.raises(CDPUnavailable) as ei:
            S.debugger_url(cfg)
        assert "evil.example" in str(ei.value)

    def test_remote_allowed_when_opted_in(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        cfg = cfg_for(srv, allow_remote_host=True)
        assert S.debugger_url(cfg).startswith("ws://")

    def test_explicit_ws_url_wins(self, fake_cdp, cfg_for):
        # 显式 ws_url 时不去读 /json（SSH 转发场景下自动发现的地址是错的）
        srv = fake_cdp()
        cfg = cfg_for(srv, ws_url="ws://127.0.0.1:1/devtools/page/X")
        assert S.debugger_url(cfg) == "ws://127.0.0.1:1/devtools/page/X"

    def test_explicit_ws_url_still_checks_host(self):
        from netease_cdp.config import CDPConfig

        cfg = CDPConfig(ws_url="ws://192.168.1.9:9222/devtools/page/X")
        with pytest.raises(CDPUnavailable):
            S.debugger_url(cfg)


class TestEvaluate:
    def test_returns_scalar(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=lambda _e: 42)
        assert S.evaluate("return 42;", cfg=cfg_for(srv)) == 42

    def test_returns_dict(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=lambda _e: {"a": 1, "b": [2, 3]})
        assert S.evaluate("return {};", cfg=cfg_for(srv)) == {"a": 1, "b": [2, 3]}

    def test_returns_none_for_null(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=lambda _e: None)
        assert S.evaluate("return null;", cfg=cfg_for(srv)) is None

    def test_expression_reaches_server(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        S.evaluate("return 'hello-世界';", cfg=cfg_for(srv))
        assert "hello-世界" in srv.last()

    def test_skips_interleaved_events(self, fake_cdp, cfg_for):
        # FakeCDP 每条求值前都会插一条 consoleAPICalled 通知；
        # 若客户端没跳过它就会解析错
        srv = fake_cdp(handler=lambda _e: "ok")
        assert S.evaluate("return 1;", cfg=cfg_for(srv)) == "ok"

    def test_script_error_is_raised(self, fake_cdp, cfg_for):
        srv = fake_cdp(raise_on_eval="TypeError: x is not a function")
        with pytest.raises(ScriptError) as ei:
            S.evaluate("boom", cfg=cfg_for(srv))
        assert "is not a function" in str(ei.value)

    def test_handler_exception_becomes_script_error(self, fake_cdp, cfg_for):
        def boom(_expr):
            raise KeyError("nope")

        srv = fake_cdp(handler=boom)
        with pytest.raises(ScriptError):
            S.evaluate("x", cfg=cfg_for(srv))

    def test_timeout_when_id_never_matches(self, fake_cdp, cfg_for):
        srv = fake_cdp(omit_id=True)
        with pytest.raises(CDPTimeout):
            S.evaluate("x", cfg=cfg_for(srv), timeout=0.8)

    def test_timeout_when_server_is_slow(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=lambda _e: True, delay_sec=2.5)
        with pytest.raises(CDPTimeout):
            S.evaluate("x", cfg=cfg_for(srv), timeout=0.7)

    def test_unavailable_when_port_dead(self):
        with pytest.raises(CDPUnavailable):
            S.evaluate("x", cfg=CDPConfig(port=1, timeout=0.4))

    def test_custom_msg_id(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=lambda _e: "ok")
        assert S.evaluate("x", cfg=cfg_for(srv), msg_id=99) == "ok"


class TestSession:
    def test_available(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        assert S.Session(cfg_for(srv)).available() is True

    def test_url(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        assert S.Session(cfg_for(srv)).url().startswith("ws://")

    def test_target_and_evaluate(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=lambda _e: [1, 2])
        s = S.Session(cfg_for(srv))
        assert s.target()["type"] == "page"
        assert s.evaluate("x") == [1, 2]

    def test_config_defaults_when_none(self):
        assert S.Session().config.port == 9222
