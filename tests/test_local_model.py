"""Local bridge safeguards without importing or downloading a model."""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import HTTPException

from jev_scout.local_model import (
    CompletionRequest,
    build_enum_token_trie,
    enum_prefix_callback,
    enum_schema_options,
    run_generation_exclusively,
    validate_enum_answer,
)


class CharacterTokenizer:
    """Synthetic tokenizer makes allowed JSON paths inspectable in a unit test."""

    eos_token_id = 999_999

    def __call__(self, texts, **kwargs):
        return {"input_ids": [[ord(character) for character in text] for text in texts]}


def schema_for(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def test_constrained_paths_preserve_json_boolean_types():
    schema = schema_for({"value": {"enum": [True, False, "unknown"]}})
    tokenizer = CharacterTokenizer()
    permitted = enum_prefix_callback(build_enum_token_trie(tokenizer, schema), prompt_length=2)
    for text in ('{"value":true}', '{"value":false}', '{"value":"unknown"}'):
        prefix = [101, 102]
        for character in text:
            assert ord(character) in permitted(0, prefix)
            prefix.append(ord(character))
        assert permitted(0, prefix) == [tokenizer.eos_token_id]
    # The exact invalid format observed in a real Qwen run is impossible here.
    prefix = [101, 102, *map(ord, '{"value":"')]
    assert ord("t") not in permitted(0, prefix)
    assert ord("f") not in permitted(0, prefix)


def test_typed_enum_validation_does_not_coerce_model_output():
    schema = schema_for({"value": {"enum": [True, False, "unknown"]}})
    validate_enum_answer('{"value":true}', schema)
    validate_enum_answer('{"value":"unknown"}', schema)
    for text in (
        '{"value":"true"}',
        '{"value":1}',
        '{"value":null}',
        '{"value":true,"extra":false}',
        '```json\n{"value":true}\n```',
    ):
        with pytest.raises(HTTPException) as caught:
            validate_enum_answer(text, schema)
        assert caught.value.status_code == 502


def test_decoding_handles_token_boundaries_without_assuming_single_json_tokens():
    class TwoCharacterTokenizer(CharacterTokenizer):
        vocabulary = {}

        def __call__(self, texts, **kwargs):
            sequences = []
            for text in texts:
                sequence = []
                for start in range(0, len(text), 2):
                    piece = text[start : start + 2]
                    sequence.append(self.vocabulary.setdefault(piece, len(self.vocabulary) + 1))
                sequences.append(sequence)
            return {"input_ids": sequences}

    tokenizer = TwoCharacterTokenizer()
    schema = schema_for({"value": {"enum": [True, False]}})
    trie = build_enum_token_trie(tokenizer, schema)
    allowed = enum_prefix_callback(trie, 0)
    encoded = tokenizer(['{"value":false}'])["input_ids"][0]
    for end, token in enumerate(encoded):
        assert token in allowed(0, encoded[:end])
    assert allowed(0, encoded) == [tokenizer.eos_token_id]


@pytest.mark.parametrize(
    "schema",
    [
        None,
        {"type": "object", "additionalProperties": True},
        {**schema_for({"value": {"enum": [True, False]}}), "maxProperties": 0},
        schema_for({"value": {"type": "string"}}),
        schema_for({"value": {"enum": []}}),
        schema_for({"value": {"enum": [float("nan")]}}),
        schema_for({"value": {"enum": [{"nested": "object"}]}}),
        schema_for({"value": {"type": "integer", "enum": [True]}}),
        schema_for({"value": {"enum": [True, True]}}),
        schema_for({"value": {"enum": ["x"], "pattern": "unsafe-unimplemented-constraint"}}),
        schema_for({f"field_{index}": {"enum": [0, 1, 2]} for index in range(10)}),
    ],
)
def test_unsupported_or_excessive_schema_fails_before_generation(schema):
    with pytest.raises(HTTPException) as caught:
        enum_schema_options(schema)
    assert caught.value.status_code == 422


def test_existing_scout_decision_schema_is_supported():
    from jev_scout.engine import _llm_request, split_sentences
    from jev_scout.fixtures import load_papers, load_profiles

    paper, profile = load_papers()[0], load_profiles()[0]
    request = _llm_request(
        paper, profile, split_sentences(paper["abstract"]), profile["preferences"], "test-model"
    )
    options = enum_schema_options(request["response_format"]["json_schema"]["schema"])
    assert options["relevance"] == [0, 1, 2, "unknown"]
    assert options["preference_1"] == [True, False, "unknown"]


@pytest.mark.asyncio
async def test_cancelled_http_request_holds_gpu_until_worker_finishes():
    lock = asyncio.Lock()
    entered = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    request = CompletionRequest(model="test", messages=[{"role": "user", "content": "test"}])

    def slow_generate(_body):
        loop.call_soon_threadsafe(entered.set)
        release.wait(timeout=3)
        return {"done": True}

    task = asyncio.create_task(run_generation_exclusively(lock, slow_generate, request))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # A second cancellation also cannot release GPU ownership.
        await asyncio.sleep(0)
        assert lock.locked()
        assert not task.done()
        with pytest.raises(HTTPException) as caught:
            await run_generation_exclusively(lock, lambda body: {}, request)
        assert caught.value.status_code == 429
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert not lock.locked()
        assert await run_generation_exclusively(lock, lambda body: {"next": True}, request) == {"next": True}
    finally:
        release.set()


@pytest.mark.asyncio
async def test_worker_failure_releases_gpu_lock():
    lock = asyncio.Lock()
    request = CompletionRequest(model="test", messages=[{"role": "user", "content": "test"}])

    def fail(_body):
        raise ValueError("Synthetic worker failure")

    with pytest.raises(ValueError, match="Synthetic worker"):
        await run_generation_exclusively(lock, fail, request)
    assert not lock.locked()
