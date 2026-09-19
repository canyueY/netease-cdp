# -*- coding: utf-8 -*-
"""控制器：状态读取、点播、发现页、异常容忍。"""
from __future__ import annotations

from netease_cdp import NeteaseCDP
from netease_cdp.client import (
    cdp_get_playing_track_info,
    cdp_is_playing,
    cdp_play_song,
)
from netease_cdp.config import CDPConfig
from netease_cdp.models import PlayResult, Track


class FakeMusicState:
    """假客户端的播放状态机。

    按注入的 JS 属于哪一类来更新内部状态——这样测试走的是「表达式内容
    决定行为」这条路，而不是「第几次调用」。
    """

    def __init__(self) -> None:
        self.track_id = ""
        self.name = ""
        self.artists: list[str] = []
        self.duration = 0
        self.playing = False
        self.dispatched: list[tuple[str, str]] = []
        self.nav_hash = "#/discover"
        #: 发现页上当前「找不到」的卡片关键词
        self.missing_cards: set[str] = set()
        #: 日推详情页是否已经渲染好
        self.daily_page_ready = False

    def __call__(self, expr: str):
        if "resourceArtists" in expr:  # current_track
            return {
                "id": self.track_id,
                "name": self.name,
                "artists": "/".join(self.artists),
                "playing": self.playing,
                "duration": self.duration,
            }
        if "s.playing?.resourceTrackId" in expr:
            return self.track_id if ("return !!" in expr) else str(self.track_id)
        if "doAction" in expr:  # dispatch
            self._on_dispatch(expr)
            return True
        if "btn-next" in expr:  # DOM 切歌
            return True
        # 顺序要紧：日推页面脚本里**也**含卡片相关片段（它调 findSection /
        # 「个性化推荐」），所以必须先判「播放全部」这条更具体的特征
        if "播放全部" in expr:  # 日推详情页
            if not self.daily_page_ready:
                return {"ok": False, "reason": "navigating-daily-page", "needRetry": True}
            self.playing = True
            self.track_id = self.track_id or "7001"
            return {"ok": True, "how": "play-all"}
        if "location.hash" in expr:  # navigate
            self._on_navigate(expr)
            return self.nav_hash
        if "个性化推荐" in expr:  # 发现页卡片
            return self._on_card(expr)
        return True

    def _on_dispatch(self, expr: str) -> None:
        action = ""
        for cand in ("playNext", "playPrev", "addToPlayList", "play"):
            if f"actionId:'{cand}'" in expr:
                action = cand
                break
        self.dispatched.append((action, expr))
        if action != "play":
            return
        # 卡片点播也是走 play，但没有显式 id——别把它当成点单曲
        if "String(" not in expr:
            self.playing = True
            if not self.track_id:
                self.track_id = "7777"
                self.name = "卡片第一首"
            return
        sid = expr.split("String(", 1)[1].split(")", 1)[0]
        self.track_id = sid
        self.name = f"曲目{sid}"
        self.artists = ["测试歌手"]
        self.duration = 200000
        self.playing = True

    def _on_navigate(self, expr: str) -> None:
        if "discover/recommend" in expr:
            self.nav_hash = "#/discover/recommend"
            self.daily_page_ready = True
        else:
            self.nav_hash = "#/discover"
            self.daily_page_ready = False

    def _on_card(self, expr: str):
        # 命中关键词的卡片都算「点到了」；missing_cards 用来模拟找不到
        for kw in self.missing_cards:
            if kw in expr:
                return {"ok": False, "reason": "card-not-found", "section": True}
        self.playing = True
        if not self.track_id:
            self.track_id = "9001"
            self.name = "每日推荐第一首"
            self.artists = ["推荐歌手"]
        return {"ok": True, "how": "play-btn", "label": "个性化推荐"}


def _client(fake_cdp, cfg_for, **kwargs) -> tuple[NeteaseCDP, FakeMusicState]:
    state = FakeMusicState()
    srv = fake_cdp(handler=state, **kwargs)
    return NeteaseCDP(cfg_for(srv)), state


class DailyCardMissing(FakeMusicState):
    """发现页找不到日推卡片——用来逼出「日推详情页」这条回退路径。

    注意不能用 ``missing_cards`` 模拟：卡片关键词是「每日歌曲推荐」，
    而「每日推荐」是它的**子串**，按子串判断会误伤。
    """

    def __call__(self, expr):
        # 「播放全部」这条更具体的特征由父类先判，这里只管卡片
        if "个性化推荐" in expr and "播放全部" not in expr:
            # 日推卡片有「每日歌曲推荐」和「每日推荐」两个词，两个都要拦
            if "每日" in expr:
                return {"ok": False, "reason": "card-not-found", "section": True}
            return super()._on_card(expr)
        return super().__call__(expr)


class DailyFullyBlocked(DailyCardMissing):
    """卡片找不到，详情页也不给控件——两条路都断，必须如实报告失败。"""

    def __call__(self, expr):
        if "播放全部" in expr:
            return {"ok": False, "reason": "daily-page-no-control"}
        return super().__call__(expr)


class TestState:
    def test_is_playing_false_initially(self, fake_cdp, cfg_for):
        nc, _ = _client(fake_cdp, cfg_for)
        assert nc.is_playing() is False

    def test_current_track_id_empty(self, fake_cdp, cfg_for):
        nc, _ = _client(fake_cdp, cfg_for)
        assert nc.current_track_id() == ""

    def test_current_track_parses(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        state.track_id, state.name = "123", "夜航星"
        state.artists, state.duration, state.playing = ["不才", "GAI"], 254000, True
        t = nc.current_track()
        assert t
        assert (t.id, t.name, t.artist, t.duration_ms, t.playing) == (
            "123",
            "夜航星",
            "不才/GAI",
            254000,
            True,
        )

    def test_state_methods_never_raise_on_dead_port(self):
        nc = NeteaseCDP(CDPConfig(port=1, timeout=0.4))
        assert nc.is_playing() is False
        assert nc.current_track_id() == ""
        assert not nc.current_track()
        assert nc.available() is False
        assert nc.next_track() is False
        assert nc.play(1) is False

    def test_probe_shape_on_dead_port(self):
        out = NeteaseCDP(CDPConfig(port=1, timeout=0.4)).probe()
        assert out["available"] is False
        assert out["error"]
        assert out["track"] is None

    def test_probe_shape_when_live(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        state.track_id, state.name, state.playing = "5", "曲子", True
        out = nc.probe()
        assert out["available"] is True
        assert out["track"]["id"] == "5"
        assert out["error"] == ""

    def test_probe_target_metadata_from_json(self, fake_cdp, cfg_for):
        # /json 里的 title/url 能通过探测读到（走显式 ws_url 时 url 留空，
        # 因为元数据只存在于 /json 响应里）
        from netease_cdp import NeteaseCDP as NC

        srv = fake_cdp(target_title="网易云音乐", target_url="https://music.163.com/#/x")
        out = NC(cfg_for(srv)).probe()
        assert set(out) == {"available", "url", "title", "track", "error"}
        assert out["available"] is True and out["error"] == ""


class TestPlay:
    def test_play_dispatches_and_succeeds(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        assert nc.play(1446615816) is True
        assert state.track_id == "1446615816"
        assert any(a == "play" for a, _ in state.dispatched)

    def test_play_skips_dispatch_when_already_current(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        state.track_id, state.playing = "555", True
        assert nc.play(555) is True
        # 已经在放同一首，不该再派发
        assert not any(a == "play" for a, _ in state.dispatched)

    def test_play_force_redispatches(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        state.track_id, state.playing = "555", True
        assert nc.play(555, force=True) is True
        assert any(a == "play" for a, _ in state.dispatched)

    def test_play_bad_id_returns_false(self, fake_cdp, cfg_for):
        nc, _ = _client(fake_cdp, cfg_for)
        assert nc.play("not-a-number") is False

    def test_play_accepts_str_id(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        assert nc.play("42") is True
        assert state.track_id == "42"

    def test_insert_next(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        assert nc.insert_next(999) is True
        assert any(a == "addToPlayList" for a, _ in state.dispatched)

    def test_insert_next_bad_id(self, fake_cdp, cfg_for):
        nc, _ = _client(fake_cdp, cfg_for)
        assert nc.insert_next("x") is False

    def test_next_and_prev(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        assert nc.next_track() is True
        assert nc.previous_track() is True
        actions = [a for a, _ in state.dispatched]
        assert "playNext" in actions and "playPrev" in actions

    def test_next_track_dom(self, fake_cdp, cfg_for):
        nc, _ = _client(fake_cdp, cfg_for)
        assert nc.next_track_dom() is True

    def test_play_retries_then_fails(self, fake_cdp, cfg_for):
        # 派发返回 True，但状态永远不变 → 重试完应返回 False
        srv = fake_cdp(handler=lambda e: True if "doAction" in e else "")
        nc = NeteaseCDP(cfg_for(srv))
        assert nc.play(1, retries=2, settle_sec=0.01) is False


class TestDiscover:
    def test_play_daily_succeeds(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        res = nc.play_daily()
        assert res.ok
        assert res.strategy in ("discover-card", "daily-page")
        assert state.playing is True

    def test_play_daily_page_script_runs_after_navigation(self, fake_cdp, cfg_for):
        # 日推页面脚本的**第一步**是检查 hash 是否已在详情页；不在就只改
        # hash 并返回 needRetry。所以第一次调用必然拿不到结果。
        # 这里验证真的接着又调了一次（而不是把 hash 当结果返回）
        srv = fake_cdp(handler=DailyCardMissing())
        nc = NeteaseCDP(cfg_for(srv))
        nc.play_daily()
        assert srv.saw("播放全部")

    def test_play_daily_falls_back_to_page(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=DailyCardMissing())
        nc = NeteaseCDP(cfg_for(srv))
        res = nc.play_daily()
        assert res.ok
        assert res.strategy == "daily-page"

    def test_play_daily_page_reports_retry_exhaustion(self, fake_cdp, cfg_for):
        # 详情页永远返回 needRetry（DOM 一直没渲染出来）→ 重试耗尽后
        # 必须如实报告，而不是把 hash 字符串当成"成功"
        class NeverRenders(DailyCardMissing):
            def __call__(self, expr):
                if "播放全部" in expr:
                    return {
                        "ok": False,
                        "reason": "navigating-daily-page",
                        "needRetry": True,
                    }
                return super().__call__(expr)

        srv = fake_cdp(handler=NeverRenders())
        res = NeteaseCDP(cfg_for(srv)).play_daily()
        assert not res.ok
        assert res.detail["page"]["reason"] == "navigating-daily-page"
        assert res.detail["page"]["ok"] is False

    def test_play_daily_reports_failure(self, fake_cdp, cfg_for):
        srv = fake_cdp(handler=DailyFullyBlocked())
        nc = NeteaseCDP(cfg_for(srv))
        res = nc.play_daily()
        assert not res.ok
        assert res.reason == "daily-page-no-control"
        assert isinstance(res, PlayResult)
        # 两条路径的原始结果都要带回来，方便排查
        assert "card" in res.detail and "page" in res.detail

    def test_play_card_radar(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        res = nc.play_card("private_radar")
        assert res.ok
        assert res.strategy == "discover-card"

    def test_play_card_unknown_key_uses_literal(self, fake_cdp, cfg_for):
        nc, _ = _client(fake_cdp, cfg_for)
        # 不在 CARD_KEYWORDS 里的键按字面量当关键词，自定义卡片也能点
        out = nc.click_card("我的自定义卡片")
        assert out.get("ok") is True

    def test_click_card_not_found(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        state.missing_cards.add("私人雷达")
        out = nc.click_card("private_radar", retries=1)
        assert out["ok"] is False
        assert out["reason"] == "card-not-found"

    def test_navigate_returns_hash(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        assert nc.navigate("#/discover/recommend").startswith("#/discover")
        assert state.nav_hash == "#/discover/recommend"

    def test_navigate_never_raises_on_dead_port(self):
        nc = NeteaseCDP(CDPConfig(port=1, timeout=0.4))
        assert nc.navigate("#/x") == "#/x"

    def test_play_card_on_dead_port_is_falsey(self):
        nc = NeteaseCDP(CDPConfig(port=1, timeout=0.4))
        res = nc.play_card("private_radar")
        assert not res and res.reason


class TestConstructor:
    def test_config_and_session_are_exclusive(self):
        import pytest

        from netease_cdp.session import Session

        with pytest.raises(ValueError):
            NeteaseCDP(CDPConfig(), session=Session())

    def test_config_property(self, fake_cdp, cfg_for):
        srv = fake_cdp()
        cfg = cfg_for(srv)
        assert NeteaseCDP(cfg).config is cfg


class TestLegacyLayer:
    def test_get_playing_track_info_shape(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        state.track_id, state.name, state.artists = "1", "n", ["a"]
        out = cdp_get_playing_track_info(port=nc.config.port)
        assert set(out) == {"id", "name", "artists", "playing", "duration"}
        assert out["id"] == "1"
        assert out["artists"] == "a"

    def test_is_playing_on_dead_port(self):
        assert cdp_is_playing(port=1) is False

    def test_play_song_on_dead_port(self):
        assert cdp_play_song(1, port=1) is False

    def test_legacy_play_song_works(self, fake_cdp, cfg_for):
        nc, state = _client(fake_cdp, cfg_for)
        assert cdp_play_song(321, port=nc.config.port) is True
        assert state.track_id == "321"
