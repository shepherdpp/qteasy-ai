# qteasy-ai 文档清单

给发版和以后改文档时用。用户只需要「用户向」这一列。

## 用户向

| 文档 | 谁读 | 0.2.0 |
|------|------|--------|
| [README.md](../README.md) | 安装前先看的介绍 | 版本句由 Jackie 升到 0.2.0 时改 |
| [docs/RELEASE_HISTORY.md](RELEASE_HISTORY.md) | 中文发布史，事实真源 | 已有 0.1.0 短条；0.2.0 正文在发版清单里，升版时贴上 |
| [CHANGELOG.md](../CHANGELOG.md) | 同一版的英文短条 | 与 RELEASE_HISTORY 同一批要点，升版时贴上 |
| [docs/USER_GUIDE.md](USER_GUIDE.md) | 基本使用，含工作台截图 | **发版必交** |
| [docs/tutorials/quickstart.md](tutorials/quickstart.md) | 命令行与 Notebook | 文首指向用户指南 |
| [docs/OFFICIAL_SKILL_CATALOG.md](OFFICIAL_SKILL_CATALOG.md) | 官方能力目录 | 「不进 0.2.0」已改口 |
| `examples/` | 可运行示例 | 保持现有演示脚本 |

[docs/WORKBENCH.md](WORKBENCH.md) 只保留启动命令，并指向用户指南的工作台一节。

## 维护者向

不放进给用户的阅读顺序。

- `docs/design/11`–`13`：阶段 A 历史备忘
- `docs/design/14-as-built-0.2.md`：0.2.0 实现总览
- `docs/design/15-ui-style.md`：已实现的界面风格
- `docs/KB_TIER1.md`：官方知识库篇目
- `docs/LIVE_FIRE_DRILL_*.md` 与 `docs/LIVE_FIRE_DRILL_1.0_RESULTS.md`：实弹
- `docs/MANUAL_TEST.md`、`docs/dev-context.md`：早期测试与开发备忘
- `docs/RELEASE_CHECKLIST.md`：Jackie 手工发版步骤

## 0.2.0 必交

用户指南和工作台截图必须在打 `v0.2.0` 之前就在仓库里。README 的版本句、RELEASE_HISTORY 与 CHANGELOG 的 0.2.0 正文由 Jackie 升版时写入。中文草稿和英文短条都在 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md)。
