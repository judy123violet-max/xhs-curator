# -*- coding: utf-8 -*-
"""
小红书关键词搜索 → 笔记列表（接勾选工作台）

用法:
    python xhs_search_fetch.py --keyword "AI产品经理 面试" [--count 50] [--sort 热门|最新]

产出:
    search_notes.json  （与 notes.json 同构，可直接喂 xhs_picker_server.py --notes）

说明:
    复用 browser_profile 已登录会话；DOM 收集搜索结果卡片（滚动到稳定），
    每条自带 xsec_token 的原文链接，详情抓取走 xhs_fetch_selected.py。
"""
import argparse
import json
import os
import re
import time
import urllib.parse

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(BASE, "browser_profile")
OUT = os.path.join(BASE, "search_notes.json")

JS_COLLECT = r"""
() => {
  const out = [];
  const seen = {};
  document.querySelectorAll('a[href*="/search_result/"], a[href*="/explore/"]').forEach(a => {
    const href = a.href || '';
    const m = href.match(/(?:explore|search_result)\/([0-9a-f]{24})/);
    if (!m || seen[m[1]]) return;
    const card = a.closest('section') || a.closest('[class*="note-item"]') || a.closest('div');
    if (!card) return;
    seen[m[1]] = 1;
    const tEl = card.querySelector('.title span') || card.querySelector('.title') || a;
    const title = tEl ? tEl.textContent.trim() : '';
    const img = card.querySelector('img');
    const cover = img ? (img.getAttribute('src') || '') : '';
    const isVideo = !!card.querySelector('.play-icon, [class*="play-icon"], .switch-btn');
    const cEl = card.querySelector('.count, .like-wrapper .count');
    const liked = cEl ? cEl.textContent.trim() : '';
    out.push({
      note_id: m[1],
      title: (title || '').slice(0, 120),
      cover: cover,
      type: isVideo ? 'video' : 'normal',
      liked: liked,
      url: href,
    });
  });
  return JSON.stringify(out);
}
"""


def log(*a):
    print(*a, flush=True)


def sanitize(name, maxlen=48):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
    return (name or "untitled")[:maxlen]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--count", type=int, default=40, help="收集上限，默认 40")
    ap.add_argument("--max-rounds", type=int, default=40, help="滚动轮数上限")
    args = ap.parse_args()

    kw = args.keyword.strip()
    url = ("https://www.xiaohongshu.com/search_result?keyword="
           + urllib.parse.quote(kw) + "&source=web_explore_feed")

    from playwright.sync_api import sync_playwright

    items, seen_ids = [], set()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE, channel="chrome", headless=False,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.new_page()
        page.set_default_timeout(45000)
        log(f"[*] 搜索: {kw}")

        # 直接导航搜索 URL 会被挂起/空壳，改走拟人路径：首页 → 搜索框输入 → 回车
        try:
            page.goto("https://www.xiaohongshu.com/", wait_until="domcontentloaded",
                      timeout=60000)
        except Exception as e:
            log("! 首页加载超时（继续尝试）:", str(e)[:120])
        page.wait_for_timeout(2500)

        entered = False
        for sel in ['input[placeholder*="搜索"]', 'input[type="text"]']:
            try:
                box = page.query_selector(sel)
                if box:
                    box.click()
                    box.type(kw, delay=60)
                    page.wait_for_timeout(600)
                    page.keyboard.press("Enter")
                    entered = True
                    break
            except Exception:
                continue
        page.wait_for_timeout(3000)
        # 没跳转就补点搜索按钮
        if "search_result" not in page.url:
            for bsel in ['[class*="search-button"]', '.input-button', 'button:has-text("搜索")']:
                try:
                    b = page.query_selector(bsel)
                    if b:
                        b.click()
                        break
                except Exception:
                    continue
            page.wait_for_timeout(3000)
        # 还不行就直接导航
        if "search_result" not in page.url:
            log("! 搜索框未生效，退回直接导航搜索 URL")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                log("! 搜索 URL 超时:", str(e)[:120])
            page.wait_for_timeout(4000)

        if "search_result" not in page.url:
            page.screenshot(path=os.path.join(BASE, "_diag", "search_fail.png"))
            log("[X] 最终未进入搜索结果页（截图 _diag/search_fail.png），放弃收集以免混入首页推荐流")
            ctx.close()
            return

        page.wait_for_timeout(5000)

        # 检查是否被风控/要求登录
        body = page.content()
        if "请登录" in body or "website-login" in page.url:
            log("[X] 触发登录墙 —— 请删掉 browser_profile/ 重新扫码登录")
            ctx.close()
            return
        if len(items) == 0:
            page.screenshot(path=os.path.join(BASE, "_diag", "search_last.png"))

        stall, last = 0, -1
        for rnd in range(args.max_rounds):
            raw = page.evaluate(JS_COLLECT)
            fresh = 0
            for it in json.loads(raw):
                if it["note_id"] not in seen_ids:
                    seen_ids.add(it["note_id"])
                    items.append(it)
                    fresh += 1
            log(f"  轮 {rnd + 1}: 累计 {len(items)} 条（+{fresh}）")
            if len(items) >= args.count:
                break
            if fresh == 0:
                stall += 1
                if stall >= 3:
                    log("[*] 连续 3 轮无新增，判定到底")
                    break
            else:
                stall = 0
            page.evaluate("window.scrollBy(0, 1600)")
            page.wait_for_timeout(1600)

        ctx.close()

    items = items[:args.count]
    out = {
        "nickname": f"搜索：{kw}",
        "user_id": None,
        "profile_url": url,
        "count": len(items),
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "notes": items,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log(f"[√] 收集 {len(items)} 条 → {OUT}")
    log(f"    下一步: python xhs_picker_server.py --port 8789 --notes search_notes.json")


if __name__ == "__main__":
    main()
