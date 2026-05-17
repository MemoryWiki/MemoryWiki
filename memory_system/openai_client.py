from __future__ import annotations

import json

from openai import OpenAI


class OpenAIChatClient:
    def __init__(
        self,
        api_key,
        base_url=None,
        timeout=30,
        max_retries=2,
        max_output_tokens=2048,
    ):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.max_output_tokens = max_output_tokens

    def chat(self, model, messages):
        response = self.client.responses.create(
            model=model,
            input=messages,
            max_output_tokens=self.max_output_tokens,
        )
        usage = getattr(response, "usage", None)
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", 0) or 0,
            "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }
        return response.output_text, usage_dict

    def compact_memory(self, model, prompt):
        response = self.client.responses.create(
            model=model,
            input=prompt,
            max_output_tokens=self.max_output_tokens,
            text={"format": {"type": "json_object"}},
        )
        return json.loads(response.output_text)
