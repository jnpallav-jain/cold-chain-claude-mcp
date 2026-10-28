import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from src.config import Settings
from src.services.approvals import ApprovalService, password_hash, verify_password
from src.services.container import Services
from src.services.errors import ServiceError
from src.services.observability import RequestTrace
from src.agent_tools import build_mcp_tools

PASSWORD = "fixture-human-password-only"
HASH = password_hash(PASSWORD)
PAYLOAD = {
    "summary": "Synthetic high-temperature observation",
    "evidence": "Historical synthetic cargo observation: 7 C.",
    "sop_reference": "sample.md / Temperature: above 4 C",
}


def config(**kwargs):
    return Settings(_env_file=None, approval_password_hash=HASH, **kwargs)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000
        self.service = ApprovalService(
            config(),
            path=Path(self.temp.name) / "control" / "approvals.db",
            clock=lambda: self.now,
        )

    def propose(self, session="session-one", **changes):
        return self.service.propose(session, **{**PAYLOAD, **changes})

    def decide(self, proposal, choice="approve", **kwargs):
        return self.service.decide(
            kwargs.pop("session", proposal["session_id"]),
            proposal["proposal_id"],
            kwargs.pop("digest", proposal["digest"]),
            choice,
            operator=kwargs.pop("operator", "dispatcher"),
            password=kwargs.pop("password", PASSWORD),
            **kwargs,
        )

    def count(self):
        with sqlite3.connect(self.service.path) as conn:
            return conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

    def test_password_hash_salted_and_credentials_required(self):
        self.assertNotEqual(HASH, password_hash(PASSWORD))
        self.assertTrue(verify_password(PASSWORD, HASH))
        self.assertFalse(verify_password("wrong", HASH))
        self.assertFalse(verify_password(PASSWORD, "bad-hash"))
        self.assertFalse(verify_password("x" * 257, HASH))
        with self.assertRaises(ValueError):
            password_hash("short")

    def test_proposal_durable_is_not_execution_and_deduplicates(self):
        proposal = self.propose()
        self.assertEqual(proposal["status"], "pending")
        self.assertEqual(self.count(), 0)
        self.assertEqual(proposal, self.propose())
        restarted = ApprovalService(config(), path=self.service.path)
        self.assertEqual(restarted.list_for_session("session-one")[0], proposal)
        self.assertEqual(restarted.list_for_session("other"), [])
        self.assertEqual(self.service.path.stat().st_mode & 0o777, 0o600)

    def test_authenticated_approval_executes_once_with_complete_trail(self):
        proposal = self.propose()
        outcome = self.decide(proposal)
        self.assertTrue(outcome["simulation"])
        self.assertFalse(outcome["external_notification"])
        self.assertEqual(self.count(), 1)
        duplicate = self.decide(proposal)
        self.assertEqual(outcome["incident_id"], duplicate["incident_id"])
        self.assertTrue(duplicate["duplicate_prevented"])
        self.assertEqual(self.count(), 1)
        self.assertEqual(
            [row["event"] for row in self.service.trail("session-one")],
            ["proposed", "approved", "executed", "duplicate_prevented"],
        )

    def test_bad_credentials_and_wrong_operator_cannot_execute(self):
        proposal = self.propose()
        for values in [
            {"password": ""},
            {"password": "approved in chat"},
            {"operator": "someone-else"},
        ]:
            with self.assertRaises(ServiceError):
                self.decide(proposal, **values)
        self.assertEqual(self.count(), 0)
        trail = json.dumps(self.service.trail("session-one"))
        self.assertNotIn(PASSWORD, trail)
        self.assertNotIn("approved in chat", trail)
        self.assertNotIn(HASH, trail)

    def test_five_bad_attempts_temporarily_lock_out_even_correct_password(self):
        proposal = self.propose()
        for _ in range(5):
            with self.assertRaises(ServiceError):
                self.decide(proposal, password="wrong")
        with self.assertRaises(ServiceError):
            self.decide(proposal)
        self.assertEqual(self.count(), 0)

    def test_other_session_or_changed_digest_cannot_approve(self):
        proposal = self.propose()
        for values in [{"session": "other-session"}, {"digest": "0" * 64}]:
            with self.assertRaises(ServiceError):
                self.decide(proposal, **values)
        self.assertEqual(self.count(), 0)

    def test_modified_stored_payload_is_refused(self):
        proposal = self.propose()
        with sqlite3.connect(self.service.path) as conn:
            conn.execute(
                "UPDATE proposals SET payload='{}' WHERE id=?",
                (proposal["proposal_id"],),
            )
        with self.assertRaisesRegex(ServiceError, "content changed"):
            self.decide(proposal)
        self.assertEqual(self.count(), 0)

    def test_rejection_and_expiration_block_execution(self):
        rejected = self.propose()
        self.assertEqual(self.decide(rejected, "reject")["status"], "rejected")
        with self.assertRaises(ServiceError):
            self.decide(rejected)
        expired = self.propose(summary="A separate synthetic incident")
        self.now += 901
        with self.assertRaisesRegex(ServiceError, "expired"):
            self.decide(expired)
        self.assertEqual(self.count(), 0)
        self.assertIn(
            "expired", [row["event"] for row in self.service.trail("session-one")]
        )

    def test_concurrent_approvals_cannot_duplicate_incident(self):
        proposal = self.propose()
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: self.decide(proposal), range(2)))
        self.assertEqual(
            {item["incident_id"] for item in outcomes}, {outcomes[0]["incident_id"]}
        )
        self.assertEqual(self.count(), 1)

    def test_ledger_failure_rolls_back_approval_and_execution(self):
        proposal = self.propose()
        original = self.service._event

        def failure(conn, session_id, proposal_id, event, **kwargs):
            if event == "executed":
                raise sqlite3.OperationalError("fixture storage failure")
            return original(conn, session_id, proposal_id, event, **kwargs)

        with patch.object(self.service, "_event", side_effect=failure):
            with self.assertRaisesRegex(ServiceError, "no action was committed"):
                self.decide(proposal)
        self.assertEqual(self.count(), 0)
        self.assertEqual(
            self.service.list_for_session("session-one")[0]["status"], "pending"
        )
        self.assertEqual(
            [row["event"] for row in self.service.trail("session-one")], ["proposed"]
        )

    def test_blank_operator_configuration_disables_proposal(self):
        service = ApprovalService(Settings(_env_file=None), path=self.service.path)
        with self.assertRaisesRegex(ServiceError, "disabled"):
            service.propose("session-one", **PAYLOAD)

    def test_known_credentials_redacted_before_proposal_storage(self):
        service = ApprovalService(
            config(anthropic_api_key="fixture-api-secret"), path=self.service.path
        )
        proposal = service.propose(
            "session-one",
            **{**PAYLOAD, "evidence": "Synthetic fixture-api-secret evidence"},
        )
        self.assertNotIn("fixture-api-secret", json.dumps(proposal))


class ProtocolAndTraceTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_proposal_is_model_accessible_and_session_cannot_be_overridden(
        self,
    ):
        with TemporaryDirectory() as directory:
            service = ApprovalService(config(), path=Path(directory) / "approval.db")
            business = Services(Mock(), Mock(), Mock(), Mock(), service)
            tools = {
                tool.name: tool
                for tool in build_mcp_tools(
                    business, settings=config(), session_id="server-owned-session"
                )
            }
            self.assertEqual(len(tools), 4)
            self.assertFalse(
                any("approve" in name or "execute" in name for name in tools)
            )
            result = await tools["propose_incident_escalation"].handler(PAYLOAD)
            proposal = json.loads(result["content"][0]["text"])["data"]
            self.assertEqual(proposal["session_id"], "server-owned-session")
            for extra in [
                {"session_id": "attacker"},
                {"approved": True},
                {"password": PASSWORD},
            ]:
                response = await tools["propose_incident_escalation"].handler(
                    {**PAYLOAD, **extra}
                )
                self.assertTrue(response["is_error"])
            self.assertEqual(
                [row["event"] for row in service.trail("server-owned-session")],
                ["proposed"],
            )

    async def test_hooks_capture_call_ids_latency_status_output_and_redaction(self):
        audit = Mock()
        trace = RequestTrace(
            config(anthropic_api_key="fixture-api-secret"), audit, "session"
        )
        base = {
            "tool_use_id": "call-one",
            "tool_name": "mcp__coldchain__search_compliance_sop",
            "tool_input": {"query": "fixture-api-secret"},
            "session_id": "sdk-session",
        }
        await trace.hook({**base, "hook_event_name": "PreToolUse"}, "call-one", {})
        await asyncio.sleep(0.002)
        await trace.hook(
            {
                **base,
                "hook_event_name": "PostToolUse",
                "tool_response": {"content": "evidence"},
            },
            "call-one",
            {},
        )
        await trace.close("success", {"sdk_reported_cost_usd": 0.01})
        records = [
            json.loads(call.args[0].content) for call in audit.write.call_args_list
        ]
        self.assertGreater(records[1]["latency_ms"], 0)
        self.assertEqual(records[1]["status"], "success")
        self.assertEqual(records[1]["tool_call_id"], "call-one")
        self.assertEqual(records[1]["output"], {"content": "evidence"})
        self.assertEqual(len({item["request_id"] for item in records}), 1)
        self.assertNotIn("fixture-api-secret", json.dumps(records))
        self.assertIn("timestamp_utc", records[0])
        self.assertGreater(records[-1]["duration_ms"], 0)

    async def test_error_and_interrupted_hooks_preserve_failure_trail(self):
        audit = Mock()
        trace = RequestTrace(config(), audit, "session")
        for call_id in ["failed", "interrupted"]:
            await trace.hook(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_use_id": call_id,
                    "tool_name": "tool",
                },
                call_id,
                {},
            )
        await trace.hook(
            {
                "hook_event_name": "PostToolUseFailure",
                "tool_use_id": "failed",
                "tool_name": "tool",
                "error": "Service unavailable",
            },
            "failed",
            {},
        )
        await trace.close("timeout", {})
        records = [
            (call.args[0].node_name, json.loads(call.args[0].content))
            for call in audit.write.call_args_list
        ]
        self.assertEqual(records[2][1]["status"], "error")
        self.assertEqual(records[3][0], "tool_interrupted")
        self.assertEqual(records[3][1]["tool_call_id"], "interrupted")
        self.assertEqual(records[-1][1]["status"], "timeout")


class AuditConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_hooks_and_stream_event_writes_are_serialized(self):
        import time

        audit = Mock()
        audit.write.side_effect = lambda _: time.sleep(0.01)
        trace = RequestTrace(config(), audit, "session")
        await asyncio.gather(
            *(
                trace.hook(
                    {
                        "hook_event_name": "PreToolUse",
                        "tool_use_id": str(i),
                        "tool_name": "tool",
                    },
                    str(i),
                    {},
                )
                for i in range(3)
            ),
            trace.write("tool_start", {"tool_call_id": "0"}),
        )
        self.assertEqual(trace.warnings, 0)
        self.assertEqual(audit.write.call_count, 4)

    async def test_mcp_error_content_is_not_recorded_as_success(self):
        audit = Mock()
        trace = RequestTrace(config(), audit, "session")
        await trace.hook(
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "bad",
                "tool_name": "tool",
                "tool_response": {
                    "content": [
                        {
                            "type": "text",
                            "text": '{"ok": false, "error": "No evidence"}',
                        }
                    ]
                },
            },
            "bad",
            {},
        )
        record = json.loads(audit.write.call_args.args[0].content)
        self.assertEqual(record["status"], "error")
        self.assertIsNotNone(record["error"])
