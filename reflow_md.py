# -*- coding: utf-8 -*-
"""合并导出 md 的正文/图片转录段落，去掉逐句之间的空行。

用法: python reflow_md.py <目录>
"""
import argparse
import os
import re

TEXT_HEADS = ("## 正文", "## 图片文字转录", "## 图片与文字转录")
STOP_PREFIX = ("## ", "![[", ">", "|", "---")


def join_lines(lines):
    out = ""
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if not out:
            out = s
        elif re.search(r"[A-Za-z0-9]$", out) and re.match(r"[A-Za-z0-9]", s):
            out += " " + s
        else:
            out += s
    return out


def split_para(text, max_len=160):
    """按句号切句，攒成约 max_len 字一段；段间只留单换行，不留空行"""
    # 中文标点前后的多余空格、半角逗号统一成全角（不影响英文/数字之间的空格）
    text = re.sub(r"(?<=[，。；：、！？])\s+(?=[\u4e00-\u9fa5])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fa5]),\s*(?=[\u4e00-\u9fa5])", "，", text)
    sents = [s for s in re.split(r"(?<=[。！？])", text) if s.strip()]
    out = []
    cur = ""
    for s in sents:
        if cur and len(cur) + len(s) > max_len:
            out.append(cur)
            cur = s
        else:
            cur += s
    if cur:
        out.append(cur)
    return "\n".join(out)


def reflow(text):
    lines = text.split("\n")
    out = []
    section = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            if out and out[-1].strip():
                out.append("")
            section = ln.strip()
            out.append(ln)
            i += 1
            continue
        if section in TEXT_HEADS:
            if not ln.strip():
                i += 1
                continue
            if ln.startswith("![["):
                if out and out[-1].strip():
                    out.append("")
                out.append(ln)
                out.append("")
                i += 1
                continue
            if ln.startswith(STOP_PREFIX):
                out.append(ln)
                i += 1
                continue
            buf = []
            while i < len(lines) and not lines[i].startswith(STOP_PREFIX):
                buf.append(lines[i])
                i += 1
            out.append(split_para(join_lines(buf)))
            continue
        out.append(ln)
        i += 1
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    args = ap.parse_args()
    for name in sorted(os.listdir(args.folder)):
        if not name.endswith(".md"):
            continue
        p = os.path.join(args.folder, name)
        with open(p, encoding="utf-8") as f:
            src = f.read()
        new = reflow(src)
        if new != src:
            with open(p, "w", encoding="utf-8") as f:
                f.write(new)
            print(f"reflowed: {name}")


if __name__ == "__main__":
    main()
