# coding=utf-8
# ======================================
# File: run_ux_probe.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-29
# Desc:
# UX Probe CLI：跑画像×任务体验罗盘并写出人读报告。
# ======================================

"""CLI entry for the UX Probe compass (not a product Skill)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from evals.ux_probe.loader import DEFAULT_PRODUCT, PROBE_ROOT  # noqa: E402
from evals.ux_probe.runner import run_probe  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """构建参数解析器。"""

    parser = argparse.ArgumentParser(
        description=(
            "Run qteasy-ai UX Probe (persona × task). "
            "Improvement compass only — never a release gate."
        )
    )
    parser.add_argument(
        "--task",
        action="append",
        dest="tasks",
        default=None,
        help="Task id to run (repeatable). Default: all eligible tasks.",
    )
    parser.add_argument(
        "--product",
        default=DEFAULT_PRODUCT,
        help=f"Current product floor (default: {DEFAULT_PRODUCT}).",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip unattended judge; only write transcripts.",
    )
    parser.add_argument(
        "--root",
        default=str(PROBE_ROOT),
        help="YAML root (default: evals/ux_probe).",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output directory (default: evals/ux_probe/runs/<run_id>).",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional run id / directory name.",
    )
    return parser


def main(argv: list | None = None) -> int:
    """主入口。退出码：常 0；仅当加载失败等硬错误时非 0。红线低分不挡关。"""

    args = build_parser().parse_args(argv)
    try:
        payload = run_probe(
            root=Path(args.root),
            task_ids=args.tasks,
            current_product=str(args.product),
            judge=not bool(args.no_judge),
            out_dir=Path(args.out) if str(args.out or "").strip() else None,
            run_id=str(args.run_id or "").strip() or None,
        )
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"[ux_probe] FAILED: {exc}", file=sys.stderr)
        return 2
    paths = payload.get("paths") or {}
    print("[ux_probe] not a release gate; scores are guidance only.")
    print(f"[ux_probe] run_id={payload.get('run_id')}")
    print(f"[ux_probe] runs={len(payload.get('runs') or [])}")
    print(f"[ux_probe] skipped={len(payload.get('skipped') or [])}")
    for item in payload.get("skipped") or []:
        print(f"  skip {item.get('task_id')}: {item.get('reason')}")
    print(f"[ux_probe] markdown={paths.get('markdown')}")
    print(f"[ux_probe] json={paths.get('json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
