# coding=utf-8
# ======================================
# File: identity.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-12
# Desc:
# 出厂身份 Kairos 与 user_kb/rules/identity.md 按槽叠合。
# 内核底线由代码附在系统提示末尾。
# ======================================

"""助手身份：出厂 Kairos，用户文件按槽覆盖，底线始终附在最后。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_NAME = "Kairos"
IDENTITY_FILENAME = "identity.md"
VOICE_CHAR_CAP = 400

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_NAME_PATTERNS = (
    re.compile(r"把你的名字(?:改成|换成|叫做)\s*(?P<name>[^\s，,。！？!?吗吧啊呢]{1,32})"),
    re.compile(r"你的名字(?:改成|换成|是)\s*(?P<name>[^\s，,。！？!?吗吧啊呢]{1,32})"),
    re.compile(r"把你叫做\s*(?P<name>[^\s，,。！？!?吗吧啊呢]{1,32})"),
    re.compile(r"以后叫你\s*(?P<name>[^\s，,。！？!?吗吧啊呢]{1,32})"),
    re.compile(r"(?:以后|接下来)?你(?:以后)?叫\s*(?P<name>[^\s，,。！？!?吗吧啊呢]{1,32})"),
    re.compile(r"(?i)\bcall yourself\s+(?P<name>[A-Za-z][\w\-]{0,31})"),
    re.compile(r"(?i)\byour name is\s+(?P<name>[A-Za-z][\w\-]{0,31})"),
)
_RESTORE_RE = re.compile(
    r"^(?:请)?(?:"
    r"恢复默认|恢复出厂(?:称呼和语气)?|"
    r"还是叫\s*kairos|"
    r"忘掉我(?:给你)?改的称呼|忘掉我给你起的名字"
    r")[。！？!?\s]*$",
    re.IGNORECASE,
)
_FLOOR_ONLY_RE = re.compile(
    r"^(?:请)?(?:不要确认|不用确认|你自己算收益|笔记可以改执行|直接实盘)[。！？!?\s]*$"
)
_REJECTED_NAMES = frozenset({"什么", "谁", "啥", "what", "who", "which"})
_FLOOR_MARKERS = (
    "不要确认",
    "不用确认",
    "你自己算收益",
    "直接实盘",
    "笔记可以改执行",
    "skip confirmation",
    "calculate returns yourself",
)
_VOICE_CUES = ("说话", "语气", "个性", "说话方式")
_VOICE_QUESTIONS = ("什么", "啥", "如何", "怎么")

_DEFAULT_VOICE = """语气：
- 精确但不冷：数字、run_id、版本照实说；短句。
- 先说下一句能确认的事，再说原因。
- 不知道就说不知道；不能做就说不能，并给一个可执行的下一步。
- 高风险先给人看差异；缺字段就问，不拿最近模板顶上。
- 出图、确认、算收益都不在你手里。
- 建议能指回来源（手册、笔记、某次 run）。笔记和内核冲突时站内核，并说出来。
- 不夸「好问题」，不说「放心没问题」，不说「这个策略会赚」。
- 一次只说当前任务需要的话。

样例：
- 用户要跑回测：先确认标的、策略、区间。确认后再跑。
- 用户问上次的收益：没有「上次」的参照。请给 run_id，或列出最近的 runs 给用户选。
- 用户要求直接实盘：实盘不自动执行。可以整理实盘计划，执行需要用户明示确认。

不要说：我算了收益是…；我已经帮你跑了…；根据我的经验会赚…。"""

_FLOOR = """这些规则始终有效，盖过上面的语气：
- 数字由 qteasy 计算。
- 高风险步骤等人确认后再执行。
- 没执行过的事不说已经执行。
- 笔记里的收益不是 metrics。
- 实盘不自动执行。
- 用户笔记不改内核语义，不改执行图。"""

_REFUSAL_BY_MARKER = (
    ("直接实盘", "实盘仍要你确认。"),
    ("不要确认", "高风险步骤仍要你确认。"),
    ("不用确认", "高风险步骤仍要你确认。"),
    ("你自己算收益", "数字由 qteasy 计算。"),
    ("笔记可以改执行", "用户笔记不改执行图。"),
    ("skip confirmation", "高风险步骤仍要你确认。"),
    ("calculate returns yourself", "数字由 qteasy 计算。"),
)


@dataclass(frozen=True)
class IdentityUtterance:
    """一句明确的身份要求。"""

    action: str
    name: str = ""
    voice: str = ""
    confirm_text: str = ""
    refusal: str = ""


def identity_file(user_kb_dir: Path) -> Path:
    """用户身份文件路径。

    Parameters
    ----------
    user_kb_dir : Path
        ``user_kb`` 根目录。

    Returns
    -------
    Path
        ``rules/identity.md``。
    """

    return Path(user_kb_dir) / "rules" / IDENTITY_FILENAME


def parse_identity_document(text: str) -> Tuple[str, str]:
    """从身份文件取出名字和语气。缺 front matter 时整篇当语气。

    Parameters
    ----------
    text : str
        文件正文。

    Returns
    -------
    tuple of str
        ``(name, voice)``。空字符串表示该槽未设置。
    """

    raw = str(text or "").lstrip("\ufeff")
    match = _FRONT_MATTER_RE.match(raw)
    if match is None:
        return "", _clip_voice(strip_floor_clauses(raw))
    name = ""
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("name:"):
            name = stripped.split(":", 1)[1].strip().strip("\"'")
            break
    voice = _clip_voice(strip_floor_clauses(match.group(2)))
    return name.strip(), voice


def load_identity_slots(user_kb_dir: Optional[Path]) -> Tuple[str, str]:
    """读取用户身份槽。文件不存在或读失败时两个槽都空。

    Parameters
    ----------
    user_kb_dir : Path or None
        ``user_kb`` 根目录。

    Returns
    -------
    tuple of str
        ``(name, voice)``。
    """

    if user_kb_dir is None:
        return "", ""
    path = identity_file(Path(user_kb_dir))
    if not path.is_file():
        return "", ""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    return parse_identity_document(text)


def render_identity_markdown(name: str, voice: str) -> str:
    """写成带 front matter 的身份文件。

    Parameters
    ----------
    name : str
        名字槽。可空。
    voice : str
        语气正文。可空。底线句会被去掉。

    Returns
    -------
    str
        文件正文。
    """

    kept_name = str(name or "").strip()
    kept_voice = _clip_voice(strip_floor_clauses(voice))
    lines = ["---"]
    if kept_name:
        lines.append("name: " + _yaml_scalar(kept_name))
    lines.append("---")
    lines.append("")
    if kept_voice:
        lines.append(kept_voice)
        lines.append("")
    return "\n".join(lines)


def write_identity_file(user_kb_dir: Path, *, name: str, voice: str) -> Path:
    """写入 ``rules/identity.md``。

    Parameters
    ----------
    user_kb_dir : Path
        ``user_kb`` 根目录。
    name : str
        名字槽。
    voice : str
        语气正文。

    Returns
    -------
    Path
        写入的文件。
    """

    path = identity_file(user_kb_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_identity_markdown(name, voice), encoding="utf-8")
    return path


def remove_identity_file(user_kb_dir: Path) -> None:
    """删除用户身份文件。不存在时保持原样。

    Parameters
    ----------
    user_kb_dir : Path
        ``user_kb`` 根目录。

    Returns
    -------
    None
    """

    path = identity_file(user_kb_dir)
    if path.is_file():
        path.unlink()


def strip_floor_clauses(text: str) -> str:
    """丢掉含底线抵触句的句子。

    Parameters
    ----------
    text : str
        用户原文或文件正文。

    Returns
    -------
    str
        去掉抵触句后的文本。
    """

    kept: List[str] = []
    for sentence in _split_sentences(str(text or "")):
        lowered = sentence.lower()
        if any(marker.lower() in lowered for marker in _FLOOR_MARKERS):
            continue
        kept.append(sentence.strip())
    return "".join(kept).strip(" \n，,")


def resolved_identity_prefix(user_kb_dir: Optional[Path] = None) -> str:
    """出厂身份叠上用户槽，底线附在最后。

    Parameters
    ----------
    user_kb_dir : Path or None
        ``user_kb`` 根目录。缺省或文件不存在时用出厂身份。

    Returns
    -------
    str
        系统提示前缀。
    """

    custom_name, custom_voice = load_identity_slots(user_kb_dir)
    name = custom_name or DEFAULT_NAME
    voice = custom_voice or _DEFAULT_VOICE
    return _intro(name) + "\n\n" + voice.strip() + "\n\n" + _FLOOR


def prefix_system_prompt(system_prompt: str, user_kb_dir: Optional[Path] = None) -> str:
    """在既有系统提示前接身份前缀。

    Parameters
    ----------
    system_prompt : str
        原系统提示。
    user_kb_dir : Path or None
        ``user_kb`` 根目录。

    Returns
    -------
    str
        带身份前缀的系统提示。
    """

    prefix = resolved_identity_prefix(user_kb_dir)
    base = str(system_prompt or "").strip()
    if not base:
        return prefix
    return prefix + "\n\n" + base


def parse_identity_utterance(text: str) -> Optional[IdentityUtterance]:
    """判断这句话是否在改助手自己的名字或语气。

    判断不中返回 None。整句只要求越过底线时 ``action='refuse'``。

    Parameters
    ----------
    text : str
        用户原句。

    Returns
    -------
    IdentityUtterance or None
        恢复、改槽，或拒绝写入。
    """

    raw = " ".join(str(text or "").split())
    if not raw:
        return None
    if _RESTORE_RE.match(raw):
        return IdentityUtterance(
            action="restore",
            confirm_text="恢复出厂称呼和语气。",
        )
    if _FLOOR_ONLY_RE.match(raw):
        return IdentityUtterance(action="refuse", refusal=_refusal_for(raw))

    name, name_span = _extract_name(raw)
    remainder = raw
    if name_span is not None:
        remainder = (raw[: name_span[0]] + raw[name_span[1] :]).strip(" ，,。！？!?")
    voice = ""
    if _is_voice_request(raw) or _is_voice_request(remainder):
        voice = _clip_voice(strip_floor_clauses(remainder or raw))
        if name and voice == raw:
            voice = _clip_voice(strip_floor_clauses(remainder))
    if not name and not voice:
        if any(marker.lower() in raw.lower() for marker in _FLOOR_MARKERS) and (
            _is_voice_request(raw) or name_span is not None
        ):
            return IdentityUtterance(action="refuse", refusal=_refusal_for(raw))
        return None
    lines: List[str] = []
    if name:
        lines.append(f"记下名字：{name}。")
    if voice:
        lines.append(f"记下语气：{voice}")
    return IdentityUtterance(
        action="set",
        name=name,
        voice=voice,
        confirm_text="\n".join(lines),
    )


def _intro(name: str) -> str:
    """称谓段。只有 Kairos 保留希腊语词源句。"""

    who = (
        f"你是 {name}，qteasy-ai 里的研究搭档，软件。数字由 qteasy 算。"
        "被问到是不是软件时如实承认。不要主动说「作为 AI 语言模型」。"
    )
    if name == DEFAULT_NAME:
        gloss = (
            "Kairos 是希腊语里「该动手的那一刻」。"
            "它把你想研究的事写成 qteasy 能执行的计划，执行前让你看清将发生什么。"
        )
    else:
        gloss = ""
    role = (
        f"{name} 把「我想研究什么」写成 qteasy 能确定性执行的计划，"
        "执行前让你看清风险。你确认，qteasy 计算。"
    )
    parts = [who]
    if gloss:
        parts.append(gloss)
    parts.append(role)
    return "\n".join(parts)


def _extract_name(text: str) -> Tuple[str, Optional[Tuple[int, int]]]:
    """抽出助手的新名字。问句里的「什么」不算名字。"""

    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        name = str(match.group("name") or "").strip()
        if name.lower() in _REJECTED_NAMES:
            continue
        return name, match.span()
    return "", None


def _is_voice_request(text: str) -> bool:
    """这句话是在改说话方式，而不是在问语气是什么。"""

    body = str(text or "")
    if not any(cue in body for cue in _VOICE_CUES):
        return False
    if any(token in body for token in _VOICE_QUESTIONS):
        return False
    return True


def _split_sentences(text: str) -> List[str]:
    """按句号、逗号和换行切开，保留分隔符在句尾。"""

    parts = re.split(r"(?<=[。！？\n，,])", str(text or ""))
    return [part for part in parts if part.strip()]


def _clip_voice(text: str) -> str:
    """语气正文截到上限。"""

    body = str(text or "").strip()
    if len(body) <= VOICE_CHAR_CAP:
        return body
    return body[:VOICE_CHAR_CAP].rstrip()


def _refusal_for(text: str) -> str:
    """按句中的底线要求给出拒绝句。"""

    lowered = str(text or "").lower()
    lines: List[str] = []
    for marker, line in _REFUSAL_BY_MARKER:
        if marker.lower() in lowered and line not in lines:
            lines.append(line)
    if not lines:
        return "高风险步骤仍要你确认。数字由 qteasy 计算。"
    return "".join(lines)


def _yaml_scalar(value: str) -> str:
    """名字含特殊字符时加引号。"""

    if re.search(r"[:#\n\"']", value):
        return '"' + value.replace('"', '\\"') + '"'
    return value
