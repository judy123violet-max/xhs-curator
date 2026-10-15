# -*- coding: utf-8 -*-
"""
按 selection.json 抓取选中笔记的正文 + 原图（复用已登录的浏览器会话）

用法:
    python xhs_fetch_selected.py                 # 抓 selection.json 里全部
    python xhs_fetch_selected.py --limit 3       # 只抓前 3 条（测试用）
    python xhs_fetch_selected.py --only <note_id>

产出:
    downloads/<序号>_<标题>/
        raw.json        # 原始字段（标题/正文/时间/类型/图片URL/视频信息）
        note.md         # 正文 + 图片引用（骨架，供后续精修）
        img_01.jpg ...  # 原图（图文）
        subtitle.srt    # 官方字幕（视频，若有）
        frames/         # 关键帧（视频且无字幕时）
"""
import argparse
import json
import os
import re
import time
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
SEL = os.path.join(BASE, "selection.json")
PROFILE = os.path.join(BASE, "browser_profile")
OUTDIR = os.path.join(BASE, "downloads")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 从笔记详情页内存里提取结构化字段（Vue ref 必须走 _rawValue）
JS_EXTRACT = r"""
() => {
  const out = {ok:false, err:''};
  try {
    const st = window.__INITIAL_STATE__ || {};
    let map = (st.note || {}).noteDetailMap;
    if (map && map._rawValue) map = map._rawValue;
    if (!map) { out.err = 'no noteDetailMap'; return JSON.stringify(out); }
    const keys = Object.keys(map).filter(k => k !== 'undefined');
    if (!keys.length) { out.err = 'empty noteDetailMap'; return JSON.stringify(out); }
    let entry = map[keys[0]];
    if (entry && entry._rawValue) entry = entry._rawValue;
    const n = (entry && entry.note) ? entry.note : entry;
    if (!n) { out.err = 'no note obj'; return JSON.stringify(out); }

    out.ok = true;
    out.noteId = n.noteId || keys[0];
    out.title = n.title || '';
    out.desc = n.desc || '';
    out.type = n.type || '';
    out.time = n.time || n.lastUpdateTime || 0;
    out.ipLocation = n.ipLocation || '';
    const ui = n.user || {};
    out.nickname = ui.nickname || ui.nickName || '';
    const ii = n.interactInfo || {};
    out.liked = ii.likedCount || '';
    out.collected = ii.collectedCount || '';
    out.commented = ii.commentCount || '';

    const imgs = [];
    (n.imageList || []).forEach(function (im) {
      let u = im.urlDefault || im.url || '';
      if (!u && im.infoList && im.infoList.length) {
        const last = im.infoList[im.infoList.length - 1];
        u = last.url || '';
      }
      if (u) imgs.push(u);
    });
    out.images = imgs;

    let subs = [];
    const v = n.video || {};
    out.videoDuration = (v.capa && v.capa.duration) || 0;
    // 字幕线索
    try {
      if (v.subtitle) subs = JSON.parse(JSON.stringify(v.subtitle));
    } catch (e) {}
    out.rawSubtitle = subs;
    // 视频直链
    try {
      const st2 = v.media && v.media.stream;
      const h264 = st2 && st2.h264;
      if (h264 && h264.length) out.videoUrl = h264[0].masterUrl || '';
    } catch (e) {}
    return JSON.stringify(out);
  } catch (e) {
    out.err = String(e);
    return JSON.stringify(out);
  }
}
"""


def log(*a):
    print(*a, flush=True)


def sanitize(name, maxlen=48):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" ._")
    return (name or "untitled")[:maxlen]


def download(url, path, referer="https://www.xiaohongshu.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def load_done_index():
    """扫描 downloads/，返回 {序号: 目录名}（仅 raw.json ok=true 的算完成）"""
    done = {}
    if not os.path.isdir(OUTDIR):
        return done
    for dname in os.listdir(OUTDIR):
        m = re.match(r"^(\d+)_", dname)
        rp = os.path.join(OUTDIR, dname, "raw.json")
        if not m or not os.path.exists(rp):
            continue
        try:
            with open(rp, encoding="utf-8") as f:
                if json.load(f).get("ok"):
                    done[int(m.group(1))] = dname
        except Exception:
            pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="同 --count")
    ap.add_argument("--count", type=int, default=0, help="本次最多抓几篇；0=不限")
    ap.add_argument("--offset", type=int, default=0, help="跳过清单前 N 篇（断点续导）")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-resume", action="store_true", help="忽略断点，强制重抓已完成项")
    args = ap.parse_args()

    if not os.path.exists(SEL):
        log("[X] 找不到 selection.json —— 请先在勾选工作台点「保存选中清单」")
        return
    with open(SEL, encoding="utf-8") as f:
        sel = json.load(f)
    notes_full = sel.get("notes") or []
    if not notes_full:
        log("[X] selection.json 里没有笔记")
        return

    count = args.count or args.limit  # --limit 为兼容旧写法
    done = load_done_index()

    # 切片（offset/count）+ 断点跳过；序号始终取全量清单位置，保证目录编号稳定
    todo = []
    for i, note in enumerate(notes_full, 1):
        if args.only and note.get("note_id") != args.only:
            continue
        if i <= args.offset:
            continue
        if not args.no_resume and i in done:
            continue
        todo.append((i, note))
    if count and count > 0:
        todo = todo[:count]

    os.makedirs(OUTDIR, exist_ok=True)
    log("=" * 64)
    log(f"[*] 博主: {sel.get('nickname')} | 清单 {len(notes_full)} 篇 | "
        f"已完成(断点跳过) {len(done)} 篇 | 本次待抓 {len(todo)} 篇"
        + (f" | offset={args.offset} count={count}" if (args.offset or count) else ""))
    if not todo:
        log("[√] 没有需要抓取的笔记（全部完成或切片为空）")
        return
    log("=" * 64)

    from playwright.sync_api import sync_playwright

    manifest = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.new_page()
        page.set_default_timeout(45000)

        # —— 评论区捕获：监听官方 comment/page 接口，稍后按 user_id 只留博主的发言 ——
        author_uid = str(sel.get("user_id") or "")
        comment_hits = []  # (url里的note_id, [comment...])

        def _on_resp(resp):
            try:
                if "comment/page" in resp.url and resp.status == 200:
                    m = re.search(r"note_id=([0-9a-f]{24})", resp.url)
                    if not m:
                        return
                    cs = ((resp.json().get("data") or {}).get("comments")) or []
                    if cs:
                        comment_hits.append((m.group(1), cs))
            except Exception:
                pass

        page.on("response", _on_resp)

        def collect_author_comments(note_id):
            """从已捕获的接口响应里筛出博主的评论（含子评论、置顶）"""
            out, seen = [], set()
            for hit_nid, cs in comment_hits:
                if hit_nid != note_id:
                    continue
                for c in cs:
                    group = [c] + (c.get("sub_comments") or [])
                    for cc in group:
                        cid = cc.get("id")
                        uid = str((cc.get("user_info") or {}).get("user_id") or "")
                        if not cid or cid in seen:
                            continue
                        if not author_uid or uid != author_uid:
                            continue
                        seen.add(cid)
                        out.append({
                            "content": (cc.get("content") or "").strip(),
                            "time": cc.get("create_time"),
                            "likes": cc.get("like_count"),
                            "ip": cc.get("ip_location") or "",
                            "pinned": bool(c.get("is_pinned")) and cc is c,
                        })
            return out

        def scroll_for_comments():
            """滚动触发评论分页加载"""
            for _ in range(8):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1100)

        for i, note in todo:
            nid = note.get("note_id")
            title = note.get("title") or ""
            url = note.get("url") or f"https://www.xiaohongshu.com/explore/{nid}"
            log(f"\n[{i}/{len(notes_full)}] {title[:40]} ({note.get('type')})")

            rec = {"note_id": nid, "list_title": title, "list_type": note.get("type"),
                   "list_date": note.get("date"), "url": url, "ok": False, "_seq": i}

            try:
                page.goto(url, wait_until="domcontentloaded")
            except Exception as e:
                log("     ! 打开失败:", e)
                rec["error"] = f"goto: {e}"
                manifest.append(rec)
                continue

            # 等详情数据挂上
            data = None
            for _ in range(20):
                page.wait_for_timeout(700)
                try:
                    raw = page.evaluate(JS_EXTRACT)
                    d = json.loads(raw)
                    if d.get("ok"):
                        data = d
                        break
                except Exception:
                    pass
            if not data:
                # 退路：从 SSR/HTML 里正则捞
                html = page.content()
                d = {"ok": False, "title": "", "desc": "", "images": []}
                m = re.search(r'"desc":"((?:[^"\\]|\\.)*)"', html)
                if m:
                    d["desc"] = json.loads('"' + m.group(1) + '"')
                t = re.search(r'"title":"((?:[^"\\]|\\.)*)"', html)
                if t:
                    d["title"] = json.loads('"' + t.group(1) + '"')
                imgs = re.findall(r'"urlDefault":"((?:[^"\\]|\\.)*)"', html)
                d["images"] = [u.replace("\\u002F", "/") for u in imgs]
                data = d if (d["desc"] or d["images"]) else None

            if not data:
                log("     ! 拿不到详情数据")
                rec["error"] = "no detail data"
                manifest.append(rec)
                continue

            ntitle = data.get("title") or title
            folder = os.path.join(OUTDIR, f"{i:02d}_{sanitize(ntitle)}")
            os.makedirs(folder, exist_ok=True)

            rec.update({
                "ok": True,
                "title": ntitle,
                "desc": data.get("desc", ""),
                "type": data.get("type") or note.get("type"),
                "time": data.get("time"),
                "ip": data.get("ipLocation"),
                "liked": data.get("liked"),
                "collected": data.get("collected"),
                "commented": data.get("commented"),
                "video_duration": data.get("videoDuration"),
                "video_url": data.get("videoUrl", ""),
                "raw_subtitle": data.get("rawSubtitle"),
                "folder": folder,
                "images": [],
                "subtitle_file": "",
                "frame_files": [],
            })

            # 下载图片
            imgs = data.get("images") or []
            img_files = []
            for k, u in enumerate(imgs, 1):
                fn = f"img_{k:02d}.jpg"
                p = os.path.join(folder, fn)
                try:
                    sz = download(u, p)
                    img_files.append(fn)
                    log(f"     · 图 {k}: {sz // 1024} KB")
                except Exception as e:
                    log(f"     ! 图 {k} 失败: {e}")
                time.sleep(0.25)
            rec["images"] = img_files

            # 视频：找官方字幕
            html = page.content()
            srt = re.findall(r"https://sns-subtitle[^\"\\ ]+\.srt\?[^\"\\ ]+", html)
            if srt:
                u = srt[0].replace("\\u002F", "/")
                p = os.path.join(folder, "subtitle.srt")
                try:
                    download(u, p, referer=url)
                    rec["subtitle_file"] = "subtitle.srt"
                    log("     · 已下载官方字幕")
                except Exception as e:
                    log("     ! 字幕下载失败:", e)
            elif (data.get("type") == "video"):
                # 无字幕 → 存关键帧（spectrum 图）
                frames = data.get("images") or []
                if frames:
                    fdir = os.path.join(folder, "frames")
                    os.makedirs(fdir, exist_ok=True)
                    ff = []
                    for k, u in enumerate(frames, 1):
                        fn = f"frame_{k:02d}.jpg"
                        try:
                            download(u, os.path.join(fdir, fn))
                            ff.append(fn)
                        except Exception:
                            pass
                        time.sleep(0.2)
                    rec["frame_files"] = ff
                    log(f"     · 无字幕，已存 {len(ff)} 张关键帧")

            # 评论区：滚动加载 → 只留博主的发言
            n_hits = len(comment_hits)
            scroll_for_comments()
            ac = collect_author_comments(nid)
            rec["author_comments"] = ac
            if ac:
                log(f"     · 博主评论 {len(ac)} 条")
            elif len(comment_hits) > n_hits:
                log("     · 评论区无博主发言")

            # raw.json + 骨架 md
            with open(os.path.join(folder, "raw.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)

            lines = [f"# {ntitle}", ""]
            meta = []
            if rec.get("time"):
                meta.append(time.strftime("%Y-%m-%d", time.localtime(rec["time"] / 1000)))
            if rec.get("type"):
                meta.append("视频" if rec["type"] == "video" else "图文")
            if rec.get("ip"):
                meta.append(rec["ip"])
            if rec.get("liked"):
                meta.append(f"♥ {rec['liked']}")
            lines += [f"> {' · '.join(meta)}", "", f"> 原文链接：{url}", "",
                      "## 正文", "", rec.get("desc", "").strip() or "(无正文)", ""]
            if img_files:
                lines += ["## 原图", ""]
                lines += [f"![{fn}]({fn})" for fn in img_files]
            if rec.get("author_comments"):
                lines += ["", "## 博主的评论", ""]
                for c in rec["author_comments"]:
                    t = c.get("time")
                    if t and t > 1e12:
                        t = t / 1000
                    ts = time.strftime("%Y-%m-%d", time.localtime(t)) if t else ""
                    pre = "【置顶】" if c.get("pinned") else ""
                    lk = f"（♥ {c['likes']}）" if c.get("likes") else ""
                    lines.append(f"- {pre}{c['content']}　{ts}{lk}".rstrip())
            with open(os.path.join(folder, "note.md"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            log(f"     √ 完成 → {os.path.basename(folder)}")
            manifest.append(rec)
            time.sleep(0.8)

        ctx.close()

    # manifest 增量合并（按 note_id 去重，保留历史记录以支持断点续导）
    mpath = os.path.join(OUTDIR, "_manifest.json")
    prev = {}
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                for r in json.load(f):
                    if r.get("note_id"):
                        prev[r["note_id"]] = r
        except Exception:
            pass
    for r in manifest:
        if r.get("note_id"):
            prev[r["note_id"]] = r
    all_recs = sorted(prev.values(), key=lambda r: r.get("_seq") or 0)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(all_recs, f, ensure_ascii=False, indent=2)

    okn = sum(1 for m in all_recs if m.get("ok"))
    log("\n" + "=" * 64)
    log(f"[√] 本次完成 {len(manifest)} 篇 | 累计 {okn}/{len(all_recs)} 篇，产出在 downloads/")
    for m in all_recs:
        flag = "√" if m.get("ok") else "X"
        log(f"  {flag} {m.get('title','')[:36]} | 图{len(m.get('images') or [])}"
            f"{' | 字幕' if m.get('subtitle_file') else ''}"
            f"{' | 帧' + str(len(m.get('frame_files'))) if m.get('frame_files') else ''}")


if __name__ == "__main__":
    main()
