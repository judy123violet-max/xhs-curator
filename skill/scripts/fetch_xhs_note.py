#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书笔记抓取器（图文 + 视频统一版 · Any Link 2 Note 引擎 A）
用法: python3 fetch_xhs_note.py <分享链接> [输出目录]

输入: xhslink.cn 短链 或 xiaohongshu.com 完整链接
输出: <目录>/metadata.json   (标题/作者/正文/时间/类型/图片/字幕等)
      <目录>/imgs/note_XX.jpg (全部高清原图)
      <目录>/subtitle.srt     (视频官方字幕，若有)

原理: 小红书笔记页是 SSR 渲染，未登录 HTML 内嵌 __INITIAL_STATE__ 数据。
      该 JSON 含 undefined 等非标准字面量，不能整体 json.loads，
      必须用正则从 noteDetailMap / note.data.noteData 区域提取字段。

HTTP 层（2026-10-17 指纹升级 · 重要）:
  - 普通 curl/urllib/requests 的 TLS 指纹已被平台识别（2026-10-17
    实验记录：连续两天降级，失败模式恶化到整页无笔记数据）。
  - 现走 curl_cffi 指纹模拟：iPhone UA 配 safari_ios 指纹、桌面 UA 配
    chrome146 指纹（对齐 XHS-Downloader 方案）。curl 子进程仅作
    curl_cffi 不可用时的回退。
  - 必须节流：短时间密集请求（10+ 次）同样触发降级，冷却约 2-3 分钟。
    页面请求间 polite_sleep() 随机 2-4s，图片间 0.4s。
"""
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# Windows 控制台可能是 GBK：日志里的 ⚠ / ℹ 不能把抓取流程打断
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass

try:
    from curl_cffi import requests as _cffi_requests
except ImportError:
    _cffi_requests = None  # 回退 curl 子进程

UA_DESKTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/16.0 Mobile/15E148 Safari/604.1")
REFERER = "https://www.xiaohongshu.com/"
ACCEPT_HTML = ("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")


def die(msg):
    print("ERROR:", msg)
    sys.exit(1)


def _impersonate_for_ua(ua):
    """指纹与 UA 配套：iPhone UA 用 iOS Safari 指纹，桌面 UA 用 chrome146。
    指纹与 UA 不配套（如桌面 Chrome TLS + iPhone UA）容易被风控盯上。"""
    return "chrome146" if ua == UA_DESKTOP else "safari_ios"


def curl_get(url, headers=None, timeout=30, binary=False):
    """HTTP GET —— curl_cffi 指纹模拟优先（2026-10-17 升级，普通 curl
    指纹已被平台识别），curl_cffi 不可用时回退 curl 子进程。

    headers: dict（UA 已默认带 UA_IPHONE，可覆盖）；
    binary=True 返回 bytes（图片/SRT），否则 utf-8 文本。
    """
    merged = {"User-Agent": UA_IPHONE, **(headers or {})}
    if _cffi_requests is not None:
        r = _cffi_requests.get(
            url, headers=merged, timeout=timeout,
            impersonate=_impersonate_for_ua(merged["User-Agent"]),
            allow_redirects=False)
        return r.content if binary else r.content.decode("utf-8", "ignore")
    cmd = ["curl", "-s", "-m", str(timeout)]
    for k, v in merged.items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    if r.returncode != 0:
        raise RuntimeError(f"curl exit {r.returncode}: {r.stderr[:200]!r}")
    return r.stdout if binary else r.stdout.decode("utf-8", "ignore")


# ---- 本地语音转写（2026-10-16：无官方字幕的视频，faster-whisper 兜底）----
# 纯 pip 安装（PyAV 随包解码，不需要系统 ffmpeg）、无 API key，匿名可跑。
# 模型放 <脚本目录>/models/faster-whisper-<name>/，首次自动从 hf-mirror 逐文件
# 流式下载——不要用 huggingface_hub 下载器（本环境实测会拿到 0 字节文件）。
HF_MIRROR = "https://hf-mirror.com"
_WHISPER_FILES = ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
_WHISPER = {"model": None, "name": ""}


def _model_dir(name):
    if not re.fullmatch(r"[a-z0-9._-]+", name or ""):
        raise ValueError(f"模型名不合法: {name!r}")
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "models", f"faster-whisper-{name}")
    binp = os.path.join(d, "model.bin")
    if os.path.exists(binp) and os.path.getsize(binp) > 1_000_000:
        return d
    os.makedirs(d, exist_ok=True)
    base_url = f"{HF_MIRROR}/Systran/faster-whisper-{name}/resolve/main"
    for fn in _WHISPER_FILES:
        p = os.path.join(d, fn)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        print(f"      · 下载模型文件 {fn} …")
        tmp = p + ".part"
        req = urllib.request.Request(f"{base_url}/{fn}",
                                     headers={"User-Agent": UA_DESKTOP})
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
        print(f"      · 加载本地 Whisper 模型 {model_name}")
        _WHISPER["model"] = WhisperModel(d, device="cpu", compute_type="int8")
        _WHISPER["name"] = model_name
    segs, _info = _WHISPER["model"].transcribe(path, language="zh", vad_filter=True)
    return "\n".join(s.text.strip() for s in segs if s.text.strip())


def curl_final_url(url):
    """跟随重定向拿最终 URL（短链解析用）；curl_cffi 优先，回退 curl 子进程"""
    if _cffi_requests is not None:
        r = _cffi_requests.get(
            url, headers={"User-Agent": UA_IPHONE}, timeout=20,
            impersonate="safari_ios", allow_redirects=True)
        return r.url
    r = subprocess.run(
        ["curl", "-s", "-m", "20", "-A", UA_IPHONE, "-L", "-o", os.devnull,
         "-w", "%{url_effective}", url],
        capture_output=True, timeout=30)
    return r.stdout.decode("utf-8", "ignore").strip()


def polite_sleep(a=2.0, b=4.0):
    """请求间随机节流 —— 防密集触发 SSR 降级（缺字幕字段假页面）"""
    time.sleep(random.uniform(a, b))


def unwrap_redirect(url):
    """URL 是 /login?redirectPath=... 时解出里层真实目标，否则原样返回"""
    m = re.search(r'[?&]redirectPath=([^&\s]+)', url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url


def resolve_url(link):
    """短链跳转 → 最终 URL；已是完整链接则原样返回"""
    link = link.strip()
    if "xhslink." not in link:
        return link
    return unwrap_redirect(curl_final_url(link))


def parse_note_url(url):
    """从 URL 提取 note_id 与 xsec_token(保持原编码)"""
    url = unwrap_redirect(url)
    m = re.search(r'/(?:discovery/item|explore|item)/([0-9a-f]{24})', url)
    if not m:
        die(f"无法从 URL 解析 note_id: {url}")
    note_id = m.group(1)
    qs = urllib.parse.urlparse(url).query
    token = None
    for kv in qs.split("&"):
        if kv.startswith("xsec_token="):
            token = kv.split("=", 1)[1]  # 保留 %3D 原样编码
    return note_id, token


def fetch_html(note_id, token):
    """抓笔记页 HTML（未登录 SSR 可拿到 noteDetailMap / note.data.noteData）

    坑（2026-10-16 实测）：
    - 桌面 UA 请求 discovery/item 会被 302 去登录页（258 字节壳）；
    - 移动端 UA + 完整分享参数（app_platform/ignoreEngage/type）才返回真页面；
    - 页面结构已改版：老 key noteDetailMap 没了，数据在
      __INITIAL_STATE__.note.data.noteData。
    """
    if token:
        url = (f"https://www.xiaohongshu.com/discovery/item/{note_id}"
               f"?xsec_token={token}&xsec_source=app_share"
               f"&app_platform=android&ignoreEngage=true&app_version=9.47.0"
               f"&type=video")
    else:
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
    last = ""
    for ua in (UA_IPHONE, UA_DESKTOP):
        html = curl_get(url, headers={
            "Referer": REFERER,
            "Accept": ACCEPT_HTML,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if "noteDetailMap" in html or '"noteData"' in html:
            return html
        last = "页面无笔记数据（可能: 链接过期/被风控降级/需要登录）"
        polite_sleep()
    die(f"抓取失败：{last}。请让用户重新从 App 分享一条新链接")


def rx(pattern, region, default=""):
    m = re.search(pattern, region)
    return m.group(1) if m else default


def unescape_url(u):
    """还原 \\u002F → / 并升级 https"""
    u = u.replace("\\u002F", "/").replace("\\u002f", "/")
    return re.sub(r'^http://', 'https://', u)


def unescape_text(s):
    """JSON 字符串反转义（页面里的正文常带 \\n / \\t / \\uXXXX）。"""
    try:
        return json.loads('"' + s + '"')
    except Exception:
        return (s.replace("\\n", "\n").replace("\\t", "\t")
                 .replace('\\"', '"').replace("\\/", "/"))


def find_note_region(html):
    """定位笔记数据块：优先新结构 note.data.noteData，兜底老结构 noteDetailMap"""
    i = html.find('"data":{"noteData":{')
    if i >= 0:
        return html[i:i + 120000]
    i = html.find("noteDetailMap")
    if i >= 0:
        return html[i:i + 120000]
    return ""


def balanced_region(s, start):
    """从 s[start]（必须是 '['）做括号配对，返回 '[...]' 完整子串"""
    depth = 0
    for j in range(start, len(s)):
        c = s[j]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return s[start:j + 1]
    return s[start:]


def extract_note(html):
    """从笔记数据块提取元数据与图片 URL（非标准 JSON, 用正则）

    - 数据块从 noteDetailMap 改为 __INITIAL_STATE__.note.data.noteData
    - 图片从 imageList[i].urlDefault 改为 imageList[i].url
      （infoList 里还有 H5_DTL/H5_PRV 两个场景的同图 URL，按 fileId 去重）
    - 块开头有一段 illegalInfo.desc，真实 desc 在它后面
    """
    region = find_note_region(html)
    if not region:
        die("页面里找不到笔记数据块（noteData / noteDetailMap 都没有）")

    note_id = rx(r'"noteId":"((?:[^"\\]|\\.)*)"', region)
    title = unescape_text(rx(r'"title":"((?:[^"\\]|\\.)*)"', region))
    desc = ""
    for m in re.finditer(r'"desc":"((?:[^"\\]|\\.)*)"', region):
        tail = region[m.end():m.end() + 12]
        if tail.startswith(',"leftIcon"'):
            continue
        desc = unescape_text(m.group(1))
        break
    # 笔记作者在 user 对象里是 nickName（大写 N）；评论区才是 nickname。
    um = re.search(
        r'"user":\{[^{}]*?"userId":"([^"]*)"[^{}]*?"nickName":"((?:[^"\\]|\\.)*)"',
        region)
    if um:
        user_id, author = um.group(1), unescape_text(um.group(2))
    else:
        author = unescape_text(
            rx(r'"nickName":"((?:[^"\\]|\\.)*)"', region)
            or rx(r'"nickname":"((?:[^"\\]|\\.)*)"', region))
        user_id = rx(r'"userId":"((?:[^"\\]|\\.)*)"', region)
    ip = unescape_text(rx(r'"ipLocation":"((?:[^"\\]|\\.)*)"', region))
    # type 只可能是 video/normal；region 里话题标签的 "type":"topic" 会干扰
    # 简单正则，故按字面值优先判定（2026-10-16 实测踩坑）
    if '"type":"video"' in region:
        ntype = "video"
    elif '"type":"normal"' in region:
        ntype = "normal"
    else:
        ntype = rx(r'"type":"((?:[^"\\]|\\.)*)"', region)

    liked = rx(r'"likedCount":"((?:[^"\\]|\\.)*)"', region)
    comments = rx(r'"commentCount":"((?:[^"\\]|\\.)*)"', region)
    collected = rx(r'"collectedCount":"((?:[^"\\]|\\.)*)"', region)
    shared = rx(r'"shareCount":"((?:[^"\\]|\\.)*)"', region)

    tm = re.search(r'"time":(\d+)', region)
    pub_time = time.strftime("%Y-%m-%d %H:%M",
                             time.gmtime(int(tm.group(1)) / 1000 + 8 * 3600)) if tm else ""
    ts = int(tm.group(1)) if tm else 0

    tags = []
    for t in (re.findall(r'"name":"((?:[^"\\]|\\.)*)","type":"topic"', region)
              + re.findall(r'"type":"topic","id":"[^"]*","name":"((?:[^"\\]|\\.)*)"', region)):
        t = unescape_text(t)
        if t not in tags:
            tags.append(t)

    urls, seen = [], set()
    il = region.find('"imageList":[')
    if il >= 0:
        block = balanced_region(region, il + len('"imageList":'))
        for u in re.findall(r'"url":"((?:[^"\\]|\\.)*)"', block):
            cu = unescape_url(u)
            fid = cu.split("/")[-1].split("!")[0] or cu
            if cu and fid not in seen:
                seen.add(fid)
                urls.append(cu)
    if not urls:
        for u in re.findall(r'"urlDefault":"((?:[^"\\]|\\.)*)"', region):
            cu = unescape_url(u)
            if cu and cu not in seen:
                seen.add(cu)
                urls.append(cu)

    # 官方字幕 / 视频流（视频笔记才有；页面被降级时为空 —— 节流后重试）
    # 页面里的 URL 可能是 http:\u002F\u002Fsns-video...，先还原转义再匹配
    flat = html.replace("\\u002F", "/").replace("\\u002f", "/")
    subs = sorted(set(unescape_url(u) for u in
                      re.findall(r'https://sns-subtitle[^"\\ ]+', flat)))
    vids = sorted(set(unescape_url(u) for u in
                      re.findall(r'https?://sns-video[^"\\ ]+', flat)))

    return {
        "note_id": note_id, "title": title, "desc": desc, "type": ntype,
        "author": author, "author_id": user_id, "ip_location": ip,
        "publish_time": pub_time, "time_ms": ts,
        "stats": {"liked": liked, "comments": comments,
                  "collected": collected, "shared": shared},
        "tags": tags, "image_urls": urls,
        "subtitle_urls": subs, "video_urls": vids,
    }


def _cjk_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "\u4e00" <= c <= "\u9fff") / len(letters)


def pick_cn_subtitle(subs):
    """优先选中文轨（中文轨里取信息最全的一条）；没有中文时回退 _1 源字幕。
    返回 (url, data)；data 为空表示未能预取。"""
    picked = []
    for u in subs[:4]:
        try:
            data = curl_get(u, headers={"Referer": REFERER}, timeout=30,
                            binary=True)
        except Exception:
            continue
        text = data.decode("utf-8", "ignore")
        if text.strip():
            picked.append((u, data, text))
        time.sleep(0.2)
    zh = [p for p in picked if _cjk_ratio(p[2]) >= 0.2]
    if zh:
        u, data, _ = max(zh, key=lambda p: len(p[2]))
        return u, data
    for u, data, _ in picked:
        if re.search(r'_1\.srt\?', u):
            return u, data
    if picked:
        return picked[0][0], picked[0][1]
    fallback = next((u for u in subs if re.search(r'_1\.srt\?', u)), "")
    return fallback or (subs[0] if subs else ""), b""


def download_images(urls, outdir):
    """带防盗链头下载全部图片（curl），返回本地路径列表"""
    paths = []
    for i, u in enumerate(urls):
        fn = os.path.join(outdir, f"note_{i + 1:02d}.jpg")
        try:
            data = curl_get(u, headers={"Referer": REFERER}, timeout=60,
                            binary=True)
            if len(data) > 5000:
                with open(fn, "wb") as f:
                    f.write(data)
                paths.append(fn)
                print(f"  [{i + 1}/{len(urls)}] OK {len(data) // 1024}KB")
            else:
                print(f"  [{i + 1}/{len(urls)}] FAIL size {len(data)}")
                paths.append(None)
        except Exception as e:
            print(f"  [{i + 1}/{len(urls)}] ERR {e}")
            paths.append(None)
        time.sleep(0.4)  # 礼貌限速
    return paths


def safe_stem(s, maxlen=60):
    """标题 → 文件名安全子串"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", s or "").strip()
    return s[:maxlen] or "未命名"


def srt_to_text(raw):
    """SRT → 可读纯文本（2026-10-19 验收缺陷修复）：
    去序号行与时间轴行、去 HTML 标签，压缩连续重复行（滚动字幕每条 cue
    常复述上一条尾部）。只做保守清理，不重排语序。"""
    out, prev = [], None
    for ln in raw.replace("\r\n", "\n").split("\n"):
        s = ln.strip()
        if not s or re.fullmatch(r"\d+", s) or "-->" in s:
            continue
        s = re.sub(r"<[^>]+>", "", s).strip()
        if not s or s == prev:
            continue
        out.append(s)
        prev = s
    return "\n".join(out)


def write_markdown(meta, outdir):
    """单篇正式交付物：持久 .md 文稿（2026-10-19 实施计划 §3.1）

    - 图片用相对引用 imgs/note_XX.jpg：md 与 imgs/ 文件夹一起保留即可访问
    - 视频只带字幕/转写，不带封面（封面留档，雅旭 2026-10-19 拍板 B）
    - 转写失败不阻断：正文照常产出，并显式标注「未取得字幕/转写」
    - 返回 md 路径，文件名记录进 meta["markdown_file"]
    """
    lines = [f"# {meta.get('title') or '未命名笔记'}", ""]
    info = []
    if meta.get("author"):
        info.append(f"作者：{meta['author']}")
    t = meta.get("time_ms") or 0
    if t:
        info.append("发布：" + time.strftime("%Y-%m-%d", time.localtime(t / 1000)))
    if meta.get("ip_location"):
        info.append(meta["ip_location"])
    if meta.get("source_url"):
        info.append(f"[原笔记链接]({meta['source_url']})")
    if info:
        lines += ["> " + " ｜ ".join(info), ""]

    body = (meta.get("desc") or "").strip()
    if body:
        lines += [body, ""]

    is_video = (meta.get("type") == "video")
    if not is_video:
        imgs = meta.get("local_images") or []
        if imgs:
            lines += ["## 图片", ""]
            for i, p in enumerate(imgs, 1):
                lines.append(f"![图{i}](imgs/{os.path.basename(p)})")
                lines.append("")

    if is_video:
        # 字幕/转写（2026-10-19 验收缺陷修复）：字幕正文要写进文稿（不只给
        # 附件链接）；「未取得」警告仅在既无官方字幕、也无本地转写时出现
        srt_text = ""
        if meta.get("subtitle_file") and os.path.exists(
                os.path.join(outdir, meta["subtitle_file"])):
            try:
                with open(os.path.join(outdir, meta["subtitle_file"]),
                          encoding="utf-8", errors="replace") as f:
                    srt_text = srt_to_text(f.read())
            except Exception:
                srt_text = ""
        if srt_text:
            lines += ["## 字幕（官方）", "", srt_text, "",
                      f"> 原始字幕文件：[{meta['subtitle_file']}]"
                      f"({meta['subtitle_file']})", ""]
        tf = meta.get("transcript_file") or ""
        tp = os.path.join(outdir, tf) if tf else ""
        if tf and os.path.exists(tp):
            with open(tp, encoding="utf-8") as f:
                txt = f.read().strip()
            lines += ["## 语音转写（本地 Whisper，可能有少量识别误差）", "", txt, ""]
        elif not srt_text:
            lines += ["> ⚠ 未取得字幕/转写（无官方字幕且本地转写不可用），"
                      "重跑本脚本可补。", ""]

    path = os.path.join(outdir, safe_stem(meta.get("title")) + ".md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    meta["markdown_file"] = os.path.basename(path)
    return path


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    link = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else "xhs_note"
    os.makedirs(outdir, exist_ok=True)
    imgdir = os.path.join(outdir, "imgs")
    os.makedirs(imgdir, exist_ok=True)

    print("[1/4] 解析分享链接...")
    final_url = resolve_url(link)
    note_id, token = parse_note_url(final_url)
    print(f"      note_id={note_id}")

    print("[2/4] 抓取笔记页并提取数据（curl + 节流）...")
    html = fetch_html(note_id, token)
    meta = extract_note(html)
    # 降级检测与重试：视频笔记必有视频流字段，缺流 = 命中间歇性降级
    # （2026-10-16 实测：降级随机出现，同参数重抓即可恢复）
    tries = 0
    backoff = [(6, 10), (20, 35), (50, 80)]  # 指数退避：频率惩罚会随当天累计请求加重
    while meta.get("type") == "video" and not meta.get("video_urls") and tries < 3:
        lo, hi = backoff[tries]
        print(f"      ⚠ 疑似降级页面（视频无流字段），退避重试 {tries + 1}/3 ...")
        polite_sleep(lo, hi)
        html = fetch_html(note_id, token)
        meta = extract_note(html)
    if meta.get("type") == "video" and not meta.get("video_urls"):
        print("      ℹ 多次重试仍缺流字段（当日请求配额可能耗尽）——"
              "先落库，字幕/视频流稍后重跑本脚本可补")
    meta["source_url"] = final_url
    print(f"      标题: {meta['title']}")
    print(f"      作者: {meta['author']}  类型: {meta['type'] or '未知'}"
          f"  图: {len(meta['image_urls'])}"
          f"  字幕: {len(meta['subtitle_urls'])}")

    # 视频：下载官方字幕（优先中文轨，没有中文再回退 _1 源字幕）
    if meta["subtitle_urls"]:
        sub_url, sub_data = pick_cn_subtitle(meta["subtitle_urls"])
        try:
            data = sub_data or curl_get(sub_url, headers={"Referer": REFERER},
                                        timeout=30, binary=True)
            with open(os.path.join(outdir, "subtitle.srt"), "wb") as f:
                f.write(data)
            meta["subtitle_file"] = "subtitle.srt"
            print(f"[3/4] 官方字幕已下载: {len(data)} 字节")
        except Exception as e:
            print(f"[3/4] 字幕下载失败（不影响其余产出）: {e}")
    else:
        # 无官方字幕 → 下载视频做本地语音转写（faster-whisper；全程匿名，无需登录）
        vurls = meta.get("video_urls") or []
        vurl = vurls[0] if vurls else ""
        no_asr = "--no-asr" in sys.argv
        model_name = "small"
        if "--whisper-model" in sys.argv:
            i = sys.argv.index("--whisper-model")
            model_name = sys.argv[i + 1] if i + 1 < len(sys.argv) else "small"
        if vurl and not no_asr:
            print("[3.5/4] 无官方字幕，下载视频做本地语音转写…")
            vp = os.path.join(outdir, "video.mp4")
            try:
                subprocess.run(["curl", "-sL", "-m", "600",
                                "-A", UA_DESKTOP,
                                "-H", f"Referer: {REFERER}",
                                "-o", vp, vurl],
                               check=True, timeout=660)
                if not (os.path.exists(vp) and os.path.getsize(vp) > 100_000):
                    raise RuntimeError("视频下载不完整")
                txt = transcribe_audio(vp, model_name)
                if txt:
                    with open(os.path.join(outdir, "transcript.txt"), "w",
                              encoding="utf-8") as f:
                        f.write(txt)
                    meta["transcript_file"] = "transcript.txt"
                    print(f"      ✓ 语音转写完成，{len(txt)} 字")
                else:
                    print("      ! 转写结果为空")
            except Exception as e:
                print(f"      ! 语音转写失败（不影响其余产出）: {e}")
            finally:
                if os.path.exists(vp):
                    os.remove(vp)   # 转写完即删，不占空间
        elif vurl and no_asr:
            print("[3.5/4] --no-asr：跳过语音转写")
        elif meta.get("type") == "video":
            print("[3.5/4] 无官方字幕且未取到视频流（降级页），跳过转写——"
                  "重跑本脚本可补")
        else:
            print("[3.5/4] 图文笔记，无字幕环节")

    # 图片
    if meta["image_urls"]:
        print("[4/4] 下载原图...")
        paths = download_images(meta["image_urls"], imgdir)
        meta["local_images"] = [p for p in paths if p]
        meta["failed_images"] = sum(1 for p in paths if not p)
    else:
        meta["local_images"] = []
        meta["failed_images"] = 0
        print("[4/4] 无图片（视频笔记正常）")

    meta_path = os.path.join(outdir, "metadata.json")

    # 正式交付物：持久 .md 文稿（2026-10-19 实施计划 §3.1）
    md_path = ""
    try:
        md_path = write_markdown(meta, outdir)
    except Exception as e:
        print(f"! Markdown 生成失败（不影响其余产出）: {e}")

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("\n===== 完成 =====")
    print(f"元数据: {meta_path}")
    if md_path:
        print(f"文稿:   {md_path}")
    if meta.get("subtitle_file"):
        print(f"字幕: {os.path.join(outdir, 'subtitle.srt')}")
    print(f"图片: {len(meta['local_images'])} 张"
          + (f"（失败 {meta['failed_images']}）" if meta["failed_images"] else ""))
    print("\n下一步(AI 操作): 按 SKILL.md 模板整理成 Markdown；"
          "或跑 to_downloads.py 转换后由 xhs-curator 导出 Obsidian。")


if __name__ == "__main__":
    main()
