# -*- coding: utf-8 -*-
"""注入 JS 的生成逻辑。

这些片段一旦拼错，失败是**静默**的（页面返回 false，客户端毫无反应），
所以这里逐个断言关键结构。
"""
from __future__ import annotations

import json

from netease_cdp import js


class TestWrap:
    def test_wraps_in_iife(self):
        out = js.wrap("return 1;")
        assert out.startswith("(function(){")
        assert out.endswith("})()")
        assert "return 1;" in out

    def test_includes_ensure_store(self):
        # 每个 wrap 出来的表达式都必须自带 _ensureStore，
        # 否则页面没被探索过时调用会直接 ReferenceError
        assert "_ensureStore" in js.wrap("return 1;")
        assert len(js.FIBER_STORE_JS.strip()) > 100

    def test_body_is_not_template_substituted(self):
        # body 里出现花括号不能被当成格式串
        tricky = "var o={a:{b:1}};return o;"
        assert tricky in js.wrap(tricky)


class TestDispatch:
    def test_action_and_data_present(self):
        body = js.dispatch_body("play", "{resource:{id:'1'}}")
        assert "'async:action/doAction'" in body
        assert "actionId:'play'" in body
        assert "data:{resource:{id:'1'}}" in body

    def test_has_return_paths(self):
        body = js.dispatch_body("playNext", "{eventType:'click'}")
        assert "return true;" in body
        assert "return false;" in body

    def test_play_track_data_shape(self):
        data = js.play_track_data(1234567)
        assert "String(1234567)" in data
        assert "resourceType:'track'" in data
        # 网易云靠 dblclick 事件类型区分「播放」和「选中」
        assert "eventType:'dblclick'" in data

    def test_play_track_data_coerces_id(self):
        assert "String(42)" in js.play_track_data("42")  # type: ignore[arg-type]

    def test_insert_next_data_shape(self):
        data = js.insert_next_data(999)
        assert "duration:0" in data
        assert "eventType:'click'" in data


class TestTrackBody:
    def test_prefers_playing_resource_artists(self):
        # entities.tracks 在多数版本里是空的（trackIsNull），
        # 所以必须先读 playing.resourceArtists
        body = js.CURRENT_TRACK_BODY
        assert "artists=joinArtists(pl.resourceArtists)" in body
        assert "if(!artists&&track){" in body
        # 先读 playing.resourceArtists，再退回 track.ar / track.artists
        assert body.index("joinArtists(pl.resourceArtists)") < body.index(
            "joinArtists(cands[i])"
        )
        assert body.index("joinArtists(cands[i])") < body.index("return {id:String(id||'')")

    def test_falls_back_to_track_entities(self):
        body = js.CURRENT_TRACK_BODY
        assert "s.entities&&s.entities.tracks" in body
        # 至少覆盖这几个歌手字段名
        for f in ("track.ar", "track.artists", "track.singer"):
            assert f in body

    def test_playing_flag_matches_is_playing(self):
        # 两处对 playing 的判定必须一致，否则 current_track().playing
        # 和 is_playing() 会互相矛盾
        assert "pl.playing!==false" in js.CURRENT_TRACK_BODY
        assert "s.playing?.playing!==false" in js.IS_PLAYING_BODY

    def test_returns_expected_keys(self):
        for key in ("id:", "name:", "artists:", "playing:", "duration:"):
            assert key in js.CURRENT_TRACK_BODY

    def test_id_falls_back_to_online_resource(self):
        for body in (js.CURRENT_TRACK_BODY, js.CURRENT_TRACK_ID_BODY):
            assert "onlineResourceId" in body
            assert "resourceTrackId" in body


class TestNavigate:
    def test_json_quotes_hash(self):
        body = js.navigate_hash_body("#/discover/recommend")
        assert json.dumps("#/discover/recommend") in body

    def test_hash_normalisation_present(self):
        assert "startsWith('#')" in js.navigate_hash_body("#/x")

    def test_escapes_hash_slash_regex(self):
        # 源码里是 /^\/+/，落到 Python 字符串必须仍是合法 JS
        assert r"\/+" in js.navigate_hash_body("#/x")


class TestDiscover:
    def test_click_card_embeds_keywords_as_json(self):
        expr = js.click_card_js(("每日歌曲推荐", "每日推荐"))
        assert json.dumps(["每日歌曲推荐", "每日推荐"], ensure_ascii=False) in expr

    def test_click_card_is_self_contained_iife(self):
        expr = js.click_card_js(("私人雷达",))
        # 自带 IIFE，不需要也不应该再套 wrap（套了会缺 _ensureStore）
        assert expr.startswith("\n(function(keywords)")
        assert expr.endswith(")")

    def test_click_card_finds_personalised_section(self):
        assert "个性化推荐" in js.DISCOVER_CLICK_CARD_JS

    def test_click_card_scoring_hints(self):
        # 卡片文案会撞车（好几个都含「心动」），靠这些上下文加分区分
        for hint in ("根据你的口味", "猜你喜欢", "红心", "银河"):
            assert hint in js.DISCOVER_CLICK_CARD_JS

    def test_click_card_reports_reason_on_failure(self):
        assert "card-not-found" in js.DISCOVER_CLICK_CARD_JS

    def test_daily_page_asks_for_retry_after_nav(self):
        # 改 hash 后同一帧 DOM 还没渲染，必须告诉调用方重试
        assert "needRetry" in js.PLAY_DAILY_PAGE_JS
        assert "navigating-daily-page" in js.PLAY_DAILY_PAGE_JS

    def test_daily_page_clicks_play_all_first(self):
        assert "播放全部" in js.PLAY_DAILY_PAGE_JS
        assert js.PLAY_DAILY_PAGE_JS.index("播放全部") < js.PLAY_DAILY_PAGE_JS.index("m-table")

    def test_only_dispatch_body_is_a_template(self):
        # DISPATCH_BODY 是唯一带 {placeholder} 的模板；其余都是成品，
        # 一旦有人误加空占位符，注入到页面就是语法错误
        assert "{action_id}" in js.DISPATCH_BODY
        assert "{data_js}" in js.DISPATCH_BODY
        for name in (
            "FIBER_STORE_JS",
            "IS_PLAYING_BODY",
            "CURRENT_TRACK_BODY",
            "CURRENT_TRACK_ID_BODY",
            "NEXT_DOM_JS",
            "DISCOVER_CLICK_CARD_JS",
            "PLAY_DAILY_PAGE_JS",
        ):
            src = getattr(js, name)
            assert "{action_id}" not in src
            assert "{data_js}" not in src
        # 花括号必须成对出现——JS 片段里 { 多于 } 几乎一定是拼错了
        for name in ("IS_PLAYING_BODY", "CURRENT_TRACK_BODY", "CURRENT_TRACK_ID_BODY"):
            src = getattr(js, name)
            assert src.count("{") == src.count("}"), name
