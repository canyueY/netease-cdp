# -*- coding: utf-8 -*-
"""netease-cdp —— 通过 Chrome DevTools Protocol 驱动网易云桌面客户端。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

设计前提：你机器上有一个**已经登录好**的网易云客户端，并且它以
``--remote-debugging-port=9222`` 启动。本库通过该端口在页面里取 Redux
状态、派发播放动作——不走 HTTP API、不碰 cookie，所以 VIP 与私人推荐
天然可用。

快速上手::

    from netease_cdp import NeteaseCDP

    nc = NeteaseCDP()
    if not nc.available():
        nc.ensure_ready(auto_restart=True)   # 会重启客户端

    print(nc.current_track().name)
    nc.play(1234567)
    nc.play_daily()
"""
from __future__ import annotations

from . import js, launcher, session
from .client import (
    NeteaseCDP,
    cdp_available,
    cdp_click_discover_personal_card,
    cdp_current_track_id,
    cdp_get_playing_track_info,
    cdp_insert_next,
    cdp_is_playing,
    cdp_navigate_discover_hash,
    cdp_play_daily_recommend_full,
    cdp_play_daily_recommend_page,
    cdp_play_discover_card_full,
    cdp_play_discover_personal_card,
    cdp_play_next,
    cdp_play_next_dom,
    cdp_play_prev,
    cdp_play_song,
    default_client,
    ensure_cdp_ready,
    restart_cloudmusic_with_cdp,
)
from .config import CARD_KEYWORDS, CDPConfig
from .errors import (
    CDPTimeout,
    CDPUnavailable,
    ClientNotFound,
    NeteaseCDPError,
    ScriptError,
)
from .models import PlayResult, Track
from .session import Session

__version__ = "0.1.0"

__all__ = [
    "CARD_KEYWORDS",
    "CDPConfig",
    "CDPTimeout",
    "CDPUnavailable",
    "ClientNotFound",
    "NeteaseCDP",
    "NeteaseCDPError",
    "PlayResult",
    "ScriptError",
    "Session",
    "Track",
    "__version__",
    "cdp_available",
    "cdp_click_discover_personal_card",
    "cdp_current_track_id",
    "cdp_get_playing_track_info",
    "cdp_insert_next",
    "cdp_is_playing",
    "cdp_navigate_discover_hash",
    "cdp_play_daily_recommend_full",
    "cdp_play_daily_recommend_page",
    "cdp_play_discover_card_full",
    "cdp_play_discover_personal_card",
    "cdp_play_next",
    "cdp_play_next_dom",
    "cdp_play_prev",
    "cdp_play_song",
    "default_client",
    "ensure_cdp_ready",
    "js",
    "launcher",
    "restart_cloudmusic_with_cdp",
    "session",
    "track",
]


def track(raw: object = None) -> Track:
    """便捷构造：``track()`` 得到空曲目，``track(raw_dict)`` 解析返回值。"""
    if raw is None:
        return Track()
    return Track.from_raw(raw)
