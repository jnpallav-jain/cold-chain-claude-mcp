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


class ApprovalFrontendTests(unittest.TestCase):
    def test_authenticated_ui_creates_simulation_and_resets_isolate_proposals(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import Mock
        from src.services.approvals import ApprovalService, password_hash
        from src.services.container import Services

        password = "fixture-ui-operator-password"
        config = Settings(
            _env_file=None, approval_password_hash=password_hash(password)
        )
        with TemporaryDirectory() as directory:
            approvals = ApprovalService(config, path=Path(directory) / "approval.db")
            business = Services(Mock(), Mock(), Mock(), Mock(), approvals)
            with (
                patch("src.config.get_settings", return_value=config),
                patch("src.services.container.get_services", return_value=business),
            ):
                app = AppTest.from_file(str(PROJECT_ROOT / "src/ui.py")).run()
                session_id = app.session_state["agent_session"].id
                proposal = approvals.propose(
                    session_id,
                    summary="Synthetic high-temperature incident",
                    evidence="Synthetic historical reading 7 C.",
                    sop_reference="sample.md / Temperature above 4 C",
                )
                app.run()
                self.assertEqual(len(app.exception), 0)
                next(
                    item for item in app.text_input if item.label == "Operator password"
                ).set_value(password)
                next(item for item in app.radio if item.label == "Decision").set_value(
                    "Approve and create simulated incident"
                )
                app.checkbox[0].check()
                next(
                    item for item in app.button if item.label == "Submit human decision"
                ).click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(
                    approvals.list_for_session(session_id)[0]["status"], "executed"
                )
                self.assertTrue(
                    any("Simulation only" in item.value for item in app.success)
                )
                self.assertNotIn(password, str(app.json))
                next(
                    item for item in app.button if item.label == "New conversation"
                ).click().run()
                self.assertNotEqual(app.session_state["agent_session"].id, session_id)
                self.assertEqual(
                    approvals.list_for_session(app.session_state["agent_session"].id),
                    [],
                )
                self.assertEqual(
                    approvals.list_for_session(session_id)[0]["proposal_id"],
                    proposal["proposal_id"],
                )
