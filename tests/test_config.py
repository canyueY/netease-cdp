# -*- coding: utf-8 -*-
"""配置校验与目标发现。"""
from __future__ import annotations

import pytest

from netease_cdp.config import CARD_KEYWORDS, CDPConfig
from netease_cdp.errors import CDPUnavailable
from netease_cdp.session import fetch_targets, pick_page_target


class TestCDPConfig:
    def test_defaults_usable(self):
        cfg = CDPConfig()
        assert cfg.port == 9222
        assert cfg.timeout > 0
        assert cfg.retries >= 1
        assert cfg.exe_path == ""

    def test_http_endpoint(self):
        assert CDPConfig(port=9333).http_endpoint == "http://127.0.0.1:9333/json"

    def test_rejects_bad_port(self):
        # 0 也算非法：那是「让内核挑端口」，对 CDP 客户端没有意义
        for bad in (0, -1, 70000):
            with pytest.raises(ValueError):
                CDPConfig(port=bad)

    def test_rejects_bad_timeout(self):
        for bad in (0, -1.0):
            with pytest.raises(ValueError):
                CDPConfig(timeout=bad)

    def test_rejects_bad_retries(self):
        with pytest.raises(ValueError):
            CDPConfig(retries=0)

    def test_replace_returns_new_instance(self):
        base = CDPConfig()
        other = base.replace(port=1234)
        assert other.port == 1234
        assert base.port == 9222  # 原对象不变
        assert other is not base

    def test_frozen(self):
        with pytest.raises(Exception):
            CDPConfig().port = 1  # type: ignore[misc]

    def test_allow_remote_host_defaults_off(self):
        assert CDPConfig().allow_remote_host is False


class TestCardKeywords:
    def test_known_cards(self):
        for key in ("daily", "private_radar", "heart_mode", "private_roam"):
            assert key in CARD_KEYWORDS
            assert CARD_KEYWORDS[key]

    def test_values_are_tuples(self):
        for kws in CARD_KEYWORDS.values():
            assert isinstance(kws, tuple)


class TestPickPageTarget:
    def _cfg(self, **kw):
        return CDPConfig(**kw)

    def _page(self, url, ws="ws://127.0.0.1:9222/devtools/page/X"):
        return {"type": "page", "url": url, "webSocketDebuggerUrl": ws, "title": "t"}

    def test_matches_url_hint(self):
        targets = [self._page("devtools://x"), self._page("https://music.163.com/#/x")]
        got = pick_page_target(targets, self._cfg())
        assert "music.163.com" in got["url"]

    def test_ignores_non_page_targets(self):
        targets = [
            {"type": "service_worker", "url": "https://music.163.com/sw",
             "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/SW"},
            self._page("https://music.163.com/#/x"),
        ]
        assert pick_page_target(targets, self._cfg())["type"] == "page"

    def test_falls_back_to_first_page(self):
        targets = [self._page("https://example.com/")]
        got = pick_page_target(targets, self._cfg())
        assert got["url"] == "https://example.com/"

    def test_fallback_can_be_disabled(self):
        targets = [self._page("https://example.com/")]
        with pytest.raises(CDPUnavailable):
            pick_page_target(targets, self._cfg(allow_url_fallback=False))

    def test_no_pages_at_all(self):
        with pytest.raises(CDPUnavailable):
            pick_page_target([], self._cfg())
        with pytest.raises(CDPUnavailable):
            pick_page_target([{"type": "page", "url": "u"}], self._cfg())  # 没有 ws 地址

    def test_first_hint_wins(self):
        # orpheus 排在 music.163.com 后面，同时命中时以 hints 顺序为准
        h1 = self._page("https://music.163.com/#/a")
        h2 = self._page("https://orpheus.example/b")
        assert pick_page_target([h2, h1], self._cfg()) is h1

    def test_custom_hints(self):
        targets = [self._page("https://my.fork.local/app")]
        cfg = CDPConfig(url_hints=("my.fork.local",))
        assert pick_page_target(targets, cfg)["url"].endswith("/app")


class TestFetchTargets:
    def test_raises_unavailable_on_dead_port(self):
        # 1 端口上不该有东西在监听
        with pytest.raises(CDPUnavailable):
            fetch_targets(CDPConfig(port=1, timeout=0.5))

    def test_reads_real_json_endpoint(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        targets = fetch_targets(cfg_for(srv))
        assert isinstance(targets, list) and len(targets) == 1
        assert targets[0]["type"] == "page"

    def test_unavailable_message_mentions_port(self):
        with pytest.raises(CDPUnavailable) as ei:
            fetch_targets(CDPConfig(port=1, timeout=0.5))
        assert "1" in str(ei.value)
