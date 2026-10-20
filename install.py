#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xhs-curator 安装器（2026-10-20 P0：发布包完整性与主页批量入口）

用法:
    python install.py                                # 装到默认 Agent 技能目录
    python install.py --skill-dir "D:\\skills"       # 指定技能目录
    python install.py --repo-root "D:\\tools\\xhs-curator"  # 仓库在其他位置时显式指定
    python install.py --with-deps                    # 检测到缺依赖时自动 pip 安装

做什么:
    1. 校验仓库完整性（批量链路 + 单篇链路脚本齐全）
    2. 把 skill/ 复制为 <技能目录>/xhs-curator/（幂等，重复安装覆盖）
    3. 写 marker: xhs-curator/.xhs-curator-root = 仓库绝对路径
       （Skill 运行时按「环境变量 → marker → 向上探测」定位仓库根）
    4. 依赖检测: python 版本 / curl_cffi / playwright / Chrome，缺什么给什么命令

标准安装路径 = 克隆本仓库 → 运行本脚本。
「仅复制 skill/ 目录」只支持单篇速读，不能用于主页批量采集。
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
SKILL_SRC = os.path.join(BASE, "skill")
MARKER_NAME = ".xhs-curator-root"

BATCH_SCRIPTS = ["xhs_creator_fetch.py", "xhs_picker_server.py",
                 "xhs_fetch_selected.py", "xhs_export_md.py",
                 "xhs_search_fetch.py"]
SINGLE_SCRIPTS = ["skill/scripts/fetch_xhs_note.py",
                  "skill/scripts/to_downloads.py"]
REQUIRED = BATCH_SCRIPTS + SINGLE_SCRIPTS


AGENT_SKILL_DIRS = {
    "WorkBuddy": (".workbuddy", "skills"),
    "Codex": (".codex", "skills"),
    "Claude Code": (".claude", "skills"),
    "Cursor": (".cursor", "skills"),
}


def agent_skill_dirs():
    """各 Agent 技能目录（调用时展开 ~，便于测试重定向 HOME）"""
    return {name: os.path.join(os.path.expanduser("~"), *parts)
            for name, parts in AGENT_SKILL_DIRS.items()}


def default_skill_dir():
    """仅在能可靠识别当前 Agent 技能目录时自动选择（目录已存在才算可靠）；
    识别不了返回 None——由调用方打印各 Agent 的明确命令并退出，绝不猜测。"""
    for name, d in agent_skill_dirs().items():
        if os.path.isdir(d):
            return d
    return None


def print_agent_dirs():
    print("[X] 无法自动识别你的 Agent 技能目录——请显式指定，例如：")
    for name, d in agent_skill_dirs().items():
        print(f'    {name}:  python install.py --skill-dir "{d}"')
    print("    其他 Agent: python install.py --skill-dir <你的技能目录>")


def check_repo(repo_root):
    """仓库完整性校验：批量链路与单篇链路脚本必须齐全"""
    missing = [s for s in REQUIRED if not os.path.exists(os.path.join(repo_root, s))]
    return missing


def find_spec(mod):
    return importlib.util.find_spec(mod) is not None


def _module_exists(python_exe, mod):
    """探测指定解释器里模块是否可导入（2026-10-20 实测教训：
    依赖装在哪个解释器、脚本就得用哪个解释器跑）"""
    r = subprocess.run([python_exe, "-c", f"import {mod}"],
                       capture_output=True)
    return r.returncode == 0


def dependency_report(with_deps=False, python_exe=None):
    """依赖检测：针对指定解释器（默认=运行安装器的解释器）；
    缺什么报什么并附可操作命令——装依赖必须装给「跑脚本的那个解释器」"""
    python_exe = python_exe or sys.executable
    lines, need_pip = [], []
    ver = subprocess.run([python_exe, "-c",
                          "import sys;print('%d.%d' % sys.version_info[:2])"],
                         capture_output=True, text=True)
    ver_str = (ver.stdout or "").strip() or "?"
    try:
        major, minor = int(ver_str.split(".")[0]), int(ver_str.split(".")[1])
        if (major, minor) < (3, 10):
            lines.append(f"[X] Python 需要 3.10+，当前 {ver_str}: {python_exe}")
    except Exception:
        lines.append(f"[!] 无法探测解释器版本: {python_exe}")
    for mod, desc, req in (("curl_cffi", "单篇匿名抓取", "curl_cffi>=0.16.3"),
                           ("playwright", "主页批量采集", "playwright>=1.40.0")):
        if _module_exists(python_exe, mod):
            lines.append(f"[√] {mod} 已安装（{desc}）")
        else:
            need_pip.append(req)
            lines.append(f"[!] {mod} 未安装（{desc}）——解释器: {python_exe}")
    chrome_ok = any(os.path.exists(p) for p in (
        r"C://Program Files//Google//Chrome//Application//chrome.exe",
        r"C://Program Files (x86)//Google//Chrome//Application//chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")))
    lines.append(("[√] 已检测到本机 Chrome（登录态批量采集用）" if chrome_ok
                  else "[!] 未检测到 Chrome——主页批量采集需要本机安装 Chrome"))
    if _module_exists(python_exe, "faster_whisper"):
        lines.append("[√] faster-whisper 已安装（无字幕视频本地转写）")
    else:
        lines.append("[i] faster-whisper 未安装（可选：无字幕视频的本地转写，"
                     '需要时再装：pip install "faster-whisper>=1.0.0" "av<15"）')
    if need_pip:
        cmd = f'"{python_exe}" -m pip install {" ".join(need_pip)}'
        if with_deps:
            subprocess.run([python_exe, "-m", "pip", "install", *need_pip], check=True)
            lines.append("[√] 已自动安装: " + " ".join(need_pip))
        else:
            lines.append(f"[!] 请执行依赖安装（装给运行脚本的那个解释器）:\n    {cmd}")
    return lines


def install(repo_root, skill_dir, python_exe=None):
    repo_root = os.path.abspath(repo_root)
    python_exe = os.path.abspath(python_exe or sys.executable)
    missing = check_repo(repo_root)
    if missing:
        print("[X] 仓库不完整，缺少以下文件（请重新 git clone，不要手工裁剪）:")
        for m in missing:
            print("    - " + m)
        return False
    dest = os.path.join(skill_dir, "xhs-curator")
    os.makedirs(dest, exist_ok=True)
    src_skill = os.path.join(repo_root, "skill")
    n = 0
    for root, dirs, files in os.walk(src_skill):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(root, src_skill)
        target_root = dest if rel == "." else os.path.join(dest, rel)
        os.makedirs(target_root, exist_ok=True)
        for fn in files:
            shutil.copy2(os.path.join(root, fn), os.path.join(target_root, fn))
            n += 1
    with open(os.path.join(dest, MARKER_NAME), "w", encoding="utf-8") as f:
        json.dump({"repo_root": repo_root, "python": python_exe}, f,
                  ensure_ascii=False, indent=2)
    ok, detail = verify_marker(dest)
    print(f"[√] 已安装 {n} 个文件 → {dest}")
    print(f"    Skill 名称: xhs-curator | 仓库: {repo_root}")
    print(f"    marker 校验: {detail}")
    return ok


def read_marker(skill_dir):
    """读 marker：新版 JSON {repo_root, python}；旧版纯文本（仅仓库路径）"""
    marker = os.path.join(skill_dir, MARKER_NAME)
    if not os.path.exists(marker):
        return None
    with open(marker, encoding="utf-8") as f:
        raw = f.read().strip()
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            return d.get("repo_root", ""), d.get("python") or ""
        except Exception:
            return None
    return raw, ""  # 旧版纯文本


def verify_marker(skill_dir):
    """marker 校验：指向的仓库必须存在且必要脚本齐全；失效给可执行修复提示"""
    got = read_marker(skill_dir)
    if got is None:
        return False, f"marker 缺失——请重新运行 install.py（仓库: {BASE}）"
    root, python_exe = got
    if not os.path.isdir(root):
        return False, (f"marker 指向的仓库不存在: {root}\n"
                       f"    修复: 仓库移动/删除后，重新运行 install.py 即可更新")
    missing = check_repo(root)
    if missing:
        return False, (f"marker 指向的仓库不完整，缺: {missing}\n"
                       f"    修复: 重新运行 install.py 或重新 git clone")
    if python_exe and not os.path.exists(python_exe):
        # 2026-10-21 复验 P0-4：解释器失效不得静默降级到当前解释器
        # （否则重现「依赖装在 A、脚本用 B 跑」），必须验证失败并引导修复
        return False, (f"marker 记录的 Python 解释器已不存在: {python_exe}\n"
                       f"    修复: 重新运行 install.py（必要时加 --with-deps），"
                       f"会用当前解释器更新记录")
    return True, f"仓库有效: {root}（解释器: {python_exe}）"


def resolve_repo_root(skill_dir):
    """Skill 运行时定位仓库根：返回 (root, python_exe) 或 None。
    环境变量 → marker（含记录的解释器）→ 向上探测。"""
    env = os.environ.get("XHS_CURATOR_HOME")
    if env and os.path.exists(os.path.join(env, "xhs_export_md.py")):
        return env, sys.executable
    d = os.path.abspath(skill_dir)
    while True:
        marker = os.path.join(d, MARKER_NAME)
        if os.path.exists(marker):
            got = read_marker(d)
            if got:
                root, python_exe = got
                if root and os.path.exists(os.path.join(root, "xhs_export_md.py")):
                    if python_exe and not os.path.exists(python_exe):
                        # 2026-10-21 复验 P0-4：解释器失效 → 路由停止，
                        # 不回退到当前解释器（防「装在 A、跑在 B」重现）
                        return None
                    return root, (python_exe or sys.executable)
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", default=default_skill_dir(),
                    help="Agent 技能目录；能可靠识别时自动选择（WorkBuddy/Codex/"
                         "Claude Code/Cursor 已存在的目录），否则必须显式指定")
    ap.add_argument("--repo-root", default=BASE,
                    help="仓库根目录（默认=本脚本所在目录）")
    ap.add_argument("--verify", action="store_true",
                    help="只校验已安装 Skill 的 marker，不安装")
    ap.add_argument("--with-deps", action="store_true",
                    help="检测到缺依赖时自动 pip 安装（默认只提示命令）")
    ap.add_argument("--python", default=sys.executable,
                    help="记录到 marker 的 Python 解释器（运行脚本用它，"
                         "依赖也装给它；默认=运行本安装器的解释器）")
    a = ap.parse_args()
    print("===== xhs-curator 安装器 =====")
    if not a.skill_dir:
        print_agent_dirs()
        sys.exit(1)
    print(f"  技能目录: {a.skill_dir}")
    deps = dependency_report(a.with_deps, a.python)
    for ln in deps:
        print("  " + ln)
    if a.verify:
        ok, detail = verify_marker(a.skill_dir)
        print(("[√] " if ok else "[X] ") + detail)
        sys.exit(0 if ok else 1)
    ok = install(a.repo_root, a.skill_dir)
    print("=====\n下一步: 重启 Agent 对话，然后直接发送小红书链接即可"
          "（单篇→匿名速读；博主主页→登录态工作台）")
    sys.exit(0 if ok else 1)
