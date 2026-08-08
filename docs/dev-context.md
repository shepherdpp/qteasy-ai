# qteasy-ai 开发上下文

本文说明 **qteasy-ai 独立代码仓** 与 **qteasy 协作真源** 的关系（Session 0 建立）。

## 1. 为何独立成仓

- qteasy 主线聚焦 2.6.0+ 数据通道、模拟实盘、xtQuant 协作等
- AI 外壳迭代频率与发布节奏与内核不同，独立 semver 更灵活
- Stage A 代码原在 qteasy `qt_ai_dev` 分支，**永不 merge 进 qteasy master**

## 2. 计划与规范在哪里

| 内容 | 路径（相对并列目录 `~/Projects/`） |
| --- | --- |
| Cursor rules | `qteasy/.cursor/rules/` |
| Q-AI 剥离与执行 plan | `qteasy/.cursor/plans/s1.4_剥离_qteasy-ai_10ba0551.plan.md` |
| AI skills / execution plan | `qteasy/.cursor/plans/qteasy_ai_*.plan.md`、`s1.4a_*.plan.md` |
| master-plan §7 交叉索引 | `qteasy/.cursor/plans/量化工具对比与qteasy展望_f384dd4a.plan.md` |

本文件 **不重复** 上述 rules 全文；开发 qteasy-ai 时请在 Cursor 中打开 **multi-root 工作区**，使 qteasy 的 rules 对两仓生效。

## 3. 本地目录布局

```
~/Projects/
├── qteasy/                 # 内核（master = 2.6.0，无 qteasy/ai）
├── qteasy-ai/              # 本仓（Stage A 于 Session 2 迁入）
└── qteasy-ecosystem.code-workspace
```

## 4. Session 进度（摘录）

| Session | 内容 | 状态 |
| --- | --- | --- |
| 0 | 脚手架 + multi-root + git init | **已完成（2026-08-05）** |
| 1 | qteasy 文档（master-plan、ROADMAP、rules stub） | **已完成（2026-08-06）** |
| 2 | 自 `qt_ai_dev` 原样迁移 Stage A | **已完成（2026-08-06）** |
| 3 | qteasy RELEASE/README 补充 | **已完成（2026-08-06）** |
| 4 | 0.1.0 发布 + 人工测试金标准 | **已完成（2026-08-08）** — Jackie Mode-R smoke + 34 tests |

## 5. 迁移源码只读来源

```bash
# 在 qteasy 仓查看 Stage A 文件（勿 merge qt_ai_dev → master）
git -C ../qteasy show qt_ai_dev:qteasy/ai/app.py
```

完整文件列表见 Session 2 plan：`qteasy/.cursor/plans/s1.4_剥离_qteasy-ai_10ba0551.plan.md` §2.1。

## 6. Git commit 索引（2026-08-06）

| 仓库 | 分支 | Commit | 说明 | 远程 |
| --- | --- | --- | --- | --- |
| qteasy-ai | `main` | `8e8c0b2` | Session 0 脚手架 | 已 push |
| qteasy-ai | `main` | `a845cbb` | Session 2 Stage A 迁移 | 已 push |
| qteasy-ai | `main` | `35b2981` | Session 4 发布 0.1.0 | **待 push** |
| qteasy-ai | `main` | `9a5b274` | dev-context 交付记录 | **待 push** |
| qteasy | `docs/qteasy-ai-split` | `0539905` | Session 1 ROADMAP | **待 push** |
| qteasy | `docs/qteasy-ai-split` | `c52b897` | Session 3 用户向文档 | **待 push** |
| qteasy | `docs/qteasy-ai-split` | `02b693a` | ROADMAP Q-AI 进度记录 | **待 push** |

## 7. Jackie 人工测试入口

- 简明清单：本仓 [`docs/MANUAL_TEST.md`](MANUAL_TEST.md)
- 完整语料：qteasy `.cursor/plans/s1.4a人工测试金标准_6d66df64.plan.md`
- 记录模板：`tests/ai_corpus/manual_record_template.md`
- 语料批跑：`python tests/run_ai_manual_corpus.py`（需 `pip install -e .` 或设置 PYTHONPATH）
