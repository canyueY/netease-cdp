# netease-cdp

用 **Chrome DevTools Protocol** 驱动 **网易云音乐桌面客户端**。

不碰 HTTP API、不需要登录、不读 cookie——它控制的是你机器上那个**已经登录好**的
客户端窗口。于是 VIP 曲目、私人雷达、每日推荐这些「必须有账号才能碰」的东西
天然可用，因为用的就是客户端自己的会话。

```python
from netease_cdp import NeteaseCDP

nc = NeteaseCDP()
print(nc.current_track().name)     # 当前在放什么
nc.play(1446615816)                # 点播一首歌
nc.play_card("private_radar")      # 播放私人雷达
```

> **平台**：Windows。网易云桌面端是 Electron 应用，CDP 是 Chromium 的能力，
> 而客户端只在 Windows / macOS 发行。端口发现、进程重启这些实现按 Windows 写。

## 三分钟接入

调试端口**只能在进程启动时**由命令行参数打开，没法给一个已经在跑的客户端补开。
所以第一次接入必然要重启一次客户端：

```bash
# ① 关掉网易云，然后带上调试端口重新启动
"C:\Program Files\Netease\CloudMusic\cloudmusic.exe" --remote-debugging-port=9222
```

```python
# ② 验证
from netease_cdp import NeteaseCDP

nc = NeteaseCDP()
probe = nc.probe()
print(probe["available"], probe["track"])
```

嫌麻烦就让库自己重启（会打断正在播的歌）：

```python
nc.ensure_ready(auto_restart=True)          # 自动找安装路径 + 重启
nc.ensure_ready(auto_restart=True, exe_path=r"D:\CloudMusic\cloudmusic.exe")
```

开机自启的用法见 [`examples/auto_start.py`](examples/auto_start.py)。

## 安装

```bash
pip install netease-cdp
# 或从源码
pip install -e ".[dev]"
```

只有一个运行时依赖：`websockets`。其余全是标准库。

## 能做什么

| 方法 | 说明 |
| --- | --- |
| `available()` | 调试端口是否可用（不抛异常） |
| `probe()` | 一次拿回「连接状态 + 当前曲目」，适合做健康检查 |
| `is_playing()` | 是否在播放 |
| `current_track()` | 当前曲目 → `Track(id, name, artists, duration_ms, playing)` |
| `current_track_id()` | 只要 id |
| `play(song_id)` | 点播单曲（已在放同一首时不重复派发） |
| `insert_next(song_id)` | 插到「下一首播放」 |
| `next_track()` / `previous_track()` | 上一首 / 下一首 |
| `next_track_dom()` | 下一首（DOM 回退，Redux 被拦时用） |
| `navigate(hash_path)` | 切客户端内部路由 |
| `click_card(card_key)` | 点开发现页个性化推荐卡片 |
| `play_daily()` | 播放「每日推荐」（卡片 → 详情页两级回退） |
| `play_card(card_key)` | 播放私人雷达 / 心动模式 / 私人漫游 |
| `ensure_ready(auto_restart=)` | 确保端口可用，必要时重启客户端 |
| `restart_client()` | 关掉并带调试端口重启 |

`card_key` 取 `daily` / `private_radar` / `heart_mode` / `private_roam`；
不在表里的值会按字面量当文案关键词用，所以自定义卡片也能点。

低层入口也开放着，需要更细的控制时直接用：

```python
from netease_cdp import Session, CDPConfig, js

s = Session(CDPConfig(port=9222))
print(s.target())                                  # 页面元信息
print(s.evaluate(js.wrap("return navigator.userAgent;")))
```

## 两种调用风格

面向对象和函数式都提供，函数式那套与早期版本一一对应，迁移时改个 import 就行：

```python
from netease_cdp import cdp_play_song, cdp_get_playing_track_info

cdp_play_song(1446615816, port=9222)
print(cdp_get_playing_track_info(port=9222))
```

## 为什么走 CDP

网易云客户端是 Electron + React + Redux。它没有对外 IPC，但：

* **Redux store 挂在 React fiber 树上。** 从 `#root` 的 `__reactContainer$…`
  键往下 BFS，就能在某个节点的 `memoizedProps.store` 上把 store 捞出来。
* **`async:action/doAction` 这个 action 名长期稳定。** 拿到 store 后直接
  `dispatch`，可以精确指定资源 id，不必先把元素滚进视口、也不必赌 DOM 选择器。
* **DOM 层仍然保留为回退。** 有些版本的 `playNext` 会被前端守卫拦掉，这时
  直接点 `.prv[data-action="next"]` 反而有效。

代价是：**前端改版就可能失效**。所以本库对每一处依赖内部结构的地方都写了
注释说明「为什么是它、失效时会怎样」，注入的 JS 也集中在
[`src/netease_cdp/js.py`](src/netease_cdp/js.py) 一个文件里，便于改版后定位。

## 几个刻意的设计决定

**只连本机。** 调试端口连上就等于交出页面控制权。默认拒绝非环回地址的
WebSocket 端点；确实需要（比如经 SSH 端口转发）再开
`allow_remote_host=True`。

**显式 `ws_url`。** 默认从 `GET /json` 自动发现调试地址。若调试端口对外的
地址与进程内监听的不一致（SSH 转发、容器映射），用 `CDPConfig(ws_url=...)`
直接指定。

**不自动重启。** `available()` 为假时不会自作主张去重启客户端——那会打断
用户正在听的歌。要自动重启必须显式传 `auto_restart=True`。

**状态读取吞异常。** `is_playing()` / `current_track()` 这类查询在连不上时
返回假值而不是抛异常，方便轮询；而 `Session.evaluate()` 会如实抛出
`CDPUnavailable` / `ScriptError` / `CDPTimeout`，需要区分故障原因时用它。

**点播以客户端实际状态为准。** `play()` 不看 dispatch 的返回值，而是派发后
回读 `currentTrackId` / `isPlaying`；只有客户端真的开始放了才返回 `True`。

**当前曲目字段的位置是实测出来的。** `s.entities.tracks[trackId]` 在多数
版本里取不到（`trackIsNull: true`），歌手名实际在 `s.playing.resourceArtists`。
详见 `js.CURRENT_TRACK_BODY` 的注释——如果哪天歌名/歌手读不出来，先看那里。

## 排错

| 现象 | 原因 |
| --- | --- |
| `CDPUnavailable`：连不上端口 | 客户端没带 `--remote-debugging-port` 启动 |
| `CDPUnavailable`：没有可用的 page | 端口开了但客户端窗口还没加载完；等几秒重试 |
| `CardNotFound`：`card-not-found` | 发现页文案或结构变了，或当前账号没有该推荐位 |
| `ScriptError` | 前端改版，注入的选择器/Redux 结构对不上；改 `js.py` |
| 点播返回 `False` 但没报错 | dispatch 成功但客户端没真的开始放；看 `play()` 的重试次数 |
| 上一首/下一首无效 | 试 `next_track_dom()` 走 DOM 回退 |

抓页面结构快照来对照：

```python
from netease_cdp import Session, js
print(Session().evaluate(js.wrap("var s=window._reduxStore.getState(); return Object.keys(s);")))
```

## 授权

**AGPL-3.0-or-later**，见 [LICENSE](LICENSE)。

本库从作者自己的桌宠项目 [MurasamePet](https://github.com/canyueY/MurasamePet)
（AGPL-3.0）中抽出。代码是那个项目自己新增的部分，但既然来自 AGPL 项目，
这里就继续沿用 AGPL，不做改许可。

网易云音乐是网易的商标，本库与网易无任何关系。请自行确认你的使用方式符合
其服务条款。

## 来源与开发位置

> **本仓库是镜像；权威源码在 MurasamePet 仓库里。**
>
> 开发位置：`MurasamePet/packages/netease-cdp/`。
> 桌宠通过 **path 依赖**直接使用它——不再保留任何副本，改这里立即可见。
> 这个独立仓库用于对外发布与展示，内容由 Monorepo 同步而来。
>
> **为什么不反过来（本仓库为源、桌宠用 `git` 依赖）？**
> 开发机上网关受限：`github.com` 必须走本地代理，而 `uv` 拉 git 依赖时
> 用不上该代理（实测 `git fetch` 失败）。path 依赖离线可用、不受代理开关影响。

## 测试

```bash
uv run --python 3.10 --extra dev python -m pytest tests -q
```

测试**不需要**真的开网易云：`tests/conftest.py` 里有一个真实的假 CDP 服务器
（真 HTTP 端点 + 真 WebSocket 服务端），所以 JSON 组包、`id` 匹配、事件插播
跳过、超时这些容易写错的地方都真的被执行到了。
