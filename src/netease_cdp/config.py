# -*- coding: utf-8 -*-
"""连接参数。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CDPConfig:
    """网易云客户端 CDP 连接参数。

    所有字段都有可直接使用的默认值，因此 ``CDPConfig()`` 在绝大多数机器上
    开箱即用。默认值对应「网易云以 ``--remote-debugging-port=9222`` 启动」
    这一前提；首次接入的完整流程见 README 的「三分钟接入」。
    """

    #: 网易云启动时传入的 `--remote-debugging-port`。必须显式给一个可用端口。
    port: int = 9222

    #: 显式指定 WebSocket 调试地址；留空则从 ``/json`` 里取。
    #: 真实用途：SSH 端口转发 / 容器映射时，调试端口对外暴露的地址与进程内
    #: 监听的地址不一致，自动发现会拿到连不上的那个。
    ws_url: str = ""

    #: cloudmusic.exe 路径。仅 `restart_client()` / `ensure_ready()` 需要；
    #: 留空时这两个方法直接返回 False，不会去猜路径。
    exe_path: str = ""

    #: 等待 CDP 响应的超时（秒）
    timeout: float = 3.5

    #: 单次播放等操作的默认重试次数
    retries: int = 3

    #: 命中何种 URL 的目标页才认作网易云。按顺序匹配，先命中先用。
    url_hints: tuple[str, ...] = ("music.163.com", "orpheus", "y.163.com")

    #: 未命中 `url_hints` 时，是否退而使用第一个 page 目标。
    #: 网易云换域名会让 hint 全部失效，留着它更稳。
    allow_url_fallback: bool = True

    #: 重启客户端时最多等待多少秒（内部按 1 秒轮询）
    restart_wait_sec: float = 12.0

    #: 切歌/点播后等待客户端状态更新（秒）
    settle_sec: float = 0.35

    #: 允许的 CDP 端点主机。锁定 127.0.0.1 是刻意的：调试端口一旦暴露到
    #: 局域网，等于把浏览器控制权交出去。确认过风险再用 `allow_remote_host`。
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]", "::1")
    allow_remote_host: bool = False

    #: 校验用：发现页 hash 路由
    discover_hash: str = "#/discover"
    daily_page_hash: str = "#/discover/recommend"

    def __post_init__(self) -> None:
        if not 1 <= int(self.port) <= 65535:
            raise ValueError(
                f"port 必须在 1..65535，收到 {self.port!r}"
                "（0 是「让内核挑端口」的意思，对 CDP 客户端没有意义）"
            )
        if float(self.timeout) <= 0:
            raise ValueError(f"timeout 必须为正数，收到 {self.timeout!r}")
        if int(self.retries) < 1:
            raise ValueError(f"retries 至少为 1，收到 {self.retries!r}")
        # 空串会被 urlparse 解析成「无主机」，静默降级失败；不如当场报错
        if self.ws_url and not self.ws_url.startswith(("ws://", "wss://")):
            raise ValueError(
                f"ws_url 必须以 ws:// 或 wss:// 开头，收到 {self.ws_url!r}"
            )

    # -- 派生值 ---------------------------------------------------------

    @property
    def http_endpoint(self) -> str:
        """CDP 的 HTTP 目标列表地址。"""
        return f"http://127.0.0.1:{int(self.port)}/json"

    def replace(self, **kwargs: object) -> "CDPConfig":
        """返回替换了若干字段的新实例（frozen dataclass 的便捷写法）。"""
        from dataclasses import replace as _replace

        return _replace(self, **kwargs)  # type: ignore[arg-type]


#: 发现页个性化推荐卡片的标识 → 卡片文案关键词。
#: 值同时用于「在页面里找卡片」和「区分是哪种推荐」。
CARD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "daily": ("每日歌曲推荐", "每日推荐"),
    "private_radar": ("私人雷达",),
    "heart_mode": ("心动模式", "心动"),
    "private_roam": ("私人漫游",),
}

__all__ = ["CDPConfig", "CARD_KEYWORDS"]
