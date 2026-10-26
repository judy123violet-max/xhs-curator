# -*- coding: utf-8 -*-
"""生成 downloads/ 下已抓取笔记的可点击预览页（00-预览.html）。

用法:
    python xhs_preview.py
    python xhs_preview.py --open   # 生成后用系统默认浏览器打开

产出:
    downloads/00-预览.html —— 一篇卡片一张：封面缩略图、标题、类型、日期，
    以及「打开笔记 .md / 打开原文 / 打开文件夹」三个可点击链接。
    AI 拿到路径后用 present_files 打开，用户即可直接点开查看，
    不必再去文件夹里翻找（这是「看已抓的」与「导入 Obsidian」的区别：
    前者只看 downloads/ 里的原始素材包，无需进一步处理）。

设计（2026-10-25，对应雅旭反馈「导出后应直接给可点击结果」）：
    抓取完成后，用户常会问「把已抓的给我导出/看看」。此时若未指定 Obsidian 库，
    不应只回一句「都在 downloads/」——而是把结果以可点击形式呈现。本脚本即为此而生。
"""
import argparse
import html
import json
import os
import time
import webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "downloads")


def file_uri(p):
    return "file:///" + p.replace("\\", "/")


def first_image(folder):
    """目录里第一张图片（按文件名排序），找不到返回空串。"""
    try:
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                return os.path.join(folder, fn)
    except Exception:
        pass
    return ""


def note_summary(note_md):
    """取 note.md 正文首句（非标题/引用/分隔/表格行）作摘要。"""
    try:
        with open(note_md, encoding="utf-8") as f:
            for ln in f:
                s = ln.strip()
                if s and not s.startswith(("#", ">", "---", "|", "<")):
                    return s[:80]
    except Exception:
        pass
    return ""


def collect():
    if not os.path.isdir(SRC):
        return []
    out = []
    for d in sorted(os.listdir(SRC)):
        folder = os.path.join(SRC, d)
        if not os.path.isdir(folder):
            continue
        raw_p = os.path.join(folder, "raw.json")
        note_p = os.path.join(folder, "note.md")
        if not os.path.exists(raw_p) and not os.path.exists(note_p):
            continue
        title, ntype, date_str, url, cover, ok = d, "?", "", "", "", True
        if os.path.exists(raw_p):
            try:
                with open(raw_p, encoding="utf-8") as f:
                    r = json.load(f)
            except Exception:
                continue
            if not r.get("ok"):
                continue
            title = (r.get("title") or d).strip()
            ntype = "视频" if (r.get("type") == "video") else "图文"
            url = r.get("url") or ""
            if r.get("time"):
                try:
                    date_str = time.strftime("%Y-%m-%d", time.localtime(r["time"] / 1000))
                except Exception:
                    date_str = ""
            imgs = r.get("images") or []
            cover = os.path.join(folder, imgs[0]) if imgs else ""
            if cover and not os.path.exists(cover):
                cover = first_image(folder)
        cover_uri = file_uri(cover) if (cover and os.path.exists(cover)) else ""
        note_uri = file_uri(note_p) if os.path.exists(note_p) else ""
        folder_uri = file_uri(folder)
        out.append({
            "title": title, "ntype": ntype, "date": date_str, "url": url,
            "cover": cover_uri, "note": note_uri, "folder": folder_uri,
            "summary": note_summary(note_p), "dir": d,
        })
    out.sort(key=lambda c: c["date"], reverse=True)
    return out


def card_block(c):
    if c["cover"]:
        cover = f'<img src="{c["cover"]}" alt="">'
    else:
        cover = '<div class="ph">无封面</div>'
    links = []
    if c["note"]:
        links.append(f'<a class="btn" href="{c["note"]}" target="_blank">打开笔记 .md</a>')
    if c["url"]:
        links.append(f'<a class="btn ghost" href="{c["url"]}" target="_blank">打开原文 ↗</a>')
    links.append(f'<a class="btn ghost" href="{c["folder"]}" target="_blank">打开文件夹</a>')
    meta = html.escape(c["ntype"])
    if c["date"]:
        meta += " · " + html.escape(c["date"])
    return f'''
    <article class="card">
      <div class="cover">{cover}</div>
      <div class="body">
        <div class="meta">{meta}</div>
        <h3>{html.escape(c["title"])}</h3>
        <p class="sum">{html.escape(c["summary"])}</p>
        <div class="links">{''.join(links)}</div>
      </div>
    </article>'''


PAGE_TEMPLATE = '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>已抓取笔记预览（__N__ 篇）</title>
<style>
  body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       background:#f5f6f8;margin:0;padding:24px;color:#1a1a1a}
  h1{font-size:20px;margin:0 0 4px}
  .sub{color:#888;font-size:13px;margin-bottom:18px}
  .sub a{color:#ff2e4d}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
  .card{background:#fff;border:1px solid #e6e8eb;border-radius:12px;overflow:hidden;
        display:flex;flex-direction:column;box-shadow:0 1px 2px rgba(0,0,0,.04)}
  .cover{height:160px;background:#eef0f2;overflow:hidden}
  .cover img{width:100%;height:100%;object-fit:cover}
  .ph{height:100%;display:flex;align-items:center;justify-content:center;color:#aaa;font-size:13px}
  .body{padding:12px 14px 14px;display:flex;flex-direction:column;gap:6px;flex:1}
  .meta{color:#888;font-size:12px}
  h3{font-size:15px;margin:0;line-height:1.4}
  .sum{color:#555;font-size:13px;margin:0;line-height:1.5;
       display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
  .links{margin-top:auto;display:flex;flex-wrap:wrap;gap:8px;padding-top:8px}
  .btn{font-size:12.5px;padding:5px 10px;border-radius:8px;background:#ff2e4d;color:#fff;
       text-decoration:none;font-weight:600;white-space:nowrap}
  .btn.ghost{background:#fff;color:#ff2e4d;border:1px solid #ffd0d8}
</style></head>
<body>
  <h1>已抓取笔记预览</h1>
  <div class="sub">共 __N__ 篇 · 素材在 <a href="__SRC__" target="_blank">downloads/</a>
    （「导入 Obsidian」才会生成带 frontmatter 的正式 .md，本页只是已抓素材的速览）</div>
  <div class="grid">__CARDS__</div>
</body></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true", help="生成后用系统默认浏览器打开")
    args = ap.parse_args()
    cards = collect()
    if not cards:
        print(f"[!] {SRC} 下没有已抓取的笔记（先抓取，或本批都未成功）")
        return
    page = (PAGE_TEMPLATE
            .replace("__CARDS__", "\n".join(card_block(c) for c in cards))
            .replace("__N__", str(len(cards)))
            .replace("__SRC__", file_uri(SRC)))
    out = os.path.join(SRC, "00-预览.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"[√] 预览已生成：{out}（{len(cards)} 篇）")
    if args.open:
        try:
            webbrowser.open(out)
        except Exception:
            pass


if __name__ == "__main__":
    main()
