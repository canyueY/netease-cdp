# -*- coding: utf-8 -*-
"""注入到网易云页面里的 JS 片段。

Copyright (C) 2026 canyueY <https://github.com/canyueY>
SPDX-License-Identifier: AGPL-3.0-or-later

本模块只做一件事：把验证过的 JS 源码集中存放，不掺任何 Python 逻辑。
字符串内容与线上实测通过的版本逐字一致——改这里之前请先确认真实客户端
还能跑通，因为 React 内部结构一旦对不上，失败是静默的（返回 false /
空对象），不会抛异常。

一点背景，供改版后排查用：

* **为什么要爬 React fiber。** 网易云桌面端是 Electron + React + Redux，
  没有对外 IPC。但 React 会把 store 挂在 fiber 树某个节点的
  ``memoizedProps.store`` 上，同时根容器带 ``__reactContainer$xxx``
  之类的键。从根往下 BFS 就能把 Redux store 捞出来。
* **为什么用 Redux dispatch 而不是点 DOM。** DOM 选择器随版本漂移，
  而 ``async:action/doAction`` 这个 action 名长期稳定，且能直接指定
  资源 id，不必先滚到可见区域。
* **``_ensureStore`` 的结果缓存在 ``window._reduxStore``。** 页面重载后
  会失效，所以每次调用都重新确认一遍（有就直接返回）。
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# 0. 前置：把 Redux store 从 React fiber 树里捞出来
# ---------------------------------------------------------------------------

FIBER_STORE_JS = r"""
function _ensureStore() {
  if (!window.__debug_store_log) window.__debug_store_log = [];
  try {
    if (window._reduxStore) return true;
    const rootEl = document.querySelector('#root');
    let root = window._fiberRoot
      || (rootEl && rootEl._reactRootContainer && rootEl._reactRootContainer._internalRoot);
    if (!root && rootEl) {
      const rk = Object.keys(rootEl).find(function(k) {
        return k.indexOf('__reactContainer') === 0 || k.indexOf('__reactFiber') === 0;
      });
      if (rk) {
        const holder = rootEl[rk];
        root = (holder && (holder._reactRootContainer || holder)) || null;
        if (root && root._internalRoot) root = root._internalRoot;
      }
    }
    if (!root) return false;
    let queue = [root.current || root];
    let visited = 0;
    while (queue.length > 0) {
      let node = queue.shift();
      if (!node) continue;
      visited++;
      if (visited > 20000) break;
      if (node.memoizedProps && node.memoizedProps.store) {
        window._reduxStore = node.memoizedProps.store;
        return true;
      }
      if (node.pendingProps && node.pendingProps.store) {
        window._reduxStore = node.pendingProps.store;
        return true;
      }
      if (node.stateNode && node.stateNode.store) {
        window._reduxStore = node.stateNode.store;
        return true;
      }
      let child = node.child;
      while (child) { queue.push(child); child = child.sibling; }
    }
    return false;
  } catch (err) {
    return false;
  }
}
"""


def wrap(body: str) -> str:
    """把片段包成自带 ``_ensureStore`` 的完整 IIFE。

    ``Runtime.evaluate`` 的顶层不允许 ``return``，所以必须包一层函数；
    这里顺手把 :data:`FIBER_STORE_JS` 前置进去，调用方就不用自己拼了。

    :param body: 函数体源码，可以直接写 ``return ...;``
    """
    return f"(function(){{\n{FIBER_STORE_JS}\n{body}\n}})()"


# ---------------------------------------------------------------------------
# 1. 播放控制（走 Redux dispatch）
# ---------------------------------------------------------------------------

#: ``{action_id}`` / ``{data_js}`` 由 Python 侧填充
DISPATCH_BODY = (
    "if(_ensureStore()){{window._reduxStore.dispatch({{type:'async:action/doAction',"
    "payload:{{actionId:'{action_id}',data:{data_js}}}}});return true;}}"
    "return false;"
)


def dispatch_body(action_id: str, data_js: str) -> str:
    """拼一条 ``async:action/doAction`` 派发语句。

    ``action_id`` 是逗号分隔的动作名（网易云客户端自己会拆），
    ``data_js`` 必须是**合法 JS 对象字面量源码**，不是 JSON——
    客户端前端用的是单引号风格的字面量。
    """
    return DISPATCH_BODY.format(action_id=action_id, data_js=data_js)


#: 双击播放某首歌
def play_track_data(song_id: int) -> str:
    """播放单曲的 ``data`` 字面量。"""
    return f"{{resource:{{id:String({int(song_id)})}},resourceType:'track',eventType:'dblclick'}}"


#: 把某首歌插到「下一首播放」
def insert_next_data(song_id: int) -> str:
    """插播单曲的 ``data`` 字面量。"""
    return (
        f"{{resource:{{id:String({int(song_id)}),duration:0}},"
        f"resourceType:'track',eventType:'click'}}"
    )


PLAY_NEXT_DATA = "{eventType:'click'}"
PLAY_PREV_DATA = "{eventType:'click'}"


# -- 状态读取 ---------------------------------------------------------------

IS_PLAYING_BODY = (
    "if(_ensureStore()){const s=window._reduxStore.getState();"
    "const id=s.playing?.resourceTrackId||s.playing?.onlineResourceId;"
    "return !!(id&&(s.playing?.playing!==false));}"
    "return false;"
)

CURRENT_TRACK_ID_BODY = (
    "if(_ensureStore()){const s=window._reduxStore.getState();"
    "const id=s.playing?.resourceTrackId||s.playing?.onlineResourceId;"
    "return id?String(id):'';}"
    "return '';"
)

#: 当前曲目详情。字段位置是**实测**出来的：
#: ``s.entities.tracks[trackId]`` 在多数版本里取不到（``trackIsNull: True``），
#: 真正的歌手名在 ``s.playing.resourceArtists``（``[{id,name,...}]``），
#: 歌名在 ``s.playing.resourceName``。所以以 ``playing.*`` 为主、
#: ``entities.tracks`` 为辅。
CURRENT_TRACK_BODY = (
    "if(_ensureStore()){"
    "var s=window._reduxStore.getState();"
    "var pl=s.playing||{};"
    "var id=pl.resourceTrackId||pl.onlineResourceId||'';"
    "var track=(s.entities&&s.entities.tracks&&s.entities.tracks[id])"
    "||(s.track&&s.track.entities&&s.track.entities[id])||null;"
    "var name=(track&&(track.name||track.title))||pl.resourceName||'';"
    "function pickName(a){"
    "if(!a)return '';"
    "if(typeof a==='string')return a;"
    "if(typeof a!=='object')return '';"
    "return a.name||a.nickname||a.title||'';"
    "}"
    "function joinArtists(v){"
    "if(!v)return '';"
    "if(typeof v==='string')return v;"
    "if(typeof v!=='object')return '';"
    "if(!Array.isArray(v))v=[v];"
    "return v.map(pickName).filter(Boolean).join('/');"
    "}"
    "var artists='';"
    "artists=joinArtists(pl.resourceArtists);"
    "if(!artists&&track){"
    "var cands=[track.ar,track.artists,track.singer,track.singers,track.artist];"
    "for(var i=0;i<cands.length;i++){"
    "var got=joinArtists(cands[i]);"
    "if(got){artists=got;break;}"
    "}"
    "}"
    "return {id:String(id||''),name:String(name||''),artists:artists,"
    # 与 is_playing 用完全一致的判定，避免两处语义漂移
    "playing:!!(id&&pl.playing!==false),"
    "duration:Number(pl.resourceDuration||0)||0};"
    "}"
    "return {id:'',name:'',artists:'',playing:false};"
)


# -- DOM 回退：Redux 拿不到时直接点按钮 -------------------------------------

NEXT_DOM_JS = """
(function() {
  const nextBtn = document.querySelector('.prv[data-action="next"]')
    || document.querySelector('.btn-next');
  if (nextBtn) { nextBtn.click(); return true; }
  return false;
})()
"""


def navigate_hash_body(hash_path: str) -> str:
    """改 ``location.hash`` 并回读实际值。"""
    return (
        f"var h={json.dumps(hash_path)};"
        "if(!h.startsWith('#'))h='#/'+h.replace(/^\\/+/, '');"
        "try{if(window.location.hash!==h)window.location.hash=h;}catch(e){}"
        "return window.location.hash||h;"
    )


# ---------------------------------------------------------------------------
# 2. 发现页个性化推荐卡片
# ---------------------------------------------------------------------------
# 用法：DISCOVER_CLICK_CARD_JS + json.dumps(keywords) + ")"
# 注意这段**自带** IIFE 包装，不要再套 wrap()。

DISCOVER_CLICK_CARD_JS = r"""
(function(keywords){
  function norm(t){return String(t||'').replace(/\s+/g,'');}
  function findSection(){
    var nodes=document.querySelectorAll(
      'h2,h3,h4,.tit,.hd h2,.tit-txt,[class*="title"],[class*="Title"],[class*="header"]'
    );
    for(var i=0;i<nodes.length;i++){
      var t=norm(nodes[i].textContent);
      if(t.indexOf('个性化推荐')>=0){
        var sec=nodes[i].closest('section')
          ||nodes[i].closest('[class*="recommend"]')
          ||nodes[i].closest('[class*="Recommend"]')
          ||nodes[i].parentElement;
        for(var d=0;d<8&&sec;d++){
          var cnt=sec.querySelectorAll(
            'li,[class*="item"],[class*="card"],[class*="Rec"],[class*="rec-"]'
          ).length;
          if(cnt>=2) return sec;
          sec=sec.parentElement;
        }
      }
    }
    return document.querySelector('.n-recommend')
      ||document.querySelector('[class*="personalized"]')
      ||document.querySelector('[id*="recommend"]')
      ||document.body;
  }
  function pickCard(root, kws){
    var nodes=root.querySelectorAll(
      'li,[class*="item"],[class*="card"],[class*="RecItem"],[class*="rec-item"],[class*="m-rec"]'
    );
    var best=null, bestScore=-1;
    for(var i=0;i<nodes.length;i++){
      var el=nodes[i];
      var text=norm(el.textContent);
      for(var j=0;j<kws.length;j++){
        var kw=norm(kws[j]);
        if(!kw||text.indexOf(kw)<0) continue;
        var score=kw.length*12;
        if(kw.indexOf('每日')>=0&&text.indexOf('根据你的口味')>=0) score+=20;
        if(kw.indexOf('私人雷达')>=0&&text.indexOf('猜你喜欢')>=0) score+=20;
        if(kw.indexOf('心动')>=0&&text.indexOf('红心')>=0) score+=20;
        if(kw.indexOf('私人漫游')>=0&&(text.indexOf('银河')>=0||text.indexOf('漫游')>=0)) score+=20;
        if(score>bestScore){bestScore=score;best=el;}
      }
    }
    return best;
  }
  function clickPlay(card){
    var root=card.closest('li')||card.closest('[class*="item"]')||card;
    try{root.scrollIntoView({block:'center',inline:'nearest'});}catch(e){}
    var sel='.icon-play,.u-coverplay,[class*="coverplay"],[class*="CoverPlay"],'
      +'.ply,.btn-play,[data-action="play"],[class*="play-btn"]';
    var btn=root.querySelector(sel);
    if(btn){btn.click();return {ok:true,how:'play-btn',label:norm(root.textContent).slice(0,40)};}
    var cover=root.querySelector('.u-cover, [class*="cover"] img, [class*="cover"]');
    if(cover){cover.click();return {ok:true,how:'cover',label:norm(root.textContent).slice(0,40)};}
    root.click();
    return {ok:true,how:'card',label:norm(root.textContent).slice(0,40)};
  }
  var sec=findSection();
  var card=pickCard(sec, keywords);
  if(!card) return {ok:false,reason:'card-not-found',section:!!sec};
  return clickPlay(card);
})
"""


def click_card_js(keywords: tuple[str, ...] | list[str]) -> str:
    """生成「在发现页点某张推荐卡片」的完整表达式。"""
    return f"{DISCOVER_CLICK_CARD_JS}{json.dumps(list(keywords), ensure_ascii=False)})"


#: 日推详情页（``#/discover/recommend``）的「播放全部」。
#: 自带 IIFE，同样不要再套 wrap()。
PLAY_DAILY_PAGE_JS = r"""
(function(){
  function norm(t){return String(t||'').replace(/\s+/g,'');}
  function clickPlay(el){
    if(!el) return false;
    try{el.scrollIntoView({block:'center',inline:'nearest'});}catch(e){}
    el.click();
    return true;
  }
  var hash=(window.location.hash||'');
  if(hash.indexOf('discover/recommend')<0){
    window.location.hash='#/discover/recommend';
    return {ok:false,reason:'navigating-daily-page',needRetry:true};
  }
  var nodes=document.querySelectorAll('a,button,span,i,div');
  for(var i=0;i<nodes.length;i++){
    var t=norm(nodes[i].textContent);
    if(t==='播放全部'||t.indexOf('播放全部')===0){
      if(clickPlay(nodes[i])) return {ok:true,how:'play-all'};
    }
  }
  var headerPlay=document.querySelector(
    '.icon-play,.u-coverplay,[class*="coverplay"],[class*="CoverPlay"],.ply'
  );
  if(headerPlay&&clickPlay(headerPlay)) return {ok:true,how:'header-play'};
  var row=document.querySelector(
    'table.m-table tbody tr, table tbody tr, [class*="songlist"] [class*="item"], [class*="SongItem"]'
  );
  if(row){
    var pb=row.querySelector('.icon-play,.u-coverplay,[class*="coverplay"],.ply');
    if(pb&&clickPlay(pb)) return {ok:true,how:'first-row-play'};
    try{
      row.dispatchEvent(new MouseEvent('dblclick',{bubbles:true,cancelable:true}));
      return {ok:true,how:'first-row-dblclick'};
    }catch(e){}
  }
  return {ok:false,reason:'daily-page-no-control'};
})()
"""


__all__ = [
    "FIBER_STORE_JS",
    "wrap",
    "dispatch_body",
    "play_track_data",
    "insert_next_data",
    "PLAY_NEXT_DATA",
    "PLAY_PREV_DATA",
    "IS_PLAYING_BODY",
    "CURRENT_TRACK_ID_BODY",
    "CURRENT_TRACK_BODY",
    "NEXT_DOM_JS",
    "navigate_hash_body",
    "DISCOVER_CLICK_CARD_JS",
    "click_card_js",
    "PLAY_DAILY_PAGE_JS",
]
