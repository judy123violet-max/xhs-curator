#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
引擎 A 产物 → xhs-curator downloads/ 结构转换器（A3 工程债 ②）

用法: python3 to_downloads.py <引擎A输出目录> [--downloads <xhs-curator的downloads路径>]

作用: 把 fetch_xhs_note.py 的产物（metadata.json + imgs/ + subtitle.srt）
      转成 xhs-curator 认的 downloads/<序号>_<标题>/ 结构，使
      xhs_export_md.py 无需改动即可导出 Obsidian —— 导出层统一的
      「转换器」实现（不改对方代码，零冲突）。

raw.json 字段对齐 xhs_fetch_selected.py 的 rec 结构：
    ok/title/desc/type/time/url/author/liked/ip/images/
    subtitle_file/frame_files/author_comments/note_id/_seq
"""
import argparse
import json
import os
import re
import shutil
import sys

DEFAULT_DOWNLOADS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "downloads")


def sanitize(name, maxlen=40):
    """标题 → 目录名安全子串（对齐 B 侧的目录命名习惯）"""
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", name or "").strip()
    return name[:maxlen] or "未命名"


def next_seq(downloads):
    best = 0
    if os.path.isdir(downloads):
        for d in os.listdir(downloads):
            m = re.match(r"^(\d+)_", d)
            if m:
                best = max(best, int(m.group(1)))
    return best + 1


def find_by_note_id(downloads, note_id):
    """已存在则返回 (序号, 目录名)；否则 (0, '')"""
    if not os.path.isdir(downloads):
        return 0, ""
    for d in os.listdir(downloads):
        rp = os.path.join(downloads, d, "raw.json")
        if not os.path.exists(rp):
            continue
        try:
            with open(rp, encoding="utf-8") as f:
                if json.load(f).get("note_id") == note_id:
                    m = re.match(r"^(\d+)_", d)
                    return (int(m.group(1)) if m else 0), d
        except Exception:
            continue
    return 0, ""


def convert(src, downloads):
    meta_path = os.path.join(src, "metadata.json")
    if not os.path.exists(meta_path):
        print(f"[X] 找不到 {meta_path}")
        return False
    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)

    note_id = meta.get("note_id") or ""
    if not note_id:
        print("[X] metadata.json 缺 note_id")
        return False

    seq, old = find_by_note_id(downloads, note_id)
    if seq:
        folder = os.path.join(downloads, old)
        print(f"[i] 该笔记已入库（{old}），覆盖更新")
    else:
        seq = next_seq(downloads)
        folder = os.path.join(downloads, f"{seq:02d}_{sanitize(meta.get('title'))}")
    os.makedirs(folder, exist_ok=True)

    # 图片：imgs/note_XX.jpg → img_XX.jpg（对齐 B 侧命名）
    images = []
    for i, p in enumerate(meta.get("local_images") or [], 1):
        dst = os.path.join(folder, f"img_{i:02d}.jpg")
        shutil.copy2(p, dst)
        images.append(f"img_{i:02d}.jpg")

    # 字幕
    subtitle_file = ""
    if meta.get("subtitle_file"):
        sp = os.path.join(src, meta["subtitle_file"])
        if os.path.exists(sp):
            shutil.copy2(sp, os.path.join(folder, "subtitle.srt"))
            subtitle_file = "subtitle.srt"

    # 语音转写（无字幕视频的 transcript.txt：2026-10-19 实施计划 §3.2，
    # 转换不得丢失可用的本地转写）
    transcript_file = ""
    if meta.get("transcript_file"):
        tp = os.path.join(src, meta["transcript_file"])
        if os.path.exists(tp):
            shutil.copy2(tp, os.path.join(folder, "transcript.txt"))
            transcript_file = "transcript.txt"

    # AI 侧 OCR 产物（如有）：原样带过，导出层直接消费
    for name in ("ocr_status.json", "ocr.md"):
        p = os.path.join(src, name)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(folder, name))

    # 视频流 URL（B 侧 raw.json 不存，但留着无妨；export 不读）
    rec = {
        "ok": True,
        "note_id": note_id,
        "_seq": seq,
        "title": meta.get("title") or "",
        "desc": meta.get("desc") or "",
        "type": meta.get("type") or "normal",
        "time": meta.get("time_ms") or 0,
        "url": meta.get("source_url") or "",
        "author": meta.get("author") or "",
        "liked": meta.get("stats", {}).get("liked") or "",
        "ip": meta.get("ip_location") or "",
        "images": images,
        "subtitle_file": subtitle_file,
        "transcript_file": transcript_file,
        "frame_files": [],
        "author_comments": [],  # 引擎 A 拿不到评论（登录态独占），如实留空
        "via": "engineA",       # 来源标记，便于区分与追溯
    }
    with open(os.path.join(folder, "raw.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    # 更新 _manifest.json（追加/覆盖该条）
    mpath = os.path.join(downloads, "_manifest.json")
    manifest = []
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = []
    manifest = [m for m in manifest if m.get("note_id") != note_id]
    manifest.append({k: rec[k] for k in
                     ("ok", "note_id", "_seq", "title", "type",
                      "images", "subtitle_file", "frame_files")})
    manifest.sort(key=lambda r: r.get("_seq") or 0)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[√] 已入库: {folder}")
    print(f"    图 {len(images)} | 字幕 {'有' if subtitle_file else '无'}"
          f" | 转写 {'有' if transcript_file else '无'}"
          f" | 评论 无（引擎 A 不抓评论，需要请走引擎 B --url）")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="引擎 A 输出目录（含 metadata.json）")
    ap.add_argument("--downloads", default=DEFAULT_DOWNLOADS,
                    help="xhs-curator 的 downloads 目录")
    a = ap.parse_args()
    ok = convert(a.src, a.downloads)
    sys.exit(0 if ok else 1)
