# -*- coding: utf-8 -*-
"""网易云桌面客户端控制主入口。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations

import time
from typing import Any

from . import discover, js, launcher
from .config import CDPConfig
from .models import PlayResult, Track
from .session import Session

__all__ = [
    "NeteaseCDP",
    "PlayResult",
    "Track",
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
    "restart_cloudmusic_with_cdp",
]


class NeteaseCDP:
    """网易云桌面客户端的 CDP 控制器。

    本库不碰 HTTP API、不需要登录、不读 cookie——它驱动的是你**已经登录好**
    的那个客户端窗口，所以 VIP / 私人推荐这类需要账号的内容天然可用。

    典型用法::

        from netease_cdp import NeteaseCDP

        nc = NeteaseCDP()
        if not nc.available():
            nc.ensure_ready(auto_restart=True)
        print(nc.current_track())
        nc.play(1234567)

    :param config: 连接参数，缺省即 ``CDPConfig()``
    :param session: 复用已有会话对象；与 ``config`` 二选一
    """

    def __init__(
        self, config: CDPConfig | None = None, *, session: Session | None = None
    ) -> None:
        if session is not None and config is not None:
            raise ValueError("config 与 session 只能给一个")
        self.session = session or Session(config)

    @property
    def config(self) -> CDPConfig:
        """当前生效的连接参数。"""
        return self.session.config

    # -- 可用性 ---------------------------------------------------------

    def available(self) -> bool:
        """调试端口是否可用（不抛异常）。"""
        return self.session.available()

    def probe(self) -> dict[str, Any]:
        """一次调用拿回「连接状态 + 当前曲目」，适合健康检查。

        全程吞异常，永远返回字典，字段固定：
        ``available`` / ``url`` / ``title`` / ``track`` / ``error``。
        """
        out: dict[str, Any] = {
            "available": False,
            "url": "",
            "title": "",
            "track": None,
            "error": "",
        }
        try:
            target = self.session.target()
        except Exception as exc:
            out["error"] = str(exc)
            return out
        out["available"] = True
        out["url"] = str(target.get("url") or "")
        out["title"] = str(target.get("title") or "")
        try:
            out["track"] = self.current_track().as_dict()
        except Exception as exc:
            out["error"] = str(exc)
        return out

    # -- 状态读取 -------------------------------------------------------

    def is_playing(self) -> bool:
        """客户端当前是否在播放。"""
        try:
            return bool(self.session.evaluate(js.wrap(js.IS_PLAYING_BODY)))
        except Exception:
            return False

    def current_track_id(self) -> str:
        """当前曲目 id；取不到返回空串。"""
        try:
            val = self.session.evaluate(js.wrap(js.CURRENT_TRACK_ID_BODY))
            return str(val or "").strip()
        except Exception:
            return ""

    def current_track(self) -> Track:
        """当前曲目详情；取不到返回空的 :class:`Track`（``bool()`` 为假）。"""
        try:
            raw = self.session.evaluate(js.wrap(js.CURRENT_TRACK_BODY))
            return Track.from_raw(raw)
        except Exception:
            return Track()

    # -- 播放控制 -------------------------------------------------------

    def _dispatch(self, action_id: str, data_js: str) -> bool:
        """派发一条 ``async:action/doAction``。失败返回 ``False``。"""
        try:
            expr = js.wrap(js.dispatch_body(action_id, data_js))
            return bool(self.session.evaluate(expr))
        except Exception:
            return False

    def play(
        self,
        song_id: int | str,
        *,
        retries: int | None = None,
        settle_sec: float | None = None,
        force: bool = False,
    ) -> bool:
        """点播一首歌。

        已经在放同一首时默认直接返回 ``True``（省一次往返）；
        ``force=True`` 强制重新派发。

        :param retries: 覆盖配置里的重试次数
        :param settle_sec: 派发后等待客户端状态更新
        :param force: 即使当前就是这首歌也重新派发
        """
        try:
            sid = int(song_id)
        except (TypeError, ValueError):
            return False
        if not force:
            current = self.current_track_id()
            if current and current == str(sid):
                return True

        attempts = max(1, int(retries if retries is not None else self.config.retries))
        pause = float(settle_sec if settle_sec is not None else self.config.settle_sec)
        data = js.play_track_data(sid)
        for i in range(attempts):
            if self._dispatch("play", data):
                _sleep(pause)
                if self.current_track_id() == str(sid) or self.is_playing():
                    return True
            if i + 1 < attempts:
                _sleep(max(0.6, pause))
        return False

    def insert_next(self, song_id: int | str) -> bool:
        """把一首歌插到「下一首播放」。"""
        try:
            sid = int(song_id)
        except (TypeError, ValueError):
            return False
        return self._dispatch("addToPlayList", js.insert_next_data(sid))

    def next_track(self) -> bool:
        """下一首。"""
        return self._dispatch("playNext", js.PLAY_NEXT_DATA)

    def previous_track(self) -> bool:
        """上一首。"""
        return self._dispatch("playPrev", js.PLAY_PREV_DATA)

    def next_track_dom(self) -> bool:
        """下一首（DOM 回退）。

        某些版本 Redux 的 ``playNext`` 会被前端守卫拦掉，这时直接点按钮
        反而有效。
        """
        try:
            return bool(self.session.evaluate(js.NEXT_DOM_JS))
        except Exception:
            return False

    # -- 路由 -----------------------------------------------------------

    def navigate(self, hash_path: str = "#/discover") -> str:
        """切换客户端内部路由，返回实际生效的 hash。"""
        try:
            val = self.session.evaluate(js.wrap(js.navigate_hash_body(hash_path)))
            return str(val or hash_path)
        except Exception:
            return hash_path

    # -- 发现页个性化推荐 -----------------------------------------------

    def click_card(
        self, card_key: str, *, wait_sec: float = 2.0, retries: int = 3
    ) -> dict[str, Any]:
        """在发现页点开某张个性化推荐卡片，返回底层结果字典。"""
        return discover.click_card(
            self.session, card_key, wait_sec=wait_sec, retries=retries
        )

    def play_daily(self, *, wait_sec: float = 2.0) -> PlayResult:
        """播放「每日推荐」：先卡片、再日推详情页，以客户端实际播放为准。"""
        return discover.play_daily(self.session, wait_sec=wait_sec)

    def play_card(self, card_key: str, *, wait_sec: float = 2.0) -> PlayResult:
        """播放私人雷达 / 心动模式 / 私人漫游 等卡片。"""
        return discover.play_card(self.session, card_key, wait_sec=wait_sec)

    # -- 启动 / 重启 -----------------------------------------------------

    def ensure_ready(
        self, *, auto_restart: bool = False, exe_path: str = ""
    ) -> bool:
        """确保调试端口可用；``auto_restart=True`` 时允许自动重启客户端。"""
        return launcher.ensure_ready(
            self.config, auto_restart=auto_restart, exe_path=exe_path
        )

    def restart_client(self, exe_path: str = "") -> bool:
        """关掉并带调试端口重启客户端（会打断当前播放）。"""
        return launcher.restart_with_cdp(exe_path or self.config.exe_path, cfg=self.config)


def _sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


# ---------------------------------------------------------------------------
# 函数式兼容层
# ---------------------------------------------------------------------------
# 与原 Murasame 里那批 `cdp_*` 函数一一对应，迁移期换 import 即可，行为不变。


_default: NeteaseCDP | None = None


def default_client() -> NeteaseCDP:
    """进程级默认控制器（用默认 :class:`CDPConfig`）。"""
    global _default
    if _default is None:
        _default = NeteaseCDP()
    return _default


def _nc(port: int, **kw: Any) -> NeteaseCDP:
    return NeteaseCDP(CDPConfig(port=port, **kw))


def cdp_available(port: int = 9222) -> bool:
    """调试端口是否可用。"""
    return _nc(port).available()


def cdp_is_playing(*, port: int = 9222) -> bool:
    """客户端当前是否在播放。"""
    return _nc(port).is_playing()


def cdp_current_track_id(*, port: int = 9222) -> str:
    """当前曲目 id。"""
    return _nc(port).current_track_id()


def cdp_get_playing_track_info(*, port: int = 9222) -> dict[str, Any]:
    """当前曲目详情（原始字典形式）。"""
    return _nc(port).current_track().as_dict()


def cdp_play_song(song_id: int, *, port: int = 9222, retries: int = 3) -> bool:
    """点播一首歌。"""
    return _nc(port).play(song_id, retries=retries)


def cdp_insert_next(song_id: int, *, port: int = 9222) -> bool:
    """插到下一首播放。"""
    return _nc(port).insert_next(song_id)


def cdp_play_next(*, port: int = 9222) -> bool:
    """下一首。"""
    return _nc(port).next_track()


def cdp_play_prev(*, port: int = 9222) -> bool:
    """上一首。"""
    return _nc(port).previous_track()


def cdp_play_next_dom(*, port: int = 9222) -> bool:
    """下一首（DOM 回退）。"""
    return _nc(port).next_track_dom()


def cdp_navigate_discover_hash(
    hash_path: str = "#/discover", *, port: int = 9222
) -> str:
    """切换客户端内部路由。"""
    return _nc(port).navigate(hash_path)


def cdp_click_discover_personal_card(
    card_key: str,
    *,
    port: int = 9222,
    hash_path: str = "#/discover",
    wait_sec: float = 2.0,
    retries: int = 3,
) -> dict[str, Any]:
    """点开发现页个性化推荐卡片。"""
    nc = _nc(port, discover_hash=hash_path)
    return nc.click_card(card_key, wait_sec=wait_sec, retries=retries)


def cdp_play_daily_recommend_page(
    *, port: int = 9222, wait_sec: float = 2.0
) -> dict[str, Any]:
    """在日推详情页点「播放全部」/ 首曲。"""
    return discover.play_daily_page(_nc(port), wait_sec=wait_sec)


def cdp_play_daily_recommend_full(
    *, port: int = 9222, hash_path: str = "#/discover", wait_sec: float = 2.0
) -> dict[str, Any]:
    """每日推荐完整点播。"""
    nc = _nc(port, discover_hash=hash_path)
    res = discover.play_daily(nc.session, wait_sec=wait_sec)
    if res.detail:
        return dict(res.detail)
    return {"ok": res.ok, "strategy": res.strategy, "reason": res.reason}


def cdp_play_discover_personal_card(
    card_key: str,
    *,
    port: int = 9222,
    hash_path: str = "#/discover",
    wait_sec: float = 2.0,
) -> dict[str, Any]:
    """发现页卡片点播。"""
    return cdp_click_discover_personal_card(
        card_key, port=port, hash_path=hash_path, wait_sec=wait_sec, retries=3
    )


def cdp_play_discover_card_full(
    card_key: str,
    *,
    port: int = 9222,
    hash_path: str = "#/discover",
    wait_sec: float = 2.0,
) -> dict[str, Any]:
    """发现页卡片点播（带回退判定）。"""
    nc = _nc(port, discover_hash=hash_path)
    res = discover.play_card(nc.session, card_key, wait_sec=wait_sec)
    return dict(res.detail) if res.detail else {"ok": res.ok, "reason": res.reason}


def restart_cloudmusic_with_cdp(exe_path: str, *, port: int = 9222) -> bool:
    """关掉并以 ``--remote-debugging-port`` 重启网易云。"""
    return launcher.restart_with_cdp(exe_path, cfg=CDPConfig(port=port))


def ensure_cdp_ready(
    exe_path: str, *, port: int = 9222, auto_restart: bool = False
) -> bool:
    """确保 CDP 就绪，必要时重启客户端。"""
    return launcher.ensure_ready(
        CDPConfig(port=port, exe_path=exe_path), auto_restart=auto_restart
    )
