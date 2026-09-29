from __future__ import annotations

import copy
import json
import os
from typing import Any

from groq import Groq

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_TIMEOUT_MS = 120_000


def get_api_key() -> str:
    try:
        import streamlit as st

        if "GROQ_API_KEY" in st.secrets:
            return str(st.secrets["GROQ_API_KEY"])
    except Exception:
        pass

    return os.environ.get("GROQ_API_KEY", "")


def get_client() -> Groq:
    key = get_api_key()

    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not configured. Add it to Streamlit Secrets "
            "or set it as an environment variable."
        )

    return Groq(
        api_key=key,
        timeout=GROQ_TIMEOUT_MS / 1000,
    )


def _make_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Convert our application JSON schema into the stricter schema
    requirements used by Groq Structured Outputs.

    Groq strict mode requires:
    - every object to have additionalProperties=false
    - every object property to be listed in required
    """
    result = copy.deepcopy(schema)

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return

        if node.get("type") == "object":
            properties = node.get("properties", {})

            if isinstance(properties, dict):
                node["additionalProperties"] = False
                node["required"] = list(properties.keys())

                for child in properties.values():
                    visit(child)

        if node.get("type") == "array":
            if "items" in node:
                visit(node["items"])

        for key in ("anyOf", "oneOf", "allOf"):
            values = node.get(key)
            if isinstance(values, list):
                for child in values:
                    visit(child)

    visit(result)
    return result


def structured_call(
    *,
    instructions: str,
    input_text: str,
    schema: dict[str, Any],
    schema_name: str,
    model: str = GROQ_MODEL,
) -> dict[str, Any]:

    client = get_client()

    strict_schema = _make_strict_schema(schema)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": instructions,
                },
                {
                    "role": "user",
                    "content": input_text,
                },
            ],
            reasoning_effort="low",

            max_completion_tokens=8192,

            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": strict_schema,
                },
            },
        )
    finally:
        client.close()

    text = (response.choices[0].message.content or "").strip()

    if not text:
        raise RuntimeError("Groq returned an empty response.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "Groq returned output that was not valid JSON. Please try again."
        ) from exc



