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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--author", default="",
                    help="博主昵称；默认读 selection.json，读不到则不写 author 字段")
    ap.add_argument("--extra-tags", default="",
                    help="额外的固定标签，逗号分隔（可选）")
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

        # 附件目录
        att_name = safe(d)
        att_dir = os.path.join(att_root, att_name)
        os.makedirs(att_dir, exist_ok=True)
        img_files = []
        for fn in (r.get("images") or []):
            sp = os.path.join(SRC, d, fn)
            if os.path.exists(sp):
                shutil.copy2(sp, os.path.join(att_dir, fn))
                img_files.append(fn)

        # 视频字幕/关键帧
        sub_rel = ""
        sp = os.path.join(SRC, d, "subtitle.srt")
        if os.path.exists(sp):
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

        if desc:
            L.append("## 正文")
            L.append("")
            L.append(desc)
            L.append("")

        # 博主的评论（只收博主本人的发言，常藏干货/补充链接）
        if r.get("author_comments"):
            L.append("## 博主的评论")
            L.append("")
            for c in r["author_comments"]:
                t = c.get("time")
                if t and t > 1e12:
                    t = t / 1000
                ts = time.strftime("%Y-%m-%d", time.localtime(t)) if t else ""
                pre = "【置顶】" if c.get("pinned") else ""
                lk = f"（♥ {c['likes']}）" if c.get("likes") else ""
                body = clean_body(c.get("content"))
                L.append(f"**{pre}{ts}**" if ts else f"**{pre}**")
                L.append("")
                L.append(body or "（空）")
                if lk:
                    L.append("")
                    L.append(lk)
                L.append("")

        if img_files:
            ocr = load_ocr(os.path.join(SRC, d))
            head = "## 图片" + ("与文字转录" if ocr else "")
            L.append(head)
            L.append("")
            for fn in img_files:
                t = ocr.get(fn, "").strip()
                if t == "（照片）":
                    # 纯自拍/风景照片：只保留图片本身，不加标题和说明
                    L.append(f"![[_附件/{att_name}/{fn}]]")
                    L.append("")
                    continue
                L.append(f"### {fn}")
                L.append(f"![[_附件/{att_name}/{fn}]]")
                if t:
                    L.append("")
                    L.append(t)
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

        md_name = safe(title) + ".md"
        md_path = os.path.join(dest, md_name)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(L))
        n_ok += 1
        index_lines.append(f"| {date_str} | [[{safe(title)}]] | {ntype} | {len(img_files)} |")
        log(f"  √ {md_name}  (图 {len(img_files)})")

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
