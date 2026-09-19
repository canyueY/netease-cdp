# -*- coding: utf-8 -*-
"""返回值类型：Track / PlayResult。"""
from __future__ import annotations

from netease_cdp.models import PlayResult, Track


class TestTrackParsing:
    def test_empty_inputs(self):
        for raw in (None, "", 0, [], {}, {"id": ""}):
            t = Track.from_raw(raw)
            assert not t
            assert t.id == ""
            assert t.artists == ()

    def test_full_dict(self):
        t = Track.from_raw(
            {
                "id": "1446615816",
                "name": "夜航星",
                "artists": ["不才", "GAI"],
                "duration": 254000,
                "playing": True,
            }
        )
        assert t
        assert t.id == "1446615816"
        assert t.name == "夜航星"
        assert t.artist == "不才/GAI"
        assert t.duration_ms == 254000
        assert abs(t.duration_sec - 254.0) < 1e-6
        assert t.playing is True

    def test_artists_as_prejoined_string(self):
        # 老接口直接给 "A/B" 字符串
        t = Track.from_raw({"id": "1", "artists": "A/B"})
        assert t.artists == ("A", "B")
        assert t.artist == "A/B"

    def test_artists_with_empty_entries_dropped(self):
        t = Track.from_raw({"id": "1", "artists": ["A", "", None, "B"]})
        assert t.artists == ("A", "B")

    def test_artists_wrong_type(self):
        assert Track.from_raw({"id": "1", "artists": 123}).artists == ()

    def test_duration_garbage_becomes_zero(self):
        for bad in ("abc", None, [], {}):
            assert Track.from_raw({"id": "1", "duration": bad}).duration_ms == 0

    def test_duration_float_string(self):
        assert Track.from_raw({"id": "1", "duration": "254000.7"}).duration_ms == 254000

    def test_id_coerced_to_str(self):
        assert Track.from_raw({"id": 12345}).id == "12345"

    def test_missing_name_is_empty_not_none(self):
        assert Track.from_raw({"id": "1"}).name == ""

    def test_bool_only_when_id_present(self):
        assert not Track.from_raw({"name": "有名字但没 id"})
        assert Track.from_raw({"id": "0"})  # "0" 也算有 id


class TestTrackAsDict:
    def test_shape_matches_legacy_api(self):
        t = Track.from_raw({"id": "7", "name": "n", "artists": ["a"], "duration": 1000})
        d = t.as_dict()
        assert d == {
            "id": "7",
            "name": "n",
            "artists": "a",
            "playing": False,
            "duration": 1000,
        }

    def test_empty_track_dict_is_all_empty(self):
        d = Track().as_dict()
        assert d["id"] == "" and d["name"] == "" and d["artists"] == ""
        assert d["playing"] is False and d["duration"] == 0


class TestPlayResult:
    def test_bool_follows_ok(self):
        assert PlayResult(ok=True)
        assert not PlayResult(ok=False)

    def test_defaults(self):
        r = PlayResult(ok=True)
        assert r.strategy == "" and r.reason == "" and r.track is None
        assert r.detail == {}

    def test_as_dict_omits_empty_optional_parts(self):
        assert PlayResult(ok=True, strategy="redux").as_dict() == {
            "ok": True,
            "strategy": "redux",
            "reason": "",
        }

    def test_as_dict_includes_track_when_present(self):
        r = PlayResult(ok=True, track=Track.from_raw({"id": "5", "name": "x"}))
        assert r.as_dict()["track"]["id"] == "5"

    def test_as_dict_includes_detail_when_present(self):
        r = PlayResult(ok=True, detail={"how": "play-btn"})
        assert r.as_dict()["detail"] == {"how": "play-btn"}

    def test_as_dict_is_json_serialisable(self):
        import json

        r = PlayResult(ok=True, strategy="s", track=Track.from_raw({"id": "1"}))
        json.dumps(r.as_dict())
