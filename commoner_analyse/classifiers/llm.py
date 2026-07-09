from __future__ import annotations

import json
import re
import time
from typing import Any

from .. import llm_client
from .base import BaseClassifier, ClassifyResult


class LLMClassifier(BaseClassifier):
    name = "llm"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        tag_definitions: dict[str, str],
        system_prompt: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
        allow_private: bool = True,
        client: Any | None = None,
    ):
        if not tag_definitions:
            raise ValueError("llm classifier requires non-empty tag_definitions")
        self.endpoint = endpoint
        self.model = model
        self.tag_definitions = tag_definitions
        self.system_prompt = system_prompt or "Tag Indian parliamentary questions against the provided taxonomy."
        self.api_key = api_key or "local"
        self.temperature = float(temperature)
        self.timeout_s = float(timeout_s)
        # Default True to preserve the zero-config local-Ollama path; set
        # False (or "allow_private": false in the topic profile's
        # classifier block) to reject loopback/private/link-local hosts.
        self.allow_private = allow_private
        self.client = client

    def warmup(self) -> None:
        return None

    def classify(self, *parts: str | None, **ctx: object) -> ClassifyResult:
        start = time.perf_counter()
        text = " ".join(part for part in parts if part).strip()
        if not text:
            return ClassifyResult(tags=[], classifier=self.name, model=self.model)
        self.warmup()
        prompt = {
            "task": "Return JSON only. Choose zero or more tag keys that apply to the text.",
            "tag_definitions": self.tag_definitions,
            "text": text,
            "schema": {
                "tags": ["tag_key"],
                "confidence": {"tag_key": 0.0},
                "reasoning": "brief explanation",
            },
        }
        try:
            if self.client is not None:
                response = self.client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                )
                content = response.choices[0].message.content or "{}"
            else:
                payload = {
                    "model": self.model,
                    "temperature": self.temperature,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                }
                content = llm_client.llm_http_post(
                    self.endpoint,
                    payload,
                    timeout_s=self.timeout_s,
                    api_key=self.api_key,
                    allow_private=self.allow_private,
                )
            try:
                parsed = llm_client.parse_llm_json(content)
            except Exception as exc:  # noqa: BLE001
                tags = _fallback_tags(content, self.tag_definitions)
                return ClassifyResult(
                    tags=tags,
                    matches={tag: 1.0 for tag in tags},
                    score=float(len(tags)),
                    explain=f"LLM returned non-JSON output: {exc}",
                    classifier=self.name,
                    model=self.model,
                    elapsed_ms=(time.perf_counter() - start) * 1000,
                )
            allowed = set(self.tag_definitions)
            tags = [tag for tag in parsed.get("tags", []) if tag in allowed]
            confidence = parsed.get("confidence") or {}
            matches = {tag: float(confidence.get(tag, 1.0)) for tag in tags}
            return ClassifyResult(
                tags=tags,
                matches=matches,
                score=sum(matches.values()),
                explain=parsed.get("reasoning"),
                classifier=self.name,
                model=self.model,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            tags = _fallback_tags(str(exc), self.tag_definitions)
            return ClassifyResult(
                tags=tags,
                matches={tag: 1.0 for tag in tags},
                score=float(len(tags)),
                explain=f"LLM classification failed: {exc}",
                classifier=self.name,
                model=self.model,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )


def _fallback_tags(content: str, tag_definitions: dict[str, str]) -> list[str]:
    found = []
    for tag in tag_definitions:
        if re.search(rf"\b{re.escape(tag)}\b", content):
            found.append(tag)
    return found
