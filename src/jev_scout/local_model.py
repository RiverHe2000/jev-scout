"""Optional loopback-only OpenAI-compatible bridge for an existing local model.

This is a small, single-user inference service, not a production model server.
The finite-enum decision schema is enforced during decoding, and the application
independently validates every response. Unsupported schemas are rejected.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import lru_cache
from itertools import product
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=100000)


class CompletionRequest(BaseModel):
    model: str
    messages: list[Message] = Field(min_length=1, max_length=20)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=700, ge=1, le=1600)
    stream: bool = False
    response_format: dict | None = None


def enum_schema_options(schema: dict) -> dict[str, list]:
    """Validate the bounded JSON-schema subset used by the decision adapter.

    Each required object property must have a finite list of primitive choices.
    A typed serialization distinguishes JSON true from 1 and from "true".
    """
    if isinstance(schema, dict) and set(schema) - {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "title",
        "description",
    }:
        raise HTTPException(422, "This local bridge does not support additional schema constraints.")
    if (
        not isinstance(schema, dict)
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
    ):
        raise HTTPException(
            422, "Local structured decoding requires an object schema with no additional properties."
        )
    properties, required = schema.get("properties"), schema.get("required")
    if not isinstance(properties, dict) or not 1 <= len(properties) <= 12:
        raise HTTPException(422, "Local structured decoding requires 1 to 12 enum properties.")
    if (
        not isinstance(required, list)
        or not all(isinstance(key, str) for key in required)
        or len(required) != len(set(required))
        or set(required) != set(properties)
    ):
        raise HTTPException(422, "All structured decision properties must be required exactly once.")
    options = {}
    for key, specification in properties.items():
        if not isinstance(key, str) or not 1 <= len(key) <= 80 or not isinstance(specification, dict):
            raise HTTPException(422, "Invalid structured decision property.")
        if set(specification) - {"enum", "type", "description", "title"}:
            raise HTTPException(422, "This local bridge supports enum properties only.")
        choices = specification.get("enum")
        if not isinstance(choices, list) or not 1 <= len(choices) <= 128:
            raise HTTPException(422, "Structured decision choices must be a bounded, nonempty enum.")
        serialized = []
        for choice in choices:
            if (
                type(choice) not in (str, bool, int, float, type(None))
                or isinstance(choice, str)
                and len(choice) > 1000
            ):
                raise HTTPException(422, "Structured decision enums accept bounded primitive values only.")
            if isinstance(choice, float) and not math.isfinite(choice):
                raise HTTPException(422, "Structured decision enums cannot contain nonfinite numbers.")
            declared_type = specification.get("type")
            correct_type = {
                "string": type(choice) is str,
                "boolean": type(choice) is bool,
                "integer": type(choice) is int,
                "number": type(choice) in (int, float),
                "null": choice is None,
            }
            if declared_type is not None and (
                not isinstance(declared_type, str) or not correct_type.get(declared_type, False)
            ):
                raise HTTPException(422, "An enum choice conflicts with its declared JSON type.")
            serialized.append(json.dumps(choice, ensure_ascii=False, allow_nan=False))
        if len(serialized) != len(set(serialized)):
            raise HTTPException(422, "Structured decision enum choices must be unique.")
        options[key] = choices
    if math.prod(len(choices) for choices in options.values()) > 50000:
        raise HTTPException(422, "The requested structured decision space is too large for the local bridge.")
    return options


def build_enum_token_trie(tokenizer, schema: dict) -> dict:
    """Encode every permitted small decision, then share all common prefixes.

    This uses actual tokenizer boundaries instead of assuming that a boolean or
    JSON delimiter is one token. The trie is cached per schema by the service.
    """
    options = enum_schema_options(schema)
    eos = tokenizer.eos_token_id
    if type(eos) is not int:
        raise HTTPException(422, "This local tokenizer does not expose a supported end-of-sequence token.")
    texts = []
    characters = 0
    for values in product(*options.values()):
        text = json.dumps(
            dict(zip(options, values, strict=True)),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        characters += len(text)
        if characters > 8_000_000:
            raise HTTPException(422, "The requested structured decoding table is too large.")
        texts.append(text)
    root: dict = {}
    # Chunk tokenization to avoid allocating an unbounded padded tensor/table.
    for start in range(0, len(texts), 256):
        encoded = tokenizer(texts[start : start + 256], add_special_tokens=False)["input_ids"]
        for tokens in encoded:
            node = root
            for token in [*tokens, eos]:
                node = node.setdefault(int(token), {})
    return root


def enum_prefix_callback(trie: dict, prompt_length: int) -> Callable:
    def permitted(_batch_id, input_ids):
        node = trie
        suffix = input_ids[prompt_length:]
        if hasattr(suffix, "tolist"):
            suffix = suffix.tolist()
        for token in suffix:
            node = node.get(int(token))
            if node is None:
                raise RuntimeError("Local generation left the permitted structured-output prefix.")
        if not node:
            raise RuntimeError("Local generation continued beyond the structured-output terminator.")
        return list(node)

    return permitted


def validate_enum_answer(text: str, schema: dict) -> None:
    """A second, strict check after decoding; never repair or coerce an answer."""
    options = enum_schema_options(schema)
    try:
        answer = json.loads(text)
        if not isinstance(answer, dict) or set(answer) != set(options):
            raise ValueError("Unexpected decision fields")
        for key, choices in options.items():
            encoded = json.dumps(answer[key], ensure_ascii=False, allow_nan=False)
            if encoded not in {json.dumps(choice, ensure_ascii=False, allow_nan=False) for choice in choices}:
                raise ValueError("Invalid typed enum choice")
    except (TypeError, ValueError) as error:
        raise HTTPException(502, "The local model did not produce a valid structured decision.") from error


async def run_generation_exclusively(lock: asyncio.Lock, generate: Callable, body: CompletionRequest) -> dict:
    """Keep GPU ownership after client cancellation until its thread has ended."""
    if lock.locked():
        raise HTTPException(
            429,
            "Local GPU is busy. Retry after the current decision completes.",
            headers={"Retry-After": "5"},
        )
    async with lock:
        task = asyncio.create_task(asyncio.to_thread(generate, body))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Cancelling the HTTP coroutine cannot stop a running CUDA call.
            # Repeated cancellation must not unlock the GPU prematurely either.
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()  # Consume a background error before propagating cancellation.
            raise


def create_local_app(model_path: Path, model_name: str = "qwen3-4b") -> FastAPI:
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not model_path.is_dir():
            raise RuntimeError("Local model directory does not exist.")
        if not torch.cuda.is_available():
            raise RuntimeError(
                "The local showcase bridge requires a CUDA GPU. Use a compatible model API on other machines."
            )
        app.state.tokenizer = AutoTokenizer.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False
        )
        app.state.model = AutoModelForCausalLM.from_pretrained(
            model_path,
            local_files_only=True,
            trust_remote_code=False,
            dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
            device_map="cuda",
            attn_implementation="sdpa",
        ).eval()
        yield
        del app.state.model
        torch.cuda.empty_cache()

    app = FastAPI(title="Jev Scout local inference", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_requests(request: Request, call_next):
        if request.headers.get("origin") or request.headers.get("sec-fetch-site") == "cross-site":
            from fastapi.responses import JSONResponse

            return JSONResponse(
                {"detail": "Local inference accepts server-to-server requests only."}, status_code=403
            )
        return await call_next(request)

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "model": model_name,
            "device": "cuda",
            "json_schema_enforcement": "constrained finite-enum decoding and independent caller validation",
        }

    @app.get("/v1/models")
    def models():
        return {"object": "list", "data": [{"id": model_name, "object": "model", "owned_by": "local"}]}

    @lru_cache(maxsize=8)
    def constraint_for_schema(schema_json: str) -> dict:
        return build_enum_token_trie(app.state.tokenizer, json.loads(schema_json))

    def generate(body: CompletionRequest) -> dict:
        import torch

        messages = [message.model_dump() for message in body.messages]
        schema = None
        if body.response_format:
            schema_block = body.response_format.get("json_schema")
            if body.response_format.get("type") != "json_schema" or not isinstance(schema_block, dict):
                raise HTTPException(422, "The local bridge supports only the finite-enum json_schema format.")
            schema = schema_block.get("schema")
            enum_schema_options(schema)
            instruction = (
                "Return only a valid JSON object. No markdown fences, no explanation, no extra fields."
            )
            instruction += (
                ' Use unquoted JSON booleans true and false, and quote the string "unknown". Match this JSON schema: '
                + json.dumps(schema, ensure_ascii=False)
            )
            if messages[0]["role"] == "system":
                messages[0]["content"] += "\n\n" + instruction
            else:
                messages.insert(0, {"role": "system", "content": instruction})
        tokenizer = app.state.tokenizer
        prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(app.state.model.device)
        input_tokens = inputs.input_ids.shape[-1]
        if input_tokens > 12000:
            raise HTTPException(413, "Local model input exceeds 12,000 tokens.")
        constraints = {}
        if schema is not None:
            trie = constraint_for_schema(json.dumps(schema, ensure_ascii=False))
            constraints["prefix_allowed_tokens_fn"] = enum_prefix_callback(trie, input_tokens)
        with torch.inference_mode():
            outputs = app.state.model.generate(
                **inputs,
                max_new_tokens=body.max_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
                eos_token_id=tokenizer.eos_token_id,
                **constraints,
            )
        generated = outputs[0, input_tokens:]
        text = tokenizer.decode(generated, skip_special_tokens=True).strip()
        output_tokens = len(generated)
        if schema is not None:
            validate_enum_answer(text, schema)
        return {
            "id": "local-" + str(uuid4()),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop"
                    if len(generated) and int(generated[-1]) == tokenizer.eos_token_id
                    else "length",
                }
            ],
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        }

    @app.post("/v1/chat/completions")
    async def complete(body: CompletionRequest):
        if body.model != model_name:
            raise HTTPException(404, "Requested local model is not loaded.")
        if body.stream:
            raise HTTPException(422, "This local decision bridge does not stream responses.")
        try:
            return await run_generation_exclusively(lock, generate, body)
        except torch_oom_type():
            raise HTTPException(
                503, "Local GPU memory is full. Close other GPU workloads and retry."
            ) from None

    return app


def torch_oom_type():
    import torch

    return torch.cuda.OutOfMemoryError


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Serve an existing local Qwen model for Jev Scout.")
    parser.add_argument("--model-path", type=Path, default=os.environ.get("JEV_SCOUT_LOCAL_MODEL_PATH"))
    parser.add_argument("--model-name", default="qwen3-4b")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not args.model_path:
        parser.error("Set --model-path to an existing local model directory.")
    uvicorn.run(
        create_local_app(Path(args.model_path).resolve(), args.model_name),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
