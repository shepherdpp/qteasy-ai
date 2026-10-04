# qteasy-ai 0.2.0 发版清单

包号锁定 **0.2.0**。PyPI 上已有 0.1.0（Stage A）。David 不改版本号、不打标签、不上传 PyPI。

升版要改哪些文件、发布史怎么写，以 qteasy 仓 `.cursor/rules/10-working-versioning-semver.mdc` 的 qteasy-ai 节为准。

## 发版前仓库里必须已经有

- [USER_GUIDE.md](USER_GUIDE.md) 与 `docs/img/` 里的工作台截图
- [design/14-as-built-0.2.md](design/14-as-built-0.2.md)
- [RELEASE_HISTORY.md](RELEASE_HISTORY.md) 中的 0.1.0 短条
- 本清单

没有使用说明，不发 0.2.0。

## 1. 实弹

按 [LIVE_FIRE_DRILL_1.0.md](LIVE_FIRE_DRILL_1.0.md) 填写 [LIVE_FIRE_DRILL_1.0_RESULTS.md](LIVE_FIRE_DRILL_1.0_RESULTS.md)。

- Part A：全量 `test_ai_*.py`，以及 22 个技能、18 条知识库的命令行检查
- Part B：工作台手测
- 任一 FAIL 不打 `0.2.0`

## 2. 同时改这 6 个文件

路径相对 qteasy-ai 仓根：

1. `meta.yaml`：`package.version`、`source.git_rev` 写成 `0.2.0` / `v0.2.0`
2. `pyproject.toml`：`[project].version`
3. `qteasy_ai/__init__.py`：`__version__`
4. `README.md`：正文里的当前版本号，去掉「只是 Stage A」的说法
5. `docs/RELEASE_HISTORY.md`：把下面的中文草稿贴到文件最上方，日期用发版当天
6. `CHANGELOG.md`：把 Unreleased 里仍属于本版的条目收进 `## 0.2.0`，并补上下面的英文短条

不要改技能元数据里的 `version=`，不要改 `web/package.json`。

## 3. 发布史草稿

贴进 `docs/RELEASE_HISTORY.md` 时放在 0.1.0 之上。日期换成发版日。

```markdown
## 0.2.0 (YYYY-MM-DD)

相对 0.1.0，这是第一次带工作台的版本。

- **问答、计划与执行分开**。Ask 只回答问题；Plan 先给你看步骤；确认之后才会取数、回测或优化。没有配置模型也可以用。
- **工作台**。`qteasy-ai serve` 打开桌面三栏：对话、产物、当前任务。计划说明在产物里打开。可以停止一次运行，或让它在后台继续。
- **官方能力**。可以用自然语言完成环境检查、有界补数、读数与摘要、内置策略回测与优化、看懂上一次回测，以及按双均线模板起草策略。实盘只会生成计划，不会自动下单。
- **接着说**。同一会话里可以补上日期或标的，也可以改上一份计划。澄清时可以直接选，跳过则这一句结束。
- **模型**。可以在设置里保存多个 Provider 并切换。列表不会显示密钥。不配置模型时，问答走内置说明，计划按规则生成。
```

同一批要点的英文短条，贴进 `CHANGELOG.md`：

```markdown
## 0.2.0 (YYYY-MM-DD)

### Added

- Ask answers questions without running skills. Plan shows steps before anything runs. Confirm, then read data, backtest, or optimize. Works without a model.
- Desktop workbench (`qteasy-ai serve`): conversation, artifacts, and the current task. Stop a run, or leave it in the background.
- Official jobs for a bounded data check, a built-in backtest and optimization, a short read of the last backtest, and a dual-moving-average strategy draft. Live trade stays plan-only.
- Multi-turn sessions, clarification choices, and a provider pool that never prints raw API keys.
```

## 4. 发出去

- 提交并推送 qteasy-ai 的 `main`
- 标签 `v0.2.0`，GitHub Release
- 上传 PyPI
- 发版后把 qteasy 仓展望 §7.1 里 Q-AI.7 的关联版本写成已发布的 **0.2.0**
- 不要把 qteasy-ai 合并进 qteasy

发版之后的第一优先仍是把官方问答从入门问题扩开，版本从 0.2.0 往上堆，不再叫 0.1.x。
