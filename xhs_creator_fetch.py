# -*- coding: utf-8 -*-
"""
小红书博主主页笔记列表抓取（本机 Chrome + 登录态复用）

用法:
    python xhs_creator_fetch.py <博主主页URL/短链/用户ID>
    python xhs_creator_fetch.py --from-raw --user-id xxx --nick xxx

抓取原理（踩坑记录）:
    博主主页的笔记列表有两个来源，缺一不可：
      ① 首屏第一页由服务端直出（SSR），内嵌在 HTML 里，
         **不会产生任何网络请求** —— 只抓接口必然漏掉最新一整屏；
      ② 之后的分页由前端滚动调 user_posted 接口加载。
    页面自身的 SPA store（__INITIAL_STATE__.user.notes._rawValue[0]）
    会把 ① + ② 合并累积，因此以它为权威数据源，接口捕获作为兜底。
"""
import argparse
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE, "browser_profile")
OUT_JSON = os.path.join(BASE, "notes.json")
RAW_JSON = os.path.join(BASE, "raw_notes.json")
STORE_JSON = os.path.join(BASE, "raw_store_items.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 读取 SPA store 里第 0 个 tab（笔记）的全部条目
JS_STORE = """() => {
    try {
        const u = (window.__INITIAL_STATE__ || {}).user || {};
        const nt = u.notes;
        const raw = nt && (nt._rawValue || nt._value || nt.value || nt);
        if (!Array.isArray(raw) || !Array.isArray(raw[0])) return [];
        return raw[0].filter(x => x && (x.noteCard || x.noteId || x.id)).map(x => {
            const c = x.noteCard || {};
            const info = c.interactInfo || {};
            const cov = c.cover || {};
            const user = c.user || {};
            return {
                note_id: x.id || x.noteId || '',
                display_title: c.displayTitle || c.title || '',
                type: c.type || 'normal',
                interact_info: {liked_count: info.likedCount || '0',
                                sticky: !!info.sticky},
                cover: {url_default: cov.urlDefault || cov.urlPre || cov.url_pre || ''},
                xsec_token: x.xsecToken || '',
                time: c.time || 0
            };
        });
    } catch (e) { return []; }
}"""

JS_STORE_LEN = """() => {
    try {
        const u = (window.__INITIAL_STATE__ || {}).user || {};
        const nt = u.notes;
        const raw = nt && (nt._rawValue || nt._value || nt.value || nt);
        return (Array.isArray(raw) && Array.isArray(raw[0])) ? raw[0].length : 0;
    } catch (e) { return -1; }
}"""


def log(*a):
    print(*a, flush=True)


def parse_target(arg):
    arg = (arg or "").strip()
    m = re.search(r"/user/profile/([0-9a-fA-F]{16,})", arg)
    uid = m.group(1) if m else None
    if not uid and re.fullmatch(r"[0-9a-fA-F]{16,}", arg):
        uid = arg
    mt = re.search(r"xsec_token=([^&\s]+)", arg)
    return uid, (mt.group(1) if mt else None)


def is_logged_in(page):
    """小红书会给访客也发 web_session，必须靠页面特征判断"""
    try:
        if len(page.query_selector_all("section.note-item, .note-item")) > 0:
            return True
    except Exception:
        pass
    try:
        body = page.inner_text("body")
    except Exception:
        body = ""
    if "手机号登录" in body or "扫码登录" in body:
        return False
    for sel in [".login-container", ".login-box", ".login-modal",
                "div[class*='login-container']"]:
        try:
            if page.query_selector(sel):
                return False
        except Exception:
            pass
    try:
        if "/login" not in page.url and body.strip():
            return True
    except Exception:
        pass
    return False


def scrape(uid, xsec, max_notes=800, login_wait=600):
    from playwright.sync_api import sync_playwright

    store, net = {}, {}
    has_more = {"v": True}
    nick = {"v": None}
    doc = {}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR, channel="chrome", headless=False,
            viewport={"width": 1440, "height": 900}, user_agent=UA,
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        try:
            page.goto("https://www.xiaohongshu.com/explore",
                      wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log("[!] 打开首页超时:", e)
        page.wait_for_timeout(4000)

        if not is_logged_in(page):
            log("=" * 60)
            log(" 需要登录：浏览器窗口已打开，请用小红书 App 扫码登录")
            log(" （登录一次即可，之后会自动复用）")
            log("=" * 60)
            try:
                page.goto("https://www.xiaohongshu.com/login",
                          wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(3000)
                page.bring_to_front()
            except Exception:
                pass
            t0 = time.time()
            tick = 0
            while time.time() - t0 < login_wait:
                page.wait_for_timeout(2000)
                tick += 1
                if is_logged_in(page):
                    log("[√] 登录成功")
                    break
                if tick % 5 == 0:
                    try:
                        t = page.title()
                    except Exception:
                        t = "?"
                    log(f"    ...等待扫码中（剩余 {int(login_wait - time.time() + t0)}s）当前页: {t}")
                    if "安全限制" in t or "验证" in t:
                        log("    [!] 检测到安全验证页，请在浏览器里手动完成滑块验证")
            else:
                log("[X] 等待登录超时")
                ctx.close()
                return {}, None
        else:
            log("[√] 已检测到有效登录态，直接开抓")

        def on_response(resp):
            u = resp.url
            if (resp.request.resource_type == "document"
                    and "/user/profile/" in u and "html" not in doc):
                try:
                    doc["html"] = resp.text()
                except Exception:
                    pass
                return
            if "user_posted" in u and "sns/web" in u:
                try:
                    d = (resp.json().get("data") or {})
                except Exception:
                    return
                notes = d.get("notes") or []
                for n in notes:
                    nid = (n.get("note_id") or n.get("id")
                           or (n.get("note_card") or {}).get("note_id"))
                    if nid and nid not in net:
                        net[nid] = n
                        if not nick["v"]:
                            nick["v"] = (n.get("user") or {}).get("nick_name")
                if "has_more" in d:
                    has_more["v"] = bool(d.get("has_more"))
                log(f"    接口返回 {len(notes)} 条 / 接口累计 {len(net)} 条 "
                    f"/ has_more={has_more['v']}")

        page.on("response", on_response)

        url = f"https://www.xiaohongshu.com/user/profile/{uid}"
        if xsec:
            url += f"?xsec_token={xsec}&xsec_source=pc_user"
        log("[*] 打开主页:", url)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        for sel in [".user-name", ".user-nickname"]:
            try:
                el = page.query_selector(sel)
                if el and el.inner_text().strip():
                    nick["v"] = el.inner_text().strip()
                    break
            except Exception:
                pass

        # SSR 首屏是否内嵌（诊断信息）
        if doc.get("html"):
            n_ssr = len(set(re.findall(r'data-note-id="([0-9a-f]{16,})"', doc["html"])))
            log(f"[*] SSR 内嵌首屏卡片：{n_ssr} 条（不产生网络请求，靠 SPA store 回收）")

        # ---------- 滚动加载，以 SPA store 长度为准 ----------
        stable, last = 0, -1
        for _ in range(500):
            try:
                page.mouse.wheel(0, 3000)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(1800)
            cur = page.evaluate(JS_STORE_LEN)
            if cur == last:
                stable += 1
                if stable >= 4 and not has_more["v"]:
                    log("[*] 已加载完毕（has_more=false 且数量稳定）")
                    break
                if stable >= 8:
                    log("[*] 连续无新增，判定到底")
                    break
            else:
                stable, last = 0, cur
            if cur >= max_notes:
                log("[*] 已达抓取上限")
                break
        log(f"[*] SPA store 最终条数：{last}")

        for n in (page.evaluate(JS_STORE) or []):
            nid = n.get("note_id")
            if nid:
                store[nid] = n

        ctx.close()

    # store 是权威源（含 SSR 首屏 + 全部分页）；接口仅作兜底。
    # 注意：同一条笔记在 SSR 与接口里的 id 后缀可能不同，
    # 因此除 id 外还必须按「标题+日期」去重，否则会重复计数。
    def key_of(n):
        card = n.get("note_card") or {}
        t = (card.get("display_title") or n.get("display_title") or n.get("title") or "").strip()
        ts = n.get("time") or card.get("time") or 0
        day = time.strftime("%Y-%m-%d", time.localtime(ts / 1000)) if ts else ""
        return f"{t}|{day}"

    merged = {}
    seen_keys = set()
    for nid, n in store.items():
        merged[nid] = n
        seen_keys.add(key_of(n))
    added = 0
    for nid, n in net.items():
        k = key_of(n)
        if nid in merged or (k and k in seen_keys):
            continue
        merged[nid] = n
        seen_keys.add(k)
        added += 1
    log(f"[*] 数据源合并：store {len(store)}（权威） + 接口补充 {added} → 共 {len(merged)} 条")

    with open(RAW_JSON, "w", encoding="utf-8") as f:
        json.dump({"net": list(net.values()), "store": list(store.values())},
                  f, ensure_ascii=False)
    with open(STORE_JSON, "w", encoding="utf-8") as f:
        json.dump(list(store.values()), f, ensure_ascii=False)
    return merged, nick["v"]


def load_raw():
    if os.path.exists(STORE_JSON):
        with open(STORE_JSON, encoding="utf-8") as f:
            items = json.load(f)
        nick = None
        for n in items:
            nick = nick or ((n.get("user") or {}).get("nick_name")
                            or (n.get("note_card") or {}).get("user", {}).get("nickName"))
        return {n["note_id"]: n for n in items if n.get("note_id")}, nick
    with open(RAW_JSON, encoding="utf-8") as f:
        blob = json.load(f)
    items = blob.get("net", blob) if isinstance(blob, dict) else blob
    out = {}
    for n in items:
        nid = n.get("note_id") or n.get("id")
        if nid:
            out[nid] = n
    return out, None


def normalize(captured, uid, nick):
    items = []
    for nid, n in captured.items():
        card = n.get("note_card") or {}
        c = card.get("cover") or n.get("cover") or {}
        cover = ""
        if isinstance(c, dict):
            cover = (c.get("url_default") or c.get("url_preview")
                     or c.get("url_pre") or "")
        info = card.get("interact_info") or n.get("interact_info") or {}
        ts = n.get("time") or card.get("time") or 0
        date = time.strftime("%Y-%m-%d", time.localtime(ts / 1000)) if ts else ""
        ntype = card.get("type") or n.get("type") or "normal"
        token = n.get("xsec_token") or card.get("xsec_token") or ""
        items.append({
            "note_id": nid,
            "title": (card.get("display_title") or n.get("display_title")
                      or n.get("title") or "").strip(),
            "type": ntype,
            "liked": str(info.get("liked_count") or "0"),
            "sticky": bool(info.get("sticky")),
            "date": date,
            "_ts": ts,
            "cover": cover,
            "xsec_token": token,
            "url": f"https://www.xiaohongshu.com/explore/{nid}"
                   + (f"?xsec_token={token}&xsec_source=pc_user" if token else ""),
        })
    items.sort(key=lambda x: x["_ts"], reverse=True)
    for it in items:
        it.pop("_ts", None)
    return {
        "user_id": uid,
        "nickname": nick,
        "profile_url": f"https://www.xiaohongshu.com/user/profile/{uid}",
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(items),
        "notes": items,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?", default="")
    ap.add_argument("--from-raw", action="store_true")
    ap.add_argument("--user-id", default="")
    ap.add_argument("--nick", default="")
    ap.add_argument("--max", type=int, default=800)
    ap.add_argument("--login-wait", type=int, default=600)
    args = ap.parse_args()

    if args.from_raw:
        captured, nick = load_raw()
        uid = args.user_id or ""
        nick = args.nick or nick
        log(f"[*] 从原始数据重建：{len(captured)} 条")
    else:
        uid, xsec = parse_target(args.target)
        if not uid:
            log("[X] 无法解析用户 ID:", args.target)
            sys.exit(1)
        log(f"[*] 目标博主 ID: {uid}")
        captured, nick = scrape(uid, xsec, args.max, args.login_wait)
        if not captured:
            log("[X] 未抓到任何笔记（未登录或被风控）")
            sys.exit(3)

    out = normalize(captured, uid, nick)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    log("=" * 60)
    log(f"[√] 完成：{out['nickname']} 共 {out['count']} 条笔记")
    log(f"[√] 列表已保存: {OUT_JSON}")
    sticky = [x for x in out["notes"] if x["sticky"]]
    log(f"    其中置顶 {len(sticky)} 条，视频 "
        f"{len([x for x in out['notes'] if x['type'] == 'video'])} 条")
    for it in out["notes"][:10]:
        flag = "[置顶]" if it["sticky"] else ""
        log(f"   - [{it['date']}] {it['type']:<6} ♥{it['liked']:<6}{flag} {it['title'][:32]}")


if __name__ == "__main__":
    main()
