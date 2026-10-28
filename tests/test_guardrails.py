import asyncio
import json
import threading
import unittest
from unittest.mock import Mock
from src.config import Settings
from src.security.sql_policy import validate_query, SqlPolicyError
from src.security.redaction import Redactor, StreamingRedactor
from src.security.execution import BoundedWorkers, RequestBudget, ToolTimedOut
from src.agent_tools import build_mcp_tools, tool_result
from src.services.container import Services
from src.services.telemetry import TelemetryResult, TelemetryService
from src.services.errors import ServiceError, TransientServiceError

VIEW = "FDE_VIEWS.VW_ACTIVE_FLEET"


class SqlPolicyTests(unittest.TestCase):
    def test_supported_queries_and_top_clamping(self):
        supported = [
            f"SELECT * FROM {VIEW}",
            f"SELECT TOP 100 Latitude, Longitude FROM {VIEW} ORDER BY Latitude DESC",
            f"SELECT COUNT(*) AS breach_count FROM {VIEW} WHERE Current_Temperature_C > 4",
            f"SELECT Risk_Classification, AVG(Current_Temperature_C) AS avg_temp FROM {VIEW} GROUP BY Risk_Classification HAVING COUNT(*) > 0 ORDER BY avg_temp",
            f"SELECT f.Latitude FROM {VIEW} f WHERE f.Longitude BETWEEN -120 AND -110",
            f"SELECT [Timestamp] FROM {VIEW} WHERE Risk_Classification IN ('High Risk','Low Risk')",
            f"SELECT Latitude FROM {VIEW} WHERE Risk_Classification = 'semi;colon'",
        ]
        for sql in supported:
            with self.subTest(sql=sql):
                result = validate_query(sql, row_limit=10)
                self.assertIn("TOP 10", result.sql)
        self.assertIn("TOP 2", validate_query(f"SELECT TOP 2 * FROM {VIEW}").sql)

    def test_wildcard_expansion_does_not_expose_future_view_columns(self):
        from sqlglot import exp

        query = validate_query(f"SELECT * FROM {VIEW}")
        self.assertEqual(len(query.expression.expressions), 9)
        self.assertFalse(
            any(isinstance(item, exp.Star) for item in query.expression.expressions)
        )
        self.assertIn("Current_Temperature_C", query.sql)
        self.assertIn("COUNT(*)", validate_query(f"SELECT COUNT(*) FROM {VIEW}").sql)

    def test_untrusted_statements_and_constructs_are_rejected(self):
        rejected = [
            f"SELECT * FROM {VIEW}; DELETE FROM dbo.TBL_SC_FLEET_HIST_RAW",
            f"SELECT * FROM {VIEW};;",
            f"DELETE FROM {VIEW}",
            "WAITFOR DELAY '00:00:10'",
            "SELECT * FROM dbo.TBL_SC_FLEET_HIST_RAW",
            "SELECT * FROM sys.objects",
            "SELECT * FROM master.FDE_VIEWS.VW_ACTIVE_FLEET",
            f"SELECT * INTO dbo.copy FROM {VIEW}",
            f"SELECT * FROM {VIEW} a CROSS JOIN {VIEW} b",
            f"SELECT * FROM {VIEW} WHERE Latitude IN (SELECT Latitude FROM {VIEW})",
            f"WITH x AS (SELECT * FROM {VIEW}) SELECT * FROM x",
            f"SELECT * FROM {VIEW} UNION SELECT * FROM {VIEW}",
            f"SELECT @@VERSION FROM {VIEW}",
            f"SELECT DB_NAME() FROM {VIEW}",
            f"SELECT dbo.secret_function() FROM {VIEW}",
            f"SELECT UnknownColumn FROM {VIEW}",
            f"SELECT evil.Latitude FROM {VIEW} f",
            f"SELECT TOP 1 PERCENT * FROM {VIEW}",
            f"SELECT TOP 1 WITH TIES * FROM {VIEW} ORDER BY Latitude",
            f"SELECT * FROM {VIEW} WITH (NOLOCK)",
            f"SELECT * FROM {VIEW} -- disregard policy",
            f"SELECT /* ignore */ * FROM {VIEW}",
            f"SELECT ROW_NUMBER() OVER (ORDER BY Latitude) FROM {VIEW}",
            f"SELECT CAST(Latitude AS VARCHAR(100)) FROM {VIEW}",
            "SELECT 1",
        ]
        for sql in rejected:
            with self.subTest(sql=sql), self.assertRaises(SqlPolicyError):
                validate_query(sql)

    def test_policy_rejection_does_not_create_a_connection(self):
        engine = Mock()
        with self.assertRaises(SqlPolicyError):
            TelemetryService(Settings(_env_file=None), engine=engine).query(
                "SELECT * FROM sys.objects"
            )
        engine.raw_connection.assert_not_called()

    def test_query_size_literal_size_and_complexity_limits(self):
        for sql in [
            "X" * 8001,
            f"SELECT Latitude FROM {VIEW} WHERE Risk_Classification='"
            + "a" * 257
            + "'",
            f"SELECT * FROM {VIEW} WHERE "
            + " OR ".join("Latitude=1" for _ in range(100)),
        ]:
            with self.assertRaises(SqlPolicyError):
                validate_query(sql)


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.secret = "secret-anthropic-credential-123456"
        self.redactor = Redactor(
            Settings(
                _env_file=None,
                anthropic_api_key=self.secret,
                sql_agent_password="pass-123456",
            )
        )

    def test_nested_values_and_connection_details_are_masked(self):
        result = self.redactor.data(
            {
                "nested": [
                    self.secret,
                    "DRIVER=ODBC;UID=sa;PWD=pass-123456;",
                    "pcsk_abcdefghijklmnop",
                ]
            }
        )
        encoded = json.dumps(result)
        self.assertNotIn(self.secret, encoded)
        self.assertNotIn("pass-123456", encoded)
        self.assertNotIn("UID=sa", encoded)
        self.assertNotIn("pcsk_", encoded)

    def test_every_possible_delta_split_keeps_secret_out_of_stream(self):
        source = "prefix " + self.secret + " suffix"
        for split in range(len(source) + 1):
            stream = StreamingRedactor(self.redactor)
            result = (
                stream.feed(source[:split])
                + stream.feed(source[split:])
                + stream.flush()
            )
            self.assertNotIn(self.secret, result)
            self.assertEqual(result, "prefix [REDACTED] suffix")

    def test_output_limit_returns_valid_error_json(self):
        result = tool_result(
            {"data": "a" * 2000}, redactor=self.redactor, max_bytes=512
        )
        self.assertTrue(result["is_error"])
        self.assertFalse(json.loads(result["content"][0]["text"])["ok"])
        self.assertLess(len(result["content"][0]["text"].encode()), 512)


class RetrievalDeadlineAdapterTests(unittest.TestCase):
    def test_langchain_vectorstore_keeps_config_and_passes_native_timeout(self):
        from types import SimpleNamespace
        from langchain_pinecone import PineconeVectorStore
        from src.services.sop import TimedQueryIndex

        index = Mock()
        index.config = SimpleNamespace(
            host="https://test-index.example", api_key="test-key"
        )
        index.query.return_value = {
            "matches": [
                {
                    "id": "rule",
                    "score": 0.9,
                    "metadata": {"text": "Rule text", "source_file": "sample.md"},
                }
            ]
        }
        embedding = Mock()
        embedding.embed_query.return_value = [0.1] * 1024
        store = PineconeVectorStore(
            index=TimedQueryIndex(index, 4), embedding=embedding, namespace="sop-v1"
        )
        docs = store.similarity_search("temperature", k=2)
        self.assertEqual(docs[0].metadata["source_file"], "sample.md")
        self.assertEqual(index.query.call_args.kwargs["_request_timeout"], (3, 4))
        self.assertEqual(index.query.call_args.kwargs["namespace"], "sop-v1")


class WorkerBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_retains_capacity_until_real_operation_stops(self):
        pool = BoundedWorkers(1)
        release = threading.Event()
        try:
            with self.assertRaises(ToolTimedOut):
                await pool.run(lambda: release.wait(1), seconds=0.01)
            with self.assertRaisesRegex(ServiceError, "busy"):
                await pool.run(lambda: 1, seconds=1)
        finally:
            release.set()
            await asyncio.sleep(0.03)
        self.assertEqual(await pool.run(lambda: 42, seconds=1), 42)

    async def test_tool_deadline_calls_cancellation_handle(self):
        pool = BoundedWorkers(1)
        release = threading.Event()
        cancel = Mock(side_effect=release.set)
        with self.assertRaises(ToolTimedOut):
            await pool.run(lambda: release.wait(1), seconds=0.01, cancel=cancel)
        cancel.assert_called_once()
        await asyncio.sleep(0.01)

    async def test_request_call_and_time_budgets(self):
        budget = RequestBudget(1, 1)
        self.assertGreater(budget.reserve(), 0)
        with self.assertRaisesRegex(ServiceError, "call budget"):
            budget.reserve()
        budget = RequestBudget(-1, 1)
        with self.assertRaisesRegex(ServiceError, "deadline"):
            budget.reserve()

    async def test_retry_is_bounded_and_only_for_completed_transient_reads(self):
        services = Services(Mock(), Mock(), Mock(), Mock())
        services.sop.search.side_effect = [TransientServiceError("Temporary"), []]
        config = Settings(_env_file=None, tool_max_attempts=2)
        tool = {item.name: item for item in build_mcp_tools(services, settings=config)}[
            "search_compliance_sop"
        ]
        result = await tool.handler({"query": "rule"})
        self.assertFalse(result["is_error"])
        self.assertEqual(services.sop.search.call_count, 2)
        services.sop.search.side_effect = ServiceError("Permanent")
        result = await tool.handler({"query": "rule"})
        self.assertTrue(result["is_error"])
        self.assertEqual(services.sop.search.call_count, 3)

    async def test_tool_call_budget_is_shared_across_registered_tools(self):
        services = Services(Mock(), Mock(), Mock(), Mock())
        services.telemetry.query.return_value = TelemetryResult(
            ["Latitude"], [(33.77,)]
        )
        config = Settings(_env_file=None, claude_max_tool_calls=1)
        tools = {item.name: item for item in build_mcp_tools(services, settings=config)}
        first = await tools["query_telemetry_db"].handler(
            {"sql_query": f"SELECT Latitude FROM {VIEW}"}
        )
        self.assertFalse(first["is_error"])
        second = await tools["search_compliance_sop"].handler({"query": "rules"})
        self.assertTrue(second["is_error"])
        self.assertIn("budget exhausted", second["content"][0]["text"])
        services.sop.search.assert_not_called()

    async def test_tool_results_are_redacted_before_returning_to_model(self):
        services = Services(Mock(), Mock(), Mock(), Mock())
        secret = "private-agent-password"
        services.telemetry.query.return_value = TelemetryResult(
            ["Risk_Classification"], [(secret,)]
        )
        config = Settings(_env_file=None, sql_agent_password=secret)
        tool = {item.name: item for item in build_mcp_tools(services, settings=config)}[
            "query_telemetry_db"
        ]
        result = await tool.handler(
            {"sql_query": f"SELECT Risk_Classification FROM {VIEW}"}
        )
        self.assertNotIn(secret, json.dumps(result))
        self.assertIn("[REDACTED]", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
