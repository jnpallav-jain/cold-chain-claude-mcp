from dataclasses import dataclass
import math
import requests
from src.config import Settings
from src.services.errors import ServiceError


@dataclass(frozen=True)
class CorridorConditions:
    latitude: float
    longitude: float
    temperature_c: float
    wind_kmh: float
    observed_at: str
    disruption_index: float
    status: str
    interpretation: str = (
        "Wind-based demonstration heuristic; not measured traffic congestion."
    )


class WeatherService:
    def __init__(self, settings: Settings, *, http=None):
        self.settings = settings
        self.http = http if http is not None else requests

    def fetch(self, latitude: float, longitude: float) -> CorridorConditions:
        if not (
            math.isfinite(latitude)
            and math.isfinite(longitude)
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
        ):
            raise ServiceError(
                "Coordinates must be finite and within valid latitude/longitude ranges."
            )
        try:
            response = self.http.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current_weather": "true",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "timezone": "UTC",
                },
                timeout=self.settings.weather_timeout,
            )
            response.raise_for_status()
            payload = response.json()["current_weather"]
            temperature, wind = (
                float(payload["temperature"]),
                float(payload["windspeed"]),
            )
            if not math.isfinite(temperature) or not math.isfinite(wind):
                raise ValueError("Nonfinite weather values")
            return CorridorConditions(
                latitude,
                longitude,
                temperature,
                wind,
                payload["time"] + " UTC",
                8.5 if wind > 10 else 2.5,
                "High Transit Disruption" if wind > 10 else "Corridor Normal",
            )
        except Exception:
            raise ServiceError(
                "Weather service unavailable or returned invalid readings."
            ) from None
