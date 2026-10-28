from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest
from src.config import PROJECT_ROOT, Settings
from src.orchestrator import AgentSession, AgentEvent
from src.services.approvals import password_hash
from src.services.demo import DemoControl
from src.services.errors import ServiceError
from src.web import stream_web_turn
from src.presentation import evidence_cards

PASSWORD = "fixture-demo-viewer-password"
HASH = password_hash(PASSWORD)


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "demo.sqlite3"
        self.now = 100000
        self.settings = Settings(
            _env_file=None, demo_mode=True, demo_password_hash=HASH
        )
        self.control = DemoControl(
            self.settings, path=self.path, clock=lambda: self.now
        )

    def login(self):
        return self.control.login("reviewer", PASSWORD)

    def test_unauthenticated_and_expired_sessions_are_denied(self):
        with self.assertRaises(ServiceError):
            self.control.admit("forged-token")
        token = self.login()
        self.assertEqual(self.control.validate(token), "reviewer")
        self.now += 3601
        with self.assertRaises(ServiceError):
            self.control.admit(token)

    def test_lockout_persists_across_new_control_objects(self):
        for _ in range(5):
            with self.assertRaises(ServiceError):
                self.control.login("reviewer", "wrong-password")
        restarted = DemoControl(self.settings, path=self.path, clock=lambda: self.now)
        with self.assertRaises(ServiceError):
            restarted.login("reviewer", PASSWORD)
        self.now += 61
        self.assertTrue(restarted.login("reviewer", PASSWORD))

    def test_concurrent_admission_is_atomic_and_does_not_queue(self):
        token = self.login()

        def admit(_):
            try:
                return self.control.admit(token)
            except ServiceError:
                return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(admit, range(2)))
        self.assertEqual(sum(item is not None for item in outcomes), 1)
        self.control.finish(next(item for item in outcomes if item))
        self.assertTrue(self.control.admit(token))

    def test_daily_reservations_survive_restarts_and_cannot_be_refunded(self):
        self.settings = self.settings.model_copy(update={"demo_daily_budget_cents": 30})
        self.control = DemoControl(
            self.settings, path=self.path, clock=lambda: self.now
        )
        token = self.login()
        for _ in range(2):
            self.control.finish(self.control.admit(token))
        restarted = DemoControl(self.settings, path=self.path, clock=lambda: self.now)
        with self.assertRaisesRegex(ServiceError, "Daily"):
            restarted.admit(token)

    def test_hourly_rate_is_per_principal_not_reset_by_new_browser(self):
        self.settings = self.settings.model_copy(update={"demo_requests_per_hour": 1})
        self.control = DemoControl(
            self.settings, path=self.path, clock=lambda: self.now
        )
        self.control.finish(self.control.admit(self.login()))
        with self.assertRaisesRegex(ServiceError, "Hourly"):
            self.control.admit(self.login())

    def test_logout_and_password_rotation_invalidate_sessions(self):
        token = self.login()
        self.control.logout(token)
        with self.assertRaises(ServiceError):
            self.control.validate(token)
        token = self.login()
        rotated = DemoControl(
            self.settings.model_copy(
                update={
                    "demo_password_hash": SecretStr(
                        password_hash("new-fixture-password")
                    )
                }
            ),
            path=self.path,
            clock=lambda: self.now,
        )
        with self.assertRaises(ServiceError):
            rotated.validate(token)

    def test_stop_switch_blocks_admission_and_does_not_start_work(self):
        token = self.login()
        self.control.stop_path.write_text("stopped")
        with self.assertRaisesRegex(ServiceError, "paused"):
            self.control.admit(token)
        self.control.stop_path.unlink()
        self.assertTrue(self.control.admit(token))

    def test_storage_failure_is_closed_and_sanitized(self):
        bad = DemoControl(self.settings, path=Path(self.temp.name))
        with self.assertRaisesRegex(ServiceError, "Requests are disabled"):
            bad.login("reviewer", PASSWORD)

    def test_evidence_cards_preserve_data_and_ignore_invalid_or_error_results(self):
        cards = evidence_cards(
            [
                {
                    "kind": "tool_result",
                    "name": "mcp__coldchain__query_telemetry_db",
                    "content": [
                        {
                            "text": '{"ok":true,"data":{"rows":[],"normalized_sql":"SELECT TOP 10"}}'
                        }
                    ],
                },
                {
                    "kind": "tool_result",
                    "name": "tool",
                    "is_error": True,
                    "content": "bad",
                },
            ]
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["data"]["normalized_sql"], "SELECT TOP 10")


class WebAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejected_admission_cannot_construct_runner(self):
        control = Mock()
        control.admit.side_effect = ServiceError("Demo paused")
        factory = Mock()
        events = [
            event
            async for event in stream_web_turn(
                AgentSession(),
                "Question",
                "invalid",
                control=control,
                runner_factory=factory,
            )
        ]
        self.assertEqual(events[0].kind, "error")
        factory.assert_not_called()

    async def test_accepted_request_caps_sdk_budget_and_releases_lease(self):
        control = Mock()
        control.settings = Settings(_env_file=None, demo_request_budget_cents=15)
        observed = []

        class Runner:
            settings = Settings(_env_file=None, claude_max_budget_usd=0.5)

            async def stream_turn(self, session, prompt):
                observed.append(self.settings.claude_max_budget_usd)
                yield AgentEvent("complete", {"text": "Fixture answer"})

        events = [
            event
            async for event in stream_web_turn(
                AgentSession(),
                "Question",
                "valid",
                control=control,
                runner_factory=Runner,
            )
        ]
        self.assertEqual(events[-1].kind, "complete")
        self.assertEqual(observed, [0.15])
        control.finish.assert_called_once()


class DemoUITests(unittest.TestCase):
    def test_login_gate_hides_chat_audit_and_services_until_authenticated(self):
        with TemporaryDirectory() as directory:
            settings = Settings(_env_file=None, demo_mode=True, demo_password_hash=HASH)
            control = DemoControl(settings, path=Path(directory) / "demo.db")
            with (
                patch("src.config.get_settings", return_value=settings),
                patch("src.services.demo.get_demo_control", return_value=control),
                patch("src.services.container.get_services") as services,
            ):
                app = AppTest.from_file(str(PROJECT_ROOT / "src/ui.py")).run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.chat_input), 0)
                services.assert_not_called()
                self.assertFalse(
                    any(
                        item.value == "Administrative audit viewer"
                        for item in app.subheader
                    )
                )

    def test_viewer_login_hides_admin_and_logout_clears_conversation(self):
        from src.services.container import Services

        with TemporaryDirectory() as directory:
            settings = Settings(
                _env_file=None,
                demo_mode=True,
                demo_password_hash=HASH,
                anthropic_api_key="fixture-api-key",
            )
            control = DemoControl(settings, path=Path(directory) / "demo.db")
            services = Services(Mock(), Mock(), Mock(), Mock(), None)
            with (
                patch("src.config.get_settings", return_value=settings),
                patch("src.services.demo.get_demo_control", return_value=control),
                patch("src.services.container.get_services", return_value=services),
            ):
                app = AppTest.from_file(str(PROJECT_ROOT / "src/ui.py")).run()
                next(
                    item for item in app.text_input if item.label == "Demo username"
                ).set_value("reviewer")
                next(
                    item for item in app.text_input if item.label == "Demo password"
                ).set_value(PASSWORD)
                next(
                    item for item in app.button if item.label == "Sign in"
                ).click().run()
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.chat_input), 1)
                self.assertNotIn("Audit log", app.radio[0].options)
                token = app.session_state["_demo_token"]
                next(
                    item for item in app.button if item.label == "Sign out"
                ).click().run()
                self.assertEqual(len(app.chat_input), 0)
                with self.assertRaises(ServiceError):
                    control.validate(token)
