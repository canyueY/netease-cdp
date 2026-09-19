# Changelog

本文件记录 netease-cdp 的对外变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-09-19

首次发布。从 [MurasamePet](https://github.com/canyueY/MurasamePet) 的
`Murasame/netease_cdp.py` 抽出并重构。

### Added

- `NeteaseCDP` 控制器：`available` / `probe` / `is_playing` /
  `current_track` / `current_track_id` / `play` / `insert_next` /
  `next_track` / `previous_track` / `next_track_dom` / `navigate` /
  `click_card` / `play_daily` / `play_card` / `ensure_ready` / `restart_client`。
- `Session` 低层会话层：目标发现与 `Runtime.evaluate`。
- `Track` / `PlayResult` 返回值类型（frozen dataclass，可 JSON 化）。
- `CDPConfig` 连接参数，含端口/超时/重试/路由等校验。
- `js` 模块：集中存放注入页面用的 JS 片段，附「为什么这么写」的注释。
- `launcher` 模块：查找客户端、带调试端口启动、重启、就绪等待。
- 异常层次：`NeteaseCDPError` / `CDPUnavailable` / `CDPTimeout` /
  `ScriptError` / `ClientNotFound`。
- 函数式兼容层：`cdp_play_song` / `cdp_get_playing_track_info` 等，
  与抽取前的接口一一对应，便于迁移。

### Changed

相对于抽取前的实现：

- 当前曲目的歌手名改从 `s.playing.resourceArtists` 读取。原实现只认
  `track.ar` / `track.artists`，而 `s.entities.tracks[trackId]` 在多数
  客户端版本里是空的（`trackIsNull: true`），导致**歌手名永远取不到**。
  现在以 `playing.*` 为主、`entities.tracks` 为辅。
- `play()` 会增加一次「已经在放同一首」的短路判断，避免多余的一次
  往返；需要强制重新派发时用 `force=True`。
- 日推详情页脚本的 `needRetry` 语义修正：原来重试耗尽后会把 hash 字符串
  当成结果返回，看起来像成功；现在如实报告 `navigating-daily-page`。
- 连接端点默认限制为环回地址（新增 `allow_remote_host` 开关）。
- `port=0` 直接报错，而不是让内核分配一个谁也连不上的端口。

### Security

- 新增 `CDPConfig.allowed_hosts` / `allow_remote_host`：默认拒绝连接到
  非本机的 CDP 端点。调试端口一旦暴露到局域网，等于把浏览器控制权交出去。

[0.1.0]: https://github.com/canyueY/netease-cdp/releases/tag/v0.1.0
