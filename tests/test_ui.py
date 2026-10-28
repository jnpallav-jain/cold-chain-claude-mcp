import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from src.config import Settings, PROJECT_ROOT
from src.orchestrator import AgentEvent


class FakeRunner:
    async def stream_turn(self, session, prompt):
        yield AgentEvent(
            "tool_start",
            {
                "tool_call_id": "test",
                "name": "mcp__coldchain__search_compliance_sop",
                "arguments": {"query": "rules"},
            },
        )
        yield AgentEvent(
            "tool_result",
            {
                "tool_call_id": "test",
                "name": "mcp__coldchain__search_compliance_sop",
                "content": "Sample rule",
                "is_error": False,
            },
        )
        yield AgentEvent(
            "complete", {"text": "Supported test answer [sample.md]", "turns": 2}
        )


class FrontendTests(unittest.TestCase):
    def test_missing_key_disables_chat_without_crashing(self):
        with patch("src.config.get_settings", return_value=Settings(_env_file=None)):
            app = AppTest.from_file(str(PROJECT_ROOT / "src/ui.py")).run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(app.chat_input[0].disabled)
            self.assertIn("ANTHROPIC_API_KEY", app.info[0].value)

    def test_chat_renders_shared_runner_results_and_reset_clears_history(self):
        config = Settings(
            _env_file=None, anthropic_api_key="test-key-only", claude_model="sonnet"
        )
        with (
            patch("src.config.get_settings", return_value=config),
            patch("src.orchestrator.AgentRunner", return_value=FakeRunner()),
        ):
            app = AppTest.from_file(str(PROJECT_ROOT / "src/ui.py")).run()
            before = app.session_state["agent_session"].id
            app.chat_input[0].set_value("What is the policy?").run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(len(app.chat_message), 2)
            self.assertEqual(
                app.session_state["messages"][-1]["content"],
                "Supported test answer [sample.md]",
            )
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotEqual(app.session_state["agent_session"].id, before)
            self.assertEqual(app.session_state["messages"], [])


if __name__ == "__main__":
    unittest.main()
