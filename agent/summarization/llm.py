from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol

from openai import OpenAI


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class LLMResponse:
    payload: dict[str, Any]
    usage: LLMUsage


class LLMClient(Protocol):
    def complete_json(self, task: str, payload: dict[str, Any]) -> LLMResponse:
        ...


class PulseCostExceeded(Exception):
    """Raised when an LLM budget is exceeded."""


class MockLLMClient:
    def complete_json(self, task: str, payload: dict[str, Any]) -> LLMResponse:
        serialized = json.dumps(payload, sort_keys=True)
        usage = LLMUsage(
            input_tokens=max(10, len(serialized) // 4),
            output_tokens=120,
            cost_usd=0.0,
        )
        return LLMResponse(payload={"task": task, "ok": True}, usage=usage)


class GroqLLMClient:
    def __init__(self, model: str, api_key: str | None = None) -> None:
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set")
        self._model = model
        self._client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)

    def complete_json(self, task: str, payload: dict[str, Any]) -> LLMResponse:
        completion = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a product insights assistant. "
                        "Return strictly valid JSON object only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"task": task, "payload": payload}, ensure_ascii=False),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        content = completion.choices[0].message.content or "{}"
        usage = completion.usage
        input_tokens = int(usage.prompt_tokens if usage else 0)
        output_tokens = int(usage.completion_tokens if usage else 0)
        # Groq API currently does not always return direct USD cost.
        return LLMResponse(
            payload=json.loads(content),
            usage=LLMUsage(input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=0.0),
        )


class BudgetedLLM:
    def __init__(
        self,
        client: LLMClient,
        *,
        max_retries: int,
        timeout_seconds: int,
        token_cap: int,
        cost_cap_usd: float,
    ) -> None:
        self.client = client
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.token_cap = token_cap
        self.cost_cap_usd = cost_cap_usd
        self.total_tokens = 0
        self.total_cost = 0.0

    def call_json(self, task: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            started = time.time()
            try:
                response = self.client.complete_json(task=task, payload=payload)
                elapsed = time.time() - started
                if elapsed > self.timeout_seconds:
                    raise TimeoutError(f"LLM timeout exceeded for task={task}")
                self.total_tokens += response.usage.total_tokens
                self.total_cost += response.usage.cost_usd
                if self.total_tokens > self.token_cap or self.total_cost > self.cost_cap_usd:
                    raise PulseCostExceeded(
                        f"Budget exceeded tokens={self.total_tokens} cost={self.total_cost:.4f}"
                    )
                return response.payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                time.sleep(0.05)
        assert last_error is not None
        raise last_error
