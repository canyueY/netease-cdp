# -*- coding: utf-8 -*-
"""开机自启场景：等客户端起来，然后播放每日推荐。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

桌宠这类常驻程序真正需要的用法：进程启动时客户端可能还没开，也可能开了
但没带调试端口。这里的顺序是「先等、再按需重启、最后播放」，每一步都可
单独失败而不影响其他步骤。
"""
from __future__ import annotations

import sys
import time

from netease_cdp import CDPConfig, NeteaseCDP


def main() -> int:
    nc = NeteaseCDP(CDPConfig(port=9222))

    # ① 客户端可能正在启动，先给它一点时间，不要一上来就重启
    for i in range(10):
        if nc.available():
            print(f"调试端口就绪（等了 {i} 秒）")
            break
        time.sleep(1)
    else:
        print("端口一直没起来，尝试带调试端口重启客户端…")
        if not nc.ensure_ready(auto_restart=True):
            print("重启失败：确认网易云已安装，或用 exe_path= 显式指定路径")
            return 1

    # ② 先看看现在在放什么，别贸然打断
    probe = nc.probe()
    if not probe["available"]:
        print("连不上：", probe["error"])
        return 1
    print("已连接：", probe["title"] or probe["url"])

    track = nc.current_track()
    if track:
        print(f"当前在放：{track.name} - {track.artist}")
        if track.playing:
            print("已经在放了，不打扰。")
            return 0

    # ③ 播放每日推荐
    res = nc.play_daily()
    if res.ok:
        print(f"开始播放每日推荐（路径：{res.strategy}）")
        if res.track:
            print(f"  第一首：{res.track.name} - {res.track.artist}")
        return 0
    print("播放失败：", res.reason)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
