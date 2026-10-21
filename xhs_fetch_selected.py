# -*- coding: utf-8 -*-
"""
按 selection.json 抓取选中笔记的正文 + 原图（复用已登录的浏览器会话）

用法:
    python xhs_fetch_selected.py                 # 抓 selection.json 里全部
    python xhs_fetch_selected.py --limit 3       # 只抓前 3 条（测试用）
    python xhs_fetch_selected.py --only <note_id>
    python xhs_fetch_selected.py --url <链接>     # 单篇直抓（短链/分享文字均可）

--url 单篇模式（2026-10-16 补回的最初能力）:
    粘贴 xhslink.cn 短链、explore/discovery 完整链接、或整段分享文字都可以；
    不进 selection.json，直接抓这一篇进 downloads/（序号续在已有文件夹后），
    抓完照常出现在「已抓笔记」页、可导出 Obsidian。

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
import sys
import time
import urllib.parse
import urllib.request

# Windows 控制台可能是 GBK：日志里的 ⚠ 等字符不能把抓取流程打断
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

BASE = os.path.dirname(os.path.abspath(__file__))
SEL = os.path.join(BASE, "selection.json")
PROFILE = os.path.join(BASE, "browser_profile")
OUTDIR = os.path.join(BASE, "downloads")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/16.0 Mobile/15E148 Safari/604.1")

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
    out.userId = ui.userId || ui.user_id || '';
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


# ---- 本地语音转写（2026-10-16：无官方字幕的视频，用 faster-whisper 兜底）----
# 竞品同款简单方案：纯 pip 安装（PyAV 随包解码，不需要系统 ffmpeg）、无 API key。
# 模型放 <脚本目录>/models/faster-whisper-<name>/，首次自动从 hf-mirror 逐文件下载
# （不走 huggingface_hub 下载器——本环境实测它对镜像会拿到 0 字节文件）。
HF_MIRROR = "https://hf-mirror.com"
_WHISPER_FILES = ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
_WHISPER = {"model": None, "name": ""}


def _model_dir(name):
    if not re.fullmatch(r"[a-z0-9._-]+", name or ""):
        raise ValueError(f"模型名不合法: {name!r}")
    d = os.path.join(BASE, "models", f"faster-whisper-{name}")
    binp = os.path.join(d, "model.bin")
    if os.path.exists(binp) and os.path.getsize(binp) > 1_000_000:
        return d
    os.makedirs(d, exist_ok=True)
    base_url = f"{HF_MIRROR}/Systran/faster-whisper-{name}/resolve/main"
    for fn in _WHISPER_FILES:
        p = os.path.join(d, fn)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        log(f"     · 下载模型文件 {fn} …")
        tmp = p + ".part"
        req = urllib.request.Request(f"{base_url}/{fn}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, p)
    if os.path.getsize(binp) <= 1_000_000:
        raise RuntimeError("模型下载不完整，请检查网络后重试")
    return d


def transcribe_audio(path, model_name="small"):
    if _WHISPER["model"] is None or _WHISPER["name"] != model_name:
        from faster_whisper import WhisperModel
        d = _model_dir(model_name)
        log(f"     · 加载本地 Whisper 模型 {model_name}")
        _WHISPER["model"] = WhisperModel(d, device="cpu", compute_type="int8")
        _WHISPER["name"] = model_name
    segs, _info = _WHISPER["model"].transcribe(path, language="zh", vad_filter=True)
    # 每个语义段一行，转写文本更易读
    return "\n".join(s.text.strip() for s in segs if s.text.strip())


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


def fetch_bytes(url, referer="https://www.xiaohongshu.com/"):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": referer,
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def _cjk_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "\u4e00" <= c <= "\u9fff") / len(letters)


def pick_cn_subtitle(urls, referer):
    """优先中文轨（中文里取信息最全的一条）；没有中文时回退 _1 源字幕。"""
    picked = []
    for u in urls[:4]:
        try:
            data = fetch_bytes(u, referer)
        except Exception:
            continue
        text = data.decode("utf-8", "ignore")
        if text.strip():
            picked.append((u, data, text))
        time.sleep(0.2)
    zh = [p for p in picked if _cjk_ratio(p[2]) >= 0.2]
    if zh:
        return max(zh, key=lambda p: len(p[2]))[:2]
    for u, data, _ in picked:
        if re.search(r"_1\.srt\?", u):
            return u, data
    return (picked[0][0], picked[0][1]) if picked else (None, None)


def load_done_index():
    """扫描 downloads/，返回 {note_id: 目录名}（仅 raw.json ok=true 的算完成）"""
    done = {}
    if not os.path.isdir(OUTDIR):
        return done
    for dname in os.listdir(OUTDIR):
        rp = os.path.join(OUTDIR, dname, "raw.json")
        if not os.path.exists(rp):
            continue
        try:
            with open(rp, encoding="utf-8") as f:
                rec = json.load(f)
        except Exception:
            continue
        if rec.get("ok") and rec.get("note_id"):
            done[rec["note_id"]] = dname
    return done


def extract_link(text):
    """从分享文本里抠出第一个小红书链接（用户经常整段share文案直接粘贴）"""
    m = re.search(r"https?://(?:[\w.-]*xhslink\.(?:cn|com)"
                  r"|(?:www\.)?xiaohongshu\.com)/\S+", text or "")
    if not m:
        return ""
    return m.group(0).rstrip("）)\"'】】>>,，。；;！")


def resolve_note_link(text):
    """各种形态的输入 → (note_id, xsec_token, canonical_url, type_hint)

    支持：xhslink.cn 短链、explore/discovery 完整链接、整段分享文字。
    坑：短链匿名访问会先跳 /login?redirectPath=<真实目标>，
    真实 URL 整体编码在 redirectPath 里，必须再解一层。
    """
    link = extract_link(text)
    if not link:
        raise ValueError("没找到小红书链接（支持 xhslink.cn 短链 / "
                         "xiaohongshu.com 链接 / 带链接的分享文字）")
    if "xhslink." in link:
        req = urllib.request.Request(link, headers={"User-Agent": UA_IPHONE})
        with urllib.request.urlopen(req, timeout=30) as r:
            link = r.geturl()
    m = re.search(r"[?&]redirectPath=([^&\s]+)", link)
    if m:
        link = urllib.parse.unquote(m.group(1))
    m = re.search(r"/(?:discovery/item|explore|item)/([0-9a-f]{24})", link)
    if not m:
        raise ValueError(f"链接里找不到笔记 ID：{link}")
    nid = m.group(1)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    token = (qs.get("xsec_token") or [""])[0]
    ntype = (qs.get("type") or [""])[0]
    canon = f"https://www.xiaohongshu.com/explore/{nid}"
    if token:
        canon += ("?xsec_token=" + urllib.parse.quote(token, safe="")
                  + "&xsec_source=app_share")
    return nid, token, canon, ntype


def find_note_folder(note_id):
    """扫描 downloads/ 找该 note_id 已存在的 (序号, 目录名)；没有返回 (0, '')"""
    if not os.path.isdir(OUTDIR):
        return 0, ""
    for dname in os.listdir(OUTDIR):
        rp = os.path.join(OUTDIR, dname, "raw.json")
        if not os.path.exists(rp):
            continue
        try:
            with open(rp, encoding="utf-8") as f:
                r = json.load(f)
        except Exception:
            continue
        if r.get("note_id") == note_id:
            m = re.match(r"^(\d+)_", dname)
            return (int(m.group(1)) if m else 0), dname
    return 0, ""


def used_seqs():
    """返回 {序号: note_id}；目录没有 raw.json 时 note_id 为空串。"""
    used = {}
    if os.path.isdir(OUTDIR):
        for dname in os.listdir(OUTDIR):
            m = re.match(r"^(\d+)_", dname)
            if not m:
                continue
            seq = int(m.group(1))
            nid = ""
            rp = os.path.join(OUTDIR, dname, "raw.json")
            if os.path.exists(rp):
                try:
                    with open(rp, encoding="utf-8") as f:
                        nid = json.load(f).get("note_id") or ""
                except Exception:
                    pass
            used.setdefault(seq, nid)
    return used


def allocate_seq(preferred, note_id, used):
    """复用该 note_id 已有序号；否则用空闲的清单位置；再否则取最大序号 + 1。"""
    seq, _ = find_note_folder(note_id)
    if seq and used.get(seq) in ("", note_id):
        return seq
    if preferred and (preferred not in used or used[preferred] in ("", note_id)):
        used[preferred] = note_id
        return preferred
    seq = max(used, default=0) + 1
    used[seq] = note_id
    return seq


def plan_batch(notes_full, done, offset=0, count=0, only="", no_resume=False):
    """筛选待抓笔记并分配稳定、不冲突的目录序号。"""
    candidates = []
    for i, note in enumerate(notes_full, 1):
        if only and note.get("note_id") != only:
            continue
        if i <= offset:
            continue
        if not no_resume and note.get("note_id") in done:
            continue
        candidates.append((i, note))
    if count and count > 0:
        candidates = candidates[:count]
    used = used_seqs()
    return [(allocate_seq(i, note.get("note_id"), used), note)
            for i, note in candidates]


def job_stats_payload(todo_ids, manifest, skipped=0, current=None,
                      stage="fetching", user_stopped=False):
    """本轮统计（2026-10-20 P0 持久任务结果；2026-10-21 P0-A 增加运行期字段）：
    stage/total/processed/current_note_title 供工作台进度条与 AI 汇报消费。
    processed = success + failed（不含 skipped）；只统计本轮 todo 的 note_id。
    """
    recs = [m for m in manifest if m.get("note_id") in set(todo_ids)]
    ok = sum(1 for r in recs if r.get("ok"))
    failed = len(recs) - ok
    failures = [{"note_id": r.get("note_id"),
                 "title": (r.get("list_title") or "")[:40],
                 "error": (r.get("error") or "未取得笔记数据").strip()}
                for r in recs if not r.get("ok")]
    return {"stage": stage, "total": len(todo_ids),
            "processed": ok + failed, "ok": ok, "failed": failed,
            "skipped": skipped, "user_stopped": user_stopped,
            "current_note_title": (current or "")[:40],
            "failures": failures}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="同 --count")
    ap.add_argument("--count", type=int, default=0, help="本次最多抓几篇；0=不限")
    ap.add_argument("--offset", type=int, default=0, help="跳过清单前 N 篇（断点续导）")
    ap.add_argument("--only", default="")
    ap.add_argument("--url", default="",
                    help="单篇直抓：笔记链接/短链/分享文字（不走 selection.json）")
    ap.add_argument("--no-resume", action="store_true", help="忽略断点，强制重抓已完成项")
    ap.add_argument("--whisper-model", default="small",
                    help="无官方字幕视频的本地转写模型（tiny/base/small/medium，默认 small）")
    ap.add_argument("--no-asr", action="store_true",
                    help="跳过本地语音转写（只抓字幕/关键帧；首次用需 pip install faster-whisper）")
    ap.add_argument("--no-comments", action="store_true",
                    help="不捕获博主评论（工作台「要保留博主评论吗」选「不要」时使用；"
                         "默认捕获，导出端再按价值筛选）")
    ap.add_argument("--only-ids", default="",
                    help="只抓这些 note_id（逗号分隔）——工作台「仅重试失败项」使用")
    args = ap.parse_args()

    single = bool((args.url or "").strip())
    if single:
        try:
            nid, _token, canon, ntype = resolve_note_link(args.url)
        except Exception as e:
            log("[X]", e)
            return
        seq, old_folder = find_note_folder(nid)
        if not seq:
            seq = allocate_seq(0, nid, used_seqs())
        note = {"note_id": nid, "title": "", "type": ntype or "normal",
                "date": "", "url": canon}
        sel = {"nickname": "", "user_id": "", "notes": [note], "single": True}
        notes_full = [note]
        log("=" * 64)
        log(f"[*] 单篇直抓: {canon}")
        log(f"    note_id={nid} | 目录序号 {seq:02d}"
            + (f"（已抓过，将覆盖 {old_folder}）" if old_folder else ""))
        log("=" * 64)
    else:
        if not os.path.exists(SEL):
            log("[X] 找不到 selection.json —— 请先在采集工作台勾选笔记（勾选自动保存）")
            return
        with open(SEL, encoding="utf-8") as f:
            sel = json.load(f)
        notes_full = sel.get("notes") or []
        if not notes_full:
            log("[X] selection.json 里没有笔记")
            return

    count = args.count or args.limit  # --limit 为兼容旧写法
    done = load_done_index()

    # 仅重试失败项（2026-10-20）：工作台结果卡传入失败 note_id 列表，
    # 只抓这些篇——selection.json 本身不被改写（勾选主权）
    if args.only_ids and not single:
        want = {x.strip() for x in args.only_ids.split(",") if x.strip()}
        notes_full = [n for n in notes_full if n.get("note_id") in want]
        log(f"[*] 仅重试失败项：过滤后待抓 {len(notes_full)} 篇")
        if not notes_full:
            log("[√] 失败条目都不在当前清单里，无需重试")
            return

    # 切片（offset/count）+ 断点跳过；序号优先复用已有目录，避免单篇/批量撞号
    if single:
        todo = [(seq, notes_full[0])]   # 单篇：固定用续好的序号，且总是重抓
    else:
        todo = plan_batch(notes_full, done, args.offset, count,
                          args.only, args.no_resume)

    os.makedirs(OUTDIR, exist_ok=True)
    if not single:
        done_in_list = sum(1 for n in notes_full
                           if n.get("note_id") in done)
        log("=" * 64)
        log(f"[*] 博主: {sel.get('nickname')} | 清单 {len(notes_full)} 篇 | "
            f"已完成(断点跳过) {done_in_list} 篇 | 本次待抓 {len(todo)} 篇"
            + (f" | offset={args.offset} count={count}" if (args.offset or count) else ""))
        log("=" * 64)
    todo_ids = [n.get("note_id") for _, n in todo]
    skipped = len(notes_full) - len(todo)
    ctrl_path = os.environ.get("XHS_JOB_CONTROL") or ""

    def control_stop_requested():
        """协作式停止（2026-10-21 P0-A）：工作台经 XHS_JOB_CONTROL 写入
        stop_requested；抓取循环在「每篇开始前」读取，收到即不再开始下一篇"""
        if not ctrl_path or not os.path.exists(ctrl_path):
            return False
        try:
            with open(ctrl_path, encoding="utf-8") as f:
                return bool(json.load(f).get("stop_requested"))
        except Exception:
            return False

    def write_job_stats(manifest_now, current=None, stage="fetching",
                        user_stopped=False):
        """任务统计回写（2026-10-20 P0）：工作台经 XHS_JOB_STATS 指定的路径收集；
        2026-10-21 P0-A 起逐篇更新（运行期进度），不再只终态写一次"""
        p = os.environ.get("XHS_JOB_STATS") or ""
        if not p:
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(job_stats_payload(todo_ids, manifest_now, skipped,
                                            current, stage, user_stopped),
                          f, ensure_ascii=False, indent=2)
        except Exception as e:
            log(f"! 任务统计回写失败: {e}")

    if not todo:
        log("[√] 没有需要抓取的笔记（全部完成或切片为空）")
        write_job_stats([], stage="done")
        return
    if not single:
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

        def collect_author_comments(note_id, uid=None):
            """从已捕获的接口响应里筛出博主的评论（含子评论、置顶）

            uid 传单篇模式/详情页取到的作者 id；不传则退回清单博主的 user_id
            （搜索结果可能跨博主，按篇取 id 才不会张冠李戴）。
            """
            want = str(uid or author_uid or "")
            out, seen = [], set()
            for hit_nid, cs in comment_hits:
                if hit_nid != note_id:
                    continue
                for c in cs:
                    group = [c] + (c.get("sub_comments") or [])
                    for cc in group:
                        cid = cc.get("id")
                        cuid = str((cc.get("user_info") or {}).get("user_id") or "")
                        if not cid or cid in seen:
                            continue
                        if not want or cuid != want:
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

        stopped_by_user = False
        for i, note in todo:
            # 协作式停止（2026-10-21 P0-A）：每篇开始前读控制文件，收到即
            # 不再开始下一篇；已完成内容保留，终态由 picker 记为 stopped
            if control_stop_requested():
                log("⏹ 收到停止请求——不再开始下一篇，已完成内容保留")
                stopped_by_user = True
                break
            nid = note.get("note_id")
            title = note.get("title") or ""
            url = note.get("url") or f"https://www.xiaohongshu.com/explore/{nid}"
            label = title[:40] or nid
            if single:
                log(f"\n[单篇 {i:02d}] {label} ({note.get('type')})")
            else:
                log(f"\n[{i}/{len(notes_full)}] {label} ({note.get('type')})")
            write_job_stats(manifest, current=label)

            rec = {"note_id": nid, "list_title": title, "list_type": note.get("type"),
                   "list_date": note.get("date"), "url": url, "ok": False, "_seq": i,
                   "author": (sel.get("nickname") or "")}

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
                        # 视频的 media.stream（视频直链）是 SPA 异步填充的，
                        # 首屏 700ms 时常还没到 → 视频笔记多轮询几轮
                        if d.get("type") == "video" and not d.get("videoUrl"):
                            for _w in range(12):
                                page.wait_for_timeout(500)
                                raw = page.evaluate(JS_EXTRACT)
                                d2 = json.loads(raw)
                                if d2.get("ok") and (d2.get("videoUrl") or d2.get("rawSubtitle")):
                                    data = d2
                                    break
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
            if data.get("nickname"):
                nick = data["nickname"]
                # 页面 store 偶发截断全角括号（实测 03：'谷谷谷雨（秋招版' ）→ 补闭合
                if nick.count("（") > nick.count("）"):
                    nick += "）"
                rec["author"] = nick   # 按篇取真实作者，避免清单昵称张冠李戴
            note_uid = str(data.get("userId") or "")
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

            # 视频：找官方字幕（图文跳过——少一次 page.content 少一分导航竞态；
            # 实测 XHS 偶尔在抓取途中软跳转，page.content 会抛 context destroyed）
            is_video = (data.get("type") == "video") or (note.get("type") == "video")
            html = ""
            if is_video:
                try:
                    html = page.content()
                except Exception as e:
                    log("     ! 读取页面失败（字幕检测跳过）:", e)
            flat = (html or "").replace("\\u002F", "/").replace("\\u002f", "/")
            srt = sorted(set(re.findall(
                r"https://sns-subtitle[^\"\\ ]+\.srt\?[^\"\\ ]+", flat)))
            if srt:
                p = os.path.join(folder, "subtitle.srt")
                try:
                    u, data = pick_cn_subtitle(srt, url)
                    if data:
                        with open(p, "wb") as f:
                            f.write(data)
                    else:
                        u = srt[0]
                        download(u, p, referer=url)
                    rec["subtitle_file"] = "subtitle.srt"
                    log("     · 已下载官方字幕")
                except Exception as e:
                    log("     ! 字幕下载失败:", e)
            elif is_video:
                # 无字幕 → 下载视频做本地语音转写（faster-whisper，可 --no-asr 跳过）
                vurl = (data.get("videoUrl") or "").strip()
                transcript = ""
                if vurl and not args.no_asr:
                    vp = os.path.join(folder, "video.mp4")
                    try:
                        log("     · 无官方字幕，下载视频做本地语音转写…")
                        download(vurl, vp, referer=url)
                        transcript = transcribe_audio(vp, args.whisper_model)
                    except Exception as e:
                        log("     ! 语音转写失败（不影响其余内容）:", e)
                    finally:
                        if os.path.exists(vp):
                            os.remove(vp)   # 转写完即删，不占空间
                if transcript:
                    p = os.path.join(folder, "transcript.txt")
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(transcript)
                    rec["transcript_file"] = "transcript.txt"
                    log(f"     ✓ 语音转写完成，{len(transcript)} 字")
                elif is_video and args.no_asr:
                    log("     · --no-asr 跳过语音转写")
                # 关键帧照旧（画面文字也有信息量）
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
            #（--no-comments：工作台评论开关选「不要」时跳过，2026-10-19 新增）
            if getattr(args, "no_comments", False):
                rec["author_comments"] = []
                log("     · 按配置跳过博主评论捕获")
            else:
                n_hits = len(comment_hits)
                scroll_for_comments()
                ac = collect_author_comments(nid, note_uid)
                rec["author_comments"] = ac
                if ac:
                    log(f"     · 博主评论 {len(ac)} 条")
                elif len(comment_hits) > n_hits:
                    log("     · 评论区无博主发言")

            # raw.json + 骨架 md
            with open(os.path.join(folder, "raw.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            write_job_stats(manifest)

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
    write_job_stats(manifest, stage="stopped" if stopped_by_user else "done",
                    user_stopped=stopped_by_user)
    log("\n" + "=" * 64)
    log(f"[√] 本次完成 {len(manifest)} 篇 | 累计 {okn}/{len(all_recs)} 篇，产出在 downloads/")
    for m in all_recs:
        flag = "√" if m.get("ok") else "X"
        log(f"  {flag} {m.get('title','')[:36]} | 图{len(m.get('images') or [])}"
            f"{' | 字幕' if m.get('subtitle_file') else ''}"
            f"{' | 帧' + str(len(m.get('frame_files'))) if m.get('frame_files') else ''}")


if __name__ == "__main__":
    main()
