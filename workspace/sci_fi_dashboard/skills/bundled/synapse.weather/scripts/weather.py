"""
Entry point for synapse.weather skill.

Fetches real-time weather via the free Open-Meteo API (no API key required).
Returns a SkillResult-compatible object with context_block and source_urls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class WeatherResult:
    context_block: str
    source_urls: list[str] = field(default_factory=list)
    error: str = ""


async def get_weather_context(user_message: str, session_context: dict | None) -> WeatherResult:
    """
    Extract city from user_message, geocode it with Open-Meteo, fetch current weather,
    and return formatted context for the LLM.
    """
    import httpx  # lazy import — avoids module-level dep at skill-loader scan

    city = _extract_city(user_message)
    if not city:
        return WeatherResult(
            context_block="",
            error="Could not detect a city name in the message.",
        )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Step 1: Geocode
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "format": "json"},
            )
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            results = geo_data.get("results")
            if not results:
                return WeatherResult(
                    context_block="",
                    error=f"City not found: {city!r}",
                )

            location = results[0]
            lat = location["latitude"]
            lon = location["longitude"]
            place_name = location.get("name", city)
            country = location.get("country", "")

            # Step 2: Current weather
            wx_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": "true",
                },
            )
            wx_resp.raise_for_status()
            wx_data = wx_resp.json()

            cw = wx_data.get("current_weather", {})
            temp_c = cw.get("temperature")
            wind_kph = cw.get("windspeed")
            wmo_code = cw.get("weathercode")

            temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else None

            context_block = (
                f"Weather data for {place_name}, {country}:\n"
                f"- Temperature: {temp_c}°C / {temp_f}°F\n"
                f"- Wind speed: {wind_kph} km/h\n"
                f"- WMO weather code: {wmo_code}\n"
                f"- Coordinates: {lat}, {lon}\n"
                f"Source: Open-Meteo (https://open-meteo.com)"
            )

            return WeatherResult(
                context_block=context_block,
                source_urls=["https://open-meteo.com"],
            )

    except httpx.HTTPStatusError as exc:
        return WeatherResult(
            context_block="",
            error=f"HTTP error fetching weather: {exc.response.status_code}",
        )
    except Exception as exc:  # noqa: BLE001
        return WeatherResult(
            context_block="",
            error=f"Unexpected error: {exc}",
        )


def _extract_city(text: str) -> str:
    """
    Pull a city name from natural-language weather queries.

    Patterns handled:
      "weather in London"
      "temperature in New York"
      "forecast for Paris"
      "how's the weather in Tokyo"
      "London weather"
    """
    text = text.strip()

    # "… in <City>" or "… for <City>"
    m = re.search(
        r"\b(?:weather|temperature|forecast|conditions?)\s+(?:in|for)\s+([A-Za-z\s\-']+?)(?:\?|$|,|\.|!)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # "in <City>" — more generic
    m = re.search(r"\bin\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)", text)
    if m:
        return m.group(1).strip()

    # "for <City>"
    m = re.search(r"\bfor\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)", text)
    if m:
        return m.group(1).strip()

    # "<City> weather"
    m = re.search(
        r"^([A-Za-z\s\-']+?)\s+(?:weather|temperature|forecast)", text, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    return ""
