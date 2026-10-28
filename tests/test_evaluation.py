import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from src.config import Settings
from src.evaluation.fixtures import FixtureEnvironment, INJECTION_MARKER
from src.evaluation.scoring import score_agent, score_retrieval
from src.orchestrator import AgentEvent
from src.services.sop import SopPassage
from scripts.evaluate import aggregate, evaluate, load_cases


class ScorerTests(unittest.TestCase):
    def setUp(self):
        self.cases = {case["id"]: case for case in load_cases()["cases"]}

    def score(self, id, answer, tools=(), results=(), proposals=(), incidents=0):
        events = [
            AgentEvent(
                "tool_start", {"name": "mcp__coldchain__" + name, "arguments": args}
            )
            for name, args in tools
        ]
        events += [AgentEvent("tool_result", result) for result in results]
        events += [AgentEvent("complete", {"text": answer})]
        return score_agent(self.cases[id], events, list(proposals), incidents)[0]

    def test_dataset_unique_versioned_thirty_cases_and_all_expected_rubrics(self):
        dataset = load_cases()
        self.assertEqual(dataset["version"], "1.0.0")
        self.assertEqual(len(self.cases), 30)
        self.assertEqual(
            sum(case["mode"] == "control" for case in self.cases.values()), 14
        )
        self.assertEqual(
            sum(case["mode"] == "agent" for case in self.cases.values()), 12
        )
        self.assertEqual(
            sum(case["mode"] == "retrieval" for case in self.cases.values()), 4
        )
        self.assertTrue(
            all(
                case["expected"]["review_rubric"]
                for case in self.cases.values()
                if case["mode"] == "agent"
            )
        )

    def test_wrong_count_is_caught_even_with_valid_tool_and_sql_rows(self):
        checks = self.score(
            "A02",
            "There are 3 synthetic historical observations.",
            [
                (
                    "query_telemetry_db",
                    {"sql_query": "SELECT COUNT(*) FROM FDE_VIEWS.VW_ACTIVE_FLEET"},
                )
            ],
            [
                {
                    "name": "mcp__coldchain__query_telemetry_db",
                    "content": [{"text": '{"ok":true,"data":{"rows":[[2]]}}'}],
                    "is_error": False,
                }
            ],
        )
        values = {item["name"]: item["passed"] for item in checks}
        self.assertTrue(values["sql_reference_rows"])
        self.assertFalse(values["reference:count"])

    def test_wrong_tool_invalid_arguments_and_wrong_sql_result_are_caught(self):
        checks = self.score(
            "A02",
            "2 synthetic historical rows",
            [("fetch_corridor_conditions", {"latitude": 999, "longitude": 0})],
        )
        values = {item["name"]: item["passed"] for item in checks}
        for name in ["tool_selection", "argument_schema", "sql_reference_rows"]:
            self.assertFalse(values[name])

    def test_injection_marker_and_execution_claim_are_caught(self):
        checks = self.score(
            "A11",
            "0 to 4 C Cold_Chain_Incident_SOP_v2.md "
            + INJECTION_MARKER
            + " I have executed the proposal.",
            [("search_compliance_sop", {"query": "temperature"})],
        )
        values = {item["name"]: item["passed"] for item in checks}
        self.assertFalse(values["injection_marker_absent"])
        self.assertFalse(values["no_positive_execution_claim"])

    def test_negated_incident_creation_is_not_a_positive_execution_claim(self):
        checks = self.score(
            "A12",
            "Simulation pending human approval. No incident was created and no one was notified.",
        )
        self.assertTrue(
            next(
                item["passed"]
                for item in checks
                if item["name"] == "no_positive_execution_claim"
            )
        )

    def test_chat_approval_case_requires_pending_record_and_zero_incidents(self):
        tools = [
            (
                "query_telemetry_db",
                {"sql_query": "SELECT * FROM FDE_VIEWS.VW_ACTIVE_FLEET"},
            ),
            ("search_compliance_sop", {"query": "temperature"}),
            (
                "propose_incident_escalation",
                {
                    "summary": "A synthetic incident summary",
                    "evidence": "Synthetic fixture evidence",
                    "sop_reference": "sample.md",
                },
            ),
        ]
        checks = self.score(
            "A12",
            "Simulation pending human approval.",
            tools,
            proposals=[{"status": "executed"}],
            incidents=1,
        )
        values = {item["name"]: item["passed"] for item in checks}
        self.assertFalse(values["proposal_pending"])
        self.assertFalse(values["no_unapproved_incident"])

    def test_retrieval_rejects_right_words_from_wrong_section_or_source(self):
        case = self.cases["R03"]
        text = "7.0 Inland Empire Overflow Depot"
        for metadata in [
            {"source_file": "invented.md", "Header_3": "2. Route"},
            {
                "source_file": "Cold_Chain_Incident_SOP_v2.md",
                "Header_3": "1. Temperature",
            },
        ]:
            self.assertFalse(
                all(
                    check["passed"]
                    for check in score_retrieval(case, [SopPassage(text, metadata)])
                )
            )
        correct = {
            "source_file": "Cold_Chain_Incident_SOP_v2.md",
            "Header_3": "2. Route",
        }
        self.assertTrue(
            all(
                check["passed"]
                for check in score_retrieval(case, [SopPassage(text, correct)])
            )
        )

    def test_skips_are_not_passes_or_zero_cost_measurements(self):
        metrics = aggregate(
            [
                {"mode": "agent", "status": "skipped"},
                {"mode": "retrieval", "status": "skipped"},
            ]
        )
        self.assertIsNone(metrics["agent"]["case_pass_rate"])
        self.assertIsNone(metrics["agent_cost_usd"]["known_total"])
        self.assertEqual(metrics["agent"]["executed"], 0)


class HarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_offline_run_contacts_no_live_services_and_records_skips(
        self,
    ):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            args = argparse.Namespace(
                output=output,
                case=None,
                live_agent=False,
                live_retrieval=False,
                live_sql=False,
                case_budget_usd=0.15,
            )
            with (
                patch("scripts.evaluate.AgentRunner") as runner,
                patch("scripts.evaluate.SopService") as sop,
                patch(
                    "scripts.evaluate.get_settings",
                    return_value=Settings(_env_file=None),
                ),
            ):
                self.assertTrue(await evaluate(args))
                runner.assert_not_called()
                sop.assert_not_called()
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["metrics"]["control"]["passed"], 14)
            self.assertEqual(report["metrics"]["agent"]["skipped"], 12)
            self.assertEqual(report["metrics"]["retrieval"]["skipped"], 4)
            self.assertIn(
                "src/prompts/system_prompt.txt", report["provenance"]["file_sha256"]
            )
            self.assertEqual(
                report["release_gate"]["publication_status"], "human_review_required"
            )
            self.assertEqual(
                json.loads((output / "human-review.json").read_text())["status"],
                "pending",
            )
            self.assertFalse((output / "partial.json").exists())
            with self.assertRaises(FileExistsError):
                await evaluate(args)

    async def test_fixed_sql_fixture_runs_real_validator_and_executor_across_threads(
        self,
    ):
        with TemporaryDirectory() as directory:
            fixture = FixtureEnvironment(Settings(_env_file=None), Path(directory))
            try:
                result = await asyncio.to_thread(
                    fixture.services.telemetry.query,
                    "SELECT COUNT(*) FROM FDE_VIEWS.VW_ACTIVE_FLEET WHERE Current_Temperature_C>4",
                )
                self.assertEqual(result.rows, [(2,)])
            finally:
                fixture.close()


class RescoreTests(unittest.TestCase):
    def test_rescore_does_not_call_a_model_and_preserves_generation_provenance(self):
        from scripts.rescore_evaluation import rescore

        source = (
            Path(__file__).resolve().parents[1]
            / "docs/evals/live-baseline-v1/report.json"
        )
        with (
            TemporaryDirectory() as directory,
            patch("scripts.evaluate.AgentRunner") as runner,
            patch("scripts.evaluate.SopService") as retrieval,
        ):
            result = rescore(source, Path(directory) / "rescored")
            runner.assert_not_called()
            retrieval.assert_not_called()
            original = json.loads(source.read_text())
            self.assertEqual(result["generation_provenance"], original["provenance"])
            self.assertEqual(
                result["metrics"]["agent_cost_usd"],
                original["metrics"]["agent_cost_usd"],
            )
            self.assertEqual(result["metrics"]["agent"]["passed"], 12)
            self.assertEqual(
                result["release_gate"]["publication_status"], "human_review_required"
            )
