# -*- coding: utf-8 -*-
"""
把 downloads/ 下抓好的笔记，按 Obsidian 格式导出到目标库

用法:
    python xhs_export_md.py --dest "/path/to/your/vault"
    python xhs_export_md.py --dest ./vault --author "某博主" --extra-tags "求职,效率工具"

产出:
    <dest>/<标题>.md                 # 带 frontmatter 的笔记
    <dest>/attachments/<笔记标题>--img_*.jpg  # 原图（wikilink 引用，单层目录）

OCR 价值闸门（2026-10-19）:
    每篇产物目录可选放 ocr_status.json（逐图 class/action/skip_reason/note），
    导出按状态驱动：informational=完整OCR去图留文 / ui=留图+一句说明 /
    decorative=仅留原图 / uncertain=留图+待复核标记；无该文件时退回旧版启发式。
    --force-ocr 覆盖跳过决定；--ocr-dry-run 只出逐图报告不写文件。
"""
import argparse
import difflib
import glob
import json
import os
import re
import shutil
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "downloads")


def log(*a):
    print(*a, flush=True)


EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001F900-\U0001F9FF\U0001F1E6-\U0001F1FF"
    "\U00002600-\U000027BF\U00002B00-\U00002BFF\U00002190-\U000021FF"
    "\U00002300-\U000023FF\U000025A0-\U000025FF\U00002934-\U00002935"
    "\U0000FE0F\U0000200D\U00003030\U0000303D\U00003297]+"
)


def strip_emoji(s):
    """标题里的 emoji 全部去掉（默认行为：导入笔记的标题一律无 emoji）"""
    return re.sub(r"\s+", " ", EMOJI_RE.sub("", s or "")).strip()


def safe(name):
    name = strip_emoji(name)
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip(" .")
    return (name or "untitled")[:60]


def yaml_escape(s):
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


TAG_RE = re.compile(r"#([^#\s]{1,60})\s*\[话题\]#")
# @提及：要求 @ 前不是字母/数字/汉字/点（否则会把邮箱 gwenxygu@163.com 误伤成 gwenxygu）
MENTION_RE = re.compile(r"(?<![\w.@])@[^\s@#，。；！？、]{1,30}")


def extract_tags(s):
    """从原始正文里提取话题标签（去掉 # 和 [话题]# 外壳），保持出现顺序、去重。"""
    tags = []
    for m in TAG_RE.finditer(s or ""):
        t = re.sub(r"\s+", " ", m.group(1))[:24].strip()
        if t and t not in tags:
            tags.append(t)
    return tags[:15]


def clean_body(s):
    """小红书正文清洗：制表符转段落、剔除话题标签和 @提及、去多余空行。"""
    s = (s or "").replace("\u3000", " ").replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\t", "\n")          # 制表符 → 换行
    s = TAG_RE.sub(" ", s)             # #xxx[话题]# → 移除（已提取进 frontmatter）
    s = MENTION_RE.sub(" ", s)         # @提及 → 移除
    lines = []
    for raw_ln in s.split("\n"):
        ln = raw_ln.strip()
        # 去掉标签后只剩符号/emoji 的行 → 整行丢弃
        if ln and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", ln):
            continue
        # 行尾残留的话题标签（如 "...正文内容 #面试[话题]#"）→ 去尾
        prev = None
        while prev != ln:
            prev = ln
            ln = re.sub(r"\s*#[^#\s]{1,60}\s*\[话题\]#\s*$", "", ln).strip()
        if ln:
            lines.append(ln)
    out, blank = [], 0
    for ln in lines:
        if ln:
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank == 1:
                out.append("")
    return "\n".join(out).strip()


def one_line(s, n=90):
    return re.sub(r"\s+", " ", (s or "").strip())[:n]


# 正文中独立成行的小标题 → 自动加粗（2026-10-16：小红书正文里的 "01｜xxx"、
# "第一层是主干" 在 App 里是视觉标题，但 desc 字段是纯文本、不带任何标记，
# 靠人工加粗太累，这里按固定句式还原。只认这两种写法，避免误伤普通句子。
HEAD_RE = re.compile(
    r"^(?:\d{1,2}\s*｜\s*[^。！？；\n]{2,26}[：:]?|"
    r"第[一二三四五六七八九十]+[层步点][^。！？；\n]{0,14}[：:]?|"
    r"(?:总结|小结|写在最后|写在前面|食用指南|重点|划重点|核心结论)[：:]?)$")


def boldify_headings(text, style="hash"):
    """把正文里独立成行的小标题变成真标题
    style="hash" → `### 01｜总结了一个项目结构`（默认，可在 Obsidian 大纲里跳转）
    style="bold" → `**01｜总结了一个项目结构：**`（不产生大纲条目）"""
    out = []
    for ln in (text or "").split("\n"):
        s = ln.strip()
        if s and not s.startswith(("**", "#")) and len(s) <= 34 and HEAD_RE.match(s):
            s = ("### " + s.rstrip("：:")) if style == "hash" else f"**{s}**"
        out.append(s)
    return "\n".join(out)


def load_ocr(folder):
    """读取该笔记目录下的 ocr.md，按 '## img_NN.jpg' 切成 {文件名: 转录文本}"""
    p = os.path.join(folder, "ocr.md")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    out = {}
    cur = None
    buf = []
    for ln in txt.split("\n"):
        m = re.match(r"^#{1,3}\s*img[_-]?(\d+)\.jpg\s*$", ln.strip(), re.I)
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur = f"img_{int(m.group(1)):02d}.jpg"
            buf = []
            continue
        if cur is not None:
            buf.append(ln)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def load_ocr_status(folder):
    """读取 ocr_status.json（OCR 价值闸门 · 逐图状态，OCR 阶段产出）
    格式: [{"file": "img_01.jpg", "class": "informational|ui|decorative|uncertain",
            "action": "full_ocr|one_line|skip|pending", "skip_reason": "...", "note": "..."}]
    文件不存在或损坏 → None（导出退回旧版 has_substantive_text 启发式，向后兼容）"""
    p = os.path.join(folder, "ocr_status.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict) and (d.get("file") or "").strip()]
    except Exception:
        pass
    return None


def load_creator_nick():
    """从同目录 selection.json 读博主昵称（有则用作 frontmatter 的 author）"""
    p = os.path.join(BASE, "selection.json")
    try:
        with open(p, encoding="utf-8") as f:
            return (json.load(f).get("nickname") or "").strip()
    except Exception:
        return ""


def norm_para(s):
    """段落归一化：去 markdown 符号和空白，仅用于重复比较"""
    return re.sub(r"[\s*#>`~\-—]+", "", s or "")


def _similar(a, b):
    """两段归一化文本是否高度重复"""
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.75


def dedup_ocr(prev_text, cur_text):
    """相邻两张图的 OCR 去重：后者中与前者重复的段落整段删除。

    博主常把题目/引导语印在每张长图顶部（封面 + 每张正文图各一遍），
    逐图 OCR 会把同样的文字转写多次，这里按段落比对消掉。
    只跟紧邻的前一张图比，且段落归一化后需 >=12 字才参与比较，避免误伤短句。
    """
    if not prev_text or not cur_text:
        return cur_text
    prev_paras = [norm_para(p) for p in prev_text.split("\n\n") if p.strip()]
    prev_paras = [p for p in prev_paras if len(p) >= 12]
    if not prev_paras:
        return cur_text
    out = []
    for p in cur_text.split("\n\n"):
        s = p.strip()
        if not s:
            continue
        n = norm_para(s)
        if len(n) >= 12 and any(_similar(n, q) for q in prev_paras):
            continue
        out.append(s)
    return "\n\n".join(out)


# 「照片/自拍类」图注一律不输出（雅旭 2026-10-16 拍板：自拍、风景、氛围照旁边什么都不写）
PHOTO_CAP_KW = re.compile(r"自拍|照片|人物|拼图|表情包|贴纸|真人|露脸")


def is_photo_caption(s):
    """整行是「（…）」形式、且属于照片/自拍类的图注 → True（导出时整段丢弃）"""
    t = (s or "").strip()
    if not (t.startswith("（") and t.endswith("）")):
        return False
    inner = t[1:-1].strip()
    if inner.startswith("照片") or inner.startswith("自拍"):
        return True
    return bool(PHOTO_CAP_KW.search(inner))


def filter_photo_captions(text):
    """按段落过滤掉照片类图注，其余原样保留（App 界面截图说明仍保留一行）"""
    if not text:
        return ""
    keep = [p for p in text.split("\n\n")
            if p.strip() and not is_photo_caption(p)]
    return "\n\n".join(keep)


def render_author_comments(r):
    """博主的评论（只收博主本人的发言，常藏干货/补充链接）→ 输出到全文最末"""
    cs = r.get("author_comments") or []
    cs = [c for c in cs if is_meaningful_comment(c)]   # 寒暄短评不入库
    out = []
    if not cs:
        return out
    out.append("## 博主的评论")
    out.append("")
    for c in cs:
        t = c.get("time")
        if t and t > 1e12:
            t = t / 1000
        ts = time.strftime("%Y-%m-%d", time.localtime(t)) if t else ""
        pre = "【置顶】" if c.get("pinned") else ""
        lk = f"（♥ {c['likes']}）" if c.get("likes") else ""
        body = clean_body(c.get("content"))
        out.append(f"**{pre}{ts}**" if ts else f"**{pre}**")
        out.append("")
        out.append(body or "（空）")
        if lk:
            out.append("")
            out.append(lk)
        out.append("")
    return out


def _link_basename(link):
    """从 wikilink 目标取文件名：兼容两种 Obsidian 写法
    - `_附件/序号_标题/img_01.jpg`（旧导出格式）
    - `笔记名--img_01.jpg`（2026-10-16 契约格式 / Obsidian「最短路径」重写后的格式）"""
    base = (link or "").strip().split("/")[-1]
    if "--" in base:
        base = base.split("--")[-1]
    return base


def copy_attachment(src, dst):
    """幂等拷贝：目标已存在且大小一致就跳过（重复导出零差异）"""
    if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
        return False
    shutil.copy2(src, dst)
    return True


def recycle_file(path):
    """把过期附件移入系统回收站（可恢复），不做永久删除"""
    try:
        import ctypes
        import ctypes.wintypes as w
        FO_DELETE = 3
        FOF_SILENT, FOF_NOCONFIRMATION = 0x4, 0x10
        FOF_ALLOWUNDO, FOF_NOERRORUI = 0x40, 0x400

        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", w.HWND), ("wFunc", w.UINT),
                        ("pFrom", w.LPCWSTR), ("pTo", w.LPCWSTR),
                        ("fFlags", w.WORD), ("fAnyOperationsAborted", w.BOOL),
                        ("hNameMappings", ctypes.c_void_p),
                        ("lpszProgressTitle", w.LPCWSTR)]

        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = os.path.abspath(path) + "\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
        ctypes.windll.shell32.SHFileOperationW.restype = ctypes.c_int
        ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return not os.path.exists(path)
    except Exception:
        return False


# 博主评论筛选（2026-10-16 雅旭拍板：评论和图片一样要分「有用/装饰」，
# 寒暄短评——"往我心里埋来""想你了宝宝[doge]"——不值得入库，只留干货补充）
CHITTY_RE = re.compile(
    r"哈哈|嘿嘿|嘻|想你了?|爱你|么么|宝宝|宝子|姐妹|亲爱的|加油|冲呀|"
    r"支持|沙发|路过|打卡|来了来了|赞一?个|互关|回关|已关|关注了")


def is_meaningful_comment(c):
    """单条博主评论是否值得入库（宁缺勿滥：被过滤的仍在 raw.json，可调规则重导）
    - 归一化后 ≥20 字 → 有实质内容，保留
    - 点赞 ≥10 → 高赞短评可能是金句/干货指引，保留
    - 其余（寒暄词、<20 字的短互动、纯表情）→ 丢弃
    """
    text = c.get("content") or ""
    try:
        likes = int(c.get("likes") or 0)
    except (TypeError, ValueError):
        likes = 0
    n = norm_para(text)
    if len(n) >= 20:
        return True
    if likes >= 10:
        return True
    return False


def load_prev_img_params(dest, md_name):
    """读回用户手动加过的图片显示参数（如 |orig|left|0|400），重导时继承，避免覆盖手工排版"""
    p = os.path.join(dest, md_name)
    if not os.path.exists(p):
        return {}
    out = {}
    try:
        with open(p, encoding="utf-8") as f:
            for ln in f:
                m = re.match(r"^\s*!\[\[([^\]]+?)((?:\|[^\]]+)?)\]\]\s*$", ln)
                if not m:
                    continue
                fn = _link_basename(m.group(1))
                params = m.group(2) or ""
                # 只继承显示参数（|orig|left|0|400 这类），alias（|说明文字）不继承
                if fn and params and re.fullmatch(r"\|[a-z0-9|]+", params):
                    out[fn] = params
    except Exception:
        pass
    return out


def split_paras(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def para_covered(p, pool):
    """段落 p 的文字是否已被 pool（归一化段落列表）覆盖"""
    n = norm_para(p)
    if len(n) < 8:
        return True                       # 短句/语气行，视为无信息量
    for q in pool:
        if n in q or q in n:
            return True
        if difflib.SequenceMatcher(None, n, q).ratio() >= 0.8:
            return True
    return False


def analyze_image_note(desc, ocr_text):
    """正文里与图内文字重复的段落 → 剔除（避免同一段内容在正文和图片转录里各出现一次）

    2026-10-16 起只做正文去重：是否去图改为**逐图判定**（见 has_substantive_text），
    不再按整篇覆盖率一刀切——同一篇里可以"装饰图保留、干货图转文字"。
    """
    desc_paras = split_paras(desc)
    pool = [norm_para(p) for p in split_paras(ocr_text)]
    pool = [q for q in pool if len(q) >= 8]
    if not pool or not desc_paras:
        return desc
    kept = [p for p in desc_paras if not para_covered(p, pool)]
    return "\n\n".join(kept).strip()


CAPTION_ONLY_RE = re.compile(r"^（[^）]*）$")


def has_substantive_text(t):
    """这张图的转录里是否有「实质文字」（去掉纯括号说明后仍 ≥15 字）
    - True  → 干货图：文字已转录，图是冗余 → 去图留文
    - False → 界面截图（只有一行说明）或照片（无文字）→ 保留图
    """
    rest = [p for p in split_paras(t) if not CAPTION_ONLY_RE.match(p.strip())]
    return len(norm_para(" ".join(rest))) >= 15


OCR_CLASSES = ("informational", "ui", "decorative", "uncertain")
CLASS_ACTION = {"informational": "完整OCR", "ui": "一句说明",
                "decorative": "跳过OCR", "uncertain": "待复核"}


def plan_images(img_files, ocr_map, status_list=None, force_ocr=False):
    """OCR 价值闸门 · 消费端（2026-10-19 Codex 审计规则，雅旭授权）

    逐图决定「文字怎么用、图留不留」，四种类别（ocr_status.json 驱动）：
      informational → 完整 OCR：有实质转录 → 去图留文；转录无实质 → 保留图（不丢字）
      ui            → 保留图 + 一句用途说明（note 字段），不转录 UI 噪声
                      （2026-10-19 雅旭确认：配文属既有行为，此处仅落契约可追溯）
      decorative    → 仅保留原图，不输出文字
      uncertain     → 保留原图，不加任何标记（2026-10-19 雅旭决议：取消待复核 callout）
    status_list=None（无状态文件）→ 退回旧版 has_substantive_text() 启发式，
    行为与 2026-10-16 版完全一致（向后兼容，老数据不炸）。
    force_ocr=True → 覆盖闸门的跳过决定：凡有转录文字一律去图留文；
    无文字的图仍保留原图，绝不伪称已转录。

    返回: [{"file", "text", "keep", "one_line", "pending", "src_class", "skip_reason"}]
    """
    status_map = {}
    if status_list:
        for s in status_list:
            fn = os.path.basename((s.get("file") or "").strip())
            if fn:
                status_map[fn] = s
    plan = []
    prev_raw = ""
    for fn in img_files:
        raw_t = (ocr_map.get(fn) or "").strip()
        t = dedup_ocr(prev_raw, raw_t)      # 相邻图重复段落消重
        t = filter_photo_captions(t)        # 照片/自拍类图注整段丢弃
        if raw_t:
            prev_raw = raw_t
        st = status_map.get(fn)
        one_line, reason = "", ""
        if st:
            cls = st.get("class") if st.get("class") in OCR_CLASSES else "uncertain"
            reason = (st.get("skip_reason") or "").strip()
            if force_ocr:
                keep = not t                # 有转录就转文字，无转录保留图
            elif cls == "informational":
                keep = not has_substantive_text(t)
            elif cls == "ui":
                keep, one_line = True, (st.get("note") or "").strip()
            else:                           # decorative / uncertain
                keep = True
                if cls == "decorative":
                    t = ""                  # 装饰图：仅保留原图，转录文字不输出
        else:
            cls = "legacy"                  # 无该图状态 → 旧版启发式
            keep = not has_substantive_text(t)
        pending = keep and cls == "uncertain"
        plan.append({"file": fn, "text": t, "keep": keep,
                     "one_line": one_line, "pending": pending,
                     "src_class": cls, "skip_reason": reason})
    return plan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--author", default="",
                    help="博主昵称；默认读 selection.json，读不到则不写 author 字段")
    ap.add_argument("--extra-tags", default="",
                    help="额外的固定标签，逗号分隔（可选）")
    ap.add_argument("--only", default="",
                    help="只导出 downloads/ 目录名包含该字符串的笔记（单篇测试用）")
    ap.add_argument("--heading-style", default="hash", choices=["hash", "bold"],
                    help="正文小标题还原方式：hash=### 真标题（默认，可进大纲）；bold=**加粗**")
    ap.add_argument("--frames", action="store_true",
                    help="导出视频关键帧（默认关闭：视频产物 v2 由 AI 结构化整理判断干货）")
    ap.add_argument("--force-ocr", action="store_true",
                    help="覆盖 OCR 价值闸门的跳过决定：凡有转录文字的图一律去图留文")
    ap.add_argument("--video-cover", action="store_true",
                    help="导出视频封面图（默认关闭：封面留档 downloads，产物只含正文+字幕/转写）")
    ap.add_argument("--ocr-dry-run", action="store_true",
                    help="只输出逐图「建议OCR/跳过原因」报告，不写任何文件")
    args = ap.parse_args()
    dest = os.path.abspath(args.dest)
    fallback_author = (args.author or load_creator_nick()).strip()
    extra_tags = [t.strip() for t in (args.extra_tags or "").split(",") if t.strip()]

    if not os.path.isdir(SRC):
        log(f"[X] 找不到 {SRC} —— 请先运行 xhs_fetch_selected.py 抓取笔记")
        return

    att_root = os.path.join(dest, "attachments")   # 2026-10-16 契约：单层 attachments/（对齐 vault 设置）
    os.makedirs(att_root, exist_ok=True)

    dirs = sorted(d for d in os.listdir(SRC)
                  if os.path.isdir(os.path.join(SRC, d)))
    n_ok = 0
    index_lines = []
    authors = set()
    for d in dirs:
        if args.only and args.only not in d:
            continue
        raw_p = os.path.join(SRC, d, "raw.json")
        if not os.path.exists(raw_p):
            continue
        with open(raw_p, encoding="utf-8") as f:
            r = json.load(f)
        if not r.get("ok"):
            log(f"  X 跳过(无数据): {d}")
            continue

        title = strip_emoji((r.get("title") or d).strip())
        date_str = ""
        if r.get("time"):
            date_str = time.strftime("%Y-%m-%d", time.localtime(r["time"] / 1000))
        ntype = "视频" if (r.get("type") == "video") else "图文"
        desc_raw = (r.get("desc") or "").strip()
        topic_tags = extract_tags(desc_raw)
        desc = clean_body(desc_raw)   # 清洗后若为空就留空（标签已进 frontmatter）
        desc = boldify_headings(desc, args.heading_style)   # 正文小标题 → 真标题

        # OCR 价值闸门（2026-10-19）：逐图状态驱动（ocr_status.json），
        # 无状态文件 → 退回旧版逐图启发式，行为不变
        folder = os.path.join(SRC, d)
        images = r.get("images") or []
        # 视频封面默认不导出（2026-10-19 雅旭拍板 B，对齐关键帧 v2 逻辑）：
        # 封面在小红书是 imageList 原生数据，留档 downloads 即可；
        # 产物只含正文+字幕/转写。--video-cover 可手动恢复嵌入
        video_cover_skipped = False
        if ntype == "视频" and images and not args.video_cover:
            video_cover_skipped = True
            images = []
        ocr_map = load_ocr(folder) if images else {}
        status_list = load_ocr_status(folder) if images else None
        img_plan = plan_images(images, ocr_map, status_list, args.force_ocr)

        if args.ocr_dry_run:
            src_tag = "ocr_status.json" if status_list is not None else "旧版启发式（无状态文件）"
            log(f"  · {d}  [{ntype}，{len(img_plan)} 图，判定来源: {src_tag}]")
            for it in img_plan:
                if status_list is not None and it["src_class"] != "legacy":
                    act = CLASS_ACTION[it["src_class"]]
                    if it["src_class"] == "informational":
                        act += "→去图留文" if not it["keep"] else "→转录无实质，保留图"
                    extra = f"，{it['skip_reason']}" if it["skip_reason"] else ""
                elif it["text"]:
                    act = "完整OCR→去图留文" if not it["keep"] else "完整OCR→转录无实质，保留图"
                    extra = ""
                else:
                    act = "未转录→建议补OCR（人工复核）"
                    extra = ""
                log(f"      {it['file']}  {act}{extra}")
            log("")
            continue

        ocr_all = "\n\n".join(it["text"] for it in img_plan if it["text"])
        desc_body = analyze_image_note(desc, ocr_all)   # 正文与图内文字去重
        text_only = bool(img_plan) and not any(it["keep"] for it in img_plan)

        # 附件（2026-10-16 契约）：单层 attachments/，文件名 <笔记标题>--<原名>，
        # 重跑幂等（存在且大小一致跳过 + 清理本篇过期附件走回收站）
        md_stem = safe(title)              # 与笔记文件同名（无扩展名），附件前缀
        used_atts = set()                  # 本篇产出的附件目标名（用于幂等清理）
        img_files = []                     # 原文件名列表（引用时拼 <md_stem>--<fn>）
        for it in img_plan:
            if not it["keep"]:
                continue
            sp = os.path.join(SRC, d, it["file"])
            if os.path.exists(sp):
                dst_name = f"{md_stem}--{it['file']}"
                copy_attachment(sp, os.path.join(att_root, dst_name))
                used_atts.add(dst_name)
                img_files.append(it["file"])

        # 视频字幕/关键帧（摊平进 attachments/，不再建子目录）
        sub_rel = ""
        sp = os.path.join(SRC, d, "subtitle.srt")
        if os.path.exists(sp):
            dst_name = f"{md_stem}--subtitle.srt"
            copy_attachment(sp, os.path.join(att_root, dst_name))
            used_atts.add(dst_name)
            sub_rel = "subtitle.srt"
        frames = []
        fdir = os.path.join(SRC, d, "frames")
        # v2：关键帧默认不导出（AI 结构化整理时代为判断干货，写进 structured.md），
        # --frames 手动打开；关闭时旧帧文件会被幂等清理自动回收
        if os.path.isdir(fdir) and args.frames:
            for fn in sorted(os.listdir(fdir)):
                dst_name = f"{md_stem}--{fn}"
                if copy_attachment(os.path.join(fdir, fn), os.path.join(att_root, dst_name)):
                    pass
                used_atts.add(dst_name)
                frames.append(fn)

        # 视频结构化模式（AnyLink1号 视频产物 v2，雅旭 2026-10-16 20:58 验收）：
        # 产物目录有 structured.md（AI 结构化整理产物）→ 正文整体替换为该文件内容，
        # 原 desc/语音转写散稿/关键帧不再输出（原始 transcript.txt 留在产物目录可溯源）
        structured_path = os.path.join(SRC, d, "structured.md")
        structured_mode = (ntype == "视频") and os.path.exists(structured_path)

        # 幂等清理：attachments/ 里本篇前缀但本轮未产出的过期附件 → 回收站
        for stale in glob.glob(os.path.join(glob.escape(att_root), f"{glob.escape(md_stem)}--*")):
            if os.path.basename(stale) not in used_atts:
                if recycle_file(stale):
                    log(f"     · 清理过期附件: {os.path.basename(stale)}")

        md_name = safe(title) + ".md"
        # 继承上次导出时用户手加的图片显示参数（|left|400 之类），避免重导覆盖手工排版
        prev_params = load_prev_img_params(dest, md_name)

        # 组装 markdown
        L = []
        L.append("---")
        L.append(f'title: "{yaml_escape(title)}"')
        note_author = (r.get("author") or fallback_author).strip()
        # 旧数据兜底：作者昵称的全角括号偶发不闭合（抓取端截断）→ 补闭合
        if note_author.count("（") > note_author.count("）"):
            note_author += "）"
        authors.add(note_author)
        if note_author:
            L.append(f'author: "{yaml_escape(note_author)}"')
        if date_str:
            L.append(f"published: {date_str}")
        L.append(f"created: {time.strftime('%Y-%m-%d')}")
        L.append(f'description: "{yaml_escape(one_line(desc, 90))}"')
        L.append(f'source: "{r.get("url", "")}"')
        L.append("tags:")
        L.append("  - 小红书")
        for t in extra_tags:
            L.append(f"  - {t}")
        for t in topic_tags:
            L.append(f"  - {t}")
        L.append(f"类型: {ntype}")
        trans_src = ""
        if ntype == "视频":
            dur = r.get("video_duration") or 0
            if dur:
                L.append(f"时长: 约 {max(1, round(dur / 60))} 分钟")
            if sub_rel:
                trans_src = "官方字幕"
            elif structured_mode:
                trans_src = "本地 Whisper 语音转写（结构化整理）"
            elif os.path.exists(os.path.join(SRC, d, "transcript.txt")):
                trans_src = "本地 Whisper 语音转写"
            if trans_src:
                L.append(f"转写: {trans_src}")
        if r.get("liked"):
            L.append(f'点赞: "{r["liked"]}"')
        L.append("---")
        L.append("")

        # 标题/日期/类型/点赞/原文链接不再重复输出：frontmatter 属性面板里都有

        if structured_mode:
            # 结构化版替换正文（拍板 #3）：来源引用块 + structured.md 全文
            with open(structured_path, encoding="utf-8") as f:
                struct_body = f.read().strip()
            L.append(f"> 来源：小红书视频，作者 **{note_author or '未知作者'}**")
            if date_str:
                L.append(f"> 发布：{date_str} ｜ 转写：本地 Whisper（结构化整理）")
            L.append("> 原文链接：见 frontmatter source")
            L.append("")
            L.append(struct_body)
            L.append("")
        elif desc_body:
            L.append("## 正文")
            L.append("")
            L.append(desc_body)
            L.append("")

        if img_plan:
            any_text = any(it["text"] for it in img_plan)
            if text_only:
                head = "## 图片文字转录"
            else:
                head = "## 图片" + ("与文字转录" if any_text else "")
            L.append(head)
            L.append("")
            if text_only:
                L.append("> 原笔记内容以图片呈现，以下为图片文字转录；图片未入库。")
                L.append("")
            for it in img_plan:
                if it["keep"]:
                    L.append(f"![[{md_stem}--{it['file']}{prev_params.get(it['file'], '')}]]")
                if it["one_line"]:
                    L.append("")
                    L.append(f"（{it['one_line']}）")
                if it["text"]:
                    L.append("")
                    L.append(it["text"])
                # uncertain：仅保留原图，不输出标记（雅旭 2026-10-19 决议）
                if it["keep"] or it["text"] or it["one_line"]:
                    L.append("")

        if sub_rel:
            L.append("## 视频字幕")
            L.append("")
            L.append(f"![[{md_stem}--{sub_rel}]]")
            L.append("")

        tp = os.path.join(SRC, d, "transcript.txt")
        if os.path.exists(tp) and not structured_mode:
            L.append("## 语音转写")
            L.append("")
            L.append("> 本视频无官方字幕，以下为本地 Whisper 语音转写，可能有少量识别误差。")
            L.append("")
            with open(tp, encoding="utf-8") as f:
                L.append(f.read().strip())
            L.append("")

        if frames:
            L.append("## 视频关键帧")
            L.append("")
            for fn in frames:
                L.append(f"![[{md_stem}--{fn}]]")
            L.append("")

        if r.get("type") == "video" and not sub_rel and not structured_mode:
            L.append("> [!warning] 该条为视频笔记，平台未提供官方字幕，正文识别可能不完整。")
            L.append("")

        # 博主的评论统一放到全文最末（正文 / 图片 / 字幕 / 关键帧 都之后）
        L.extend(render_author_comments(r))

        md_path = os.path.join(dest, md_name)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        n_ok += 1
        if text_only:
            img_col = f"{len(img_plan)}（转文字）"
        elif len(img_files) < len(img_plan):
            img_col = f"{len(img_files)}/{len(img_plan)}"    # 部分图转文字、部分保留
        else:
            img_col = str(len(img_files))
        index_lines.append(f"| {date_str} | [[{safe(title)}]] | {ntype} | {img_col} |")
        log(f"  √ {md_name}  (图 {len(img_files)}/{len(img_plan)})"
            + ("  [全文转文字，未拷图]" if text_only
               else (f"  [{len(img_plan) - len(img_files)} 张干货图转文字]"
                     if len(img_files) < len(img_plan) else ""))
            + ("  [视频封面未导出]" if video_cover_skipped else ""))

    # 索引页
    uniq = sorted(a for a in authors if a)
    coll = f"小红书 · {uniq[0]}合集" if len(uniq) == 1 else "小红书笔记合集"
    idx = ["---", f'title: "{coll}"',
           f"created: {time.strftime('%Y-%m-%d')}", "tags:", "  - 小红书", "---", "",
           f"# {coll}", "",
           f"导出时间：{time.strftime('%Y-%m-%d %H:%M')}　共 {n_ok} 篇（图片列 = 保留为图/图片总数：干货图按设计转成文字、不再嵌图）", "",
           "| 发布日期 | 笔记 | 类型 | 图片 |", "|---|---|---|---|"] + index_lines
    with open(os.path.join(dest, "00 索引.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx) + "\n")

    log(f"\n[√] 导出完成：{n_ok} 篇 → {dest}")


if __name__ == "__main__":
    main()
