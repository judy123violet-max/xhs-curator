# -*- coding: utf-8 -*-
"""
小红书博主笔记 勾选工作台

用法:
    python xhs_picker_server.py [--port 8788]

读取 notes.json，在浏览器打开一个列表页：
    - 卡片式展示：封面 / 标题 / 类型 / 点赞 / 收藏
    - 复选框挑选手动勾选，支持 全选/反选/仅视频/仅图文/关键词过滤
    - 点「保存选中清单」把结果写入 selection.json，页面即时反馈
    - 封面图经本地代理转发，绕过 CDN 防盗链
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
NOTES = os.path.join(BASE, "notes.json")  # 可被 --notes 覆盖（如 search_notes.json）
SEL = os.path.join(BASE, "selection.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def load_notes():
    with open(NOTES, encoding="utf-8") as f:
        return json.load(f)


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · 笔记挑选</title>
<style>
:root{
  --bg:#f6f7f9; --card:#fff; --line:#e6e8ec; --txt:#1d2129; --sub:#86909c;
  --brand:#ff2e4d; --brand-soft:#fff1f3; --ok:#00b42a;
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#17181c; --card:#1f2126; --line:#303238; --txt:#e8e9ec; --sub:#8a8f99;
         --brand:#ff5c78; --brand-soft:#2a1d21; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:20;background:var(--bg);border-bottom:1px solid var(--line);
  padding:16px 22px 12px}
h1{margin:0 0 4px;font-size:18px}
.meta{color:var(--sub);font-size:12.5px}
.tools{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--card);
  color:var(--txt);padding:7px 13px;border-radius:8px;transition:.15s}
button:hover{border-color:var(--brand);color:var(--brand)}
button.primary{background:var(--brand);border-color:var(--brand);color:#fff;font-weight:600}
button.primary:hover{opacity:.9;color:#fff}
input[type=search]{font:inherit;padding:7px 12px;border:1px solid var(--line);border-radius:8px;
  background:var(--card);color:var(--txt);min-width:220px}
.count{margin-left:auto;font-weight:600;color:var(--brand)}
.grid{display:grid;gap:14px;padding:18px 22px 120px;
  grid-template-columns:repeat(auto-fill,minmax(215px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;
  position:relative;transition:.15s;display:flex;flex-direction:column}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 18px rgba(0,0,0,.08)}
.card.on{border-color:var(--brand);box-shadow:0 0 0 2px var(--brand-soft)}
.card img{width:100%;aspect-ratio:3/4;object-fit:cover;display:block;background:var(--line)}
.ph{width:100%;aspect-ratio:3/4;display:flex;align-items:center;justify-content:center;
  color:var(--sub);font-size:12px;background:var(--line)}
.card .body{padding:10px 11px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
.card .t{font-size:13.5px;font-weight:600;line-height:1.45;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
  word-break:break-word}
.card .s{color:var(--sub);font-size:12px;margin-top:auto}
.tag{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.62);color:#fff;font-size:11px;
  padding:2px 7px;border-radius:6px;backdrop-filter:blur(4px)}
.tag-top{top:34px;background:rgba(255,46,77,.92)}
.cb{position:absolute;top:7px;right:7px;width:23px;height:23px;border-radius:6px;
  border:2px solid #fff;background:rgba(0,0,0,.42);display:flex;align-items:center;
  justify-content:center;color:#fff;font-size:14px;font-weight:700}
.card.on .cb{background:var(--brand);border-color:var(--brand)}
.card a{color:inherit;text-decoration:none}
.card a.t:hover{color:var(--brand)}
.card .s a{color:var(--brand);font-weight:600;white-space:nowrap}
.card .s a:hover{text-decoration:underline}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:30;background:var(--card);
  border-top:1px solid var(--line);padding:12px 22px;display:flex;gap:12px;align-items:center}
.bar .tip{color:var(--sub);font-size:12.5px}
.toast{position:fixed;left:50%;top:22px;transform:translateX(-50%);z-index:50;
  background:var(--ok);color:#fff;padding:10px 20px;border-radius:10px;font-weight:600;
  opacity:0;pointer-events:none;transition:.25s}
.toast.show{opacity:1}
.empty{padding:60px 22px;text-align:center;color:var(--sub)}
</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <div class="meta">共 __TOTAL__ 条笔记 · 抓取时间 __TIME__ · 勾选后点右下角保存</div>
  <div class="tools">
    <input type="search" id="q" placeholder="搜索标题关键词…">
    <button onclick="pick('all')">全选</button>
    <button onclick="pick('none')">清空</button>
    <button onclick="pick('invert')">反选</button>
    <button onclick="pick('video')">仅视频</button>
    <button onclick="pick('normal')">仅图文</button>
    <span class="count" id="cnt">已选 0 篇</span>
  </div>
</header>
<div class="grid" id="grid"></div>
<div class="bar">
  <button class="primary" onclick="save()">保存选中清单</button>
  <button onclick="copySel()">复制清单文本</button>
  <span class="tip" id="barTip">点卡片=勾选；点标题或「原文↗」在本窗口打开详情，看完按 Alt+←（或浏览器返回键）回来，勾选不会丢</span>
</div>
<div class="toast" id="toast"></div>

<script>
const NOTES = __DATA__;
const grid = document.getElementById('grid');
const LSKEY = 'xhs_picker_sel';
const state = new Set();
// 从 localStorage 恢复勾选，防止刷新/服务重启丢清单
try{ JSON.parse(localStorage.getItem(LSKEY)||'[]').forEach(id=>{
  if(NOTES.some(n=>n.note_id===id)) state.add(id);
}); }catch(e){}

let saveTimer = null;
function persist(){
  try{ localStorage.setItem(LSKEY, JSON.stringify([...state])); }catch(e){}
  clearTimeout(saveTimer);
  saveTimer = setTimeout(()=>autoSave(), 400);
}
async function autoSave(){
  if(!state.size){ document.getElementById('barTip').textContent = '选好后保存，我就能按清单去抓正文和图片'; return; }
  try{
    const r = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ids:[...state]})});
    const j = await r.json();
    if(j.ok){
      const t = new Date().toLocaleTimeString('zh-CN',{hour12:false});
      document.getElementById('barTip').textContent = `✓ 已自动保存 ${j.count} 篇（${t}）`;
    }
  }catch(e){}
}

function render(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  grid.innerHTML = '';
  let shown = 0;
  NOTES.forEach((n,i)=>{
    const hay = (n.title||'').toLowerCase();
    if(q && !hay.includes(q)) return;
    shown++;
    const d = document.createElement('div');
    d.className = 'card' + (state.has(n.note_id) ? ' on' : '');
    d.dataset.id = n.note_id;
    d.dataset.type = n.type;
    const isVideo = n.type === 'video';
    const cover = n.cover
      ? `<img loading="lazy" src="/img?u=${encodeURIComponent(n.cover)}" alt="">`
      : `<div class="ph">无封面</div>`;
    const link = n.url || ('https://www.xiaohongshu.com/explore/' + n.note_id);
    d.innerHTML = `${cover}
      <div class="tag">${isVideo ? '视频' : '图文'}</div>
      ${n.sticky ? '<div class="tag tag-top">置顶</div>' : ''}
      <div class="cb">${state.has(n.note_id) ? '✓' : ''}</div>
      <div class="body">
        <a class="t" href="${link}" title="点开查看笔记详情（返回请按 Alt+← 或浏览器返回键，勾选已自动保存）" onclick="event.stopPropagation()">${esc(n.title) || '<span style="color:var(--sub)">(无标题)</span>'}</a>
        <div class="s">${n.date || ''}　♥ ${n.liked || 0}　<a href="${link}" onclick="event.stopPropagation()">原文↗</a></div>
      </div>`;
    d.onclick = ()=>{
      if(state.has(n.note_id)) state.delete(n.note_id); else state.add(n.note_id);
      d.classList.toggle('on');
      d.querySelector('.cb').textContent = state.has(n.note_id) ? '✓' : '';
      updCnt(); persist();
    };
    grid.appendChild(d);
  });
  if(!shown) grid.innerHTML = '<div class="empty">没有匹配的笔记</div>';
  updCnt();
}
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}
function visibleCards(){
  const q = document.getElementById('q').value.trim().toLowerCase();
  return NOTES.filter(n => !q || (n.title||'').toLowerCase().includes(q));
}
function pick(mode){
  const vis = visibleCards();
  if(mode==='all') vis.forEach(n=>state.add(n.note_id));
  if(mode==='none') state.clear();
  if(mode==='invert') vis.forEach(n=> state.has(n.note_id)?state.delete(n.note_id):state.add(n.note_id));
  if(mode==='video') vis.filter(n=>n.type==='video').forEach(n=>state.add(n.note_id));
  if(mode==='normal') vis.filter(n=>n.type!=='video').forEach(n=>state.add(n.note_id));
  render(); persist();
}
function updCnt(){ document.getElementById('cnt').textContent = `已选 ${state.size} 篇`; }
function toast(msg, bg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.background = bg || 'var(--ok)';
  t.classList.add('show'); setTimeout(()=>t.classList.remove('show'), 2200);
}
async function save(){
  if(!state.size){ toast('还没有选任何笔记', '#e64545'); return; }
  const ids = [...state];
  try{
    const r = await fetch('/save', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ids})});
    const j = await r.json();
    if(j.ok){ toast(`已保存 ${j.count} 篇 → selection.json`); }
    else toast('保存失败: ' + (j.error||''), '#e64545');
  }catch(e){ toast('保存失败: ' + e, '#e64545'); }
}
function copySel(){
  const txt = [...state].map(id=>{
    const n = NOTES.find(x=>x.note_id===id);
    return n ? `${n.title}\t${n.url}` : id;
  }).join('\n');
  navigator.clipboard.writeText(txt).then(()=>toast('已复制到剪贴板'));
}
document.getElementById('q').addEventListener('input', render);
render();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/img"):
            qs = urllib.parse.urlparse(self.path).query
            u = urllib.parse.parse_qs(qs).get("u", [""])[0]
            if not u.startswith("http"):
                self._send(404, b"bad", "text/plain")
                return
            try:
                req = urllib.request.Request(u, headers={
                    "User-Agent": UA,
                    "Referer": "https://www.xiaohongshu.com/",
                    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                })
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                    ct = r.headers.get("Content-Type", "image/jpeg")
                self._send(200, data, ct)
            except Exception as e:
                self._send(502, f"img fail: {e}".encode(), "text/plain")
            return

        if self.path.startswith("/json"):
            with open(NOTES, encoding="utf-8") as f:
                self._send(200, f.read(), "application/json; charset=utf-8")
            return

        data = load_notes()
        html = (PAGE
                .replace("__DATA__", json.dumps(data["notes"], ensure_ascii=False))
                .replace("__TITLE__", data.get("nickname") or "小红书博主")
                .replace("__TOTAL__", str(data.get("count", 0)))
                .replace("__TIME__", data.get("fetched_at", "")))
        self._send(200, html)

    def do_POST(self):
        if self.path != "/save":
            self._send(404, b"no", "text/plain")
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(n) or b"{}")
            ids = payload.get("ids") or []
            data = load_notes()
            by = {x["note_id"]: x for x in data["notes"]}
            chosen = [by[i] for i in ids if i in by]
            out = {
                "user_id": data.get("user_id"),
                "nickname": data.get("nickname"),
                "profile_url": data.get("profile_url"),
                "saved_at": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(chosen),
                "notes": chosen,
            }
            with open(SEL, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            self._send(200, json.dumps({"ok": True, "count": len(chosen)}),
                       "application/json; charset=utf-8")
        except Exception as e:
            self._send(200, json.dumps({"ok": False, "error": str(e)}),
                       "application/json; charset=utf-8")


def main():
    global NOTES
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--notes", default=NOTES, help="笔记清单 JSON（默认 notes.json，搜索结果传 search_notes.json）")
    args = ap.parse_args()
    NOTES = args.notes if os.path.isabs(args.notes) else os.path.join(BASE, args.notes)
    if not os.path.exists(NOTES):
        print(f"[X] 找不到 {NOTES}，请先运行 xhs_creator_fetch.py 或 xhs_search_fetch.py")
        return
    d = load_notes()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[√] 工作台已启动: http://127.0.0.1:{args.port}")
    print(f"    清单: {NOTES}")
    print(f"    博主: {d.get('nickname')} | 笔记: {d.get('count')} 条")
    print("    Ctrl+C 停止")
    srv.serve_forever()


if __name__ == "__main__":
    main()
