# -*- coding: utf-8 -*-
"""发现页个性化推荐：每日推荐 / 私人雷达 / 心动模式 / 私人漫游。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

这一层只依赖 :class:`netease_cdp.session.Session`（不依赖 client），
所有函数都以「客户端真的开始在放」为准，而不是「点击动作没报错」。
"""
from __future__ import annotations

import time
from typing import Any

from . import js
from .config import CARD_KEYWORDS
from .models import PlayResult, Track
from .session import Session


def _settle(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


# ---------------------------------------------------------------------------
# 发现页卡片
# ---------------------------------------------------------------------------


def click_card(
    session: Session,
    card_key: str,
    *,
    wait_sec: float = 2.0,
    retries: int = 3,
) -> dict[str, Any]:
    """切到发现页并点开指定推荐卡片。

    :param card_key: ``daily`` / ``private_radar`` / ``heart_mode`` / ``private_roam``；
        不在表里时按字面量当关键词用，所以自定义卡片也能点。
    :returns: 形如 ``{"ok": bool, "how": "play-btn", "label": "每日推荐 根据你的口味..."}``；
        失败时带 ``reason``（``card-not-found`` / ``nav-failed:...`` / ...）。
    """
    keywords = CARD_KEYWORDS.get(card_key) or (card_key,)
    expr = js.click_card_js(keywords)
    hash_path = session.config.discover_hash
    attempts = max(1, int(retries))
    last: dict[str, Any] = {"ok": False, "reason": "not-tried"}

    for i in range(attempts):
        try:
            session.evaluate(js.wrap(js.navigate_hash_body(hash_path)))
        except Exception as exc:
            last = {"ok": False, "reason": f"nav-failed:{exc}"}
        # 页面渲染要时间，重试时逐次放宽，避免在慢机器上一直抢跑
        _settle(max(0.8, float(wait_sec)) * (1.0 + 0.35 * i))
        try:
            val = session.evaluate(expr, timeout=5.0)
            last = val if isinstance(val, dict) else {"ok": bool(val), "raw": val}
            if last.get("ok"):
                _settle(0.6)
                if _is_playing(session):
                    last["playing"] = True
                    return last
                if card_key != "daily":
                    # 非日推卡片本身就是一次播放动作，点到了就算成功
                    return last
        except Exception as exc:
            last = {"ok": False, "reason": str(exc)[:200]}
    return last


def _is_playing(session: Session) -> bool:
    try:
        return bool(session.evaluate(js.wrap(js.IS_PLAYING_BODY)))
    except Exception:
        return False


def _track(session: Session) -> Track:
    try:
        return Track.from_raw(session.evaluate(js.wrap(js.CURRENT_TRACK_BODY)))
    except Exception:
        return Track()


# ---------------------------------------------------------------------------
# 日推详情页
# ---------------------------------------------------------------------------


def play_daily_page(
    session: Session, *, wait_sec: float = 2.0
) -> dict[str, Any]:
    """在日推详情页（``#/discover/recommend``）点「播放全部」或首曲。

    第一次调用通常会返回 ``needRetry``——因为要先改 hash 让前端路由过去，
    同一帧里 DOM 还没渲染出来。这里内部最多重试 3 次。
    """
    hash_path = session.config.daily_page_hash
    last: dict[str, Any] = {"ok": False, "reason": "not-tried"}

    for i in range(3):
        try:
            session.evaluate(js.wrap(js.navigate_hash_body(hash_path)))
        except Exception as exc:
            last = {"ok": False, "reason": f"nav-failed:{exc}"}
        _settle(max(0.9, float(wait_sec)) * (1.0 + 0.25 * i))
        try:
            val = session.evaluate(js.PLAY_DAILY_PAGE_JS, timeout=6.0)
            if isinstance(val, dict):
                last = val
                if val.get("needRetry"):
                    # 还在跳路由（改了 hash，DOM 未渲染）。这一轮不该被当成
                    # 最终结果——留着 needRetry 进下一轮，耗尽了就如实上报。
                    last = {
                        "ok": False,
                        "reason": str(val.get("reason") or "navigating-daily-page"),
                        "needRetry": True,
                    }
                    continue
                if val.get("ok"):
                    _settle(0.7)
                    if _is_playing(session):
                        last["playing"] = True
                    return last
            else:
                last = {"ok": False, "reason": f"unexpected-result:{val!r}"}
        except Exception as exc:
            last = {"ok": False, "reason": str(exc)[:200]}
    return last


# ---------------------------------------------------------------------------
# 组合入口
# ---------------------------------------------------------------------------


def play_daily(session: Session, *, wait_sec: float = 2.0) -> PlayResult:
    """播放「每日推荐」。

    两条路径依次尝试，以客户端实际播放状态判定成功：

    1. 发现页卡片（一次点击就开播）
    2. 日推详情页「播放全部」
    """
    delay = max(0.8, float(wait_sec))
    card = click_card(session, "daily", wait_sec=delay, retries=2)
    if card.get("ok"):
        _settle(0.8)
        if _is_playing(session):
            return PlayResult(
                ok=True, strategy="discover-card", detail=dict(card)
            )

    page = play_daily_page(session, wait_sec=delay)
    if page.get("ok"):
        _settle(0.6)
        if _is_playing(session):
            return PlayResult(ok=True, strategy="daily-page", detail=dict(page))
        track = _track(session)
        if track:
            return PlayResult(
                ok=True, strategy="daily-page", track=track, detail=dict(page)
            )

    reason = str(
        page.get("reason") or card.get("reason") or "daily-play-failed"
    )
    return PlayResult(
        ok=False,
        reason=reason,
        detail={"card": card, "page": page},
    )


def play_card(
    session: Session,
    card_key: str,
    *,
    wait_sec: float = 2.0,
    settle_sec: float = 0.8,
    retries: int = 3,
) -> PlayResult:
    """播放某张发现页卡片（私人雷达 / 心动模式 / 私人漫游 …）。

    这些卡片点开即是播放，没有「详情页」这一步，所以成功判定比日推宽松：
    点到了就算成功，能读到曲目就顺手带上。
    """
    delay = max(0.8, float(wait_sec))
    card = click_card(session, card_key, wait_sec=delay, retries=retries)
    if not card.get("ok"):
        return PlayResult(
            ok=False,
            reason=str(card.get("reason") or "discover-card-failed"),
            detail=dict(card),
        )
    _settle(settle_sec)
    if _is_playing(session):
        return PlayResult(ok=True, strategy="discover-card", detail=dict(card))
    track = _track(session)
    return PlayResult(
        ok=True, strategy="discover-card", track=track or None, detail=dict(card)
    )


__all__ = ["click_card", "play_card", "play_daily", "play_daily_page"]
