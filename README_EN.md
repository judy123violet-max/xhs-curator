<div align="center">

# xhs-curator

**<a href="README.md">简体中文</a> | English**

[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.10-blue?style=flat-square&logo=python&logoColor=white)](#-quick-start)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=flat-square)](#-quick-start)
[![GitHub stars](https://img.shields.io/github/stars/judy123violet-max/xhs-curator?style=flat-square&color=fda7df)](https://github.com/judy123violet-max/xhs-curator/stargazers)

<p>🔥 <b>Browse first, pick what matters, export clean notes into Obsidian.</b></p>

</div>

---

> **⚠️ Disclaimer**
>
> This project is for **personal learning and research** only. Do not use it for commercial purposes or large-scale scraping. You are responsible for complying with Xiaohongshu's Terms of Service and local laws, and for keeping request rates reasonable. See the full disclaimer at the bottom.

## 📖 Introduction

A **visual pipeline** that collects Xiaohongshu (RedNote) notes into an Obsidian vault.

Two ways in: **whole profile** — it lays out a creator's profile or your search results for you to browse, and you pick the notes you actually want; **single note** — paste a share link and fetch it directly. Either way it fetches the note body, original images and **comments posted by the author**, transcribes text inside images into searchable text, and finally writes everything into your vault in Obsidian-native format.

**Who it's for**: people who treat Xiaohongshu as an information source and want to keep it in a knowledge base (job-hunting notes, industry experience, tutorials, competitor research).

### 🔧 How it works

- **Reuses your local login**: Playwright drives your real Chrome; scan the QR code once and the session is persisted locally. No passwords involved.
- **No signature reverse-engineering**: reads the official page state straight from the browser, avoiding encrypted-parameter reverse engineering.
- **Dual-source listing**: merges SSR first-screen data with scroll-loaded API data, so the newest screenful is never missed.
- **Author-only comments**: listens to the official comment API and keeps only comments written by the creator.
- **Resumable**: re-running skips notes already downloaded, making low-rate batch fetching easy.

## 🎁 What you get

A real export sample (content omitted):

```markdown
---
title: "Talking about projects is also a kind of progressive disclosure"
author: "some creator"
published: 2026-08-06          # original publish date
created: 2026-10-15            # import date
description: "When preparing for interviews I suddenly realised…"
source: "https://www.xiaohongshu.com/explore/…"    # link back to the original note
tags:
  - xiaohongshu
  - interview
  - progressive-disclosure   # #hashtags in the body are moved here
类型: 图文
点赞: "465"
---

## 正文

…full body text, with #hashtag[话题]# markers and @mentions stripped out…

## 图片与文字转录

![[_附件/01_…/img_01.jpg]]

![[_附件/01_…/img_02.jpg]]
（key text inside the image, transcribed verbatim, headings and lists kept）
（selfies, scenery and mood shots keep only the image — no caption at all）

## 博主的评论                     ← always last in the note

> 03｜… (the body said "running out of space, see comments" —
> the full version from the author's comment is captured too)
```

**What you end up with**: the body text, the text inside the images, and the author's comment replies — all three. No emoji in titles, no hashtag noise in the body; ready to read.

## 📸 Screenshot

![Curation workbench](docs/images/picker.jpg)

The workbench is a local web page with four persistent tabs: **Creator profile / Keyword search / Single note / Fetched notes**. Browse notes as cards with select-all / invert / video-only / image-only / keyword filter; fetched notes are automatically badged 「已抓过」. **Click a card to select it**, **click the title or "原文↗" to preview the note in an embedded detail view** (press `Esc` or the "← 返回列表" button to come back — your selection is preserved). **Single note tab**: paste a share link (or a whole share text block) → resolve → fetch, with already-fetched notes detected automatically.

## ✨ Features

**Discovery & collection**

- ✅ Curation workbench with four persistent tabs: creator profile / keyword search / single note / fetched notes
- ✅ Fetch a creator's full note list (profile URL / share short link / user ID)
- ✅ Search by keyword right inside the page — no extra terminal
- ✅ Visual selection: select-all / invert / video-only / image-only / keyword filter / **select-unfetched**
- ✅ Fetched notes are badged automatically, reconciled with local download records
- ✅ In-window note preview; selection auto-saved
- ✅ One-click fetch from the page: the script runs in the background with live logs, badges refresh when done
- ✅ Fetch body text, original images, official subtitles for videos
- ✅ Author-only comments (including replies and pinned ones)
- ✅ Resumable fetching (offset / count)

**Processing & export**

- ✅ Three-tier OCR classification (transcribe key text / keep screenshot essentials / photos only)
- ✅ Body cleanup: hashtags → frontmatter tags, mentions removed
- ✅ Emoji stripped from titles, safe filenames
- ✅ Obsidian-native export: frontmatter + `![[wikilink]]` attachment folders

## 🆚 How it differs

| Project | Form | Input | Browse before picking | Text in images | Author comments | Output |
|---|---|---|---|---|---|---|
| **xhs-curator** | Visual workbench + scripts | Creator profile / keyword | ✅ pick by clicking | ✅ tiered OCR | ✅ author only | Obsidian vault |
| xhs-importer-pro | Obsidian plugin | Single share link (batch) | ❌ link in, note out | ❌ | ❌ | Obsidian |
| feedgrab | CLI | Single URL (multi-platform) | ❌ | video via ASR | ❌ | generic Markdown |
| XHS-Downloader | CLI / userscript | Note links, account lists | ❌ bulk download | ❌ | ❌ | local files |
| MediaCrawler | CLI crawler | Keyword / creator page | ❌ | ❌ | all comments | JSON / database |

**Put simply**: other tools are about "saving"; this one is about "saving selectively, saving cleanly" — pick what's worth keeping from a whole creator profile, then import it with image text and comment replies included, all cleaned up.

## 🔗 Supported inputs

| What you have | Command | Output |
|---|---|---|
| Creator profile URL / short link / user ID | `xhs_creator_fetch.py` | `notes.json` |
| Keyword | `xhs_search_fetch.py` | `search_notes.json` |
| Single note URL or share text | `xhs_fetch_selected.py --url "<link>"` or the "Single note" tab | `downloads/` (same pipeline as bulk import) |

Both list files feed directly into the picker (`--notes`).

## 🚀 Quick start

### Requirements

| | Requirement |
|---|---|
| Python | 3.10+ |
| Browser | Chrome installed locally |
| Account | A Xiaohongshu account (scan the QR code **once** on first run; the session is stored in `browser_profile/`) |

### 1. Install

```bash
pip install -r requirements.txt
python -m playwright install chrome
```

### 2. Fetch a note list

```bash
# A Chrome window opens on first run — scan the QR code to log in
python xhs_creator_fetch.py https://www.xiaohongshu.com/user/profile/xxxx
```

Or discover by keyword:

```bash
python xhs_search_fetch.py --keyword "AI product manager interview" --count 40
```

### 3. Open the curation workbench

```bash
python xhs_picker_server.py
```

Open `http://127.0.0.1:8788` and switch freely between four tabs:

- **Single note**: paste a share link or a whole share text block → resolve → fetch this note; already-fetched ones are detected

- **Select** the notes you want ("select-unfetched" skips already-fetched ones; selection auto-saves)
- **Keyword search**: switch to the search tab and search right in the page
- **Fetch**: click the bottom-left button — the fetch script runs in the background with live logs, and badges refresh automatically
- **Fetched notes**: track progress and open each note's local folder in one click

### 4. Fetch bodies and images

```bash
python xhs_fetch_selected.py              # everything in the selection
python xhs_fetch_selected.py --count 5    # five at a time, if you're cautious
python xhs_fetch_selected.py --offset 5   # continue from where you left off
```

### 5. OCR classification

Images land in `downloads/<note>/img_*.jpg`. **Text inside images needs a multimodal AI** — this project only defines the format. Send this to any vision-capable model:

> Read the images under `downloads`, transcribe the text in each image, and write the result to `ocr.md` in the same folder, one section per image (`## img_01.jpg` followed by the transcription). For selfies and scenery write `（照片）`; for UI screenshots keep only the meaningful content and prompts.

### 6. Export to Obsidian

```bash
python xhs_export_md.py --dest "/path/to/your/vault"
```

## 📁 Output structure

```
downloads/01_note-title/
├── raw.json        # structured raw fields
├── note.md         # body skeleton
├── img_01.jpg ...  # original images
├── subtitle.srt    # official subtitles (video notes)
└── ocr.md          # OCR result (step 5)

<vault>/
├── 01_note-title.md
└── _附件/01_note-title/img_*.jpg    # referenced with ![[wikilink]]
```

## 💻 Where it runs

**It is not tied to any agent.** It is five Python scripts plus a local web page:

- Any AI agent that can run commands works (Claude Code, Cursor, Codex CLI) — or just your own terminal.
- The picker is a plain web page (`http://127.0.0.1:8788`): open it in a normal browser tab (recommended), an embedded preview panel, or VS Code / Cursor's `Simple Browser: Show`.
- It binds to `127.0.0.1` only — not reachable from other devices on your network.

## ❓ FAQ

<details>
<summary><b>Do I have to log in? What about my password?</b></summary>

Log in once by scanning a QR code; the session is reused locally afterwards. The tool never touches your password. `browser_profile/` is gitignored — never commit it.
</details>

<details>
<summary><b>Will my account get banned?</b></summary>

It only performs read-only browsing, no likes/publishing. Still, keep request rates modest. The search entry point occasionally gets throttled — retry later.
</details>

<details>
<summary><b>What if fetching is interrupted?</b></summary>

Just run it again — completed notes are skipped automatically.
</details>

<details>
<summary><b>Does it fetch other people's comments?</b></summary>

Only comments posted by the creator, which often carry extra substance. Other users' comments are ignored.
</details>

<details>
<summary><b>Why does the detail preview ask me to log in?</b></summary>

The detail view is embedded, and browser cross-site rules mean it carries no login state. Close the dialog to read the note; for the full logged-in version (comments etc.), click "浏览器打开↗" at the top. This only affects previewing — selection and fetching are unaffected.
</details>

## 🗺️ Roadmap

- [x] Full creator profile fetching (SSR + API, deduplicated)
- [x] Visual picker workbench
- [x] Body / images / official subtitles
- [x] Author-only comment capture
- [x] Tiered OCR classification
- [x] Obsidian-native export
- [x] Resumable fetching (offset / count)
- [x] Direct import from a single note URL (`--url` / the "Single note" tab; supports short links and whole share text blocks)
- [ ] Config file for paths, ports and fetch rate
- [ ] One-click installer

## ⭐ Star history

If this project helps you, please consider giving it a star ⭐

[![Star History Chart](https://api.star-history.com/chart?repos=judy123violet-max/xhs-curator&type=timeline&legend=bottom-right)](https://www.star-history.com/#judy123violet-max/xhs-curator&Timeline)

## ⚠️ Disclaimer

1. This project is for **personal learning and research** only, and must not be used commercially.
2. You must comply with Xiaohongshu's Terms of Service and applicable laws, and keep request rates reasonable.
3. Do not use this project to obtain or distribute copyrighted content or to infringe on others' rights.
4. This project ships no credentials; you log in yourself and bear any account risk.
5. The author assumes no liability for any consequences of using this project.
6. Using this project means you have read and agreed to the above.

## 📄 License

[MIT](LICENSE)
