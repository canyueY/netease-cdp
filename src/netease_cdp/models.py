# -*- coding: utf-8 -*-
"""返回值类型。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

单独成模块是为了断开 ``client`` ↔ ``discover`` 的循环依赖：
两边都要用这两个类型，但谁也不该 import 对方。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Track:
    """当前播放曲目。

    字段名沿用网易云 API 的习惯（``artists`` 是列表），
    :attr:`artist` 给出拼接好的字符串。
    """

    id: str = ""
    name: str = ""
    artists: tuple[str, ...] = field(default_factory=tuple)
    duration_ms: int = 0
    playing: bool = False

    #: 多人时的分隔符（网易云自己也是用 ``/`` 展示合唱）
    SEP = "/"

    @classmethod
    def from_raw(cls, raw: Any) -> "Track":
        """把 CDP 返回值转成 :class:`Track`。非字典一律当空。"""
        if not isinstance(raw, dict):
            return cls()
        artists_raw = raw.get("artists")
        if isinstance(artists_raw, str):
            # 老接口返回的是已拼好的字符串
            artists = tuple(p for p in artists_raw.split(cls.SEP) if p)
        elif isinstance(artists_raw, (list, tuple)):
            artists = tuple(str(a) for a in artists_raw if a)
        else:
            artists = ()
        try:
            duration = int(float(raw.get("duration") or 0))
        except (TypeError, ValueError):
            duration = 0
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            artists=artists,
            duration_ms=duration,
            playing=bool(raw.get("playing")),
        )

    @property
    def artist(self) -> str:
        """歌手拼接串。"""
        return self.SEP.join(self.artists)

    @property
    def duration_sec(self) -> float:
        """时长（秒）。"""
        return self.duration_ms / 1000.0

    def __bool__(self) -> bool:
        """有 id 才算「拿到了一首歌」。"""
        return bool(self.id)

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 化的字典（字段名与旧调用方一致）。"""
        return {
            "id": self.id,
            "name": self.name,
            "artists": self.artist,
            "playing": self.playing,
            "duration": self.duration_ms,
        }


@dataclass(frozen=True)
class PlayResult:
    """点播结果。

    :attr:`strategy` 说明是哪条路径成功的，排查「点了没反应」时很有用：

    ``redux``
        直接走 Redux dispatch（最可靠）
    ``discover-card``
        发现页个性化推荐卡片
    ``daily-page``
        日推详情页的「播放全部」/ 首曲
    """

    ok: bool
    strategy: str = ""
    reason: str = ""
    track: Track | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok

    def as_dict(self) -> dict[str, Any]:
        """转成可 JSON 化的字典。"""
        out: dict[str, Any] = {
            "ok": self.ok,
            "strategy": self.strategy,
            "reason": self.reason,
        }
        if self.track:
            out["track"] = self.track.as_dict()
        if self.detail:
            out["detail"] = self.detail
        return out


__all__ = ["PlayResult", "Track"]
