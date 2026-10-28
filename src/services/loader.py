from pathlib import Path
import pandas as pd
from sqlalchemy import inspect
from src.config import Settings
from src.services.database import create_sql_engine

LEGACY_MAPPING = {
    "timestamp": "TS_UTC",
    "vehicle_gps_latitude": "V_LAT",
    "vehicle_gps_longitude": "V_LON",
    "iot_temperature": "IOT_TEMP_VAL_C",
    "cargo_condition_status": "CGO_COND_CD",
    "risk_classification": "RISK_CLS_TXT",
    "delay_probability": "DELAY_PROB_DEC",
    "port_congestion_level": "PRT_CNG_LVL",
    "route_risk_level": "RT_RSK_IDX",
}


def prepare_telemetry(path: Path):
    frame = pd.read_csv(path)
    missing = set(LEGACY_MAPPING) - set(frame.columns)
    if missing:
        raise ValueError("Telemetry CSV missing columns: " + ", ".join(sorted(missing)))
    result = frame[list(LEGACY_MAPPING)].rename(columns=LEGACY_MAPPING)
    result["SYS_INGEST_FLAG"] = "Y"
    return result


def load_telemetry(settings: Settings, *, engine=None, replace=False):
    frame = prepare_telemetry(settings.resolve_path(settings.telemetry_csv_path))
    own_engine = engine is None
    engine = engine if engine is not None else create_sql_engine(settings, admin=True)
    try:
        if (
            inspect(engine).has_table("TBL_SC_FLEET_HIST_RAW", schema="dbo")
            and not replace
        ):
            raise ValueError(
                "Raw table already exists. Explicit --replace is required to replace this project's table."
            )
        with engine.begin() as conn:
            frame.to_sql(
                "TBL_SC_FLEET_HIST_RAW",
                conn,
                schema="dbo",
                if_exists="replace" if replace else "fail",
                index=False,
            )
        return len(frame)
    finally:
        if own_engine:
            engine.dispose()
