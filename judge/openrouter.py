"""Shared OpenRouter client.

One provider for both transcription and scoring. OpenRouter exposes an
OpenAI-compatible `/chat/completions` endpoint, so the `openai` SDK works as a
drop-in client pointed at a different base URL.

Model choices are env-overridable so you can swap models on event day without
touching code.
"""

import json
import os
import re

from openai import (
    OpenAI,
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

BASE_URL = "https://openrouter.ai/api/v1"

# Text scoring — the judge. Overridable with OPENROUTER_SCORING_MODEL.
DEFAULT_SCORING_MODEL = "anthropic/claude-sonnet-5"

# Audio transcription. OpenRouter has no Whisper-style endpoint, so this must be
# a model that accepts audio input. Overridable with OPENROUTER_TRANSCRIPTION_MODEL.
DEFAULT_TRANSCRIPTION_MODEL = "google/gemini-3.7-flash"


class TruncatedResponse(ValueError):
    """The model hit its token ceiling before it finished the object.

    This is the failure that used to surface as a JSON syntax error somewhere in
    the middle of a document, because the parser was handed half a payload. It is
    worth retrying: reasoning token spend varies run to run, so the same request
    often completes on the next attempt.
    """


class UnparseableResponse(ValueError):
    """The model returned something that is not the JSON object we asked for."""


# Both subclass ValueError so callers that already treated a bad body as a value
# error keep working, and both are named so the retry layer and the error message
# can tell a budget problem from a formatting one.


# Transient failures worth retrying. OpenRouter routes to upstream providers, so
# 5xx from a busy provider is common and usually clears on the next attempt. A
# truncated or malformed body is retried for a different reason: it is a bad roll
# of the dice, not a bad request, and a re-roll usually lands.
RETRYABLE = (
    APITimeoutError,
    APIConnectionError,
    RateLimitError,
    InternalServerError,
    TruncatedResponse,
    UnparseableResponse,
)


def get_client(timeout: float = 90.0) -> OpenAI:
    """Build an OpenRouter-backed OpenAI client.

    Raises KeyError if OPENROUTER_API_KEY is unset — the server turns that into
    a readable "key not configured" message.
    """
    return OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=BASE_URL,
        timeout=timeout,
        default_headers={
            "HTTP-Referer": "https://sanviolabs.com",
            "X-OpenRouter-Title": "Virtual Judge",
        },
    )


def scoring_model() -> str:
    return os.environ.get("OPENROUTER_SCORING_MODEL") or DEFAULT_SCORING_MODEL


def transcription_model() -> str:
    return os.environ.get("OPENROUTER_TRANSCRIPTION_MODEL") or DEFAULT_TRANSCRIPTION_MODEL


def message_content(response, what: str = "response") -> str:
    """Pull the text out of a completion, refusing a truncated one.

    Reasoning models spend part of `max_tokens` on reasoning before they emit a
    single character of the answer, so a ceiling that looks generous against the
    finished document can still cut it off. When that happens the API says so in
    `finish_reason`, and it is the only honest signal available. Ignoring it and
    handing the fragment to a JSON parser turns a budget problem into a syntax
    error hundreds of lines from the actual cause.
    """
    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        used = getattr(getattr(response, "usage", None), "completion_tokens", None)
        detail = f" (used {used} completion tokens)" if used else ""
        raise TruncatedResponse(
            f"The model ran out of output budget while writing the {what}{detail}. "
            "Raise max_tokens for this call."
        )
    return choice.message.content or ""


def complete_json(client, model: str, messages: list, max_tokens: int,
                  what: str = "response", **kwargs) -> dict:
    """Run a chat completion that must come back as a JSON object.

    Every JSON-returning call in the judge goes through here so the truncation
    check and the parser stay in one place.
    """
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        **kwargs,
    )
    return extract_json(message_content(response, what))


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response.

    Handles bare JSON, ```json fences, bare ``` fences, and prose wrapped around
    a JSON object. Different models on OpenRouter format their output
    differently, so this has to be more forgiving than a single-provider parser.

    Forgiving does not mean silent. A payload that was cut off mid-document is
    reported as truncated rather than as a syntax error, because the two have
    completely different fixes.
    """
    if not text or not text.strip():
        raise ValueError("Model returned an empty response")

    text = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Prose before or after the object: decode the first complete value at the
    # opening brace and ignore whatever trails it.
    start = text.find("{")
    if start != -1:
        try:
            value, _ = json.JSONDecoder().raw_decode(text, start)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

        # Nothing complete parsed. If the braces do not balance, the body stops
        # partway through an object rather than being malformed, which means the
        # generation was cut off.
        if _unbalanced(text[start:]):
            raise TruncatedResponse(
                "The model stopped partway through the JSON object "
                f"({len(text) - start} characters, unbalanced braces). "
                "Raise max_tokens for this call."
            )

    raise UnparseableResponse(
        f"Could not parse JSON from model response: {text[:200]}"
    )


def _unbalanced(text: str) -> bool:
    """True if `text` opens more braces or brackets than it closes.

    Counts only outside of string literals, so a brace inside a quote does not
    move the tally.
    """
    depth = 0
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
    return in_string or depth > 0
