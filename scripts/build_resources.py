#!/usr/bin/env python3
"""把抓取到的 Awesome 树解析成结构化 JSON（英文单份）。

输入：~/.cache/capability-forge/awesome/raw/*.md（由 crawl_awesome.py 抓取）
输出：~/.cache/capability-forge/awesome/resources.json   完整数据（约 24MB，不进包）
      references/resources/index.json                    索引（约 96KB，进包）

只保留英文一份：资源名与描述本就是英文原文，分类/小节名保留英文可避免
翻译失真，且省去维护双语对照表的成本。

用法：
    python3 build_resources.py            # 解析并输出
    python3 build_resources.py --stats    # 只看统计，不写文件
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

CACHE = os.path.expanduser("~/.cache/capability-forge/awesome")
RAW_DIR = os.path.join(CACHE, "raw")
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "references", "resources")

# 严格版：顶层 awesome 用它（格式规范，只有 `- [`）
ITEM_RE = re.compile(r"^- \[([^\]]+)\]\((https?://[^)\s]+)\)\s*(?:[-–—:]\s*(.*))?$")

# 宽泛版：二级仓库用它。实测存在 * 列表、1. 有序列表、缩进嵌套三种变体，
# 中文列表还常用全角冒号「：」作描述分隔符（awesome-python-cn 931 行只解析出 7 条就是栽在这），
# 只用严格版会漏掉约三分之一的文件（条目数 65k → 106k）。
ITEM_LOOSE_RE = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])\s+\[([^\]]+)\]\((https?://[^)\s]+)\)\s*(?:[-–—:：]\s*(.*))?$"
)

# 引用式链接：`- [Name] - desc`，URL 在文末以 `[Name]: https://...` 定义。
# 实测 awesome-video-production 全文 141 条里有 132 条是这种写法，
# 不支持就会整份漏掉（漏解析率 100%）。
ITEM_REF_RE = re.compile(
    r"^\s*(?:[-*+]|\d+[.)])\s+\[([^\]]+)\]\s*(?:[-–—:：]\s*(.*))?$"
)
REF_DEF_RE = re.compile(r"^\s*\[([^\]]+)\]:\s*(\S+)\s*$")
HEAD_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")


def clean_text(s):
    """清理 markdown 残留：粗体、行内链接、反引号"""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = s.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def parse_top():
    """解析顶层 readme，返回 slug -> {category, name, desc}"""
    lines = open(os.path.join(CACHE, "top.md"), encoding="utf-8").read().split("\n")
    ci = next(i for i, l in enumerate(lines) if l.startswith("## Contents"))
    heads = [(i, l.strip().lstrip("# ").strip())
             for i, l in enumerate(lines)
             if re.match(r"^## ", l) and i > ci and l.strip() != "## Contents"]
    out = {}
    for idx, (i, cat) in enumerate(heads):
        ni = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        for l in lines[i:ni]:
            m = ITEM_RE.match(l.strip())
            if not m:
                continue
            g = re.match(r"https?://github\.com/([^/]+)/([^/#?]+)", m.group(2))
            if not g:
                continue
            slug = f"{g.group(1)}/{g.group(2)}"
            if slug not in out:
                out[slug] = {"category": cat, "name": m.group(1).strip(),
                             "desc": (m.group(3) or "").strip()}
    return out


def parse_repo(path, slug):
    """解析单个仓库 README，返回资源条目列表"""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return []
    lines = text.split("\n")

    # 引用式链接定义表（全文扫，定义可能在条目之前或之后）
    refdefs = {}
    for l in lines:
        d = REF_DEF_RE.match(l)
        if d:
            refdefs[d.group(1).strip().lower()] = d.group(2).strip()

    # 从第一个非 Contents 的 ## 标题之后开始收条目
    start = 0
    for i, l in enumerate(lines):
        if re.match(r"^##\s+", l) and "contents" not in l.lower():
            start = i
            break

    resources = []
    cur_sec = ""
    seen = set()
    for l in lines[start:]:
        h = HEAD_RE.match(l)
        if h and len(h.group(1)) >= 2:
            cur_sec = h.group(2).strip()
            continue

        s = l.rstrip()
        m = ITEM_LOOSE_RE.match(s)
        if m:
            name, url, desc = clean_text(m.group(1)), m.group(2).strip(), m.group(3) or ""
        else:
            # 退而求其次：引用式链接，URL 去定义表里查
            m2 = ITEM_REF_RE.match(s)
            if not m2:
                continue
            name = clean_text(m2.group(1))
            url = refdefs.get(name.lower(), "")
            desc = m2.group(2) or ""

        if not name:
            continue
        key = (name.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        resources.append({
            "name": name,
            "url": url,
            "desc": clean_text(desc),
            "section": cur_sec,
            "repo": slug,
        })
    return resources


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(RAW_DIR):
        print("[错误] 无原始数据，请先运行 crawl_awesome.py", file=sys.stderr)
        sys.exit(1)

    top = parse_top()

    # 树外列表（discover_awesome.py 发现的）不在顶层 readme 里，
    # 没有顶层分类，单独归到 Discovered 并带上 star 数。
    # discovered_cn.json 是中文源，单独分类便于按需取用。
    disc = {}
    for fn in ("discovered.json", "discovered_cn.json"):
        p = os.path.join(CACHE, fn)
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            for r in json.load(f)["repos"]:
                r["_cn"] = fn == "discovered_cn.json"
                disc[r["repo"].lower()] = r

    files = sorted(f for f in os.listdir(RAW_DIR) if f.endswith(".md"))

    by_cat = {}
    total = empty = 0
    from_tree = outside = 0
    for fn in files:
        slug = fn[:-3].replace("__", "/")
        if slug in top:
            t = top[slug]
            meta = {"category": t["category"], "name": t["name"], "desc": t["desc"]}
            from_tree += 1
        else:
            dr = disc.get(slug.lower())
            meta = {
                "category": "Discovered (CN)" if (dr or {}).get("_cn") else "Discovered",
                "name": (dr["repo"].split("/")[-1] if dr else slug.split("/")[-1]),
                "desc": (dr or {}).get("desc", ""),
                "stars": (dr or {}).get("stars"),
            }
            outside += 1
        res = parse_repo(os.path.join(RAW_DIR, fn), slug)
        if not res:
            empty += 1
            continue
        by_cat.setdefault(meta["category"], []).append({
            "repo": slug,
            "name": meta["name"],
            "desc": meta["desc"],
            "count": len(res),
            "resources": res,
        })
        total += len(res)

    print(f"仓库文件 {len(files)} 个，其中解析为空 {empty} 个")
    print(f"  来自 awesome 树 {from_tree} 个，树外发现 {outside} 个")
    print(f"资源条目合计 {total} 条")

    if args.stats:
        print("\n顶层分类分布：")
        for c, lst in sorted(by_cat.items(), key=lambda x: -sum(i["count"] for i in x[1])):
            print(f"  {c:<38} 列表 {len(lst):>3} 个，资源 {sum(i['count'] for i in lst):>6} 条")
        secs = Counter()
        for lst in by_cat.values():
            for r in lst:
                for x in r["resources"]:
                    if x["section"]:
                        secs[x["section"]] += 1
        print(f"\n唯一小节名 {len(secs)} 个，前 12：")
        for k, v in secs.most_common(12):
            print(f"  {k[:44]:<46} {v}")
        return

    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    cats = []
    for cat, lst in sorted(by_cat.items(), key=lambda x: -sum(i["count"] for i in x[1])):
        cats.append({
            "category": cat,
            "list_count": len(lst),
            "resource_count": sum(i["count"] for i in lst),
            "lists": [
                {"repo": r["repo"], "name": r["name"], "desc": r["desc"],
                 "count": r["count"], "resources": r["resources"]}
                for r in lst
            ],
        })

    full = {
        "meta": {
            "source": "https://github.com/sindresorhus/awesome",
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_resources": total,
            "total_lists": sum(len(v) for v in by_cat.values()),
            "total_categories": len(by_cat),
            "note": "Names and descriptions kept in original language (mostly proper nouns).",
        },
        "categories": cats,
    }
    p = os.path.join(CACHE, "resources.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False)
    print(f"完整数据 {p}  {os.path.getsize(p)/1024/1024:.1f} MB")

    index = {
        "meta": {
            "source": "https://github.com/sindresorhus/awesome",
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_resources": total,
            "total_lists": sum(len(v) for v in by_cat.values()),
            "total_categories": len(by_cat),
            "full_data": p,
            "usage": "本文件只有索引。取具体条目用 scripts/search_resources.py",
        },
        "categories": [
            {**c, "lists": [{"repo": r["repo"], "name": r["name"],
                             "desc": r["desc"], "count": r["count"]}
                            for r in c["lists"]]}
            for c in cats
        ],
    }
    p = os.path.join(OUT_DIR, "index.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"索引     {p}  {os.path.getsize(p)/1024:.0f} KB")

    print(f"\n资源条目 {total} 条，列表 {sum(len(v) for v in by_cat.values())} 个，"
          f"分类 {len(by_cat)} 个")


if __name__ == "__main__":
    main()
