"""Weekly keyless updates from official public model documentation.
No provider APIs, inference calls, environment credentials, or athlete data.
Documentary evidence is NOT live API compatibility verification.
"""
import argparse
import copy
import datetime
import hashlib
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

SOURCES = {
    "openAI": "https://developers.openai.com/api/docs/models.md",
    "claude": "https://platform.claude.com/docs/en/models/overview.md",
    "grok": "https://docs.x.ai/developers/models.md",
}
PREFIXES = {"openAI": "gpt-", "claude": "claude-", "grok": "grok-"}
STABILITY_DAYS = 6  # Second weekly observation; manual reruns cannot promote.


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def timestamp(value):
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate(catalog):
    if catalog.get("schemaVersion") != 2:
        raise ValueError("unsupported_schema")
    timestamp(catalog["updatedAt"])
    for provider, prefix in PREFIXES.items():
        item = catalog[provider]
        ids = [item["primary"]] + item.get("fallbacks", [])
        if not 1 <= len(ids) <= 4 or len(set(ids)) != len(ids):
            raise ValueError("invalid_ladder")
        if not all(isinstance(x, str) and x.startswith(prefix) and len(x) <= 128
                   and re.fullmatch(r"[a-z0-9._-]+", x) for x in ids):
            raise ValueError("invalid_model_id")


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    roots = {"developers.openai.com": "/api/docs/", "platform.claude.com": "/docs/en/",
             "docs.x.ai": "/developers/"}
    return (parsed.scheme == "https" and parsed.hostname in roots
            and parsed.path.startswith(roots[parsed.hostname])
            and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and not parsed.query and not parsed.fragment)


class DocsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError("untrusted_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url):
    if not allowed_url(url):
        raise ValueError("untrusted_source")
    # GET only. No cookie jar, auth header, request body, or credential reads.
    # The explicit .md route chooses Markdown. A mixed Accept header causes xAI's
    # content-negotiation middleware to return 404 for otherwise valid .md URLs.
    request = urllib.request.Request(url, headers={"User-Agent": "ForgeModelCatalog/3.0", "Accept": "*/*"})
    for attempt in range(2):
        try:
            with urllib.request.build_opener(DocsOnlyRedirect()).open(request, timeout=20) as response:
                if not allowed_url(response.url):
                    raise ValueError("untrusted_response")
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("oversized_document")
                text = raw.decode("utf-8")
                if len(text) < 100 or "<html" in text[:1000].lower():
                    raise ValueError("not_documentation")
                return text
        except urllib.error.HTTPError as error:
            if attempt or error.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt:
                raise
        time.sleep(2)
    raise ValueError("source_unavailable")


def one(pattern, text):
    matches = re.findall(pattern, text, flags=re.I | re.M)
    if len(matches) != 1:
        raise ValueError("ambiguous_or_changed_document")
    return matches[0]


def recommended_page(provider, text):
    # Provider's explicit default recommendation, not highest version number.
    if provider == "openAI":
        path = one(r"If you're not sure where to start, use \[[^\]]+\]\((/api/docs/models/[a-z0-9.-]+)\), our flagship", text)
    elif provider == "claude":
        path = one(r"If you're unsure which model to use, start with \[[^\]]+\]\((https://platform\.claude\.com/docs/en/models/[a-z0-9-]+/overview)\)", text)
    else:
        path = one(r"^Chat:\s*\[[^\]]+\]\((/developers/models/[a-z0-9.-]+)\)", text)
    url = urllib.parse.urljoin(SOURCES[provider], path)
    if not url.endswith(".md"):
        url += ".md"
    if not allowed_url(url) or urllib.parse.urlsplit(url).hostname != urllib.parse.urlsplit(SOURCES[provider]).hostname:
        raise ValueError("untrusted_recommendation")
    return url


def documented_model(provider, overview, detail):
    if provider == "openAI":
        model = one(r"^Model ID:\s*\x60([a-z0-9.-]+)\x60", detail)
        required = [
            r"Input modalities:\s*text,\s*image",
            r"\|\s*Chat Completions\s*\|\s*\x60v1/chat/completions\x60\s*\|\s*Supported\s*\|",
            r"^-\s*streaming\s*$",
            r"reasoning\.effort.*\x60low\x60",
        ]
    elif provider == "claude":
        model = one(r"^\|\s*Claude API\s*\|\s*\x60([a-z0-9-]+)\x60\s*\|", detail)
        required = [
            r"Input\s*→\s*output\s*\|\s*Text and images\s*→\s*text",
            r"(?:thinking can be disabled only at effort|Disabling thinking requires effort)\s*\x60high\x60\s*or below",
        ]
        if f"\x60{model}\x60" not in overview:
            raise ValueError("model_not_in_current_catalog")
    else:
        model = one(r"\*\*Model name:\*\*\s*\x60([a-z0-9.-]+)\x60", detail)
        required = [
            r"\*\*Modalities:\*\*\s*text,\s*image\s*→\s*text",
            r"\*\*Reasoning efforts \(supported\):\*\*.*\x60low\x60",
        ]
    if not model.startswith(PREFIXES[provider]) or len(model) > 128:
        raise ValueError("wrong_provider")
    if any(token in model.split("-") for token in ("preview", "experimental", "latest", "beta", "mini", "nano")):
        raise ValueError("non_stable_or_smaller_tier")
    if not all(re.search(pattern, detail, re.I | re.M) for pattern in required):
        raise ValueError("unsupported_or_unproven_request_profile")
    return model


def update(catalog, previous=None, get=fetch, now=None):
    validate(catalog)
    now = now or utcnow()
    previous = previous or {}
    updated = copy.deepcopy(catalog)
    report = {"checkedAt": now.isoformat(), "validation": "official_documentation_only",
              "liveAPITested": False, "health": "ok", "providers": {}}
    for provider, source in SOURCES.items():
        try:
            overview = get(source)
            detail_url = recommended_page(provider, overview)
            detail = get(detail_url)
            model = documented_model(provider, overview, detail)
            row = {"recommended": model, "sources": [source, detail_url],
                   "evidenceSHA256": hashlib.sha256((overview + "\n" + detail).encode()).hexdigest()}
            current = catalog[provider]["primary"]
            if model == current:
                row["state"] = "unchanged"
            elif model in catalog[provider].get("fallbacks", []):
                raise ValueError("recommendation_would_downgrade")
            else:
                prior = previous.get("providers", {}).get(provider, {})
                since = prior.get("firstSeen") if prior.get("recommended") == model else None
                first_seen = timestamp(since) if since else now
                if first_seen.tzinfo is None or first_seen > now:
                    first_seen = now
                row["firstSeen"] = first_seen.isoformat()
                row["state"] = "pending_second_weekly_observation"
                if now - first_seen >= datetime.timedelta(days=STABILITY_DAYS):
                    old = [current] + catalog[provider].get("fallbacks", [])
                    updated[provider] = {"primary": model, "fallbacks": list(dict.fromkeys(old))[:3]}
                    row["state"] = "promoted_from_documentation"
            report["providers"][provider] = row
        except (ValueError, TypeError, KeyError, OSError) as error:
            report["health"] = "degraded"
            # Error reasons are fixed local codes or HTTP status; no remote body.
            reason = ("HTTP_" + str(error.code)) if isinstance(error, urllib.error.HTTPError) else (str(error) if isinstance(error, ValueError) else type(error).__name__)
            report["providers"][provider] = {"state": "held", "reason": reason[:160],
                                             "retained": catalog[provider]["primary"], "source": source}
    if report["health"] != "ok":
        updated = copy.deepcopy(catalog)
        for row in report["providers"].values():
            if row.get("state") == "promoted_from_documentation":
                row["state"] = "held_due_to_source_failure"
    elif updated != catalog:
        updated["updatedAt"] = now.isoformat()
    report["lastSuccessfulCheckAt"] = now.isoformat() if report["health"] == "ok" else previous.get("lastSuccessfulCheckAt")
    validate(updated)
    return updated, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--status", type=Path)
    parser.add_argument("--refresh", action="store_true", help="GET public docs only; no paid inference")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text())
    validate(catalog)
    if not args.refresh:
        print("Catalog schema valid. No network or model calls.")
        return
    if not args.output or not args.status or args.output.resolve() == args.catalog.resolve() or args.status.resolve() in (args.catalog.resolve(), args.output.resolve()):
        raise ValueError("separate_artifact_paths_required")
    previous = json.loads(args.status.read_text()) if args.status.exists() else {}
    candidate, report = update(catalog, previous)
    args.status.parent.mkdir(parents=True, exist_ok=True)
    args.status.write_text(json.dumps(report, indent=2) + "\n")
    if report["health"] != "ok":
        raise ValueError("public_docs_check_failed_existing_catalog_retained")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(candidate, indent=2) + "\n")
    print("Public docs checked. No keys or inference calls. Catalog artifact ready.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise SystemExit("Catalog held: " + type(error).__name__ + ". Check status.json; no inference was called.")
