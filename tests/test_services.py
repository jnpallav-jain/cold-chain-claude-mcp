import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from sqlalchemy import create_engine, text
from src.config import Settings, ConfigurationError, PROJECT_ROOT
from src.services.telemetry import TelemetryService
from src.services.weather import WeatherService
from src.services.sop import SopService, describe_compatible_index
from src.services.audit import AuditService, AuditEvent
from src.services.errors import ServiceError
from src.services.loader import prepare_telemetry
from src.services.ingestion import ingest_policy


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


class ConfigurationTests(unittest.TestCase):
    def test_original_resource_names_are_rejected(self):
        for override in (
            {"sql_database": "master"},
            {"sql_database": "original"},
            {"pinecone_index_name": "fde-sop-index-local"},
            {"sql_agent_user": "USR_FDE_RO"},
        ):
            with self.subTest(override=override), self.assertRaises(ValueError):
                config(**override)

    def test_missing_credentials_fail_only_when_required(self):
        settings = config()
        with self.assertRaisesRegex(ConfigurationError, "SQL_AGENT_PASSWORD"):
            settings.require("sql_agent_password")
        self.assertEqual(
            settings.resolve_path(Path("data/policy")), PROJECT_ROOT / "data/policy"
        )

    def test_secret_fields_are_not_in_repr(self):
        self.assertNotIn(
            "very-secret-test", repr(config(pinecone_api_key="very-secret-test"))
        )

    def test_openai_requires_separate_index(self):
        with self.assertRaises(ValueError):
            config(embedding_mode="OPENAI")

    def test_adapter_import_has_no_network_or_model_initialization(self):
        code = "import sys; import src.agent_tools; assert 'langchain_huggingface' not in sys.modules; assert 'pinecone' not in sys.modules; assert 'streamlit' not in sys.modules"
        subprocess.run([sys.executable, "-c", code], check=True, cwd=PROJECT_ROOT)


class SqlServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS FDE_VIEWS")
            conn.exec_driver_sql(
                "CREATE TABLE FDE_VIEWS.VW_ACTIVE_FLEET (Current_Temperature_C FLOAT)"
            )
            conn.exec_driver_sql(
                "INSERT INTO FDE_VIEWS.VW_ACTIVE_FLEET VALUES (2.5),(7.0),(4.0)"
            )
            conn.exec_driver_sql(
                "CREATE TABLE FDE_VIEWS.AgentAuditLog (SessionID TEXT,NodeExecuted TEXT,ToolName TEXT,Content TEXT)"
            )

    def tearDown(self):
        self.engine.dispose()

    def test_query_returns_columns_and_bounded_rows(self):
        result = TelemetryService(config(sql_row_limit=1), engine=self.engine).query(
            "SELECT Current_Temperature_C FROM FDE_VIEWS.VW_ACTIVE_FLEET ORDER BY Current_Temperature_C"
        )
        self.assertEqual(result.columns, ["Current_Temperature_C"])
        self.assertEqual(result.rows, [(2.5,)])

    def test_empty_result(self):
        result = TelemetryService(config(), engine=self.engine).query(
            "SELECT * FROM FDE_VIEWS.VW_ACTIVE_FLEET WHERE Current_Temperature_C>50"
        )
        self.assertEqual(result.rows, [])

    def test_non_select_is_rejected_before_engine_creation(self):
        with self.assertRaisesRegex(ServiceError, "SECURITY BLOCK"):
            TelemetryService(config()).query("DELETE FROM FDE_VIEWS.VW_ACTIVE_FLEET")

    def test_database_error_is_sanitized(self):
        with self.assertRaises(ServiceError) as caught:
            TelemetryService(config(), engine=self.engine).query(
                "SELECT * FROM nonexistent"
            )
        self.assertNotIn("nonexistent", str(caught.exception))

    def test_audit_uses_bound_values_and_persists_outside_ui(self):
        service = AuditService(config(), engine=self.engine)
        content = "'); DROP TABLE AgentAuditLog; --"
        service.write(AuditEvent("session", "tools", "query_telemetry_db", content))
        with self.engine.connect() as conn:
            self.assertEqual(
                conn.execute(
                    text("SELECT Content FROM FDE_VIEWS.AgentAuditLog")
                ).scalar(),
                content,
            )
        with self.assertRaises(ServiceError):
            service.read_recent()


class RetrievalAndWeatherTests(unittest.TestCase):
    def test_weather_request_and_heuristic_are_explicit(self):
        response = Mock()
        response.json.return_value = {
            "current_weather": {
                "temperature": 28,
                "windspeed": 15,
                "time": "2025-01-01T10:00",
            }
        }
        http = Mock()
        http.get.return_value = response
        result = WeatherService(config(), http=http).fetch(33.77, -118.19)
        self.assertEqual(result.disruption_index, 8.5)
        self.assertIn("not measured traffic", result.interpretation)
        self.assertEqual(http.get.call_args.kwargs["timeout"], 6)
        self.assertEqual(http.get.call_args.kwargs["params"]["timezone"], "UTC")

    def test_weather_invalid_coords_do_not_call_http(self):
        http = Mock()
        with self.assertRaises(ServiceError):
            WeatherService(config(), http=http).fetch(float("nan"), 0)
        http.get.assert_not_called()

    def test_weather_failure_is_sanitized(self):
        http = Mock()
        http.get.side_effect = RuntimeError("secret request content")
        with self.assertRaises(ServiceError) as caught:
            WeatherService(config(), http=http).fetch(0, 0)
        self.assertNotIn("secret", str(caught.exception))

    def test_sop_preserves_source_and_handles_empty_results(self):
        retriever = Mock()
        retriever.invoke.return_value = [
            SimpleNamespace(
                page_content="Keep below 4 C", metadata={"source_file": "rules.md"}
            )
        ]
        service = SopService(config(), retriever=retriever)
        result = service.search("temperature rules")
        self.assertEqual(result[0].metadata["source_file"], "rules.md")
        retriever.invoke.return_value = []
        self.assertEqual(service.search("unknown"), [])
        with self.assertRaises(ServiceError):
            service.search(" ")

    def test_sop_failure_is_sanitized(self):
        retriever = Mock()
        retriever.invoke.side_effect = RuntimeError("secret")
        with self.assertRaisesRegex(ServiceError, "SOP retrieval unavailable"):
            SopService(config(), retriever=retriever).search("rules")

    def test_dimension_mismatch_never_deletes_index(self):
        client = Mock()
        client.describe_index.return_value = SimpleNamespace(
            dimension=1536, metric="cosine"
        )
        with self.assertRaisesRegex(ServiceError, "Automatic deletion is disabled"):
            describe_compatible_index(config(), client)
        client.delete_index.assert_not_called()

    def test_synthetic_loader_mapping(self):
        result = prepare_telemetry(PROJECT_ROOT / "data/sample/synthetic_fleet.csv")
        self.assertEqual(len(result), 4)
        self.assertIn("IOT_TEMP_VAL_C", result.columns)
        self.assertNotIn("iot_temperature", result.columns)
        self.assertEqual(set(result["SYS_INGEST_FLAG"]), {"Y"})


class IngestionTests(unittest.TestCase):
    def test_retry_cache_is_scoped_and_failed_upload_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policies = root / "policies"
            policies.mkdir()
            doc = policies / "policy.md"
            doc.write_text("# Temperature\nKeep below 4 C.\n")
            settings = config(policy_dir=policies)
            store, index = Mock(), Mock()
            with patch("src.services.ingestion.PROJECT_ROOT", root):
                result = ingest_policy(
                    settings, store=store, index=index, resource_identity="host-one"
                )
                self.assertEqual(result["processed"], 1)
                self.assertEqual(
                    store.add_documents.call_args.kwargs["namespace"], "sop-v1"
                )
                cache = list((root / "data/cache").glob("*.json"))[0]
                before = cache.read_text()
                self.assertEqual(
                    ingest_policy(
                        settings, store=store, index=index, resource_identity="host-one"
                    )["skipped"],
                    1,
                )
                doc.write_text("# Temperature\nChanged rule.\n")
                store.add_documents.side_effect = RuntimeError(
                    "temporary upload failure"
                )
                with self.assertRaises(RuntimeError):
                    ingest_policy(
                        settings, store=store, index=index, resource_identity="host-one"
                    )
                self.assertEqual(cache.read_text(), before)
                index.delete.assert_not_called()
                store.add_documents.side_effect = None
                self.assertEqual(
                    ingest_policy(
                        settings, store=store, index=index, resource_identity="host-one"
                    )["processed"],
                    1,
                )
                index.delete.assert_called()
                self.assertEqual(
                    ingest_policy(
                        settings, store=store, index=index, resource_identity="host-two"
                    )["processed"],
                    1,
                )
                self.assertEqual(len(list((root / "data/cache").glob("*.json"))), 2)

    def test_deleted_file_cleanup_failure_is_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policies = root / "policies"
            policies.mkdir()
            doc = policies / "policy.txt"
            doc.write_text("Keep cargo cool.")
            settings = config(policy_dir=policies)
            store, index = Mock(), Mock()
            with patch("src.services.ingestion.PROJECT_ROOT", root):
                ingest_policy(
                    settings, store=store, index=index, resource_identity="host-one"
                )
                cache = list((root / "data/cache").glob("*.json"))[0]
                before = cache.read_text()
                doc.unlink()
                index.delete.side_effect = RuntimeError("temporary delete failure")
                with self.assertRaises(RuntimeError):
                    ingest_policy(
                        settings, store=store, index=index, resource_identity="host-one"
                    )
                self.assertEqual(cache.read_text(), before)
                index.delete.side_effect = None
                self.assertEqual(
                    ingest_policy(
                        settings, store=store, index=index, resource_identity="host-one"
                    )["removed"],
                    1,
                )
                self.assertEqual(json.loads(cache.read_text())["files"], {})


if __name__ == "__main__":
    unittest.main()
