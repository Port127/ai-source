# ai-source

`capability-forge` 技能的**外部知识库**。本仓库不包含任何代码逻辑，只存数据。

## 这是什么

capability-forge 是一个用于「创建/改造 WorkBuddy 技能与专家」的元工具。它做决策
时需要海量「别人怎么做」的参考案例。这些数据来自：

- [sindresorhus/awesome](https://github.com/sindresorhus/awesome) 整棵树（28 个顶层分类）
- GitHub 上树外的 awesome 系列表（按 star 分段搜索发现）
- GitHub 上的中文 awesome 列表（awesome-cn 等）

共 **345,198 条资源、1,767 个列表**。

## 为什么是独立仓库

技能包（capability-forge）要保持精简、可自动加载。345k 条数据（约 80MB）放进技能包
会撑爆上下文。所以数据外置到这里，技能**运行时按需下载**：

- 按领域 → 下载 `data/categories/<slug>.json`
- 按列表 → 下载 `data/lists/<id>.json`
- 路由总表 → `manifest.json`（技能先拉它，再只下载命中的 chunk）

下载后缓存在本地 `~/.cache/capability-forge/kb/`，重复查询不重复下载。

## 目录结构

```
ai-source/
├── manifest.json                 路由总表（category -> list 级信息 + 各文件相对路径）
├── data/
│   └── lists/<id>.json           每个列表一个文件（最细粒度，含 resources）
├── scripts/                       爬虫脚本，保证本仓库可复现
└── README.md
```

`manifest.json` 是技能运行时先拉取的路由表：它列出每个分类下有哪些列表、各列表的
`list_file` 相对路径与条数，但**不重复存储 resources**（resources 只在 `data/lists/` 里
各存一份）。技能据此只下载命中的列表文件。

## 如何更新数据

```bash
cd scripts
python3 crawl_awesome.py              # 抓 awesome 树
python3 discover_awesome.py           # 发现树外/中文列表
python3 crawl_awesome.py --discovered # 抓发现的列表
python3 build_resources.py            # 解析成 resources.json
python3 ../../capability-forge/scripts/prepare_repo.py   # 拆成本仓库布局
git add -A && git commit && git push
```

> 注意：不要提交 `~/.cache` 里的 `raw/*.md`（217MB 原始 README），本仓库只存解析后的 JSON。

## 版权

本仓库只收录**公开可索引的链接与标题/简短描述**，不复制原文内容。来源见各条目
`repo` / `url` 字段，版权归原作者所有。中文长文类（知乎等）请遵守对应平台许可，
本仓库仅作索引用途。
