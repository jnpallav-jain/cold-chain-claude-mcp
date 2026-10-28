from dataclasses import dataclass
from functools import lru_cache
from src.config import get_settings
from src.services.telemetry import TelemetryService
from src.services.weather import WeatherService
from src.services.sop import SopService
from src.services.audit import AuditService
from src.services.approvals import ApprovalService


@dataclass(frozen=True)
class Services:
    telemetry: TelemetryService
    weather: WeatherService
    sop: SopService
    audit: AuditService
    approvals: ApprovalService | None = None


@lru_cache(maxsize=1)
def get_services():
    settings = get_settings()
    return Services(
        TelemetryService(settings),
        WeatherService(settings),
        SopService(settings),
        AuditService(settings),
        ApprovalService(settings),
    )
