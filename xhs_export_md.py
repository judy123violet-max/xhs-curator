# -*- coding: utf-8 -*-
"""
把 downloads/ 下抓好的笔记，按 Obsidian 格式导出到目标库

用法:
    python xhs_export_md.py --dest "/path/to/your/vault"
    python xhs_export_md.py --dest ./vault --author "某博主" --extra-tags "求职,效率工具"

产出:
    <dest>/<标题>.md                 # 带 frontmatter 的笔记
    <dest>/_附件/<序号_标题>/img_*.jpg  # 原图（wikilink 引用）
"""
import argparse
import difflib
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
    - `_附件/序号_标题/img_01.jpg`（本项目导出格式）
    - `笔记名--img_01.jpg`（Obsidian「最短路径」设置重写后的格式）"""
    base = (link or "").strip().split("/")[-1]
    if "--" in base:
        base = base.split("--")[-1]
    return base


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
    args = ap.parse_args()
    dest = os.path.abspath(args.dest)
    fallback_author = (args.author or load_creator_nick()).strip()
    extra_tags = [t.strip() for t in (args.extra_tags or "").split(",") if t.strip()]

    if not os.path.isdir(SRC):
        log(f"[X] 找不到 {SRC} —— 请先运行 xhs_fetch_selected.py 抓取笔记")
        return

    att_root = os.path.join(dest, "_附件")
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

        # 逐图判定（2026-10-16 雅旭拍板，学 xhs-claude-skills 的逐图粒度）：
        #   图内是干货长文 → 去图留文（文字已转录，图是冗余）
        #   图内只有一行说明 / 没文字（界面截图、照片）→ 保留图
        ocr_map = load_ocr(os.path.join(SRC, d)) if (r.get("images") or []) else {}
        img_plan = []            # [(文件名, 转录文字, 是否保留图)]
        prev_ocr = ""
        for fn in (r.get("images") or []):
            raw_t = ocr_map.get(fn, "").strip()
            t = dedup_ocr(prev_ocr, raw_t)      # 相邻图重复段落消重
            t = filter_photo_captions(t)        # 照片/自拍类图注整段丢弃
            if raw_t:
                prev_ocr = raw_t
            img_plan.append((fn, t, not has_substantive_text(t)))
        ocr_all = "\n\n".join(t for _, t, _ in img_plan if t)
        desc_body = analyze_image_note(desc, ocr_all)   # 正文与图内文字去重
        text_only = bool(img_plan) and not any(k for _, _, k in img_plan)

        # 附件目录：只拷需要保留的图；一张都不留时不建目录
        att_name = safe(d)
        att_dir = os.path.join(att_root, att_name)
        img_files = []
        for fn, _t, keep in img_plan:
            if not keep:
                continue
            sp = os.path.join(SRC, d, fn)
            if os.path.exists(sp):
                os.makedirs(att_dir, exist_ok=True)
                shutil.copy2(sp, os.path.join(att_dir, fn))
                img_files.append(fn)

        # 视频字幕/关键帧
        sub_rel = ""
        sp = os.path.join(SRC, d, "subtitle.srt")
        if os.path.exists(sp):
            os.makedirs(att_dir, exist_ok=True)
            shutil.copy2(sp, os.path.join(att_dir, "subtitle.srt"))
            sub_rel = "subtitle.srt"
        frames = []
        fdir = os.path.join(SRC, d, "frames")
        if os.path.isdir(fdir):
            outdir = os.path.join(att_dir, "frames")
            os.makedirs(outdir, exist_ok=True)
            for fn in sorted(os.listdir(fdir)):
                shutil.copy2(os.path.join(fdir, fn), os.path.join(outdir, fn))
                frames.append(fn)

        md_name = safe(title) + ".md"
        # 继承上次导出时用户手加的图片显示参数（|left|400 之类），避免重导覆盖手工排版
        prev_params = load_prev_img_params(dest, md_name)

        # 组装 markdown
        L = []
        L.append("---")
        L.append(f'title: "{yaml_escape(title)}"')
        note_author = (r.get("author") or fallback_author).strip()
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
        if r.get("liked"):
            L.append(f'点赞: "{r["liked"]}"')
        L.append("---")
        L.append("")

        # 标题/日期/类型/点赞/原文链接不再重复输出：frontmatter 属性面板里都有

        if desc_body:
            L.append("## 正文")
            L.append("")
            L.append(desc_body)
            L.append("")

        if img_plan:
            any_text = any(t for _, t, _ in img_plan)
            if text_only:
                head = "## 图片文字转录"
            else:
                head = "## 图片" + ("与文字转录" if any_text else "")
            L.append(head)
            L.append("")
            if text_only:
                L.append("> 原笔记内容以图片呈现，以下为图片文字转录；图片未入库。")
                L.append("")
            for fn, t, keep in img_plan:
                if keep:
                    L.append(f"![[_附件/{att_name}/{fn}{prev_params.get(fn, '')}]]")
                if t:
                    L.append("")
                    L.append(t)
                if keep or t:
                    L.append("")

        if sub_rel:
            L.append("## 视频字幕")
            L.append("")
            L.append(f"![[_附件/{att_name}/{sub_rel}]]")
            L.append("")

        tp = os.path.join(SRC, d, "transcript.txt")
        if os.path.exists(tp):
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
                L.append(f"![[_附件/{att_name}/frames/{fn}]]")
            L.append("")

        if r.get("type") == "video" and not sub_rel:
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
                     if len(img_files) < len(img_plan) else "")))

    # 索引页
    uniq = sorted(a for a in authors if a)
    coll = f"小红书 · {uniq[0]}合集" if len(uniq) == 1 else "小红书笔记合集"
    idx = ["---", f'title: "{coll}"',
           f"created: {time.strftime('%Y-%m-%d')}", "tags:", "  - 小红书", "---", "",
           f"# {coll}", "",
           f"导出时间：{time.strftime('%Y-%m-%d %H:%M')}　共 {n_ok} 篇", "",
           "| 发布日期 | 笔记 | 类型 | 图片 |", "|---|---|---|---|"] + index_lines
    with open(os.path.join(dest, "00 索引.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx) + "\n")

    log(f"\n[√] 导出完成：{n_ok} 篇 → {dest}")


if __name__ == "__main__":
    main()
