import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "analyze-codex-tokens.py"


def load_module():
    spec = importlib.util.spec_from_file_location("analyze_codex_tokens", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load analyzer module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AnalyzeCodexTokensTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def test_parse_session_extracts_usage_and_prompt(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "session.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-04-10T12:00:00Z",
                    "payload": {
                        "id": "sess-1",
                        "cwd": "C:/work/my-project",
                        "git": {"repository_url": "https://github.com/example/my-project.git"},
                        "base_instructions": {"text": "base rules"},
                    },
                },
                {
                    "type": "turn_context",
                    "payload": {"user_instructions": "specific instruction"},
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 1000,
                                "cached_input_tokens": 250,
                                "output_tokens": 100,
                                "reasoning_output_tokens": 30,
                                "total_tokens": 1100,
                            }
                        },
                    },
                },
                {
                    "type": "event_msg",
                    "timestamp": "2026-04-10T12:01:00Z",
                    "payload": {
                        "type": "user_message",
                        "message": "hello analyzer",
                    },
                },
            ]
            file_path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

            session = self.mod.parse_session(file_path)
            self.assertIsNotNone(session)
            self.assertEqual(session["session_id"], "sess-1")
            self.assertEqual(session["project"], "my-project")
            self.assertEqual(session["total_tokens"], 1100)
            self.assertEqual(session["usage"]["input_tokens"], 1000)
            self.assertEqual(session["input_output_ratio"], 10.0)
            self.assertEqual(session["cached_input_to_output_ratio"], 2.5)
            self.assertEqual(session["cached_output_ratio"], 2.5)
            self.assertEqual(
                self.mod.get_cached_input_to_output_ratio(session),
                2.5,
            )
            self.assertEqual(session["base_instruction_chars"], len("base rules"))
            self.assertEqual(
                session["max_user_instruction_chars"], len("specific instruction")
            )
            self.assertEqual(
                session["instruction_chars"],
                len("base rules") + len("specific instruction"),
            )
            self.assertEqual(session["prompt_count"], 1)
            self.assertEqual(session["turn_count"], 1)
            self.assertIn("prompts", session)
            self.assertTrue(session["prompts"])
            self.assertEqual(session["prompts"][0]["text"], "hello analyzer")
            self.assertEqual(session["prompts"][0]["timestamp"], "2026-04-10T12:01:00Z")

    def test_summarize_projects_aggregates_totals(self):
        projects = {
            "alpha": [
                {
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 10,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                        "total_tokens": 120,
                    },
                    "is_subagent": False,
                    "total_tokens": 120,
                },
                {
                    "usage": {
                        "input_tokens": 200,
                        "cached_input_tokens": 20,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 6,
                        "total_tokens": 230,
                    },
                    "is_subagent": True,
                    "total_tokens": 230,
                },
            ]
        }

        summaries = self.mod.summarize_projects(projects)
        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertEqual(summary["project"], "alpha")
        self.assertEqual(summary["sessions"], 2)
        self.assertEqual(summary["total_tokens"], 350)
        self.assertEqual(summary["subagent_count"], 1)
        self.assertEqual(summary["subagent_tokens"], 230)

    def test_normalize_prompt_for_display(self):
        normalized = self.mod.normalize_prompt_for_display(
            "# Context from my IDE setup:\n"
            "\n"
            "## Open tabs:\n- README.md\n"
            "## Active file: src/main.py\n"
            "## My request for Codex: Explain this function\n"
            "# Files mentioned by the user: src/main.py\n"
            "\n"
            "[Doc](https://example.com)"
        )
        self.assertIn("Context:", normalized)
        self.assertIn("Open tabs:", normalized)
        self.assertIn("Active file:", normalized)
        self.assertIn("User request:", normalized)
        self.assertIn("Files:", normalized)
        self.assertNotIn("[Doc](", normalized)
        self.assertIn("Doc", normalized)

    def test_normalize_prompt_for_display_empty_string(self):
        normalized = self.mod.normalize_prompt_for_display("")
        self.assertEqual(normalized, "")

    def test_normalize_prompt_for_display_without_markers(self):
        text = "Explain the function in src/main.py"
        normalized = self.mod.normalize_prompt_for_display(text)
        self.assertEqual(normalized, text)

    def test_normalize_prompt_for_display_malformed_markdown_link(self):
        text = "See [Doc](https://example.com and [broken](not-a-url"
        normalized = self.mod.normalize_prompt_for_display(text)
        self.assertIn("Doc", normalized)
        self.assertNotIn("[Doc](", normalized)
        self.assertNotIn("https://example.com", normalized)
        self.assertIn("broken", normalized)
        self.assertNotIn("[broken](", normalized)

    def test_short_session_id(self):
        self.assertEqual(self.mod.short_session_id("1234567890"), "12345678...")
        self.assertEqual(self.mod.short_session_id("12345678"), "12345678")
        self.assertEqual(self.mod.short_session_id("1234"), "1234")
        self.assertEqual(self.mod.short_session_id(""), "?")
        self.assertEqual(self.mod.short_session_id(None), "?")
        self.assertEqual(self.mod.short_session_id("1234567890", size=5), "12345...")
        self.assertEqual(self.mod.short_session_id("12345", size=5), "12345")
        self.assertEqual(self.mod.short_session_id("1234", size=5), "1234")

    def test_redact_prompt_text(self):
        redacted = self.mod.redact_prompt_text("secret prompt content")
        self.assertTrue(redacted.startswith("[redacted prompt:"))
        self.assertIn(str(len("secret prompt content")), redacted)

    def test_get_first_prompt_text_with_redaction(self):
        with patch.object(self.mod, "REDACT_PROMPTS", True):
            excerpt = self.mod.get_first_prompt_text(
                {"prompts": [{"text": "secret prompt content"}]},
                limit=120,
            )
            self.assertTrue(excerpt.startswith("[redacted prompt:"))

    def test_get_first_prompt_text_without_redaction(self):
        with patch.object(self.mod, "REDACT_PROMPTS", False):
            excerpt = self.mod.get_first_prompt_text(
                {"prompts": [{"text": "secret prompt content"}]},
                limit=120,
            )
            self.assertEqual(excerpt, "secret prompt content")

    def test_compute_cached_input_to_output_ratio_edge_cases(self):
        ratio_zero_output = self.mod.compute_cached_input_to_output_ratio(
            {"usage": {"cached_input_tokens": 250, "output_tokens": 0}}
        )
        self.assertIsNone(ratio_zero_output)

        ratio_zero_cached = self.mod.compute_cached_input_to_output_ratio(
            {"usage": {"cached_input_tokens": 0, "output_tokens": 100}}
        )
        self.assertEqual(ratio_zero_cached, 0.0)

    def test_compute_cached_input_to_output_ratio_with_session_usage_dict(self):
        session = {"usage": {"cached_input_tokens": 250, "output_tokens": 100}}
        cached_ratio = self.mod.compute_cached_input_to_output_ratio(session)
        self.assertEqual(cached_ratio, 2.5)

    def test_get_cached_input_to_output_ratio_falls_back_to_cached_output_ratio(self):
        session = {"cached_output_ratio": 2.5}
        cached_ratio = self.mod.get_cached_input_to_output_ratio(session)
        self.assertEqual(cached_ratio, 2.5)

    def test_parse_session_uses_last_token_count_event(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "session.jsonl"
            lines = [
                {
                    "type": "session_meta",
                    "timestamp": "2026-04-10T12:00:00Z",
                    "payload": {
                        "id": "sess-2",
                        "cwd": "C:/work/my-project",
                        "git": {"repository_url": "https://github.com/example/my-project.git"},
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 200,
                                "cached_input_tokens": 50,
                                "output_tokens": 20,
                                "reasoning_output_tokens": 5,
                                "total_tokens": 220,
                            }
                        },
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": 500,
                                "cached_input_tokens": 120,
                                "output_tokens": 50,
                                "reasoning_output_tokens": 12,
                                "total_tokens": 550,
                            }
                        },
                    },
                },
            ]
            file_path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")

            session = self.mod.parse_session(file_path)
            self.assertIsNotNone(session)
            self.assertEqual(session["usage"]["input_tokens"], 500)
            self.assertEqual(session["usage"]["cached_input_tokens"], 120)
            self.assertEqual(session["usage"]["output_tokens"], 50)
            self.assertEqual(session["usage"]["reasoning_output_tokens"], 12)
            self.assertEqual(session["usage"]["total_tokens"], 550)
            self.assertEqual(session["cached_input_to_output_ratio"], 2.4)
            self.assertEqual(session["cached_output_ratio"], 2.4)


if __name__ == "__main__":
    unittest.main()
