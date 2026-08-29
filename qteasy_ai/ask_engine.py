# coding=utf-8
# ======================================
# File: ask_engine.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# qteasy-ai Ask 目标态引擎：LLMClient +
# KnowledgeBase，不调用 skill / Executor。
# ======================================

"""Ask 目标态问答引擎。

只依赖 KnowledgeBase 与可选 LLM Provider。不生成可执行 ToolPlan step，
不调用 PlanExecutor，不调用 SkillRegistry handler。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .knowledge_base import KbEntry, KnowledgeBase
from .provider import BaseLLMProvider

_PLAN_LIKE_HINTS = (
    "list built-in",
    "list builtin",
    "list built in",
    "列出所有内置",
    "列出内置策略",
    "download ",
    "refill ",
    "backtest",
    "optimize",
    "export kline",
    "screen stock",
    "筛股",
    "下载",
    "回测",
    "优化",
)

_ASK_SYSTEM_PROMPT = (
    "You are a qteasy expert. Answer ONLY using the provided knowledge snippets. "
    "Reply in the same language as the user's Question "
    "(Chinese question → Chinese answer; English question → English answer). "
    "Keep qteasy identifiers, skill names, and code unchanged. "
    "If the snippets are insufficient, say so and suggest Plan mode."
)


@dataclass
class AskResponse:
    """Ask 目标态结构化响应（不含可执行 plan）。

    Parameters
    ----------
    mode : str
        恒为 ``ask``，保证模式可见。
    ok : bool
        是否成功从 KnowledgeBase 给出答案。
    answer : str
        面向用户的答案。有 Provider 时跟随问句语言；Offline 为英文 KB 模板。
    sources : list of str
        命中的 KB 条目 id。
    narrative : str
        解释层叙事（与 answer 对齐，供 explanation_template 裁剪）。
    python_code : str
        可复现示例代码。
    result_preview : str
        来源与摘要预览。
    raw : dict
        机器可读载荷（命中条目、检索上下文）。
    error : dict, optional
        ``{code, message}``；用户可见 message 为英文。
    """

    mode: str = "ask"
    ok: bool = True
    answer: str = ""
    sources: List[str] = field(default_factory=list)
    narrative: str = ""
    python_code: str = ""
    result_preview: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转为不含 execution / 非空 steps 的字典。"""

        payload: Dict[str, Any] = {
            "mode": self.mode,
            "ok": self.ok,
            "answer": self.answer,
            "sources": list(self.sources),
            "narrative": self.narrative,
            "python_code": self.python_code,
            "result_preview": self.result_preview,
            "raw": dict(self.raw),
            "error": self.error,
        }
        return payload


class AskEngine:
    """Ask 目标态编排：检索 KB，Offline 模板或 LLM 合成。

    Parameters
    ----------
    knowledge_base : KnowledgeBase
        策展知识库。
    provider : BaseLLMProvider, optional
        可选 LLM；缺省走 Offline 模板答案。
    """

    def __init__(
        self,
        *,
        knowledge_base: Optional[KnowledgeBase] = None,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.knowledge_base = knowledge_base or KnowledgeBase()
        self.provider = provider

    def ask(self, query: str, *, explanation_depth: str = "standard") -> AskResponse:
        """回答用户问题，不走 plan / skill。

        Parameters
        ----------
        query : str
            自然语言问题。
        explanation_depth : {'brief', 'standard', 'deep'}, default 'standard'
            解释层深度；C1 先生成完整通道，深度裁剪由 explanation_template 负责。

        Returns
        -------
        AskResponse
            模式为 ask 的结构化答案。
        """

        text = (query or "").strip()
        depth = explanation_depth if explanation_depth in {"brief", "standard", "deep"} else "standard"
        if self._is_plan_like(text):
            return self._plan_suggested(query=text, depth=depth)

        hits = self.knowledge_base.retrieve(text)
        if not hits:
            return self._not_found(query=text, depth=depth)

        sources = [item.id for item in hits]
        if self.provider is not None:
            answer = self._ask_llm(query=text, hits=hits)
        else:
            answer = self._offline_answer(hits)
        return self._pack(
            query=text,
            answer=answer,
            hits=hits,
            sources=sources,
            depth=depth,
            ok=True,
            error=None,
        )

    @staticmethod
    def _is_plan_like(query: str) -> bool:
        """判断是否为应走 Plan/preview 的执行型请求。"""

        q_lower = query.lower()
        return any(hint in q_lower for hint in _PLAN_LIKE_HINTS)

    def _plan_suggested(self, *, query: str, depth: str) -> AskResponse:
        """执行型请求：提示改用 Plan，不生成 steps。"""

        answer = (
            "This looks like an executable request (list/download/backtest/optimize/export). "
            "Ask mode does not call skills or PlanExecutor. "
            "Use Plan or preview to review a ToolPlan, then confirm before run."
        )
        return self._pack(
            query=query,
            answer=answer,
            hits=[],
            sources=["ask_plan_agent"],
            depth=depth,
            ok=True,
            error=None,
            extra_raw={"suggest": "plan_or_preview"},
        )

    def _not_found(self, *, query: str, depth: str) -> AskResponse:
        """KB 未命中：英文 not_found，建议 Plan，不调用 LLM。"""

        answer = (
            "No matching qteasy knowledge snippet was found for this question. "
            "Ask will not invent an answer from an empty knowledge base. "
            "If you want to list strategies, download data, backtest, or optimize, "
            "use Plan or preview instead of Ask."
        )
        error = {
            "code": "NOT_FOUND",
            "message": "No matching knowledge snippet. Try Plan mode for executable requests.",
        }
        return self._pack(
            query=query,
            answer=answer,
            hits=[],
            sources=[],
            depth=depth,
            ok=False,
            error=error,
        )

    def _ask_llm(self, *, query: str, hits: List[KbEntry]) -> str:
        """将检索片段注入 prompt 后调用 Provider。"""

        snippets = []
        for item in hits:
            snippets.append(
                f"[{item.id}] {item.title}\n{item.narrative}\npython:\n{item.python_code}"
            )
        prompt = (
            f"Question: {query}\n\n"
            "Knowledge snippets:\n"
            + "\n\n".join(snippets)
            + "\n\nWrite a concise answer in the same language as the Question, "
            "grounded in the snippets."
        )
        return str(self.provider.chat(prompt, system_prompt=_ASK_SYSTEM_PROMPT)).strip()

    @staticmethod
    def _offline_answer(hits: List[KbEntry]) -> str:
        """无 Provider 时拼接 KB narrative。"""

        parts = [item.narrative.strip() for item in hits if item.narrative.strip()]
        return "\n\n".join(parts)

    def _pack(
        self,
        *,
        query: str,
        answer: str,
        hits: List[KbEntry],
        sources: List[str],
        depth: str,
        ok: bool,
        error: Optional[Dict[str, Any]],
        extra_raw: Optional[Dict[str, Any]] = None,
    ) -> AskResponse:
        """组装 AskResponse；深度裁剪委托 explanation_template。"""

        python_code = next((item.python_code for item in hits if item.python_code), "")
        risk_notes = "\n".join(item.risk_notes for item in hits if item.risk_notes)
        raw: Dict[str, Any] = {
            "query": query,
            "hits": [item.to_dict() for item in hits],
            "explanation_depth": depth,
            "provider_enabled": self.provider is not None,
        }
        if extra_raw:
            raw.update(extra_raw)
        from .explanation import apply_explanation_depth

        rendered = apply_explanation_depth(
            narrative=answer,
            python_code=python_code,
            result_preview=f"sources={sources}" if sources else "No knowledge sources.",
            depth=depth,
            risk_notes=risk_notes,
        )
        return AskResponse(
            mode="ask",
            ok=ok,
            answer=rendered.narrative,
            sources=list(sources),
            narrative=rendered.narrative,
            python_code=rendered.python_code,
            result_preview=rendered.result_preview,
            raw=raw,
            error=error,
        )
