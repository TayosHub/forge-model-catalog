"""Offline regression tests for the keyless updater. No API credentials."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
import cloud_model_catalog as catalog

NOW = dt.datetime(2026, 9, 16, tzinfo=dt.timezone.utc)
BASE = {"schemaVersion": 2, "updatedAt": "2026-09-15",
        "openAI": {"primary": "gpt-6-astra", "fallbacks": ["gpt-5.6-sol"]},
        "claude": {"primary": "claude-opus-5", "fallbacks": ["claude-opus-4-8"]},
        "grok": {"primary": "grok-4.6", "fallbacks": ["grok-4.5"]}}


def documents(openai="gpt-6-astra"):
    return {
        catalog.SOURCES["openAI"]: "If you're not sure where to start, use [Flagship](/api/docs/models/" + openai + "), our flagship model.",
        "https://developers.openai.com/api/docs/models/" + openai + ".md":
            "Model ID: \x60" + openai + "\x60\nInput modalities: text, image\n"
            "| Chat Completions | \x60v1/chat/completions\x60 | Supported |\n"
            "- streaming\nreasoning.effort supports \x60low\x60",
        catalog.SOURCES["claude"]: "If you're unsure which model to use, start with [Claude](https://platform.claude.com/docs/en/models/opus-5/overview) for most workloads.\n\x60claude-opus-5\x60",
        "https://platform.claude.com/docs/en/models/opus-5/overview.md":
            "| Claude API | \x60claude-opus-5\x60 |\n| Input → output | Text and images → text |\n"
            "Disabling thinking requires effort \x60high\x60 or below.",
        catalog.SOURCES["grok"]: "Chat: [Grok](/developers/models/grok-4.6)\n",
        "https://docs.x.ai/developers/models/grok-4.6.md":
            "- **Model name:** \x60grok-4.6\x60\n- **Modalities:** text, image → text\n"
            "- **Reasoning efforts (supported):** \x60low\x60, \x60high\x60",
    }


class CatalogTests(unittest.TestCase):
    def test_cli_reads_observation_history_without_reusing_it_as_fresh_output(self):
        docs = documents("gpt-7-astra")
        _, pending = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        update = catalog.update
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, history, fresh, output = [root / name for name in ("catalog.json", "history.json", "fresh.json", "candidate.json")]
            source.write_text(json.dumps(BASE))
            history.write_text(json.dumps(pending))
            original = history.read_bytes()
            argv = ["catalog", "--catalog", str(source), "--refresh", "--previous-status", str(history), "--status", str(fresh), "--output", str(output)]
            with patch("sys.argv", argv), patch.object(catalog, "update", side_effect=lambda c, p: update(c, p, get=docs.__getitem__, now=NOW + dt.timedelta(days=7))):
                catalog.main()
            self.assertEqual(history.read_bytes(), original)
            self.assertEqual(json.loads(output.read_text())["openAI"]["primary"], "gpt-7-astra")
            self.assertEqual(json.loads(fresh.read_text())["health"], "ok")

    def test_cli_failure_before_update_leaves_no_fresh_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, history, fresh, output = [root / name for name in ("catalog.json", "history.json", "fresh.json", "candidate.json")]
            source.write_text(json.dumps(BASE))
            history.write_text("broken history")
            with patch("sys.argv", ["catalog", "--catalog", str(source), "--refresh", "--previous-status", str(history), "--status", str(fresh), "--output", str(output)]):
                with self.assertRaises(ValueError):
                    catalog.main()
            self.assertFalse(fresh.exists())
            self.assertFalse(output.exists())

    def test_unchanged_catalog_has_fresh_health_not_false_api_claim(self):
        result, status = catalog.update(BASE, get=documents().__getitem__, now=NOW)
        self.assertEqual(result, BASE)
        self.assertEqual(status["health"], "ok")
        self.assertFalse(status["liveAPITested"])
        self.assertEqual(status["checkedAt"], NOW.isoformat())

    def test_new_model_requires_second_weekly_observation(self):
        docs = documents("gpt-7-astra")
        first, report = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        self.assertEqual(first, BASE)
        same_day, _ = catalog.update(BASE, report, get=docs.__getitem__, now=NOW)
        self.assertEqual(same_day, BASE)
        result, report = catalog.update(BASE, report, get=docs.__getitem__, now=NOW + dt.timedelta(days=7))
        self.assertEqual(result["openAI"]["primary"], "gpt-7-astra")
        self.assertEqual(result["openAI"]["fallbacks"][0], "gpt-6-astra")
        self.assertEqual(report["providers"]["openAI"]["state"], "promoted_from_documentation")

    def test_failure_preserves_catalog_and_names_provider(self):
        docs = documents()
        docs[catalog.SOURCES["grok"]] = "unexpected page format"
        result, status = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        self.assertEqual(result, BASE)
        self.assertEqual(status["health"], "degraded")
        self.assertEqual(status["providers"]["grok"]["retained"], "grok-4.6")
        self.assertIn("ambiguous", status["providers"]["grok"]["reason"])

    def test_no_partial_publication(self):
        docs = documents("gpt-7-astra")
        _, pending = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        docs[catalog.SOURCES["claude"]] = "unavailable"
        result, report = catalog.update(BASE, pending, get=docs.__getitem__, now=NOW + dt.timedelta(days=7))
        self.assertEqual(result, BASE)
        self.assertEqual(report["providers"]["openAI"]["state"], "held_due_to_source_failure")

    def test_missing_capability_holds(self):
        docs = documents()
        url = "https://developers.openai.com/api/docs/models/gpt-6-astra.md"
        docs[url] = docs[url].replace("| Supported |", "| Not supported |")
        result, report = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        self.assertEqual(result, BASE)
        self.assertEqual(report["health"], "degraded")

    def test_provider_recommendation_not_largest_number(self):
        docs = documents()
        docs[catalog.SOURCES["grok"]] += "\nLegacy grok-4.20 and future example grok-99"
        _, report = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        self.assertEqual(report["providers"]["grok"]["recommended"], "grok-4.6")

    def test_preview_and_smaller_models_held(self):
        for name in ["gpt-7-preview", "gpt-7-mini", "gpt-7-latest"]:
            _, report = catalog.update(BASE, get=documents(name).__getitem__, now=NOW)
            self.assertEqual(report["health"], "degraded")

    def test_duplicate_recommendation_fails_closed(self):
        docs = documents()
        docs[catalog.SOURCES["openAI"]] *= 2
        _, report = catalog.update(BASE, get=docs.__getitem__, now=NOW)
        self.assertEqual(report["health"], "degraded")

    def test_paid_api_and_external_redirects_refused(self):
        for url in ["https://api.openai.com/v1/models", "https://api.anthropic.com/v1/messages",
                    "https://api.x.ai/v1/chat/completions", "http://docs.x.ai/developers/models",
                    "https://evil.test/models", "https://user:pass@docs.x.ai/developers/models"]:
            self.assertFalse(catalog.allowed_url(url))
            with self.assertRaises(ValueError):
                catalog.fetch(url)

    def test_network_failure_is_not_no_updates(self):
        def fail(url):
            raise OSError("network down")
        result, report = catalog.update(BASE, get=fail, now=NOW)
        self.assertEqual(result, BASE)
        self.assertEqual(report["health"], "degraded")

    def test_changed_candidate_restarts_observation(self):
        _, pending = catalog.update(BASE, get=documents("gpt-7-astra").__getitem__, now=NOW)
        result, report = catalog.update(BASE, pending, get=documents("gpt-8-astra").__getitem__, now=NOW + dt.timedelta(days=7))
        self.assertEqual(result, BASE)
        self.assertEqual(report["providers"]["openAI"]["state"], "pending_second_weekly_observation")

    def test_source_contains_no_funded_request_path(self):
        source = Path(catalog.__file__).read_text()
        for forbidden in ["import os", "os.environ", "Authorization", "api.openai.com", "api.anthropic.com", "api.x.ai", "probe_body"]:
            self.assertNotIn(forbidden, source)

    def test_bad_schema_and_cross_provider_rejected(self):
        for provider in catalog.PREFIXES:
            bad = copy.deepcopy(BASE)
            bad[provider]["primary"] = "not-a-provider"
            with self.assertRaises(ValueError):
                catalog.validate(bad)


if __name__ == "__main__":
    unittest.main()
