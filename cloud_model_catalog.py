"""Discover stable models within approved families; publish only after probes.

Uses dedicated CI keys from environment. Never reads Keychain or athlete data.
--check is offline. --live writes a candidate artifact, never pushes or deploys.
Failures keep the input catalog unchanged and exit nonzero. Do not print HTTP
response bodies: even synthetic probes must not leak keys/provider diagnostics.
"""
import argparse
import copy
import datetime
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

PROVIDERS = {
    "claude": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", r"claude-opus-(\d+(?:-\d+)?)"),
    "grok": ("https://api.x.ai/v1", "XAI_API_KEY", r"grok-(\d+(?:\.\d+)?)"),
    "openAI": ("https://api.openai.com/v1", "OPENAI_API_KEY", r"gpt-(\d+(?:\.\d+)?)(?:-(?:astra|sol))?"),
}
MARKER = "FORGE_MODEL_OK"
# Synthetic opaque white pixel, not a user image.
PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8X8AAAAASUVORK5CYII="


def version(provider, model):
    match = re.fullmatch(PROVIDERS[provider][2], model)
    return tuple(int(x) for x in re.split(r"[.-]", match[1])) if match else None


def created(record):
    value = record.get("created", record.get("created_at"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0


def candidates(provider, records, current, updated_at=""):
    if version(provider, current) is None:
        raise ValueError("Current model is outside the approved family")
    floor = next((created(x) for x in records if x.get("id") == current), 0)
    if floor <= 0:
        floor = created({"created_at": updated_at})
    if floor <= 0:
        raise ValueError("Cannot establish model recency")
    # Release timestamps, not lexical/numeric version order: Grok 4.20 preceded 4.6.
    eligible = [x for x in records if version(provider, x.get("id", "")) is not None
                and x["id"] != current and floor < created(x) <= time.time()]
    return list(dict.fromkeys(x["id"] for x in sorted(eligible, key=lambda x: (created(x), x["id"]), reverse=True)))[:3]


def validate(catalog):
    if catalog.get("schemaVersion") != 2:
        raise ValueError("Unsupported catalog schema")
    for provider, prefix in [("claude", "claude-"), ("grok", "grok-"), ("openAI", "gpt-")]:
        item = catalog[provider]
        ids = [item["primary"]] + item.get("fallbacks", [])
        if not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
            raise ValueError("Invalid fallback ladder")
        if not all(isinstance(x, str) and x.startswith(prefix) and len(x) <= 128
                   and re.fullmatch(r"[a-z0-9._-]+", x) for x in ids):
            raise ValueError("Invalid model ID")


def headers(provider, key):
    result = {"Content-Type": "application/json"}
    if provider == "claude":
        result.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        result["Authorization"] = "Bearer " + key
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        raise ValueError("Provider redirect refused")


def open_request(provider, key, path, body=None):
    endpoint = PROVIDERS[provider][0] + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(endpoint, data=data, headers=headers(provider, key))
    return urllib.request.build_opener(NoRedirect()).open(req, timeout=20)


def discover(provider, key):
    ids = []
    path = "/models?limit=100" if provider == "claude" else "/models"
    for _ in range(10):
        with open_request(provider, key, path) as response:
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("Model list too large")
            page = json.loads(raw)
        ids.extend(page["data"])
        if not page.get("has_more"):
            return ids
        if provider != "claude" or not page.get("last_id"):
            raise ValueError("Unsupported pagination")
        path = "/models?limit=100&after_id=" + urllib.parse.quote(page["last_id"], safe="")
    raise ValueError("Incomplete model list")


def probe_body(provider, model, stream, photo):
    prompt = "Reply with exactly " + MARKER
    if photo:
        prompt = "Name the color in this image. Reply with exactly WHITE."
    if provider == "claude":
        content = prompt if not photo else [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PIXEL}},
            {"type": "text", "text": prompt},
        ]
        return {"model": model, "system": "Follow the user's response format.",
                "messages": [{"role": "user", "content": content}], "max_tokens": 768 if stream else 512,
                "thinking": {"type": "disabled"}, "output_config": {"effort": "low"}, "stream": stream}
    content = prompt if not photo else [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + PIXEL}},
    ]
    body = {"model": model, "messages": [{"role": "system", "content": "Follow the user's response format."},
             {"role": "user", "content": content}], "stream": stream, "reasoning_effort": "low"}
    body["max_completion_tokens" if provider == "openAI" else "max_tokens"] = 4096 if provider == "openAI" else (768 if stream else 512)
    return body


def probe(provider, key, model, stream, photo):
    started = time.monotonic()
    path = "/messages" if provider == "claude" else "/chat/completions"
    with open_request(provider, key, path, probe_body(provider, model, stream, photo)) as response:
        if stream:
            text, ended, count = "", False, 0
            while True:
                line = response.readline(16_385)
                if not line:
                    break
                count += len(line)
                if len(line) > 16_384 or count > 131_072 or time.monotonic() - started > 30:
                    raise ValueError("Stream budget exceeded")
                if not line.startswith(b"data: "):
                    continue
                payload = line[6:].strip()
                if payload == b"[DONE]":
                    ended = True
                    break
                event = json.loads(payload)
                if provider == "claude":
                    text += event.get("delta", {}).get("text", "")
                    ended |= event.get("type") == "message_stop"
                    if event.get("type") == "error":
                        raise ValueError("Stream error")
                else:
                    for choice in event.get("choices", []):
                        text += choice.get("delta", {}).get("content") or ""
            if not ended:
                raise ValueError("Truncated stream")
        else:
            raw = response.read(131_073)
            if len(raw) > 131_072:
                raise ValueError("Response budget exceeded")
            result = json.loads(raw)
            if provider == "claude":
                text = "".join(x.get("text", "") for x in result["content"] if x.get("type") == "text")
                if result.get("stop_reason") != "end_turn":
                    raise ValueError("Incomplete response")
            else:
                choice = result["choices"][0]
                text = choice["message"]["content"]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("Incomplete response")
    if text.strip() != ("WHITE" if photo else MARKER) or time.monotonic() - started > 30:
        raise ValueError("Compatibility probe failed")


def update(catalog, keys, list_models=discover, check=probe):
    validate(catalog)
    updated = copy.deepcopy(catalog)
    for provider in PROVIDERS:
        current = catalog[provider]["primary"]
        options = candidates(provider, list_models(provider, keys[provider]), current, catalog["updatedAt"])
        # Verify the current model too. An outage must not publish an untested artifact.
        selected = None
        for model in options + [current]:
            try:
                for stream in [False, True]:
                    for photo in [False, True]:
                        check(provider, keys[provider], model, stream, photo)
                selected = model
                break
            except (ValueError, KeyError, TypeError, OSError):
                continue
        if selected is None:
            raise ValueError("No verified model for " + provider)
        if selected != current:
            old = [current] + catalog[provider].get("fallbacks", [])
            updated[provider] = {"primary": selected, "fallbacks": list(dict.fromkeys(old))[:3]}
    if updated != catalog:
        updated["updatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    validate(updated)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    validate(catalog)
    if not args.live:
        print("Catalog schema valid. No live API checks performed.")
        return
    if not args.output or args.output.resolve() == args.catalog.resolve():
        raise ValueError("Use a separate output artifact")
    keys = {p: os.environ.get(config[1], "") for p, config in PROVIDERS.items()}
    if not all(keys.values()):
        raise ValueError("Dedicated CI provider keys are required")
    result = update(catalog, keys)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Verified catalog artifact written. No deployment performed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        # Intentionally omit error str/body: HTTP errors can include credentials.
        raise SystemExit("Catalog check failed (" + type(error).__name__ + "). Existing catalog retained.")
