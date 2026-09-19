# -*- coding: utf-8 -*-
"""启动 / 重启网易云客户端并带上调试端口。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

调试端口只能在进程启动时由命令行参数打开，**不能**给一个已经在跑的客户端
补开。所以「接入 CDP」这件事必然包含一次重启——本模块把这次重启做干净。
"""
from __future__ import annotations

import os
import platform
import subprocess
import time
from pathlib import Path

from . import session
from .config import CDPConfig
from .errors import ClientNotFound

#: 网易云在 Windows 上的默认安装位置（仅当调用方没给路径时才用）
DEFAULT_EXE_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Netease\CloudMusic\cloudmusic.exe",
    r"C:\Program Files (x86)\Netease\CloudMusic\cloudmusic.exe",
)

_PROCESS_NAME = "cloudmusic.exe"


def find_client_exe() -> str:
    """在常见安装位置里找 ``cloudmusic.exe``，找不到返回空串。

    只查固定路径，不扫全盘——扫盘要几十秒，而且桌宠这类调用方通常已经
    知道路径了。
    """
    if platform.system() != "Windows":
        return ""
    for cand in DEFAULT_EXE_CANDIDATES:
        if Path(cand).is_file():
            return cand
    # 兜底：查注册表里的卸载信息
    try:
        import winreg  # type: ignore

        for hive, key in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ),
        ):
            try:
                with winreg.OpenKey(hive, key) as root:
                    for i in range(winreg.QueryInfoKey(root)[0]):
                        try:
                            sub = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, sub) as sk:
                                name = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                                if "网易云" not in name and "CloudMusic" not in name:
                                    continue
                                loc = str(
                                    winreg.QueryValueEx(sk, "InstallLocation")[0]
                                )
                                exe = Path(loc) / "cloudmusic.exe"
                                if exe.is_file():
                                    return str(exe)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass
    return ""


def is_running() -> bool:
    """客户端进程是否在跑。"""
    if platform.system() != "Windows":
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/fi", f"imagename eq {_PROCESS_NAME}", "/nh"],
            capture_output=True,
            timeout=15,
        )
        return _PROCESS_NAME.encode("ascii") in (out.stdout or b"").lower()
    except Exception:
        return False


def kill_client(*, timeout: float = 15.0) -> bool:
    """关掉客户端进程。已经没在跑时也算成功。"""
    if platform.system() != "Windows":
        return False
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", _PROCESS_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return True
    except Exception:
        return False


def launch_with_cdp(
    exe_path: str = "", *, port: int = 9222
) -> bool:
    """启动客户端并带上 ``--remote-debugging-port``。

    :param exe_path: 留空则走 :func:`find_client_exe`
    :raises ClientNotFound: 路径为空且自动查找也失败
    """
    exe = (exe_path or "").strip().strip('"') or find_client_exe()
    if not exe:
        raise ClientNotFound(
            "找不到 cloudmusic.exe；请显式传入路径（本库不扫全盘）"
        )
    if not Path(exe).is_file():
        raise ClientNotFound(f"cloudmusic.exe 路径不存在：{exe}")
    try:
        subprocess.Popen(
            [exe, f"--remote-debugging-port={int(port)}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            cwd=str(Path(exe).parent),
        )
        return True
    except Exception:
        return False


def restart_with_cdp(
    exe_path: str = "", *, cfg: CDPConfig | None = None
) -> bool:
    """关掉再带调试端口重启。

    这是接入 CDP 的标准动作。会**关掉用户当前正在播放的客户端**，
    所以只在用户明确要求时调用。
    """
    cfg = cfg or CDPConfig()
    exe = (exe_path or cfg.exe_path or os.environ.get("NETEASE_CLOUDMUSIC_EXE", ""))
    if not exe:
        exe = find_client_exe()
    if not exe:
        return False
    if platform.system() != "Windows":
        return False
    kill_client()
    time.sleep(1.5)
    return launch_with_cdp(exe, port=cfg.port)


def ensure_ready(
    cfg: CDPConfig | None = None,
    *,
    auto_restart: bool = False,
    exe_path: str = "",
) -> bool:
    """确保调试端口可用；``auto_restart=True`` 时允许自动重启客户端。

    默认**不**自动重启：那会打断用户正在听的歌。桌宠若要开机自启，
    应由调用方自己判断时机后传 ``auto_restart=True``。
    """
    cfg = cfg or CDPConfig()
    if session.available(cfg):
        return True
    if not auto_restart:
        return False
    if not restart_with_cdp(exe_path or cfg.exe_path, cfg=cfg):
        return False
    deadline = time.time() + max(1.0, float(cfg.restart_wait_sec))
    while time.time() < deadline:
        time.sleep(1.0)
        if session.available(cfg):
            return True
    return False


__all__ = [
    "DEFAULT_EXE_CANDIDATES",
    "ensure_ready",
    "find_client_exe",
    "is_running",
    "kill_client",
    "launch_with_cdp",
    "restart_with_cdp",
]
