# UX Probe（体验罗盘）

开发侧虚拟用户测试：**改进指引书**，不是升版 / M1 / unittest 关单。

- 真源：`personas.yaml`、`tasks/`、`rubrics.yaml`
- CLI：`../scripts/run_ux_probe.py`（从仓库根目录调用 `scripts/run_ux_probe.py`）
- Cursor Skill：qteasy 仓 `.cursor/skills/qteasy-ai-ux-probe/SKILL.md`
- Decision：`knowledge/decisions/qteasy-ai-ux-probe.md`

```bash
cd /Users/jackie/Projects/qteasy-ai
/opt/anaconda3/envs/py39/bin/python scripts/run_ux_probe.py --task ask_onboarding_v1
```

报告默认写到 `runs/<run_id>/`（gitignore）。禁止注册 `qt.ai.ux_probe.*`。
