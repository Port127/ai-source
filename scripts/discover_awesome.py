#!/usr/bin/env python3
"""发现 Awesome 树之外的垂直列表。

GitHub 搜索 API 单次最多返回 1000 条，故按 star 数分段查询以绕过上限；
搜索接口限流 10 次/分钟，请求间自动加延迟。

用法：
    python3 discover_awesome.py                     # 默认抓 >=300 stars
    python3 discover_awesome.py --min-stars 1000    # 只要高星
    python3 discover_awesome.py --dry-run           # 只报各段数量，不抓

输出：~/.cache/capability-forge/awesome/discovered.json
      字段含 is_new（是否在当前已爬的 674 个之外）
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

CACHE = os.path.expanduser("~/.cache/capability-forge/awesome")
OUT = os.path.join(CACHE, "discovered.json")
UA = {"User-Agent": "capability-forge", "Accept": "application/vnd.github+json"}

# 分段：避免单次查询超过 1000 条上限
SEGMENTS = [
    "stars:>20000", "stars:10000..20000", "stars:5000..9999",
    "stars:3000..4999", "stars:2000..2999", "stars:1000..1999",
    "stars:700..999", "stars:500..699", "stars:300..499",
    "stars:200..299", "stars:100..199", "stars:50..99",
]
MIN_STAR_OF = {
    "stars:>20000": 20000, "stars:10000..20000": 10000, "stars:5000..9999": 5000,
    "stars:3000..4999": 3000, "stars:2000..2999": 2000, "stars:1000..1999": 1000,
    "stars:700..999": 700, "stars:500..699": 500, "stars:300..499": 300,
    "stars:200..299": 200, "stars:100..199": 100, "stars:50..99": 50,
}


def api(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def existing_slugs():
    """已在 awesome 树里抓过的仓库，用于判断哪些是树外新增"""
    raw = os.path.join(CACHE, "raw")
    out = set()
    if os.path.isdir(raw):
        for fn in os.listdir(raw):
            if fn.endswith(".md"):
                out.add(fn[:-3].replace("__", "/").lower())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-stars", type=int, default=300, help="最低星数")
    ap.add_argument("--dry-run", action="store_true", help="只报各段数量")
    ap.add_argument("--query", help="自定义 GitHub 搜索查询，覆盖默认 star 分段")
    ap.add_argument("--max-pages", type=int, default=10, help="每个查询最多翻几页")
    ap.add_argument("--out", help="输出文件名（默认 discovered.json）")
    args = ap.parse_args()

    if args.query:
        segs = [args.query]
    else:
        segs = [s for s in SEGMENTS if MIN_STAR_OF[s] >= args.min_stars]
    if args.dry_run and args.query:
        d = api(f"https://api.github.com/search/repositories?q="
                f"{urllib.parse.quote(args.query)}&per_page=1")
        print(f"  命中 {d.get('total_count')} 个")
        return
    print(f"待查段 {len(segs)} 个（stars >= {args.min_stars}）")
    print("搜索接口限流 10 次/分钟，会自动限速\n")

    if args.dry_run:
        for s in segs:
            q = f"awesome in:name {s}"
            try:
                d = api(f"https://api.github.com/search/repositories?q="
                        f"{urllib.parse.quote(q)}&per_page=1")
                print(f"  {s:<20} {d.get('total_count')} 个")
            except Exception as e:
                print(f"  {s:<20} 查询失败 {e}")
            time.sleep(7)
        return

    have = existing_slugs()
    found = {}
    for seg in segs:
        q = seg if args.query else f"awesome in:name {seg}"
        page = 1
        while page <= args.max_pages:  # 搜索 API 最多 10 页
            try:
                d = api(f"https://api.github.com/search/repositories?q="
                        f"{urllib.parse.quote(q)}&per_page=100&page={page}&sort=stars")
            except Exception as e:
                print(f"  [{seg}] 第 {page} 页失败：{e}")
                break
            items = d.get("items", [])
            if not items:
                break
            for r in items:
                fn = r["full_name"]
                if fn.lower() in found:
                    continue
                found[fn.lower()] = {
                    "repo": fn,
                    "stars": r["stargazers_count"],
                    "desc": (r.get("description") or "")[:300],
                    "branch": r.get("default_branch") or "main",
                    "segment": seg,
                    "is_new": fn.lower() not in have,
                }
            print(f"  [{seg}] 第 {page} 页 +{len(items)}，累计 {len(found)}")
            if len(items) < 100:
                break
            page += 1
            time.sleep(7)  # 搜索限流 10 次/分钟
        time.sleep(7)

    os.makedirs(CACHE, exist_ok=True)
    new = [v for v in found.values() if v["is_new"]]
    out_path = os.path.join(CACHE, args.out) if args.out else OUT
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"meta": {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "min_stars": args.min_stars,
            "total_found": len(found),
            "already_in_tree": len(found) - len(new),
            "new_outside_tree": len(new),
        }, "repos": sorted(found.values(), key=lambda x: -x["stars"])}, f,
            ensure_ascii=False, indent=1)

    print(f"\n发现 {len(found)} 个 awesome 系仓库")
    print(f"  已在树内 {len(found)-len(new)} 个")
    print(f"  树外新增 {len(new)} 个  <- 这才是扩展量")
    print(f"\n写出 {out_path}")


if __name__ == "__main__":
    import urllib.parse
    main()
