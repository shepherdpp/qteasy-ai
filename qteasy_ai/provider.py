# coding=utf-8
# ======================================
# File: provider.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳模型适配层，提供统一
# Provider 抽象及 OpenAI-compatible 实现。
# ======================================

"""LLM Provider 抽象与 OpenAI 兼容实现。

本模块的目标不是“实现某个模型能力”，而是提供可替换的模型接入接口。

设计目标
--------
- 统一上层调用方式（`chat()`）；
- 降低对特定厂商 SDK 的绑定；
- 允许通过环境变量快速切换模型接入点。

阶段A说明
---------
阶段A中 Planner 仍以规则路由为主，Provider 主要用于打通工程能力和接口契约，
为后续“规则 + LLM 混合规划”做铺垫。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .config import DEFAULT_PROVIDER_TIMEOUT, ConfigCenter


class BaseLLMProvider(ABC):
    """LLM Provider 抽象基类。

    所有具体 Provider 都应实现统一 `chat()` 接口，保证上层（Planner/App）
    不需要知道底层厂商差异。
    """

    @abstractmethod
    def chat(self, prompt: str, *, system_prompt: str = "") -> str:
        """返回模型文本回复。

        Parameters
        ----------
        prompt : str
            用户提示词。
        system_prompt : str, optional
            系统级提示词。

        Returns
        -------
        str
            模型返回文本。
        """


class FakeLLMProvider(BaseLLMProvider):
    """测试用 Provider：按队列返回罐头文本，并记录 prompt。

    不发起网络请求。供 Ask 与 Hybrid Planner 的 unittest 注入。

    Parameters
    ----------
    replies : list of str, optional
        按调用顺序弹出的回复；队列为空时返回带 prompt 摘要的占位文本。
    """

    def __init__(self, replies: Optional[List[str]] = None) -> None:
        self.replies: List[str] = list(replies or [])
        self.prompts: List[str] = []
        self.system_prompts: List[str] = []

    def chat(self, prompt: str, *, system_prompt: str = "") -> str:
        """记录 prompt 并返回下一条罐头回复。"""

        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        if self.replies:
            return self.replies.pop(0)
        return f"[fake-llm] {prompt[:240]}"


class OpenAICompatProvider(BaseLLMProvider):
    """OpenAI 兼容接口 Provider。

    兼容范围
    --------
    只要服务端遵循 OpenAI `chat/completions` 协议（或兼容代理），
    都可通过该 Provider 接入。
    """

    def __init__(
        self,
        *,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_PROVIDER_TIMEOUT,
        config_center: Optional[ConfigCenter] = None,
    ) -> None:
        cfg = config_center or ConfigCenter()
        resolved = cfg.resolve_provider_config(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )
        self.model = str(resolved.get("model", "")).strip()
        self.api_key = str(resolved.get("api_key", "")).strip()
        self.base_url = str(resolved.get("base_url", "https://api.openai.com/v1")).strip()
        self.timeout = int(resolved.get("timeout", DEFAULT_PROVIDER_TIMEOUT))

    def chat(self, prompt: str, *, system_prompt: str = "") -> str:
        """调用 chat/completions 并返回文本结果。

        Parameters
        ----------
        prompt : str
            用户输入文本。
        system_prompt : str, optional
            系统提示词。

        Returns
        -------
        str
            第一条候选消息的文本内容。

        Raises
        ------
        ValueError
            API key 缺失。
        RuntimeError
            HTTP/网络/返回结构异常。
        """

        if not self.api_key:
            raise ValueError("Missing API key for OpenAI-compatible provider.")
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "temperature": 0.1,
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].append({"role": "user", "content": prompt})
        url = self.base_url.rstrip("/") + "/chat/completions"
        request = urllib.request.Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                response_payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 读取响应体有助于上层快速定位配置/权限/配额问题。
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Provider HTTP error: {exc.code} {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Provider connection failed: {exc.reason}") from exc

        choices = response_payload.get("choices", [])
        if not choices:
            raise RuntimeError("Provider returned no choices.")
        # 约定取第一条候选，后续可扩展 n-best 或打分策略。
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if not isinstance(content, str):
            raise RuntimeError("Provider response content is not string.")
        return content.strip()
