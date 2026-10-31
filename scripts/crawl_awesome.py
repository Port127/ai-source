#!/usr/bin/env python3
"""抓取 Awesome 树：顶层列表 → 各二级仓库 README。

第一阶段解析顶层 awesome/readme.md，得到 N 个二级仓库指向；
第二阶段并发抓取每个仓库的 README 原文，存入缓存供后续解析。

用法：
    python3 crawl_awesome.py --parse            # 仅解析顶层，看有多少待抓
    python3 crawl_awesome.py --limit 20         # 小规模试抓
    python3 crawl_awesome.py                    # 全量抓取
    python3 crawl_awesome.py --workers 32       # 指定并发

缓存位置：~/.cache/capability-forge/awesome/
"""

import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.request

CACHE = os.path.expanduser("~/.cache/capability-forge/awesome")
RAW_DIR = os.path.join(CACHE, "raw")
TOP_URL = "https://raw.githubusercontent.com/sindresorhus/awesome/main/readme.md"
UA = {"User-Agent": "capability-forge/0.2"}


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def get_top():
    p = os.path.join(CACHE, "top.md")
    if os.path.isfile(p):
        return open(p, encoding="utf-8").read()
    os.makedirs(CACHE, exist_ok=True)
    txt = fetch(TOP_URL, timeout=60)
    with open(p, "w", encoding="utf-8") as f:
        f.write(txt)
    return txt


ITEM_RE = re.compile(r"^- \[([^\]]+)\]\((https?://[^)]+)\)\s*(?:[-–—]\s*(.*))?$")


def parse_top():
    """解析顶层 readme，返回 [(分类, 名称, url, 描述)]"""
    lines = get_top().split("\n")
    ci = next(i for i, l in enumerate(lines) if l.startswith("## Contents"))
    headings = [(i, l.strip().lstrip("# ").strip())
                for i, l in enumerate(lines)
                if re.match(r"^## ", l) and i > ci and l.strip() != "## Contents"]

    out = []
    for idx, (i, cat) in enumerate(headings):
        ni = headings[idx + 1][0] if idx + 1 < len(headings) else len(lines)
        for l in lines[i:ni]:
            m = ITEM_RE.match(l.strip())
            if m:
                out.append({
                    "category": cat,
                    "name": m.group(1).strip(),
                    "url": m.group(2).strip(),
                    "desc": (m.group(3) or "").strip(),
                })
    return out


def repo_slug(url):
    """从 GitHub URL 提取 owner/repo"""
    m = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def grab(slug):
    """抓取一个仓库的 README，试 main / master / README.md / readme.md"""
    dst = os.path.join(RAW_DIR, slug.replace("/", "__") + ".md")
    if os.path.isfile(dst) and os.path.getsize(dst) > 0:
        return slug, "cached", 0

    for branch in ("main", "master"):
        for fname in ("README.md", "readme.md"):
            try:
                txt = fetch(f"https://raw.githubusercontent.com/{slug}/{branch}/{fname}")
                if len(txt) < 50:
                    continue
                os.makedirs(RAW_DIR, exist_ok=True)
                with open(dst, "w", encoding="utf-8") as f:
                    f.write(txt)
                return slug, branch, len(txt)
            except Exception:
                continue
    return slug, "fail", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse", action="store_true", help="仅解析顶层并统计")
    ap.add_argument("--limit", type=int, help="只抓前 N 个")
    ap.add_argument("--workers", type=int, default=24, help="并发数")
    ap.add_argument("--discovered", action="store_true",
                    help="抓 discover_awesome.py 发现的树外列表，而非顶层树")
    ap.add_argument("--discovered-file", default="discovered.json",
                    help="发现结果文件名（配合 --discovered）")
    args = ap.parse_args()

    if args.discovered:
        p = os.path.join(CACHE, args.discovered_file)
        if not os.path.isfile(p):
            print(f"[错误] 无发现结果：{p}\n请先运行 discover_awesome.py", file=sys.stderr)
            sys.exit(1)
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        slugs = [r["repo"] for r in d["repos"] if r.get("is_new")]
        print(f"树外待抓仓库 {len(slugs)} 个"
              f"（发现 {d['meta']['total_found']}，树内已有 "
              f"{d['meta']['already_in_tree']}）")
        if not args.parse:
            targets = slugs[: args.limit] if args.limit else slugs
            print(f"本次抓取 {len(targets)} 个，并发 {args.workers}\n")
            os.makedirs(RAW_DIR, exist_ok=True)
            ok = fail = cached = 0
            t0 = time.time()
            done = 0
            with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
                for slug, status, size in ex.map(grab, targets):
                    done += 1
                    if status == "fail":
                        fail += 1
                    elif status == "cached":
                        cached += 1
                    else:
                        ok += 1
                    if done % 100 == 0 or done == len(targets):
                        el = time.time() - t0
                        print(f"  进度 {done}/{len(targets)}  新抓 {ok} 缓存 {cached} "
                              f"失败 {fail}  用时 {el:.0f}s  "
                              f"预计剩余 {el/done*(len(targets)-done):.0f}s", flush=True)
            print(f"\n完成：新抓 {ok}，命中缓存 {cached}，失败 {fail}")
            print(f"原始数据：{RAW_DIR}")
            print(f"用时 {time.time()-t0:.0f}s")
        return

    top = parse_top()
    slugs = []
    seen = set()
    for it in top:
        s = repo_slug(it["url"])
        if s and s not in seen:
            seen.add(s)
            slugs.append(s)

    print(f"顶层条目 {len(top)} 条，去重后待抓仓库 {len(slugs)} 个")

    if args.parse:
        cats = {}
        for it in top:
            cats[it["category"]] = cats.get(it["category"], 0) + 1
        print("\n分类分布：")
        for k, v in sorted(cats.items(), key=lambda x: -x[1]):
            print(f"  {k:<38} {v}")
        return

    targets = slugs[: args.limit] if args.limit else slugs
    print(f"本次抓取 {len(targets)} 个，并发 {args.workers}\n")

    os.makedirs(RAW_DIR, exist_ok=True)
    ok = fail = cached = 0
    t0 = time.time()
    done = 0

    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for slug, status, size in ex.map(grab, targets):
            done += 1
            if status == "fail":
                fail += 1
            elif status == "cached":
                cached += 1
            else:
                ok += 1
            if done % 50 == 0 or done == len(targets):
                el = time.time() - t0
                print(f"  进度 {done}/{len(targets)}  新抓 {ok} 缓存 {cached} 失败 {fail}  "
                      f"用时 {el:.0f}s  预计剩余 {el/done*(len(targets)-done):.0f}s", flush=True)

    print(f"\n完成：新抓 {ok}，命中缓存 {cached}，失败 {fail}")
    print(f"原始数据：{RAW_DIR}")
    print(f"用时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
