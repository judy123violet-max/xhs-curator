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
    """判定「内容主要在图片上」的笔记（雅旭 2026-10-16 提的两类情况通用）

    返回 (is_image_note, desc_body)：
    - is_image_note：正文按字数加权覆盖率 ≥0.55，且 OCR 全文明显长于正文
      （≥1.2 倍且 ≥200 字）→ 博主把完整内容放在图片里，正文只是引流/精简版
    - desc_body：剔掉与图内文字重复的段落后的正文（避免图文同文重复展示）
    """
    desc_paras = split_paras(desc)
    pool = [norm_para(p) for p in split_paras(ocr_text)]
    pool = [q for q in pool if len(q) >= 8]
    if not pool or not desc_paras:
        return False, desc
    total = sum(len(norm_para(p)) for p in desc_paras) or 1
    covered = sum(len(norm_para(p)) for p in desc_paras
                  if para_covered(p, pool))
    cov = covered / total
    ocr_len = sum(len(q) for q in pool)
    is_img = cov >= 0.55 and ocr_len >= max(total * 1.2, 200)
    if not is_img:
        return False, desc
    kept = [p for p in desc_paras if not para_covered(p, pool)]
    return True, "\n\n".join(kept).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--author", default="",
                    help="博主昵称；默认读 selection.json，读不到则不写 author 字段")
    ap.add_argument("--extra-tags", default="",
                    help="额外的固定标签，逗号分隔（可选）")
    ap.add_argument("--only", default="",
                    help="只导出 downloads/ 目录名包含该字符串的笔记（单篇测试用）")
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

        # 先读 OCR 判定笔记形态：内容主要在图片上 → 只留转录文字、不拷图
        ocr_map = load_ocr(os.path.join(SRC, d)) if (r.get("images") or []) else {}
        ocr_all = "\n\n".join(ocr_map.get(fn, "") for fn in (r.get("images") or [])
                              if ocr_map.get(fn))
        is_image_note, desc_body = analyze_image_note(desc, ocr_all)
        keep_images = not is_image_note

        # 附件目录（图片型笔记不建不拷，避免留空目录）
        att_name = safe(d)
        att_dir = os.path.join(att_root, att_name)
        img_files = []
        if keep_images:
            os.makedirs(att_dir, exist_ok=True)
            for fn in (r.get("images") or []):
                sp = os.path.join(SRC, d, fn)
                if os.path.exists(sp):
                    shutil.copy2(sp, os.path.join(att_dir, fn))
                    img_files.append(fn)
        else:
            img_files = list(r.get("images") or [])   # 仅用于遍历 OCR，不入库

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

        if img_files:
            ocr = ocr_map
            if is_image_note:
                head = "## 图片文字转录"
            else:
                head = "## 图片" + ("与文字转录" if ocr else "")
            L.append(head)
            L.append("")
            if is_image_note:
                L.append("> 原笔记内容以图片呈现，以下为图片文字转录；图片未入库。")
                L.append("")
            prev_ocr = ""
            for fn in img_files:
                raw_t = ocr.get(fn, "").strip()
                t = dedup_ocr(prev_ocr, raw_t)      # 相邻图重复段落消重
                t = filter_photo_captions(t)        # 照片/自拍类图注整段丢弃
                if raw_t:
                    prev_ocr = raw_t
                if keep_images:
                    L.append(f"![[_附件/{att_name}/{fn}{prev_params.get(fn, '')}]]")
                if t:
                    L.append("")
                    L.append(t)
                if keep_images or t:
                    L.append("")

        if sub_rel:
            L.append("## 视频字幕")
            L.append("")
            L.append(f"![[_附件/{att_name}/{sub_rel}]]")
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
        img_col = f"{len(img_files)}（转文字）" if is_image_note else str(len(img_files))
        index_lines.append(f"| {date_str} | [[{safe(title)}]] | {ntype} | {img_col} |")
        log(f"  √ {md_name}  (图 {len(img_files)})"
            + ("  [图片型：只留转录文字，未拷图]" if is_image_note else ""))

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
