"""
Extension for the Belchertown skin.
This extension builds search list extensions as well
as a crude "cron" to download necessary files.

Pat O'Brien, August 19, 2018
"""

import calendar
import datetime
import html
import json
import locale
import logging
import math
import os
import fnmatch
import re
import time
import xml.etree.ElementTree as ET
from urllib.request import Request, urlopen
import urllib.error
from collections import OrderedDict
from math import asin, atan2, cos, degrees, radians, sin, sqrt
from re import findall, match, sub

import configobj
import weeutil.weeutil
import weewx
import weewx.reportengine
import weewx.tags
import weewx.units
from weeutil.config import accumulateLeaves
from weeutil.weeutil import (
    TimeSpan,
    archiveDaySpan,
    archiveMonthSpan,
    archiveSpanSpan,
    archiveWeekSpan,
    archiveYearSpan,
    isStartOfDay,
    startOfDay,
    to_bool,
    to_float,
    to_int,
)
from weewx.cheetahgenerator import SearchList
from weewx.tags import TimespanBinder

if weewx.__version__ < "5":
    raise weewx.UnsupportedFeature(
        f"WeeWX 5 and newer is required, found {weewx.__version__}"
    )

log = logging.getLogger(__name__)

# Print version in syslog for easier troubleshooting
VERSION = "2.0beta3-new-belchertown"
log.info(f"version {VERSION}")

# Default timeout for all HTTP requests (seconds)
DEFAULT_HTTP_TIMEOUT = 15

# HTTP Headers for different services
HTTP_HEADERS = {
    "PIRATE_WEATHER": {
        "User-Agent": "weewx-belchertown-new/pirateweather",
        "Connection": "keep-alive",
    },
    "AERIS_WEATHER": {
        "User-Agent": "weewx-belchertown-new/aerisweather",
        "Connection": "keep-alive",
    },
    "NWS_WEATHER": {
        "User-Agent": "weewx-belchertown-new (contact: https://github.com/uajqq/weewx-belchertown-new)",
        "Accept": "application/geo+json",
        "Connection": "keep-alive",
    },
    "OPEN_METEO": {
        "User-Agent": "weewx-belchertown-new/open-meteo",
        "Connection": "keep-alive",
    },
    "METEOALARM": {
        "User-Agent": "weewx-belchertown-new/meteoalarm",
        "Accept": "application/atom+xml, application/xml, text/xml",
        "Connection": "keep-alive",
    },
}

METEOALARM_COUNTRY_SLUG_BY_CODE = {
    "AD": "andorra",
    "AT": "austria",
    "BA": "bosnia-herzegovina",
    "BE": "belgium",
    "BG": "bulgaria",
    "CH": "switzerland",
    "CY": "cyprus",
    "CZ": "czechia",
    "DE": "germany",
    "DK": "denmark",
    "EE": "estonia",
    "ES": "spain",
    "FI": "finland",
    "FR": "france",
    "GB": "united-kingdom",
    "GR": "greece",
    "HR": "croatia",
    "HU": "hungary",
    "IE": "ireland",
    "IL": "israel",
    "IS": "iceland",
    "IT": "italy",
    "LT": "lithuania",
    "LU": "luxembourg",
    "LV": "latvia",
    "MD": "moldova",
    "ME": "montenegro",
    "MK": "republic-of-north-macedonia",
    "MT": "malta",
    "NL": "netherlands",
    "NO": "norway",
    "PL": "poland",
    "PT": "portugal",
    "RO": "romania",
    "RS": "serbia",
    "SE": "sweden",
    "SI": "slovenia",
    "SK": "slovakia",
    "UA": "ukraine",
    "UK": "united-kingdom",
}

METEOALARM_COUNTRY_SLUG_ALIASES = {
    "bosnia-and-herzegovina": "bosnia-herzegovina",
    "czech-republic": "czechia",
    "great-britain": "united-kingdom",
    "north-macedonia": "republic-of-north-macedonia",
    "uk": "united-kingdom",
    "united-kingdom-of-great-britain-and-northern-ireland": "united-kingdom",
}

# Shared AQI/pollutant extraction map for forecast/current-condition fallback.
AQI_OBS_MAP = {
    "aqi": {"pollutant": None, "value_key": "aqi"},
    "pm2_5": {"pollutant": "pm2.5", "value_key": "valueUGM3"},
    "pm10": {"pollutant": "pm10", "value_key": "valueUGM3"},
    "o3": {"pollutant": "o3", "value_key": "valuePPB"},
    "co": {"pollutant": "co", "value_key": "valuePPB"},
    "no2": {"pollutant": "no2", "value_key": "valuePPB"},
    "so2": {"pollutant": "so2", "value_key": "valuePPB"},
}

DEFAULT_DIRECTION_LABELS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

WINDROSE_UNIT_ALIASES = {
    "mile_per_hour": "mile_per_hour",
    "mile_per_hour2": "mile_per_hour",
    "km_per_hour": "km_per_hour",
    "km_per_hour2": "km_per_hour",
    "meter_per_second": "meter_per_second",
    "meter_per_second2": "meter_per_second",
    "knot": "knot",
    "knot2": "knot",
    "beaufort": "beaufort",
}

WINDROSE_THRESHOLDS = {
    "mile_per_hour": [1, 4, 8, 13, 19, 25],
    "km_per_hour": [2, 6, 12, 20, 29, 39],
    "meter_per_second": [0.5, 1.6, 3.4, 5.6, 8, 10.8],
    "knot": [1, 4, 7, 11, 17, 22],
    "beaufort": [2, 3, 4, 5, 6, 7],
}

WINDROSE_SPEED_RANGE_LABELS = {
    "mile_per_hour": ["< 1", "1-3", "4-7", "8-12", "13-18", "19-24", "25+"],
    "km_per_hour": ["< 2", "2-5", "6-11", "12-19", "20-28", "29-38", "39+"],
    "meter_per_second": [
        "< 0.5",
        "0.5-1.5",
        "1.6-3.3",
        "3.4-5.5",
        "5.5-7.9",
        "8-10.7",
        "10.8+",
    ],
    "knot": ["< 1", "1-3", "4-6", "7-10", "11-16", "17-21", "22+"],
    "beaufort": ["0", "1", "2", "3", "4", "5", "6+"],
}

# Cached minifier dependency status: (all_available: bool, missing: tuple[str, ...])
_MINIFIER_DEPS_STATUS = None
_MINIFIER_DEPS_MISSING_LOGGED = False

EXTERNAL_STATION_OBSERVATION_SOURCES = {
    "visibility": {"source_key": "current_conditions"},
    "cloud_cover": {"source_key": "current_conditions"},
    "aqi": {"source_key": "aqi"},
}


# Module-level helper functions for HTTP and JSON processing


def _http_get_json(url, headers=None, timeout=DEFAULT_HTTP_TIMEOUT):
    """Fetch JSON data from an HTTP endpoint and parse as UTF-8 JSON."""
    req_headers = headers or HTTP_HEADERS["PIRATE_WEATHER"]
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_text(url, headers=None, timeout=DEFAULT_HTTP_TIMEOUT):
    """Fetch text from an HTTP endpoint."""
    req_headers = headers or HTTP_HEADERS["PIRATE_WEATHER"]
    req = Request(url, headers=req_headers)
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, "replace")


def _get_minifier_dependency_status():
    """Return minifier dependency status, cached for this process."""

    global _MINIFIER_DEPS_STATUS
    if _MINIFIER_DEPS_STATUS is not None:
        return _MINIFIER_DEPS_STATUS

    missing = []
    for module_name in ("rjsmin", "rcssmin"):
        try:
            __import__(module_name)
        except Exception:
            missing.append(module_name)

    _MINIFIER_DEPS_STATUS = (len(missing) == 0, tuple(missing))
    return _MINIFIER_DEPS_STATUS


def _log_minifier_missing_error_once(missing_modules):
    """Log a single error when minification is enabled but deps are missing."""

    global _MINIFIER_DEPS_MISSING_LOGGED
    if _MINIFIER_DEPS_MISSING_LOGGED:
        return

    module_list = ", ".join(missing_modules)
    log.warning(
        "Belchertown minify: required package(s) not installed: "
        f"{module_list}. Falling back to built-in CSS minifying and JS copies."
    )
    _MINIFIER_DEPS_MISSING_LOGGED = True


def _extract_fields(source, fields):
    """Extract specified fields from a source dictionary."""
    return {field: source.get(field) for field in fields}


def _compact_alert_title(*candidates, default="Alert"):
    """Return the shortest useful alert title from provider-specific values."""
    for candidate in candidates:
        if candidate is None:
            continue
        title = sub(r"\s+", " ", str(candidate)).strip()
        if not title:
            continue

        lower_title = title.lower()
        for marker in (
            " issued ",
            " updated ",
            " extended ",
            " continued ",
            " continues ",
            " remains in effect ",
            " in effect until ",
            " until ",
            " from ",
            " cancelled ",
            " canceled ",
        ):
            marker_index = lower_title.find(marker)
            if marker_index > 0:
                title = title[:marker_index].rstrip(" :-")
                break

        if title:
            return title

    return default


def _pw_transform_to_belch(pw):
    """Map Dark Sky-style JSON from Pirate Weather to the compact structure
    this skin uses: current, hourly[], daily[], alerts[].
    """
    CURRENT_FIELDS = [
        "summary", "icon", "temperature", "apparentTemperature", "windSpeed",
        "windGust", "windBearing", "humidity", "pressure", "visibility",
        "dewPoint", "precipIntensity", "precipProbability", "cloudCover",
        "time"
    ]
    HOURLY_FIELDS = [
        "time", "summary", "icon", "temperature", "apparentTemperature",
        "windSpeed", "windGust", "windBearing", "precipIntensity",
        "precipProbability", "cloudCover", "humidity", "dewPoint"
    ]
    DAILY_FIELDS = [
        "time", "summary", "icon", "temperatureHigh", "temperatureLow",
        "windSpeed", "windGust", "windBearing", "precipIntensity",
        "precipProbability", "cloudCover"
    ]
    ALERT_FIELDS = [
        "title", "expires", "description", "severity", "uri",
        "effective", "onset", "ends", "source",
    ]

    current_data = pw.get("currently") or {}
    hourly_list = (pw.get("hourly") or {}).get("data", [])
    daily_list = (pw.get("daily") or {}).get("data", [])
    alerts_list = pw.get("alerts") or []

    hourly_all = [_extract_fields(h, HOURLY_FIELDS) for h in hourly_list]
    hourly = _slice_from_current_period(hourly_all, 1)
    daily = [_extract_fields(d, DAILY_FIELDS) for d in daily_list]

    alerts = []
    for alert in alerts_list:
        alert = alert or {}
        compact_alert = _extract_fields(alert, ALERT_FIELDS)
        compact_alert["title"] = _compact_alert_title(
            alert.get("event"),
            alert.get("title"),
            alert.get("headline"),
        )
        compact_alert["effective"] = alert.get("time")
        compact_alert["onset"] = alert.get("time")
        compact_alert["ends"] = alert.get("expires")
        compact_alert["source"] = "pirateweather"
        alerts.append(compact_alert)

    return {
        "current": _extract_fields(current_data, CURRENT_FIELDS),
        "hourly": hourly,
        "threeHourly": _pick_three_hourly_from_current_period(hourly_all),
        "daily": daily,
        "alerts": alerts,
        "provider": "pirateweather",
        "schema": "belchertown.forecast.v1",
        "generated_at": int(time.time()),
    }


def _iso_to_epoch(value):
    """Convert an ISO timestamp to unix epoch seconds."""
    if not value:
        return None
    try:
        return int(datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def _write_json_file(file_path, payload):
    """Write JSON payload to disk, creating parent directory when needed."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))


def _write_current_conditions_from_forecast(forecast_file, current_conditions_file):
    """Write current_conditions.json from forecast.json current object."""
    with open(forecast_file, "r", encoding="utf-8") as rf:
        data_cc = json.load(rf)

    cc_out = {
        "timestamp": int(time.time()),
        "provider": data_cc.get("provider"),
        "source": "forecast",
        "current": [data_cc.get("current", {})],
    }
    _write_json_file(current_conditions_file, cc_out)


def _default_current_conditions_values():
    """Return blank/fallback values for template current-condition fields."""
    return "", "", "N/A", "", ""


def _normalize_current_conditions_values(
    current_conditions_data, forecast_units, cloud_cover_scale=1.0
):
    """Normalize current_conditions.json values for templates."""
    current_conditions_data = current_conditions_data or {}

    vis_val = current_conditions_data.get("visibility")
    if forecast_units in ("si", "ca"):
        visibility_unit = "km"
    else:
        visibility_unit = "miles"

    visibility_qualifier = current_conditions_data.get("visibilityQualifier") or ""
    if visibility_qualifier not in ("<", ">"):
        visibility_qualifier = ""

    if vis_val is not None:
        visibility = visibility_qualifier + locale.format_string("%g", float(vis_val))
    else:
        visibility = "N/A"

    raw_icon = current_conditions_data.get("icon", "") or ""
    current_obs_icon = raw_icon + ".png" if raw_icon else ""
    current_obs_summary = current_conditions_data.get("summary", "") or ""

    cc_cloud = current_conditions_data.get("cloudCover")
    if cc_cloud is None:
        cloud_cover = ""
    else:
        cloud_cover = f"{float(cc_cloud) * float(cloud_cover_scale):.0f}"

    return (
        current_obs_icon,
        current_obs_summary,
        visibility,
        visibility_unit,
        cloud_cover,
    )


def _load_normalized_current_conditions(
    current_conditions_file, forecast_units, cloud_cover_scale=1.0
):
    """Read current_conditions.json and return normalized template values."""
    with open(current_conditions_file, "r", encoding="utf-8") as read_file:
        data = json.load(read_file)

    current_conditions_data = data["current"][0]
    return _normalize_current_conditions_values(
        current_conditions_data,
        forecast_units,
        cloud_cover_scale=cloud_cover_scale,
    )


def _nws_quantity_value(quantity):
    """Extract numeric value from NWS quantity object."""
    if not isinstance(quantity, dict):
        return None
    value = _safe_float(quantity.get("value"))
    if value is not None:
        return value

    # Some NWS payloads provide only bounds while primary value is null.
    for fallback_key in ("minValue", "maxValue"):
        fallback_value = _safe_float(quantity.get(fallback_key))
        if fallback_value is not None:
            return fallback_value

    return None


def _nws_parse_metar_visibility(raw_message):
    """Parse METAR visibility in meters and return any display qualifier."""
    if not raw_message:
        return None

    text = str(raw_message).upper().strip()
    if not text:
        return None

    tokens = text.split()

    def _parse_num_or_fraction(value_text):
        value_text = str(value_text).strip()
        if not value_text:
            return None

        numeric = _safe_float(value_text)
        if numeric is not None:
            return numeric

        if "/" in value_text:
            parts = value_text.split("/", 1)
            if len(parts) == 2:
                numerator = _safe_float(parts[0])
                denominator = _safe_float(parts[1])
                if numerator is not None and denominator not in (None, 0):
                    return numerator / denominator

        return None

    for idx, token in enumerate(tokens):
        if not token.endswith("SM"):
            continue

        core = token[:-2].strip()
        if not core:
            continue

        is_less_than = core.startswith("M")
        is_greater_than = core.startswith("P")
        if is_less_than or is_greater_than:
            core = core[1:].strip()

        # Handle mixed-number visibility where integer and fraction are split
        # into separate tokens, e.g. "1 1/2SM".
        miles = None
        if "/" in core and idx > 0:
            whole = _parse_num_or_fraction(tokens[idx - 1])
            fraction = _parse_num_or_fraction(core)
            if whole is not None and fraction is not None:
                miles = whole + fraction

        if miles is None:
            miles = _parse_num_or_fraction(core)

        if miles is None:
            continue

        qualifier = ""

        # "M" means less-than; preserve a sane numeric approximation.
        if is_less_than:
            miles = max(miles, 0.0)
            qualifier = "<"

        # "P" means greater-than. In US METAR, 10SM is also the common
        # ceiling for "10 statute miles or more".
        if is_greater_than or miles >= 10.0:
            miles = max(miles, 0.0)
            qualifier = ">"

        return {
            "visibility_m": miles * 1609.344,
            "qualifier": qualifier,
        }

    return None


def _nws_parse_metar_visibility_m(raw_message):
    """Parse visibility in meters from a METAR rawMessage token like 10SM or 1 1/2SM."""
    parsed = _nws_parse_metar_visibility(raw_message)
    return parsed.get("visibility_m") if parsed else None


def _nws_visibility_quantity_qualifier(visibility_m):
    """Infer NWS METAR display qualifier from numeric visibility when raw METAR is unavailable."""
    value = _safe_float(visibility_m)
    if value is None:
        return ""

    # The NWS API can omit rawMessage but still expose 10SM as 16093.44 m.
    # In US METAR this is the normal cap for "10 statute miles or more".
    if value >= (10.0 * 1609.344) - 0.5:
        return ">"

    return ""


NWS_FORECAST_TARGET_TEMP_UNIT = {
    "si": "degree_C",
    "ca": "degree_C",
}

NWS_FORECAST_TARGET_SPEED_UNIT = {
    "si": "meter_per_second",
    "ca": "km_per_hour",
}


def _nws_parse_wind_direction(direction_value):
    """Parse NWS wind direction into compass degrees."""
    numeric = _safe_float(direction_value)
    if numeric is not None:
        return numeric

    if not direction_value:
        return None

    cardinal_to_degrees = {
        "N": 0.0,
        "NNE": 22.5,
        "NE": 45.0,
        "ENE": 67.5,
        "E": 90.0,
        "ESE": 112.5,
        "SE": 135.0,
        "SSE": 157.5,
        "S": 180.0,
        "SSW": 202.5,
        "SW": 225.0,
        "WSW": 247.5,
        "W": 270.0,
        "WNW": 292.5,
        "NW": 315.0,
        "NNW": 337.5,
    }
    return cardinal_to_degrees.get(str(direction_value).strip().upper())


def _nws_parse_wind_speed_string(speed_text, forecast_units):
    """Parse NWS textual wind speed (e.g. '5 to 10 mph') into speed/gust."""
    if not speed_text:
        return (None, None)

    text = str(speed_text).lower()
    values = [float(n) for n in findall(r"\d+(?:\.\d+)?", text)]
    if not values:
        return (None, None)

    low = min(values)
    high = max(values)

    # NWS hourly/daily period windSpeed is predictable textual mph for KBOS/US.
    source_unit = "mile_per_hour"
    target_unit = NWS_FORECAST_TARGET_SPEED_UNIT.get(
        forecast_units, "mile_per_hour"
    )

    try:
        low_out = weewx.units.convert(
            (_safe_float(low), source_unit, "group_speed"), target_unit
        )[0]
    except Exception:
        low_out = None

    try:
        high_out = weewx.units.convert(
            (_safe_float(high), source_unit, "group_speed"), target_unit
        )[0]
    except Exception:
        high_out = None

    return (low_out, high_out)


def _convert_unit_value(value, source_unit, target_unit, unit_group):
    """Convert a numeric WeeWX unit value, returning None if unavailable."""
    value_float = _safe_float(value)
    if value_float is None:
        return None
    try:
        return weewx.units.convert(
            (value_float, source_unit, unit_group), target_unit
        )[0]
    except Exception:
        return None


def _probability_fraction(percent_value, default=0):
    """Convert provider percentage values to the compact 0..1 probability."""
    percent_float = _safe_float(percent_value)
    return percent_float / 100.0 if percent_float is not None else default


def _visibility_m_to_forecast_units(visibility_m, forecast_units):
    """Convert visibility in meters to the forecast distance unit used by the skin."""
    visibility_m_float = _safe_float(visibility_m)
    if visibility_m_float is None:
        return None
    if forecast_units in ("si", "ca"):
        return visibility_m_float / 1000.0
    return visibility_m_float / 1609.344


def _precip_mm_to_forecast_units(precip_mm, forecast_units):
    """Convert a precipitation amount in millimeters to configured forecast units."""
    precip_mm_float = _safe_float(precip_mm)
    if precip_mm_float is None:
        return None
    if forecast_units in ("si", "ca"):
        return precip_mm_float
    return precip_mm_float / 25.4


def _pressure_pa_to_hpa(pressure_pa):
    """Convert NWS observation pressure from pascals to hPa/mbar."""
    pressure_float = _safe_float(pressure_pa)
    if pressure_float is None:
        return None
    return pressure_float / 100.0 if pressure_float > 2000 else pressure_float


def _nws_cloud_cover_fraction(cloud_layers):
    """Estimate cloud cover from NWS/METAR cloud layer amount codes."""
    if not isinstance(cloud_layers, list):
        return None

    amount_map = {
        "CLR": 0.0,
        "SKC": 0.0,
        "FEW": 0.25,
        "SCT": 0.5,
        "BKN": 0.75,
        "OVC": 1.0,
        "VV": 1.0,
    }
    values = []
    for layer in cloud_layers:
        if not isinstance(layer, dict):
            continue
        amount = str(layer.get("amount") or "").upper()
        if amount in amount_map:
            values.append(amount_map[amount])

    return max(values) if values else None


def _nws_icon_to_darksky(icon_value, is_daytime=True):
    """Map NWS icon URL/code to Weather34 icon keys used by this skin."""
    icon = str(icon_value or "").lower()
    if not icon:
        return "unknown"

    token = icon.split("/")[-1].split("?")[0].split(",")[0].strip()
    token = token.replace("-", "_")

    if "/night/" in icon or (token.startswith("n") and len(token) > 1):
        is_daytime = False
    elif "/day/" in icon or (token.startswith("d") and len(token) > 1):
        is_daytime = True

    mapping = {
        "skc": "clear-day" if is_daytime else "clear-night",
        "clear": "clear-day" if is_daytime else "clear-night",
        "sunny": "clear-day",
        "fair": "mostly-clear-day" if is_daytime else "mostly-clear-night",
        "few": "mostly-clear-day" if is_daytime else "mostly-clear-night",
        "sct": "partly-cloudy-day" if is_daytime else "partly-cloudy-night",
        "bkn": "mostly-cloudy-day" if is_daytime else "mostly-cloudy-night",
        "ovc": "cloudy",
        "wind_skc": "wind",
        "wind_few": "wind",
        "wind_sct": "wind",
        "wind_bkn": "wind",
        "wind_ovc": "wind",
        "rain": "rain",
        "ra": "rain",
        "shra": "rain",
        "shwrs": "rain",
        "hi_shwrs": "rain",
        "rain_showers": "rain",
        "rain_showers_hi": "rain",
        "rain_showers_sct": "rain",
        "rain_snow": "sleet",
        "rain_sleet": "sleet",
        "rain_fzra": "sleet",
        "tsra": "thunderstorm",
        "tsra_sct": "thunderstorm",
        "tsra_hi": "thunderstorm",
        "hi_tsra": "thunderstorm",
        "snow": "snow",
        "sn": "snow",
        "blizzard": "snow",
        "snow_sleet": "sleet",
        "snow_fzra": "sleet",
        "sleet": "sleet",
        "fzra": "sleet",
        "ip": "sleet",
        "mix": "sleet",
        "hail": "sleet",
        "fg": "fog",
        "fog": "fog",
        "smoke": "fog",
        "haze": "fog",
        "dust": "fog",
        "tornado": "wind",
        "hurricane": "wind",
        "tropical_storm": "wind",
        "hot": "clear-day",
        "cold": "clear-night" if not is_daytime else "clear-day",
    }

    if token in mapping:
        return mapping[token]

    # Some NWS/METAR feeds use legacy day/night-prefixed codes such as
    # "nskc" or "nfew"; strip the prefix only after checking the full token.
    if len(token) > 1 and token[0] in ("d", "n") and token[1:] in mapping:
        return mapping[token[1:]]

    # Prefer a recognizable icon over the generic unknown cloud when NWS adds
    # compound codes that still contain an obvious weather signal.
    if "tsra" in token or "thunder" in token:
        return "thunderstorm"
    if "sleet" in token or "fzra" in token or "ice" in token:
        return "sleet"
    if "snow" in token or "blizzard" in token:
        return "snow"
    if "rain" in token or token in ("ra", "shra", "drizzle"):
        return "rain"
    if any(part in token for part in ("fog", "fg", "smoke", "haze", "dust")):
        return "fog"
    if any(part in token for part in ("wind", "hurricane", "tropical", "tornado")):
        return "wind"
    if "ovc" in token or "cloudy" in token:
        return "cloudy"
    if "bkn" in token:
        return "mostly-cloudy-day" if is_daytime else "mostly-cloudy-night"
    if "sct" in token:
        return "partly-cloudy-day" if is_daytime else "partly-cloudy-night"
    if "few" in token:
        return "mostly-clear-day" if is_daytime else "mostly-clear-night"
    if "skc" in token or "clear" in token:
        return "clear-day" if is_daytime else "clear-night"

    return "unknown"


def _nws_build_current(obs_payload, forecast_units):
    """Normalize NWS latest observation payload to Belchertown current schema."""
    props = (obs_payload or {}).get("properties") or {}

    temp_c = _nws_quantity_value(props.get("temperature"))
    dewpoint_c = _nws_quantity_value(props.get("dewpoint"))
    apparent_c = _nws_quantity_value(props.get("heatIndex"))
    if apparent_c is None:
        apparent_c = _nws_quantity_value(props.get("windChill"))
    humidity_pct = _nws_quantity_value(props.get("relativeHumidity"))
    metar_visibility = _nws_parse_metar_visibility(props.get("rawMessage"))
    visibility_m = (
        metar_visibility.get("visibility_m")
        if metar_visibility
        else _nws_quantity_value(props.get("visibility"))
    )
    visibility_qualifier = metar_visibility.get("qualifier") if metar_visibility else ""
    if not visibility_qualifier:
        visibility_qualifier = _nws_visibility_quantity_qualifier(visibility_m)
    wind_mps = _nws_quantity_value(props.get("windSpeed"))
    gust_mps = _nws_quantity_value(props.get("windGust"))
    pressure_pa = _nws_quantity_value(props.get("barometricPressure"))
    precip_last_hour_mm = _nws_quantity_value(props.get("precipitationLastHour"))
    wind_dir_payload = props.get("windDirection")
    if isinstance(wind_dir_payload, dict):
        wind_dir_value = wind_dir_payload.get("value")
    else:
        wind_dir_value = wind_dir_payload

    is_day = True
    icon_raw = props.get("icon")
    icon_text = str(icon_raw or "")
    if "/night/" in icon_text or icon_text.split("/")[-1].startswith("n"):
        is_day = False

    temp_target_unit = NWS_FORECAST_TARGET_TEMP_UNIT.get(
        forecast_units, "degree_F"
    )
    speed_target_unit = NWS_FORECAST_TARGET_SPEED_UNIT.get(
        forecast_units, "mile_per_hour"
    )
    temp_out = _convert_unit_value(
        temp_c, "degree_C", temp_target_unit, "group_temperature"
    )
    apparent_out = _convert_unit_value(
        apparent_c, "degree_C", temp_target_unit, "group_temperature"
    )
    dewpoint_out = _convert_unit_value(
        dewpoint_c, "degree_C", temp_target_unit, "group_temperature"
    )
    wind_out = _convert_unit_value(
        wind_mps, "meter_per_second", speed_target_unit, "group_speed"
    )
    gust_out = _convert_unit_value(
        gust_mps, "meter_per_second", speed_target_unit, "group_speed"
    )

    return {
        "time": _iso_to_epoch(props.get("timestamp")) or int(time.time()),
        "summary": props.get("textDescription") or "",
        "icon": _nws_icon_to_darksky(icon_raw, is_daytime=is_day),
        "temperature": temp_out,
        "apparentTemperature": apparent_out,
        "windSpeed": wind_out,
        "windGust": gust_out,
        "windBearing": _nws_parse_wind_direction(wind_dir_value),
        "humidity": _probability_fraction(humidity_pct, default=None),
        "pressure": _pressure_pa_to_hpa(pressure_pa),
        "visibility": _visibility_m_to_forecast_units(visibility_m, forecast_units),
        "visibilityQualifier": visibility_qualifier,
        "dewPoint": dewpoint_out,
        "precipIntensity": _precip_mm_to_forecast_units(
            precip_last_hour_mm, forecast_units
        ),
        "precipProbability": None,
        "cloudCover": _nws_cloud_cover_fraction(props.get("cloudLayers")),
        "station": props.get("station") or "",
        "rawMessage": props.get("rawMessage") or "",
    }


def _nws_build_hourly(hourly_payload, forecast_units):
    """Normalize NWS hourly periods to Belchertown hourly schema."""
    periods = ((hourly_payload or {}).get("properties") or {}).get("periods") or []
    output = []

    temp_target_unit = NWS_FORECAST_TARGET_TEMP_UNIT.get(
        forecast_units, "degree_F"
    )

    for p in periods:
        temp = _safe_float(p.get("temperature"))
        pop_pct = _nws_quantity_value(p.get("probabilityOfPrecipitation"))
        humidity_pct = _nws_quantity_value(p.get("relativeHumidity"))
        dewpoint_c = _nws_quantity_value(p.get("dewpoint"))
        wind_speed, wind_gust = _nws_parse_wind_speed_string(p.get("windSpeed"), forecast_units)

        temp_out = _convert_unit_value(
            temp, "degree_F", temp_target_unit, "group_temperature"
        )
        dewpoint_out = _convert_unit_value(
            dewpoint_c, "degree_C", temp_target_unit, "group_temperature"
        )

        output.append(
            {
                "time": _iso_to_epoch(p.get("startTime")) or int(time.time()),
                "summary": p.get("shortForecast") or p.get("detailedForecast") or "",
                "icon": _nws_icon_to_darksky(p.get("icon"), is_daytime=bool(p.get("isDaytime", True))),
                "temperature": temp_out,
                "apparentTemperature": None,
                "windSpeed": wind_speed,
                "windGust": wind_gust,
                "windBearing": _nws_parse_wind_direction(p.get("windDirection")),
                "precipIntensity": None,
                "precipProbability": _probability_fraction(pop_pct),
                "cloudCover": None,
                "humidity": _probability_fraction(humidity_pct, default=None),
                "dewPoint": dewpoint_out,
            }
        )

    return output


def _nws_build_daily(forecast_payload, forecast_units):
    """Normalize NWS day/night periods into daily high/low schema."""
    periods = ((forecast_payload or {}).get("properties") or {}).get("periods") or []
    day_buckets = OrderedDict()

    temp_target_unit = NWS_FORECAST_TARGET_TEMP_UNIT.get(
        forecast_units, "degree_F"
    )

    for p in periods:
        ts = _iso_to_epoch(p.get("startTime"))
        if ts is None:
            continue

        dt_local = datetime.datetime.fromtimestamp(ts)
        key = dt_local.strftime("%Y-%m-%d")

        temp = _safe_float(p.get("temperature"))
        temp_out = _convert_unit_value(
            temp, "degree_F", temp_target_unit, "group_temperature"
        )

        pop_pct = _nws_quantity_value(p.get("probabilityOfPrecipitation"))
        humidity_pct = _nws_quantity_value(p.get("relativeHumidity"))
        dewpoint_c = _nws_quantity_value(p.get("dewpoint"))
        dewpoint_out = _convert_unit_value(
            dewpoint_c, "degree_C", temp_target_unit, "group_temperature"
        )
        wind_speed, wind_gust = _nws_parse_wind_speed_string(p.get("windSpeed"), forecast_units)
        precip_probability = _probability_fraction(pop_pct)

        bucket = day_buckets.get(key)
        if bucket is None:
            bucket = {
                "time": ts,
                "summary": p.get("shortForecast") or p.get("detailedForecast") or "",
                "icon": _nws_icon_to_darksky(
                    p.get("icon"), is_daytime=bool(p.get("isDaytime", True))
                ),
                "temperatureHigh": temp_out,
                "temperatureLow": temp_out,
                "windSpeed": wind_speed,
                "windGust": wind_gust,
                "windBearing": _nws_parse_wind_direction(p.get("windDirection")),
                "precipIntensity": None,
                "precipProbability": precip_probability,
                "cloudCover": None,
                "humidity": _probability_fraction(humidity_pct, default=None),
                "dewPoint": dewpoint_out,
            }
            day_buckets[key] = bucket
        else:
            if temp_out is not None:
                if bucket["temperatureHigh"] is None or temp_out > bucket["temperatureHigh"]:
                    bucket["temperatureHigh"] = temp_out
                if bucket["temperatureLow"] is None or temp_out < bucket["temperatureLow"]:
                    bucket["temperatureLow"] = temp_out
            if p.get("isDaytime") and p.get("shortForecast"):
                bucket["summary"] = p.get("shortForecast")
                bucket["icon"] = _nws_icon_to_darksky(p.get("icon"), is_daytime=True)
            if precip_probability > bucket.get("precipProbability", 0):
                bucket["precipProbability"] = precip_probability
            if wind_speed is not None and (
                bucket["windSpeed"] is None or wind_speed > bucket["windSpeed"]
            ):
                bucket["windSpeed"] = wind_speed
            if wind_gust is not None and (
                bucket["windGust"] is None or wind_gust > bucket["windGust"]
            ):
                bucket["windGust"] = wind_gust
            if bucket["humidity"] is None:
                bucket["humidity"] = _probability_fraction(humidity_pct, default=None)
            if bucket["dewPoint"] is None:
                bucket["dewPoint"] = dewpoint_out

    return list(day_buckets.values())


def _nws_build_alerts(alerts_payload):
    """Normalize NWS active alerts payload to Belchertown alerts schema."""
    features = (alerts_payload or {}).get("features") or []
    output = []
    for feature in features:
        props = feature.get("properties") or {}
        output.append(
            {
                "title": _compact_alert_title(
                    props.get("event"),
                    props.get("headline"),
                ),
                "effective": _iso_to_epoch(props.get("effective")),
                "onset": _iso_to_epoch(props.get("onset")),
                "ends": _iso_to_epoch(props.get("ends")),
                "expires": _iso_to_epoch(props.get("expires")),
                "description": props.get("description") or props.get("instruction") or "",
                "severity": props.get("severity") or "",
                "uri": feature.get("id") or props.get("@id") or "",
                "source": "nws",
            }
        )
    return output


def _fetch_nws_alerts(latitude, longitude):
    """Fetch NWS alerts for a point and normalize them."""
    alerts_url = f"https://api.weather.gov/alerts/active?point={latitude},{longitude}"
    alerts_data = _http_get_json(alerts_url, headers=HTTP_HEADERS["NWS_WEATHER"])
    return _nws_build_alerts(alerts_data)


def _xml_local_name(tag):
    """Return an XML local name without its namespace."""
    return str(tag).rsplit("}", 1)[-1]


def _xml_children(element, local_name):
    """Return child elements whose local name matches."""
    if element is None:
        return []
    return [
        child
        for child in list(element)
        if _xml_local_name(child.tag) == local_name
    ]


def _xml_first_child_text(element, *local_names):
    """Return the first non-empty child text matching one of the local names."""
    if element is None:
        return ""
    local_name_set = set(local_names)
    for child in list(element):
        if _xml_local_name(child.tag) in local_name_set and child.text:
            return child.text.strip()
    return ""


def _config_list_values(value):
    """Return a normalized list from a comma-separated or ConfigObj list value."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        parts = str(value).split(",")
    return [str(part).strip() for part in parts if str(part).strip()]


def _forecast_alert_limit_value(extras_dict):
    """Return a sane forecast alert limit."""
    limit_value = to_int((extras_dict or {}).get("forecast_alert_limit", 1))
    if limit_value is None or limit_value < 1:
        return 1
    return limit_value


def _limit_alerts(alerts, limit_value):
    """Limit alert list length when a positive limit is available."""
    if not isinstance(alerts, list):
        return []
    limit_value = to_int(limit_value)
    if limit_value is None or limit_value < 1:
        return alerts
    return alerts[:limit_value]


def _meteoalarm_country_slug(country_value):
    """Normalize a MeteoAlarm country value to its public Atom feed slug."""
    values = _config_list_values(country_value)
    if not values:
        return ""

    country_text = values[0].strip()
    if not country_text:
        return ""

    country_upper = country_text.upper()
    if country_upper in METEOALARM_COUNTRY_SLUG_BY_CODE:
        return METEOALARM_COUNTRY_SLUG_BY_CODE[country_upper]

    country_slug = (
        country_text.lower()
        .replace("_", "-")
        .replace(" ", "-")
        .strip("-")
    )
    if country_slug.startswith("meteoalarm-legacy-atom-"):
        country_slug = country_slug.replace("meteoalarm-legacy-atom-", "", 1)
    return METEOALARM_COUNTRY_SLUG_ALIASES.get(country_slug, country_slug)


def _meteoalarm_country_slug_from_geocode(geocode_values):
    """Infer a MeteoAlarm country feed slug from an EMMA_ID-style geocode."""
    for geocode in _config_list_values(geocode_values):
        geocode_upper = geocode.upper()
        for country_code in sorted(
            METEOALARM_COUNTRY_SLUG_BY_CODE.keys(), key=len, reverse=True
        ):
            if geocode_upper.startswith(country_code):
                return METEOALARM_COUNTRY_SLUG_BY_CODE[country_code]
    return ""


def _meteoalarm_feed_url(extras_dict):
    """Build the MeteoAlarm Atom feed URL from explicit config."""
    feed_url_values = _config_list_values(
        (extras_dict or {}).get("meteoalarm_feed_url")
    )
    if feed_url_values:
        return feed_url_values[0]

    country_slug = _meteoalarm_country_slug(
        (extras_dict or {}).get("meteoalarm_country")
    )
    if not country_slug:
        country_slug = _meteoalarm_country_slug_from_geocode(
            (extras_dict or {}).get("meteoalarm_geocode")
        )
    if not country_slug:
        return ""

    return f"https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{country_slug}"


def _meteoalarm_entry_geocodes(entry):
    """Return geocode values from a MeteoAlarm Atom entry."""
    output = []
    for geocode in _xml_children(entry, "geocode"):
        value = _xml_first_child_text(geocode, "value")
        if value:
            output.append(value.upper())
    return output


def _meteoalarm_entry_matches(entry, geocode_filters, area_filters):
    """Return True when an Atom entry matches configured geocode or area filters."""
    if geocode_filters:
        entry_geocodes = set(_meteoalarm_entry_geocodes(entry))
        if entry_geocodes.intersection(geocode_filters):
            return True

    area_desc = _xml_first_child_text(entry, "areaDesc").lower()
    if area_filters and area_desc:
        for area_filter in area_filters:
            if area_filter in area_desc:
                return True

    return not geocode_filters and not area_filters


def _meteoalarm_entry_to_alert(entry):
    """Normalize a MeteoAlarm Atom entry to the common alert schema."""
    title = _xml_first_child_text(entry, "title")
    area_desc = _xml_first_child_text(entry, "areaDesc")
    event = _xml_first_child_text(entry, "event")
    severity = _xml_first_child_text(entry, "severity")
    urgency = _xml_first_child_text(entry, "urgency")
    certainty = _xml_first_child_text(entry, "certainty")
    effective = _xml_first_child_text(entry, "effective")
    onset = _xml_first_child_text(entry, "onset")
    ends = _xml_first_child_text(entry, "ends")
    expires = _xml_first_child_text(entry, "expires")
    identifier = (
        _xml_first_child_text(entry, "identifier")
        or _xml_first_child_text(entry, "id")
    )

    description_parts = []
    if event:
        description_parts.append(event)
    if area_desc:
        description_parts.append(f"Area: {area_desc}")
    for label, value in (
        ("Severity", severity),
        ("Urgency", urgency),
        ("Certainty", certainty),
        ("Onset", onset),
    ):
        if value:
            description_parts.append(f"{label}: {value}")

    return {
        "title": _compact_alert_title(event, title, default="MeteoAlarm Alert"),
        "effective": _iso_to_epoch(effective),
        "onset": _iso_to_epoch(onset),
        "ends": _iso_to_epoch(ends or expires),
        "expires": _iso_to_epoch(expires),
        "description": "\n".join(description_parts),
        "severity": severity,
        "uri": identifier,
        "source": "meteoalarm",
    }


def _meteoalarm_build_alerts(feed_xml, geocode_filters=None, area_filters=None):
    """Normalize a MeteoAlarm Atom feed to the common alert schema."""
    if not feed_xml:
        return []

    root = ET.fromstring(feed_xml)
    entries = [
        element
        for element in root.iter()
        if _xml_local_name(element.tag) == "entry"
    ]
    geocode_filters = set(value.upper() for value in (geocode_filters or []))
    area_filters = [value.lower() for value in (area_filters or [])]

    output = []
    for entry in entries:
        if not _meteoalarm_entry_matches(entry, geocode_filters, area_filters):
            continue
        output.append(_meteoalarm_entry_to_alert(entry))
    return output


def _fetch_meteoalarm_alerts(extras_dict):
    """Fetch configured MeteoAlarm fallback alerts."""
    feed_url = _meteoalarm_feed_url(extras_dict)
    if not feed_url:
        log.info(
            "MeteoAlarm alert fallback skipped; configure meteoalarm_geocode, "
            "meteoalarm_country, or meteoalarm_feed_url."
        )
        return None

    geocode_filters = _config_list_values(
        (extras_dict or {}).get("meteoalarm_geocode")
    )
    area_filters = _config_list_values((extras_dict or {}).get("meteoalarm_area"))
    feed_xml = _http_get_text(feed_url, headers=HTTP_HEADERS["METEOALARM"])
    return _meteoalarm_build_alerts(
        feed_xml,
        geocode_filters=geocode_filters,
        area_filters=area_filters,
    )


def _fetch_openmeteo_alerts(latitude, longitude, extras_dict):
    """Fetch Open-Meteo alerts, preferring NWS with MeteoAlarm fallback."""
    if str((extras_dict or {}).get("forecast_alert_enabled", "0")).strip() != "1":
        return ([], "")

    alert_limit = _forecast_alert_limit_value(extras_dict)

    try:
        nws_alerts = _fetch_nws_alerts(latitude, longitude)
        return (_limit_alerts(nws_alerts, alert_limit), "nws")
    except Exception as e:
        log.info(
            "NWS alerts unavailable for Open-Meteo point; trying MeteoAlarm. "
            f"Reason: {e}"
        )

    try:
        meteoalarm_alerts = _fetch_meteoalarm_alerts(extras_dict)
        if meteoalarm_alerts is None:
            return ([], "")
        return (_limit_alerts(meteoalarm_alerts, alert_limit), "meteoalarm")
    except Exception as e:
        log.warning(f"MeteoAlarm alert fallback update failed. Reason: {e}")
        return ([], "")


def _nws_transform_to_belch(
    forecast_payload,
    hourly_payload,
    observation_payload,
    alerts_payload,
    forecast_units,
):
    """Map NWS responses to the compact structure this skin uses."""
    hourly_all = _nws_build_hourly(hourly_payload, forecast_units)
    hourly = _slice_from_current_period(hourly_all, 1)
    return {
        "current": _nws_build_current(observation_payload, forecast_units),
        "hourly": hourly,
        "threeHourly": _pick_three_hourly_from_current_period(hourly_all),
        "daily": _nws_build_daily(forecast_payload, forecast_units),
        "alerts": _nws_build_alerts(alerts_payload),
        "provider": "nws",
        "schema": "belchertown.forecast.v1",
        "generated_at": int(time.time()),
    }


def _openmeteo_weather_to_icon_summary(code, is_daytime=True):
    """Map Open-Meteo weather_code to Dark-Sky style icon key and summary text."""

    code_int = to_int(code)
    if code_int is None:
        return ("Unknown", "unknown")

    if code_int == 0:
        return ("Clear", "clear-day" if is_daytime else "clear-night")
    if code_int in (1, 2):
        return (
            "Partly cloudy",
            "partly-cloudy-day" if is_daytime else "partly-cloudy-night",
        )
    if code_int == 3:
        return ("Overcast", "cloudy")
    if code_int in (45, 48):
        return ("Fog", "fog")
    if code_int in (51, 53, 55):
        return ("Drizzle", "rain")
    if code_int in (56, 57, 66, 67):
        return ("Freezing rain", "sleet")
    if code_int in (61, 63, 65, 80, 81, 82):
        return ("Rain", "rain")
    if code_int in (71, 73, 75, 77, 85, 86):
        return ("Snow", "snow")
    if code_int in (95, 96, 99):
        return ("Thunderstorm", "thunderstorm")

    return ("Unknown", "unknown")


def _aqi_category_from_us_aqi(aqi_value):
    """Return the existing AQI category key for a US AQI numeric value."""
    aqi_float = _safe_float(aqi_value)
    if aqi_float is None:
        return ""
    if aqi_float <= 50:
        return "good"
    if aqi_float <= 100:
        return "moderate"
    if aqi_float <= 150:
        return "usg"
    if aqi_float <= 200:
        return "unhealthy"
    if aqi_float <= 300:
        return "very unhealthy"
    return "hazardous"


def _openmeteo_air_quality_to_aeris_payload(payload):
    """Normalize Open-Meteo Air Quality data to the existing AQI fallback shape."""
    current = (payload or {}).get("current") or {}
    current_time = _iso_to_epoch(current.get("time")) or int(time.time())

    pollutant_map = (
        ("pm2.5", "pm2_5", "valueUGM3"),
        ("pm10", "pm10", "valueUGM3"),
        ("o3", "ozone", "valuePPB"),
        ("co", "carbon_monoxide", "valuePPB"),
        ("no2", "nitrogen_dioxide", "valuePPB"),
        ("so2", "sulphur_dioxide", "valuePPB"),
    )

    pollutants = []
    for pollutant_type, openmeteo_key, value_key in pollutant_map:
        value = _safe_float(current.get(openmeteo_key))
        if value is None:
            continue
        pollutants.append(
            {
                "type": pollutant_type,
                value_key: value,
                "valueUGM3": value,
            }
        )

    aqi_value = _safe_float(current.get("us_aqi"))
    period = {
        "timestamp": current_time,
        "aqi": aqi_value,
        "category": _aqi_category_from_us_aqi(aqi_value),
        "pollutants": pollutants,
    }

    return {
        "success": aqi_value is not None or bool(pollutants),
        "error": None,
        "response": [
            {
                "place": {"name": "Open-Meteo"},
                "periods": [period],
            }
        ],
        "provider": "open-meteo",
    }


def _fetch_openmeteo_aqi_payload(latitude, longitude):
    """Fetch Open-Meteo Air Quality as the common AQI fallback payload."""
    aqi_url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,"
        "sulphur_dioxide,ozone"
        "&timezone=auto"
    )
    aqi_raw = _http_get_json(aqi_url, headers=HTTP_HEADERS["OPEN_METEO"])
    return _openmeteo_air_quality_to_aeris_payload(aqi_raw)


def _merge_aqi_payload_into_forecast_file(forecast_file, aqi_payload):
    """Attach an AQI payload to forecast.json without disturbing forecast data."""
    if not aqi_payload or not os.path.isfile(forecast_file):
        return False

    with open(forecast_file, "r", encoding="utf-8") as fh:
        forecast_data = json.load(fh)

    forecast_data["aqi"] = [aqi_payload]
    _write_json_file(forecast_file, forecast_data)
    return True


def _load_aqi_payload_from_forecast_file(forecast_file, require_success=False):
    """Load the first cached AQI payload from forecast.json."""
    try:
        if not os.path.isfile(forecast_file):
            return None
        with open(forecast_file, "r", encoding="utf-8") as fh:
            forecast_data = json.load(fh)
        aqi_array = forecast_data.get("aqi") or []
        aqi_payload = aqi_array[0] if aqi_array else None
        if require_success and not (aqi_payload and aqi_payload.get("success")):
            return None
        return aqi_payload
    except Exception:
        return None


def _resolve_forecast_lat_lon(latitude, longitude, forecast_place):
    """Return forecast coordinates, allowing a lat,lon forecast_place override."""
    lat = _safe_float(latitude)
    lon = _safe_float(longitude)
    if forecast_place and "," in forecast_place:
        try:
            lat_raw, lon_raw = forecast_place.split(",", 1)
            parsed_lat = _safe_float(lat_raw.strip())
            parsed_lon = _safe_float(lon_raw.strip())
            if parsed_lat is not None and parsed_lon is not None:
                lat = parsed_lat
                lon = parsed_lon
        except Exception:
            pass
    return lat, lon


def _localized_aqi_category(category, label_dict):
    """Translate a provider AQI category key with skin labels."""
    aqi_category_labels = {
        "good": "aqi_good",
        "moderate": "aqi_moderate",
        "usg": "aqi_usg",
        "unhealthy": "aqi_unhealthy",
        "very unhealthy": "aqi_very_unhealthy",
        "hazardous": "aqi_hazardous",
    }
    label_key = aqi_category_labels.get(category, "aqi_unknown")
    return label_dict[label_key]


def _extract_aqi_globals_from_payload(aqi_payload, label_dict):
    """Return display AQI globals from the common AQI payload shape."""
    try:
        if not aqi_payload or not aqi_payload.get("success"):
            return ("No Data", label_dict["aqi_unknown"], "", "")

        response = aqi_payload.get("response") or []
        first_response = response[0] if response else {}
        periods = first_response.get("periods") or []
        period = periods[0] if periods else {}
        aqi_value = period.get("aqi")
        if aqi_value is None:
            return ("No Data", label_dict["aqi_unknown"], "", "")

        category = _localized_aqi_category(period.get("category"), label_dict)
        place = (first_response.get("place") or {}).get("name", "")
        point_time = period.get("timestamp", "")
        return (aqi_value, category, place.title() if place else "", point_time)
    except Exception:
        return ("No Data", label_dict["aqi_unknown"], "", "")


def _openmeteo_transform_to_belch(payload, forecast_units):
    """Map Open-Meteo response to Belchertown compact forecast schema."""

    if not isinstance(payload, dict):
        payload = {}

    current_raw = payload.get("current") or {}
    hourly_raw = payload.get("hourly") or {}
    daily_raw = payload.get("daily") or {}
    generated_at = int(time.time())

    current_is_day = bool(to_int(current_raw.get("is_day")) == 1)
    current_summary, current_icon = _openmeteo_weather_to_icon_summary(
        current_raw.get("weather_code"), is_daytime=current_is_day
    )
    current_humidity_pct = _safe_float(current_raw.get("relative_humidity_2m"))
    current = {
        "time": _iso_to_epoch(current_raw.get("time")) or generated_at,
        "summary": current_summary,
        "icon": current_icon,
        "temperature": _safe_float(current_raw.get("temperature_2m")),
        "apparentTemperature": _safe_float(current_raw.get("apparent_temperature")),
        "windSpeed": _safe_float(current_raw.get("wind_speed_10m")),
        "windGust": _safe_float(current_raw.get("wind_gusts_10m")),
        "windBearing": _safe_float(current_raw.get("wind_direction_10m")),
        "humidity": (
            current_humidity_pct / 100.0
            if current_humidity_pct is not None
            else None
        ),
        "pressure": _safe_float(current_raw.get("surface_pressure")),
        "pressureMSL": _safe_float(current_raw.get("pressure_msl")),
        "visibility": _visibility_m_to_forecast_units(
            current_raw.get("visibility"), forecast_units
        ),
        "dewPoint": _safe_float(current_raw.get("dew_point_2m")),
        "precipIntensity": _safe_float(current_raw.get("precipitation")),
        "precipProbability": None,
        "cloudCover": _safe_float(current_raw.get("cloud_cover")),
        "rain": _safe_float(current_raw.get("rain")),
        "showers": _safe_float(current_raw.get("showers")),
        "snowfall": _safe_float(current_raw.get("snowfall")),
        "weatherCode": to_int(current_raw.get("weather_code")),
    }

    hourly = []
    h_time = hourly_raw.get("time") or []
    h_weather = hourly_raw.get("weather_code") or []
    h_is_day = hourly_raw.get("is_day") or []
    h_temp = hourly_raw.get("temperature_2m") or []
    h_app = hourly_raw.get("apparent_temperature") or []
    h_wind = hourly_raw.get("wind_speed_10m") or []
    h_gust = hourly_raw.get("wind_gusts_10m") or []
    h_bearing = hourly_raw.get("wind_direction_10m") or []
    h_precip = hourly_raw.get("precipitation") or []
    h_rain = hourly_raw.get("rain") or []
    h_showers = hourly_raw.get("showers") or []
    h_snowfall = hourly_raw.get("snowfall") or []
    h_precip_prob = hourly_raw.get("precipitation_probability") or []
    h_cloud = hourly_raw.get("cloud_cover") or []
    h_visibility = hourly_raw.get("visibility") or []
    h_pressure = hourly_raw.get("surface_pressure") or []
    h_pressure_msl = hourly_raw.get("pressure_msl") or []
    h_rh = hourly_raw.get("relative_humidity_2m") or []
    h_dew = hourly_raw.get("dew_point_2m") or []

    for i, time_value in enumerate(h_time):
        is_day = bool(to_int(h_is_day[i]) == 1) if i < len(h_is_day) else True
        summary, icon = _openmeteo_weather_to_icon_summary(
            h_weather[i] if i < len(h_weather) else None,
            is_daytime=is_day,
        )
        precip_prob = _safe_float(h_precip_prob[i]) if i < len(h_precip_prob) else None
        humidity_pct = _safe_float(h_rh[i]) if i < len(h_rh) else None
        hourly.append(
            {
                "time": _iso_to_epoch(time_value) or generated_at,
                "summary": summary,
                "icon": icon,
                "temperature": _safe_float(h_temp[i]) if i < len(h_temp) else None,
                "apparentTemperature": _safe_float(h_app[i]) if i < len(h_app) else None,
                "windSpeed": _safe_float(h_wind[i]) if i < len(h_wind) else None,
                "windGust": _safe_float(h_gust[i]) if i < len(h_gust) else None,
                "windBearing": _safe_float(h_bearing[i]) if i < len(h_bearing) else None,
                "precipIntensity": _safe_float(h_precip[i]) if i < len(h_precip) else None,
                "rain": _safe_float(h_rain[i]) if i < len(h_rain) else None,
                "showers": _safe_float(h_showers[i]) if i < len(h_showers) else None,
                "snowfall": _safe_float(h_snowfall[i]) if i < len(h_snowfall) else None,
                "precipProbability": (precip_prob / 100.0) if precip_prob is not None else 0,
                "cloudCover": _safe_float(h_cloud[i]) if i < len(h_cloud) else None,
                "humidity": (
                    (humidity_pct / 100.0)
                    if humidity_pct is not None
                    else None
                ),
                "dewPoint": _safe_float(h_dew[i]) if i < len(h_dew) else None,
                "pressure": _safe_float(h_pressure[i]) if i < len(h_pressure) else None,
                "pressureMSL": (
                    _safe_float(h_pressure_msl[i]) if i < len(h_pressure_msl) else None
                ),
                "visibility": (
                    _visibility_m_to_forecast_units(h_visibility[i], forecast_units)
                    if i < len(h_visibility)
                    else None
                ),
                "weatherCode": to_int(h_weather[i]) if i < len(h_weather) else None,
            }
        )

    daily = []
    d_time = daily_raw.get("time") or []
    d_weather = daily_raw.get("weather_code") or []
    d_tmax = daily_raw.get("temperature_2m_max") or []
    d_tmin = daily_raw.get("temperature_2m_min") or []
    d_wind = daily_raw.get("wind_speed_10m_max") or []
    d_gust = daily_raw.get("wind_gusts_10m_max") or []
    d_bearing = daily_raw.get("wind_direction_10m_dominant") or []
    d_precip_prob = daily_raw.get("precipitation_probability_max") or []
    d_precip = daily_raw.get("precipitation_sum") or []
    d_rain = daily_raw.get("rain_sum") or []
    d_showers = daily_raw.get("showers_sum") or []
    d_snowfall = daily_raw.get("snowfall_sum") or []
    d_precip_hours = daily_raw.get("precipitation_hours") or []
    d_cloud = daily_raw.get("cloud_cover_mean") or []
    d_humidity = daily_raw.get("relative_humidity_2m_mean") or []
    d_dewpoint = daily_raw.get("dew_point_2m_mean") or []
    d_apparent_max = daily_raw.get("apparent_temperature_max") or []
    d_apparent_min = daily_raw.get("apparent_temperature_min") or []
    d_sunrise = daily_raw.get("sunrise") or []
    d_sunset = daily_raw.get("sunset") or []
    d_uv = daily_raw.get("uv_index_max") or []

    for i, time_value in enumerate(d_time):
        summary, icon = _openmeteo_weather_to_icon_summary(
            d_weather[i] if i < len(d_weather) else None,
            is_daytime=True,
        )
        precip_prob = _safe_float(d_precip_prob[i]) if i < len(d_precip_prob) else None
        humidity_pct = _safe_float(d_humidity[i]) if i < len(d_humidity) else None
        daily.append(
            {
                "time": _iso_to_epoch(time_value) or generated_at,
                "summary": summary,
                "icon": icon,
                "temperatureHigh": _safe_float(d_tmax[i]) if i < len(d_tmax) else None,
                "temperatureLow": _safe_float(d_tmin[i]) if i < len(d_tmin) else None,
                "windSpeed": _safe_float(d_wind[i]) if i < len(d_wind) else None,
                "windGust": _safe_float(d_gust[i]) if i < len(d_gust) else None,
                "windBearing": _safe_float(d_bearing[i]) if i < len(d_bearing) else None,
                "precipIntensity": _safe_float(d_precip[i]) if i < len(d_precip) else None,
                "precipProbability": (precip_prob / 100.0) if precip_prob is not None else 0,
                "cloudCover": _safe_float(d_cloud[i]) if i < len(d_cloud) else None,
                "humidity": (
                    (humidity_pct / 100.0) if humidity_pct is not None else None
                ),
                "dewPoint": _safe_float(d_dewpoint[i]) if i < len(d_dewpoint) else None,
                "apparentTemperatureHigh": (
                    _safe_float(d_apparent_max[i]) if i < len(d_apparent_max) else None
                ),
                "apparentTemperatureLow": (
                    _safe_float(d_apparent_min[i]) if i < len(d_apparent_min) else None
                ),
                "rain": _safe_float(d_rain[i]) if i < len(d_rain) else None,
                "showers": _safe_float(d_showers[i]) if i < len(d_showers) else None,
                "snowfall": _safe_float(d_snowfall[i]) if i < len(d_snowfall) else None,
                "precipitationHours": (
                    _safe_float(d_precip_hours[i]) if i < len(d_precip_hours) else None
                ),
                "sunrise": _iso_to_epoch(d_sunrise[i]) if i < len(d_sunrise) else None,
                "sunset": _iso_to_epoch(d_sunset[i]) if i < len(d_sunset) else None,
                "uvIndex": _safe_float(d_uv[i]) if i < len(d_uv) else None,
                "weatherCode": to_int(d_weather[i]) if i < len(d_weather) else None,
            }
        )

    return {
        "current": current,
        "hourly": _slice_from_current_period(hourly, 1),
        "threeHourly": _pick_three_hourly_from_current_period(hourly),
        "daily": daily,
        "alerts": [],
        "provider": "open-meteo",
        "schema": "belchertown.forecast.v1",
        "generated_at": generated_at,
    }


def _parse_aeris_json(obj):
    """Robustly parse JSON whether it's str or bytes."""
    if isinstance(obj, bytearray):
        obj = bytes(obj)
    if isinstance(obj, bytes):
        try:
            obj = obj.decode("utf-8")
        except UnicodeDecodeError:
            obj = obj.decode("utf-8", "replace")

    try:
        return json.loads(obj)
    except Exception as e:
        log.error(f"Error parsing forecast JSON: {e}")
        return {}


def _apply_legacy_option_mappings(section_dict, section_name, legacy_mapping):
    """Apply legacy option mappings to a configuration section.

    If a legacy key is present, it is always used for now (backward
    compatibility) and mapped onto the current key name, with a warning.
    """

    for legacy_key, new_key in legacy_mapping.items():
        if legacy_key in section_dict:
            section_dict[new_key] = section_dict[legacy_key]
            log.warning(
                f"Belchertown: Deprecated option '{legacy_key}' found in [{section_name}]. "
                f"Using it as '{new_key}' for backward compatibility. "
                f"Please rename it in weewx.conf."
            )

    return section_dict


EXTRAS_LEGACY_MAPPING = {
    "graph_page_show_all_button": "chart_page_show_all_button",
    "graph_page_default_graphgroup": "chart_page_default_chartgroup",
    "highcharts_homepage_graphgroup": "highcharts_homepage_chartgroup",
}

LABELS_GENERIC_LEGACY_MAPPING = {
    "nav_graphs": "nav_charts",
    "graphs_page_header": "charts_page_header",
    "homepage_graphs_link": "homepage_charts_link",
    "graphs_page_all_button": "charts_page_all_button",
    "graphs_windrose_frequency": "charts_windrose_frequency",
    "graphs_windDir_ordinals": "charts_windDir_ordinals",
}


def _validate_and_fix_legacy_options(extras_dict, label_generic_dict=None):
    """Check for deprecated/legacy option names and warn users.

    Maps legacy naming patterns to current ones in supported sections.
    Legacy values take precedence when present for backward compatibility.
    """

    _apply_legacy_option_mappings(extras_dict, "Extras", EXTRAS_LEGACY_MAPPING)

    if label_generic_dict is not None:
        _apply_legacy_option_mappings(
            label_generic_dict, "Labels][Generic", LABELS_GENERIC_LEGACY_MAPPING
        )

    return extras_dict


def _safe_float(value):
    """Return float(value) when possible, else None."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None


def build_earthquake_map_context(latitude, longitude, zoom=7, tile_radius=2):
    """Return OSM tile coordinates and offsets for a quake-centered map."""

    lat = _safe_float(latitude)
    lon = _safe_float(longitude)
    if lat is None or lon is None:
        return None

    zoom = int(zoom)
    tile_radius = int(tile_radius)
    tile_size = 256.0
    tile_count = 2**zoom
    clamped_lat = max(min(lat, 85.05112878), -85.05112878)
    normalized_lon = ((lon + 180.0) % 360.0) - 180.0
    lat_rad = math.radians(clamped_lat)
    world_x = ((normalized_lon + 180.0) / 360.0) * tile_count * tile_size
    world_y = (
        (
            1.0
            - math.log(math.tan(lat_rad) + (1.0 / math.cos(lat_rad))) / math.pi
        )
        / 2.0
        * tile_count
        * tile_size
    )

    tile_x_raw = int(math.floor(world_x / tile_size))
    tile_y_raw = int(math.floor(world_y / tile_size))
    tile_x = tile_x_raw % tile_count
    tile_y = max(0, min(tile_count - 1, tile_y_raw))
    local_x = max(0.0, min(tile_size, world_x - (tile_x_raw * tile_size)))
    local_y = max(0.0, min(tile_size, world_y - (tile_y * tile_size)))

    tiles = []
    for row in range((tile_radius * 2) + 1):
        current_y = max(0, min(tile_count - 1, tile_y - tile_radius + row))
        for col in range((tile_radius * 2) + 1):
            current_x = (tile_x - tile_radius + col) % tile_count
            tiles.append({"x": current_x, "y": current_y})

    grid_offset_x = (tile_radius * tile_size) + local_x
    grid_offset_y = (tile_radius * tile_size) + local_y
    return {
        "zoom": zoom,
        "tiles": tiles,
        "offset_x": f"{grid_offset_x:.2f}",
        "offset_y": f"{grid_offset_y:.2f}",
    }


def _safe_epoch(value):
    """Return an integer epoch value when possible, else None."""
    epoch_value = _safe_float(value)
    if epoch_value is None:
        return None
    return int(epoch_value)


def _local_hour_is_divisible(ts, divisor):
    """Return True when an epoch's local hour is divisible by divisor."""
    try:
        return datetime.datetime.fromtimestamp(ts).hour % divisor == 0
    except Exception:
        return False


def _current_period_start_index(rows, period_hours, now=None, hour_divisor=None):
    """Return the row index for the active forecast period."""
    if not isinstance(rows, list) or not rows:
        return 0

    now_epoch = _safe_epoch(now)
    if now_epoch is None:
        now_epoch = int(time.time())

    period_seconds = int(period_hours * 3600)
    first_future = None
    found_timestamp = False
    found_aligned_timestamp = hour_divisor is None

    for idx, row in enumerate(rows):
        ts = _safe_epoch((row or {}).get("time"))
        if ts is None:
            continue

        found_timestamp = True
        if hour_divisor is not None:
            if not _local_hour_is_divisible(ts, hour_divisor):
                continue
            found_aligned_timestamp = True

        if ts <= now_epoch < ts + period_seconds:
            return idx
        if ts >= now_epoch and first_future is None:
            first_future = idx

    if first_future is not None:
        return first_future

    if found_aligned_timestamp:
        return len(rows) if found_timestamp else 0

    return _current_period_start_index(rows, period_hours, now)


def _slice_from_current_period(rows, period_hours, now=None, hour_divisor=None):
    """Return forecast rows starting at the active period."""
    if not isinstance(rows, list) or not rows:
        return []
    start_index = _current_period_start_index(rows, period_hours, now, hour_divisor)
    return rows[start_index:]


def _pick_three_hourly_from_current_period(hourly_rows):
    """Return every third hourly row, starting with the active 3-hour period."""
    hourly_rows = _slice_from_current_period(hourly_rows, 3, hour_divisor=3)
    return hourly_rows[::3]


def _load_aeris_icon_map(config_dict, skin_dict):
    """Load Aeris/Xweather icon mappings to Belchertown icon names."""
    iconlist_file_path = os.path.join(
        config_dict["WEEWX_ROOT"],
        skin_dict["SKIN_ROOT"],
        skin_dict.get("skin", ""),
        "images/aeris-icon-list.json",
    )
    try:
        with open(iconlist_file_path, "r", encoding="utf-8") as icon_fh:
            return json.load(icon_fh)
    except Exception as e:
        log.error(f"aeris-icon-list.json is missing or unreadable in {iconlist_file_path}: {e}")
        return {}


def _aeris_icon_to_belch(icon_value, icon_map):
    """Map an Aeris/Xweather icon filename to the skin icon base name."""
    if not isinstance(icon_value, str) or not icon_value:
        return "unknown"
    icon_name = icon_value.split(".")[0]
    return icon_map.get(icon_name, "unknown")


def _aeris_coded_weather(data, label_dict, full_observation=False):
    """Convert Aeris/Xweather coded weather to a localized summary."""
    if not isinstance(data, str) or not data:
        return ""

    parts = data.split(":")
    if len(parts) < 3:
        return ""

    coverage_code = parts[0]
    intensity_code = parts[1]
    weather_code = parts[2]

    cloud_dict = {
        "CL": label_dict["forecast_cloud_code_CL"],
        "FW": label_dict["forecast_cloud_code_FW"],
        "SC": label_dict["forecast_cloud_code_SC"],
        "BK": label_dict["forecast_cloud_code_BK"],
        "OV": label_dict["forecast_cloud_code_OV"],
    }

    coverage_dict = {
        "AR": label_dict["forecast_coverage_code_AR"],
        "BR": label_dict["forecast_coverage_code_BR"],
        "C": label_dict["forecast_coverage_code_C"],
        "D": label_dict["forecast_coverage_code_D"],
        "FQ": label_dict["forecast_coverage_code_FQ"],
        "IN": label_dict["forecast_coverage_code_IN"],
        "IS": label_dict["forecast_coverage_code_IS"],
        "L": label_dict["forecast_coverage_code_L"],
        "NM": label_dict["forecast_coverage_code_NM"],
        "O": label_dict["forecast_coverage_code_O"],
        "PA": label_dict["forecast_coverage_code_PA"],
        "PD": label_dict["forecast_coverage_code_PD"],
        "S": label_dict["forecast_coverage_code_S"],
        "SC": label_dict["forecast_coverage_code_SC"],
        "VC": label_dict["forecast_coverage_code_VC"],
        "WD": label_dict["forecast_coverage_code_WD"],
    }

    intensity_dict = {
        "VL": label_dict["forecast_intensity_code_VL"],
        "L": label_dict["forecast_intensity_code_L"],
        "H": label_dict["forecast_intensity_code_H"],
        "VH": label_dict["forecast_intensity_code_VH"],
    }

    weather_dict = {
        "A": label_dict["forecast_weather_code_A"],
        "BD": label_dict["forecast_weather_code_BD"],
        "BN": label_dict["forecast_weather_code_BN"],
        "BR": label_dict["forecast_weather_code_BR"],
        "BS": label_dict["forecast_weather_code_BS"],
        "BY": label_dict["forecast_weather_code_BY"],
        "F": label_dict["forecast_weather_code_F"],
        "FR": label_dict["forecast_weather_code_FR"],
        "H": label_dict["forecast_weather_code_H"],
        "IC": label_dict["forecast_weather_code_IC"],
        "IF": label_dict["forecast_weather_code_IF"],
        "IP": label_dict["forecast_weather_code_IP"],
        "K": label_dict["forecast_weather_code_K"],
        "L": label_dict["forecast_weather_code_L"],
        "R": label_dict["forecast_weather_code_R"],
        "RW": label_dict["forecast_weather_code_RW"],
        "RS": label_dict["forecast_weather_code_RS"],
        "SI": label_dict["forecast_weather_code_SI"],
        "WM": label_dict["forecast_weather_code_WM"],
        "S": label_dict["forecast_weather_code_S"],
        "SW": label_dict["forecast_weather_code_SW"],
        "T": label_dict["forecast_weather_code_T"],
        "UP": label_dict["forecast_weather_code_UP"],
        "VA": label_dict["forecast_weather_code_VA"],
        "WP": label_dict["forecast_weather_code_WP"],
        "ZF": label_dict["forecast_weather_code_ZF"],
        "ZL": label_dict["forecast_weather_code_ZL"],
        "ZR": label_dict["forecast_weather_code_ZR"],
        "ZY": label_dict["forecast_weather_code_ZY"],
    }

    if weather_code in cloud_dict:
        return cloud_dict[weather_code]

    output = ""
    if full_observation and coverage_code in coverage_dict:
        output += coverage_dict[coverage_code] + " "
    if intensity_code in intensity_dict:
        output += intensity_dict[intensity_code] + " "
    output += weather_dict.get(weather_code, "")
    return output.strip()


def _aeris_temp_value(period, forecast_units, key_prefix):
    """Return an Aeris temperature value in the configured forecast unit."""
    if forecast_units in ("si", "ca", "uk2"):
        return _safe_float(period.get(key_prefix + "C"))
    return _safe_float(period.get(key_prefix + "F"))


def _aeris_wind_values(period, forecast_units):
    """Return Aeris wind speed and gust in the configured forecast unit."""
    if forecast_units == "ca":
        return (_safe_float(period.get("windSpeedKPH")), _safe_float(period.get("windGustKPH")))
    if forecast_units == "si":
        speed = _safe_float(period.get("windSpeedKPH"))
        gust = _safe_float(period.get("windGustKPH"))
        return (
            speed / 3.6 if speed is not None else None,
            gust / 3.6 if gust is not None else None,
        )
    return (_safe_float(period.get("windSpeedMPH")), _safe_float(period.get("windGustMPH")))


def _aeris_snow_values(period, forecast_units):
    """Return Aeris snow depth and display unit."""
    if forecast_units in ("si", "ca", "uk2"):
        return (_safe_float(period.get("snowCM")) or 0, "cm")
    return (_safe_float(period.get("snowIN")) or 0, "in")


def _aeris_period_to_common(period, interval, forecast_units, label_dict, icon_map):
    """Normalize one Aeris/Xweather forecast period."""
    period = period or {}
    wind_speed, wind_gust = _aeris_wind_values(period, forecast_units)
    snow_depth, snow_unit = _aeris_snow_values(period, forecast_units)

    row = {
        "time": _safe_epoch(period.get("timestamp")) or int(time.time()),
        "summary": _aeris_coded_weather(
            period.get("weatherPrimaryCoded"), label_dict, False
        ),
        "icon": _aeris_icon_to_belch(period.get("icon"), icon_map),
        "windSpeed": wind_speed,
        "windGust": wind_gust,
        "windBearing": _safe_float(period.get("windDirDEG")),
        "precipProbability": _probability_fraction(period.get("pop")),
        "humidity": _probability_fraction(period.get("humidity"), default=None),
        "dewPoint": _aeris_temp_value(period, forecast_units, "dewpoint"),
        "snowDepth": snow_depth,
        "snowUnit": snow_unit,
        "weatherCode": period.get("weatherPrimaryCoded"),
    }

    if interval == "forecast_24hr":
        row["temperatureHigh"] = _aeris_temp_value(period, forecast_units, "maxTemp")
        row["temperatureLow"] = _aeris_temp_value(period, forecast_units, "minTemp")
    else:
        row["temperature"] = _aeris_temp_value(period, forecast_units, "avgTemp")
        row["temperatureHigh"] = _aeris_temp_value(period, forecast_units, "maxTemp")
        row["temperatureLow"] = _aeris_temp_value(period, forecast_units, "minTemp")

    return row


def _aeris_alerts_to_common(alerts_payload, label_dict):
    """Normalize Aeris/Xweather alert payload to the common alert schema."""
    alerts_response = (
        ((alerts_payload or {}).get("alerts") or [{}])[0].get("response") or []
    )
    output = []
    for alert in alerts_response:
        details = (alert or {}).get("details") or {}
        timestamps = (alert or {}).get("timestamps") or {}
        alert_type = details.get("type") or ""
        label_key = "forecast_alert_code_" + alert_type.replace(".", "_")
        output.append(
            {
                "title": _compact_alert_title(
                    label_dict.get(label_key),
                    details.get("name"),
                ),
                "effective": timestamps.get("issued"),
                "onset": timestamps.get("begins") or timestamps.get("issued"),
                "ends": timestamps.get("expires"),
                "expires": timestamps.get("expires"),
                "description": details.get("body") or "",
                "severity": details.get("severity") or "",
                "uri": alert_type,
                "source": "aeris",
            }
        )
    return output


def _aeris_transform_to_belch(aeris_payload, forecast_units, label_dict, icon_map):
    """Map Aeris/Xweather forecast responses to the common forecast schema."""
    aeris_payload = aeris_payload or {}

    def _periods(interval):
        try:
            return (
                aeris_payload.get(interval, [{}])[0]
                .get("response", [{}])[0]
                .get("periods", [])
            )
        except Exception:
            return []

    hourly = _slice_from_current_period(
        [
            _aeris_period_to_common(
                p, "forecast_1hr", forecast_units, label_dict, icon_map
            )
            for p in _periods("forecast_1hr")
        ],
        1,
    )
    three_hourly = _slice_from_current_period(
        [
            _aeris_period_to_common(
                p, "forecast_3hr", forecast_units, label_dict, icon_map
            )
            for p in _periods("forecast_3hr")
        ],
        3,
        hour_divisor=3,
    )
    daily = [
        _aeris_period_to_common(p, "forecast_24hr", forecast_units, label_dict, icon_map)
        for p in _periods("forecast_24hr")
    ]

    return {
        "current": [],
        "hourly": hourly,
        "threeHourly": three_hourly,
        "daily": daily,
        "alerts": _aeris_alerts_to_common(aeris_payload, label_dict),
        "aqi": aeris_payload.get("aqi", []),
        "provider": "aeris",
        "schema": "belchertown.forecast.v1",
        "generated_at": _safe_epoch(aeris_payload.get("timestamp")) or int(time.time()),
    }


def _aeris_current_to_common(current_payload, current_conditions, forecast_units, label_dict, icon_map):
    """Map Aeris/Xweather current-condition response to the common current schema."""
    current_payload = current_payload or {}
    response = ((current_payload.get("current") or [{}])[0]).get("response")
    current_data = None

    if current_conditions == "obs" and isinstance(response, dict):
        current_data = response.get("ob")
    elif current_conditions == "conds" and isinstance(response, list):
        current_data = (((response[0] or {}).get("periods") or [{}])[0] if response else None)
    elif current_conditions == "obs-on-fail-conds":
        if isinstance(response, dict):
            current_data = response.get("ob")
        if current_data is None and isinstance(response, list) and response:
            current_data = ((response[0] or {}).get("periods") or [{}])[0]

    current_data = current_data or {}
    visibility = (
        _safe_float(current_data.get("visibilityKM"))
        if forecast_units in ("si", "ca")
        else _safe_float(current_data.get("visibilityMI"))
    )
    temp = (
        _safe_float(current_data.get("tempC"))
        if forecast_units in ("si", "ca", "uk2")
        else _safe_float(current_data.get("tempF"))
    )
    dewpoint = (
        _safe_float(current_data.get("dewpointC"))
        if forecast_units in ("si", "ca", "uk2")
        else _safe_float(current_data.get("dewpointF"))
    )
    feels_like = (
        _safe_float(current_data.get("feelslikeC"))
        if forecast_units in ("si", "ca", "uk2")
        else _safe_float(current_data.get("feelslikeF"))
    )
    wind_speed_key = "windSpeedKPH" if forecast_units in ("si", "ca") else "windSpeedMPH"
    wind_gust_key = "windGustKPH" if forecast_units in ("si", "ca") else "windGustMPH"

    current = {
        "time": _safe_epoch(current_data.get("timestamp")) or int(time.time()),
        "summary": _aeris_coded_weather(
            current_data.get("weatherPrimaryCoded"), label_dict, True
        ),
        "icon": _aeris_icon_to_belch(current_data.get("icon"), icon_map),
        "temperature": temp,
        "apparentTemperature": feels_like,
        "windSpeed": _safe_float(current_data.get(wind_speed_key)),
        "windGust": _safe_float(current_data.get(wind_gust_key)),
        "windBearing": _safe_float(current_data.get("windDirDEG")),
        "humidity": _probability_fraction(current_data.get("humidity"), default=None),
        "pressure": _safe_float(current_data.get("pressureMB")),
        "visibility": visibility,
        "dewPoint": dewpoint,
        "precipIntensity": _safe_float(current_data.get("precipMM" if forecast_units in ("si", "ca") else "precipIN")),
        "precipProbability": None,
        "cloudCover": _safe_float(current_data.get("sky")),
        "weatherCode": current_data.get("weatherPrimaryCoded"),
    }

    if forecast_units == "si":
        if current["windSpeed"] is not None:
            current["windSpeed"] = current["windSpeed"] / 3.6
        if current["windGust"] is not None:
            current["windGust"] = current["windGust"] / 3.6

    return {
        "timestamp": _safe_epoch(current_payload.get("timestamp")) or int(time.time()),
        "provider": "aeris",
        "schema": "belchertown.current.v1",
        "current": [current],
    }


def _format_attr(value):
    """Format numeric diagram attributes to 3 decimals, else empty string."""
    v = _safe_float(value)
    if v is None:
        return ""
    return f"{v:.3f}"


ALMANAC_DIAGRAM_DEFAULTS = {
    "min_x": 0.0,
    "max_x": 1440.0,
    "vertical_scale": 3.25,
    "object_radius": 68.0,
    "svg_width": 180.0,
    "svg_height": 300.0,
    "center_apex_mode": "transit",
}

# Baseline viewport used to normalize curve amplification behavior. When users
# increase configured SVG height relative to width, vertical curve amplitude is
# increased in Python rather than stretching via SVG aspect-ratio tricks.
ALMANAC_BASELINE_SVG_WIDTH = 200.0
ALMANAC_BASELINE_SVG_HEIGHT = 250.0


def _apply_almanac_diagram_extras_overrides(extras_dict):
    """Apply optional almanac diagram mode from [Extras]."""

    if not isinstance(extras_dict, dict):
        return

    mode_raw = extras_dict.get("align_solar_path")
    if mode_raw is None:
        mode_raw = extras_dict.get("align_luminary_path")
    if mode_raw is None:
        mode_raw = extras_dict.get("align_sky_path")
    if mode_raw is None:
        legacy_mode_raw = extras_dict.get("almanac_diagram")
        if legacy_mode_raw is not None:
            legacy_mode = str(legacy_mode_raw).strip().lower()
            if legacy_mode == "shared":
                mode_raw = "now"
            elif legacy_mode == "per_body":
                mode_raw = "transit"
            elif legacy_mode == "off":
                mode_raw = "off"
            else:
                mode_raw = legacy_mode

    if mode_raw is not None:
        mode = str(mode_raw).strip().lower()
        if mode in ("off", "now", "transit"):
            ALMANAC_DIAGRAM_DEFAULTS["center_apex_mode"] = mode

# Resolution for sampled day tracks used to build sun/moon SVG path geometry.
# Smaller values produce denser curves that better align with live alt/az points.
ALMANAC_DIAGRAM_SAMPLE_STEP_MINUTES = 30
ALMANAC_DIAGRAM_MOON_SAMPLE_STEP_MINUTES = 30

def get_almanac_diagram_defaults():
    """Return centralized defaults for almanac diagram rendering."""

    defaults = dict(ALMANAC_DIAGRAM_DEFAULTS)
    defaults["sun_track_path_attr"] = _default_track_path()
    defaults["moon_track_path_attr"] = _default_track_path()
    defaults["almanac_svg_markup_attr"] = _build_almanac_svg_markup(
        {
            "sun_track_path_attr": defaults["sun_track_path_attr"],
            "moon_track_path_attr": defaults["moon_track_path_attr"],
            "sun_alt_attr": "",
            "moon_alt_attr": "",
            "diagram_vertical_scale_attr": _format_attr(defaults.get("vertical_scale")),
            "diagram_object_radius_attr": _format_attr(defaults.get("object_radius")),
            "sun_x_offset_attr": _format_attr(0.0),
            "moon_x_offset_attr": _format_attr(0.0),
            "diagram_centering_mode_attr": _get_apex_center_mode(),
        },
        current_ts=None,
    )
    return defaults


def _get_apex_center_mode():
    """Return configured apex-centering mode for almanac tracks."""

    mode = str(ALMANAC_DIAGRAM_DEFAULTS.get("center_apex_mode", "off")).strip().lower()
    if mode in ("off", "now", "transit"):
        return mode
    return "off"


def _get_vertical_scale():
    """Return vertical scaling for raw altitude plotting.

    Scaling is amplified by configured SVG aspect ratio so increasing
    ``svg_height`` (relative to ``svg_width``) increases curve height in
    geometry space, not by stretched SVG rendering.
    """

    scale = _safe_float(ALMANAC_DIAGRAM_DEFAULTS.get("vertical_scale", 1.0))
    if scale is None:
        return 1.0

    svg_width = _safe_float(ALMANAC_DIAGRAM_DEFAULTS.get("svg_width", ALMANAC_BASELINE_SVG_WIDTH))
    svg_height = _safe_float(ALMANAC_DIAGRAM_DEFAULTS.get("svg_height", ALMANAC_BASELINE_SVG_HEIGHT))
    if svg_width is None or svg_height is None or svg_width <= 0:
        return max(0.0, scale)

    baseline_ratio = ALMANAC_BASELINE_SVG_HEIGHT / ALMANAC_BASELINE_SVG_WIDTH
    ratio = svg_height / svg_width
    amplification = ratio / baseline_ratio if baseline_ratio > 0 else 1.0

    return max(0.0, scale * amplification)


def _project_timealt_to_diagram(time_seconds, altitude):
    """Project local-day time/altitude to true diagram coordinates.

    X is minutes past midnight [0, 1440].
    Y is raw altitude in degrees [-90, 90]. Horizon is exactly 0.
    """

    seconds = _safe_float(time_seconds)
    alt = _safe_float(altitude)
    if seconds is None or alt is None:
        return None

    min_x = ALMANAC_DIAGRAM_DEFAULTS["min_x"]
    max_x = ALMANAC_DIAGRAM_DEFAULTS["max_x"]
    vertical_scale = _get_vertical_scale()

    bounded_seconds = max(0.0, min(86400.0, seconds))
    x = min_x + (bounded_seconds / 60.0)
    x = max(min_x, min(max_x, x))

    bounded_alt = max(-90.0, min(90.0, alt))
    y = -(bounded_alt * vertical_scale)

    return x, y


def _wrap_diagram_x(x_value, x_offset):
    """Wrap an x coordinate into the diagram domain after applying offset."""

    x = _safe_float(x_value)
    offset = _safe_float(x_offset)
    if x is None:
        return None
    if offset is None:
        offset = 0.0

    min_x = ALMANAC_DIAGRAM_DEFAULTS["min_x"]
    max_x = ALMANAC_DIAGRAM_DEFAULTS["max_x"]
    span = max_x - min_x
    if span <= 0:
        return x

    return ((x - min_x + offset) % span) + min_x


def _project_track_points(track_points):
    """Project list of 'minute_of_day,alt' samples into diagram coordinates."""

    projected_points = []
    for sample in track_points or []:
        try:
            minute_str, alt_str = sample.split(",", 1)
        except ValueError:
            continue
        minute_val = _safe_float(minute_str)
        if minute_val is None:
            continue
        time_seconds = minute_val * 60.0
        projected = _project_timealt_to_diagram(time_seconds, alt_str)
        if projected is not None:
            projected_points.append((minute_val, projected[0], projected[1]))

    return projected_points


def _build_track_path_from_projected_points(ordered_points):
    """Build a smooth SVG path from projected ``(order, x, y)`` points."""

    if len(ordered_points) < 2:
        return ""

    # Smooth the sampled polyline using open Catmull-Rom -> cubic Bezier
    # conversion. This preserves point order while removing visual kinks.
    segments = [f"M {ordered_points[0][1]:.1f} {ordered_points[0][2]:.1f}"]
    if len(ordered_points) == 2:
        _, curr_x, curr_y = ordered_points[1]
        segments.append(f"L {curr_x:.1f} {curr_y:.1f}")
        return " ".join(segments)

    for i in range(0, len(ordered_points) - 1):
        _, p1x, p1y = ordered_points[i]
        _, p2x, p2y = ordered_points[i + 1]

        if i > 0:
            _, p0x, p0y = ordered_points[i - 1]
        else:
            p0x, p0y = p1x, p1y

        if i + 2 < len(ordered_points):
            _, p3x, p3y = ordered_points[i + 2]
        else:
            p3x, p3y = p2x, p2y

        c1x = p1x + ((p2x - p0x) / 6.0)
        c1y = p1y + ((p2y - p0y) / 6.0)
        c2x = p2x - ((p3x - p1x) / 6.0)
        c2y = p2y - ((p3y - p1y) / 6.0)

        segments.append(
            f"C {c1x:.1f} {c1y:.1f} {c2x:.1f} {c2y:.1f} {p2x:.1f} {p2y:.1f}"
        )

    return " ".join(segments)


def _compute_apex_x_offset(track_points):
    """Compute x offset needed to center the highest point (apex) at mid-diagram."""

    projected_points = _project_track_points(track_points)
    if not projected_points:
        return 0.0

    apex = min(projected_points, key=lambda p: p[2])
    min_x = ALMANAC_DIAGRAM_DEFAULTS["min_x"]
    max_x = ALMANAC_DIAGRAM_DEFAULTS["max_x"]
    center_x = (min_x + max_x) * 0.5
    return center_x - apex[1]


def _compute_current_x_offset(current_ts):
    """Compute x offset needed to center the current-time marker."""

    now_point = _project_timealt_to_diagram(
        _seconds_since_local_midnight(current_ts), 0.0
    )
    if now_point is None:
        return 0.0

    min_x = ALMANAC_DIAGRAM_DEFAULTS["min_x"]
    max_x = ALMANAC_DIAGRAM_DEFAULTS["max_x"]
    center_x = (min_x + max_x) * 0.5
    return center_x - now_point[0]


def _current_diagram_x(current_ts):
    """Return station-local current x position in diagram coordinates."""

    now_point = _project_timealt_to_diagram(
        _seconds_since_local_midnight(current_ts), 0.0
    )
    if now_point is None:
        return None

    return now_point[0]


def _continuous_track_window_start_minute(x_offset, current_ts=None):
    """Return the absolute minute offset for display x=0 in a wrapped track.

    The returned minute can be outside the current local day. This lets a
    transit- or now-centered 24-hour curve cross midnight while still sampling
    the ephemeris in chronological order.
    """

    offset = _safe_float(x_offset)
    if offset is None:
        offset = 0.0

    start_minute = -offset
    current_seconds = _seconds_since_local_midnight(current_ts)
    current_minute = current_seconds / 60.0

    while current_minute < start_minute:
        start_minute -= 1440.0
    while current_minute > start_minute + 1440.0:
        start_minute += 1440.0

    return start_minute


def _sample_continuous_display_track_points(
    almanac_obj,
    body_name,
    day_start,
    sample_step_minutes,
    x_offset=0.0,
    current_ts=None,
):
    """Sample a wrapped display track from a continuous 24-hour ephemeris window."""

    if almanac_obj is None or day_start is None:
        return [], []

    try:
        step = max(1, int(sample_step_minutes))
    except Exception:
        step = 1

    sample_minutes = list(range(0, (24 * 60) + 1, step))
    if not sample_minutes or sample_minutes[-1] != 24 * 60:
        sample_minutes.append(24 * 60)

    start_minute = _continuous_track_window_start_minute(
        x_offset, current_ts=current_ts
    )
    projected_points = []
    point_attrs = []

    for display_minute in sample_minutes:
        absolute_minute = start_minute + float(display_minute)
        sample_dt = day_start + datetime.timedelta(minutes=absolute_minute)
        sample_ts = int(sample_dt.timestamp())
        try:
            sample_snapshot = almanac_obj(almanac_time=sample_ts)
            sample_body = getattr(sample_snapshot, body_name, None)
            if sample_body is None:
                continue
            sample_alt = _safe_float(getattr(sample_body, "alt", None))
        except Exception:
            continue

        if sample_alt is None:
            continue

        projected = _project_timealt_to_diagram(display_minute * 60.0, sample_alt)
        if projected is None:
            continue

        projected_points.append((float(display_minute), projected[0], projected[1]))
        point_attrs.append(f"{float(display_minute):.0f},{sample_alt:.3f}")

    return projected_points, point_attrs


def _build_track_path_from_points(track_points, x_offset=0.0, wrap_x=False):
    """Build SVG path string from list of 'minute_of_day,alt' samples."""

    if not track_points:
        return ""

    projected_points = _project_track_points(track_points)

    if len(projected_points) < 2:
        return ""

    if wrap_x and abs(_safe_float(x_offset) or 0.0) > 1e-9:
        shifted_points = []
        for minute_val, x_val, y_val in projected_points:
            shifted_x = _wrap_diagram_x(x_val, x_offset)
            shifted_points.append((minute_val, shifted_x, y_val))
        # Draw left-to-right in wrapped coordinates.
        ordered_points = sorted(shifted_points, key=lambda p: p[1])
    else:
        # Keep path in local-time order for a continuous 24-hour track.
        ordered_points = projected_points

    return _build_track_path_from_projected_points(ordered_points)


def _default_track_path():
    """Return a neutral fallback track path on the horizon."""

    min_x = ALMANAC_DIAGRAM_DEFAULTS["min_x"]
    max_x = ALMANAC_DIAGRAM_DEFAULTS["max_x"]
    return f"M {min_x:.1f} 0.0 L {max_x:.1f} 0.0"


def _almanac_content_viewbox(
    payload,
    current_ts,
    object_radius,
    use_x_offsets,
    sun_x_offset,
    moon_x_offset,
    vertical_scale,
):
    """Return a tight viewBox around curve geometry and object markers."""

    if payload is None:
        payload = {}

    def _fallback_viewbox(scale_value):
        scale = _safe_float(scale_value)
        if scale is None:
            scale = _get_vertical_scale()
        scale = max(0.0, scale)

        x_padding = 80.0
        y_padding = 20.0
        scaled_half_height = (90.0 * scale) + y_padding

        return (
            -x_padding,
            -scaled_half_height,
            1440.0 + (x_padding * 2.0),
            scaled_half_height * 2.0,
        )

    sun_track_raw = str(payload.get("sun_track_points_attr", "") or "").strip()
    moon_track_raw = str(payload.get("moon_track_points_attr", "") or "").strip()
    sun_display_track_raw = str(
        payload.get("sun_track_display_points_attr", "") or ""
    ).strip()
    moon_display_track_raw = str(
        payload.get("moon_track_display_points_attr", "") or ""
    ).strip()
    sun_track = [p for p in sun_track_raw.split("|") if p] if sun_track_raw else []
    moon_track = [p for p in moon_track_raw.split("|") if p] if moon_track_raw else []
    sun_display_track = (
        [p for p in sun_display_track_raw.split("|") if p]
        if sun_display_track_raw
        else []
    )
    moon_display_track = (
        [p for p in moon_display_track_raw.split("|") if p]
        if moon_display_track_raw
        else []
    )

    points = []
    for track_points, display_track_points, x_offset in (
        (sun_track, sun_display_track, sun_x_offset),
        (moon_track, moon_display_track, moon_x_offset),
    ):
        track_is_already_displayed = bool(display_track_points)
        if track_is_already_displayed:
            track_points = display_track_points
        projected = _project_track_points(track_points)
        if not projected:
            continue
        for _, x_val, y_val in projected:
            x_out = x_val
            if use_x_offsets and not track_is_already_displayed:
                wrapped = _wrap_diagram_x(x_out, x_offset)
                if wrapped is not None:
                    x_out = wrapped
            points.append((x_out, y_val))

    now_seconds = _seconds_since_local_midnight(current_ts)
    for body_alt_attr, body_offset in (
        (payload.get("sun_alt_attr"), sun_x_offset),
        (payload.get("moon_alt_attr"), moon_x_offset),
    ):
        alt = _safe_float(body_alt_attr)
        if alt is None:
            continue
        marker = _project_timealt_to_diagram(now_seconds, alt)
        if marker is None:
            continue
        marker_x = marker[0]
        if use_x_offsets:
            wrapped = _wrap_diagram_x(marker_x, body_offset)
            if wrapped is not None:
                marker_x = wrapped
        points.append((marker_x, marker[1]))

    if not points:
        return _fallback_viewbox(vertical_scale)

    xs = [p[0] for p in points if p[0] is not None]
    ys = [p[1] for p in points if p[1] is not None]
    if not xs or not ys:
        return _fallback_viewbox(vertical_scale)

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    x_padding = max(8.0, (object_radius * 0.2))
    # Include object symbol/circle area and a small visual buffer.
    y_padding = max(14.0, object_radius + 8.0)

    width = max(1.0, (max_x - min_x) + (x_padding * 2.0))
    height = max(1.0, (max_y - min_y) + (y_padding * 2.0))

    return (
        min_x - x_padding,
        min_y - y_padding,
        width,
        height,
    )


def _seconds_since_local_midnight(current_ts):
    """Return local seconds past midnight for an epoch timestamp."""

    ts = _safe_float(current_ts)
    if ts is None:
        return 0.0

    try:
        now_local = datetime.datetime.fromtimestamp(int(ts))
    except Exception:
        return 0.0

    return (
        (now_local.hour * 3600)
        + (now_local.minute * 60)
        + now_local.second
        + (now_local.microsecond / 1_000_000.0)
    )


def _build_almanac_marker_group(
    body_name,
    symbol,
    altitude_attr,
    object_radius,
    current_ts,
    x_offset=0.0,
    wrap_x=False,
):
    """Build one SVG marker group (sun or moon)."""

    marker_alt = _safe_float(altitude_attr)
    marker_point = None
    if marker_alt is not None:
        marker_point = _project_timealt_to_diagram(
            _seconds_since_local_midnight(current_ts), marker_alt
        )

    transform_attr = ""
    style_attr = ""
    below_horizon_class = ""
    if marker_point is None:
        style_attr = ' style="display:none"'
    else:
        marker_x = marker_point[0]
        if wrap_x:
            marker_x = _wrap_diagram_x(marker_x, x_offset)
        transform_attr = (
            f' transform="translate({marker_x:.1f} {marker_point[1]:.1f})"'
        )
        if marker_alt is not None and marker_alt < 0:
            below_horizon_class = " is-below-horizon"

    marker_class = (
        f"almanac-diagram-object almanac-diagram-object--{body_name}{below_horizon_class}"
    )

    return (
        f'<g class="{marker_class}"{transform_attr}{style_attr}>'
        f"<title>{html.escape(body_name.title())}</title>"
        f'<circle class="almanac-diagram-object-core" r="{object_radius:.3f}"></circle>'
        f'<text class="almanac-diagram-object-symbol" text-anchor="middle">{html.escape(symbol)}</text>'
        "</g>"
    )


def _build_almanac_svg_markup(payload, current_ts):
    """Return authoritative inline SVG markup for the almanac diagram."""

    if payload is None:
        payload = {}

    sun_path_d = str(payload.get("sun_track_path_attr", "") or "").strip()
    moon_path_d = str(payload.get("moon_track_path_attr", "") or "").strip()
    if not sun_path_d:
        sun_path_d = _default_track_path()
    if not moon_path_d:
        moon_path_d = _default_track_path()

    vertical_scale = _safe_float(payload.get("diagram_vertical_scale_attr"))
    if vertical_scale is None:
        vertical_scale = _get_vertical_scale()

    object_radius = _safe_float(payload.get("diagram_object_radius_attr"))
    if object_radius is None:
        object_radius = _safe_float(ALMANAC_DIAGRAM_DEFAULTS.get("object_radius", 8.0))
    if object_radius is None:
        object_radius = 8.0

    centering_mode = str(payload.get("diagram_centering_mode_attr", "off")).strip().lower()
    use_x_offsets = centering_mode in ("now", "transit")
    sun_x_offset = _safe_float(payload.get("sun_x_offset_attr"))
    moon_x_offset = _safe_float(payload.get("moon_x_offset_attr"))
    if sun_x_offset is None:
        sun_x_offset = 0.0
    if moon_x_offset is None:
        moon_x_offset = 0.0

    svg_width = _safe_float(payload.get("diagram_svg_width_attr"))
    if svg_width is None:
        svg_width = _safe_float(ALMANAC_DIAGRAM_DEFAULTS.get("svg_width", 180.0))
    if svg_width is None:
        svg_width = 180.0

    viewbox_x, viewbox_y, viewbox_w, viewbox_h = _almanac_content_viewbox(
        payload,
        current_ts,
        object_radius,
        use_x_offsets,
        sun_x_offset,
        moon_x_offset,
        vertical_scale,
    )
    # Keep canvas tightly fit to the content-fit viewBox. Height should follow
    # curve geometry, not a fixed configured canvas value.
    if viewbox_w > 0:
        svg_height = max(1.0, svg_width * (viewbox_h / viewbox_w))
    else:
        svg_height = _safe_float(payload.get("diagram_svg_height_attr"))
        if svg_height is None:
            svg_height = _safe_float(ALMANAC_DIAGRAM_DEFAULTS.get("svg_height", 300.0))
        if svg_height is None:
            svg_height = 300.0

    min_x = ALMANAC_DIAGRAM_DEFAULTS["min_x"]
    max_x = ALMANAC_DIAGRAM_DEFAULTS["max_x"]

    moon_group = _build_almanac_marker_group(
        "moon",
        "☾",
        payload.get("moon_alt_attr"),
        object_radius,
        current_ts,
        x_offset=moon_x_offset,
        wrap_x=use_x_offsets,
    )
    sun_group = _build_almanac_marker_group(
        "sun",
        "☀",
        payload.get("sun_alt_attr"),
        object_radius,
        current_ts,
        x_offset=sun_x_offset,
        wrap_x=use_x_offsets,
    )

    return (
        f'<svg class="almanac-diagram-svg" width="{svg_width:.1f}" height="{svg_height:.1f}" '
        f'viewBox="{viewbox_x:.1f} {viewbox_y:.1f} {viewbox_w:.1f} {viewbox_h:.1f}" '
        'preserveAspectRatio="xMidYMid meet" role="img" aria-label="Sun and moon">'
        f'<line class="almanac-diagram-horizon" x1="{min_x:.1f}" y1="0" x2="{max_x:.1f}" y2="0"></line>'
        f'<path class="almanac-diagram-track almanac-diagram-track--sun" d="{html.escape(sun_path_d)}"></path>'
        f'<path class="almanac-diagram-track almanac-diagram-track--moon" d="{html.escape(moon_path_d)}"></path>'
        f"{moon_group}"
        f"{sun_group}"
        "</svg>"
    )


def _build_almanac_inline_markup(payload, image_root="."):
    """Return compact, template-ready almanac markup block.

    Includes sunrise/sunset stacks, moonrise/moonset placeholders, and the
    Python-authored SVG diagram container with required dynamic data attributes.
    """

    if payload is None:
        payload = {}

    svg_markup = str(payload.get("almanac_svg_markup_attr", "") or "").strip()
    if not svg_markup or svg_markup == "None":
        return ""

    sun_az_attr = str(payload.get("sun_az_attr", "") or "")
    sun_alt_attr = str(payload.get("sun_alt_attr", "") or "")
    moon_az_attr = str(payload.get("moon_az_attr", "") or "")
    moon_alt_attr = str(payload.get("moon_alt_attr", "") or "")
    diagram_vertical_scale_attr = str(payload.get("diagram_vertical_scale_attr", "") or "")
    sun_x_offset_attr = str(payload.get("sun_x_offset_attr", "0.000") or "0.000")
    moon_x_offset_attr = str(payload.get("moon_x_offset_attr", "0.000") or "0.000")
    diagram_centering_mode_attr = str(payload.get("diagram_centering_mode_attr", "off") or "off")
    diagram_current_ts_attr = str(payload.get("diagram_current_ts_attr", "") or "")
    diagram_current_x_attr = str(payload.get("diagram_current_x_attr", "") or "")

    image_root_clean = str(image_root or ".").rstrip("/")
    sunrise_image = f"{image_root_clean}/images/sunrise.png"
    sunset_image = f"{image_root_clean}/images/sunset.png"

    return (
        '<div class="almanac-sun-stack almanac-sun-stack--rise">'
        '<div class="almanac-sun-time almanac-sun-time--rise almanac-time-row">'
        f'<span class="sunrise-value"></span><span class="sunrise-set-image sunrise-set-image--rise"><img src="{html.escape(sunrise_image)}" alt="" width="20" height="10" loading="lazy" decoding="async"></span>'
        '</div>'
        '<div class="almanac-sun-time almanac-sun-time--moonrise almanac-time-row">'
        '<span class="moonrise-value"></span><span class="moonrise-set-image moonrise-set-image--rise" aria-hidden="true"></span>'
        '</div>'
        '</div>'
        '<div class="almanac-diagram" '
        f'data-sun-az="{html.escape(sun_az_attr)}" '
        f'data-sun-alt="{html.escape(sun_alt_attr)}" '
        f'data-moon-az="{html.escape(moon_az_attr)}" '
        f'data-moon-alt="{html.escape(moon_alt_attr)}" '
        f'data-vertical-scale="{html.escape(diagram_vertical_scale_attr)}" '
        f'data-sun-x-offset="{html.escape(sun_x_offset_attr)}" '
        f'data-moon-x-offset="{html.escape(moon_x_offset_attr)}" '
        f'data-centering-mode="{html.escape(diagram_centering_mode_attr)}" '
        f'data-current-ts="{html.escape(diagram_current_ts_attr)}" '
        f'data-current-x="{html.escape(diagram_current_x_attr)}">'
        f'{svg_markup}'
        '</div>'
        '<div class="almanac-sun-stack almanac-sun-stack--set">'
        '<div class="almanac-sun-time almanac-sun-time--set almanac-time-row">'
        f'<span class="sunrise-set-image"><img src="{html.escape(sunset_image)}" alt="" width="20" height="10" loading="lazy" decoding="async"></span><span class="sunset-value"></span>'
        '</div>'
        '<div class="almanac-sun-time almanac-sun-time--moonset almanac-time-row">'
        '<span class="moonrise-set-image moonrise-set-image--set" aria-hidden="true"></span><span class="moonset-value"></span>'
        '</div>'
        '</div>'
    )


def _safe_getattr_chain(obj, chain):
    """Safely resolve nested attributes like ('sun', 'rise', 'raw')."""
    cur = obj
    for name in chain:
        try:
            cur = getattr(cur, name)
        except Exception:
            return None
    return cur


def detect_almanac_source(almanac_obj, has_extras=None):
    """Best-effort provider label for UI display."""

    if almanac_obj is None:
        return "none"

    def _has_skyfield_marker(obj):
        if obj is None:
            return False
        markers = []
        try:
            markers.append(str(obj.__class__.__name__).lower())
        except Exception:
            pass
        try:
            markers.append(str(obj.__class__.__module__).lower())
        except Exception:
            pass
        try:
            markers.append(str(obj).lower())
        except Exception:
            pass
        return any("skyfield" in m for m in markers)

    # Check almanac wrapper and known nested body objects.
    if _has_skyfield_marker(almanac_obj):
        return "skyfield"

    sun_obj = _safe_getattr_chain(almanac_obj, ("sun",))
    moon_obj = _safe_getattr_chain(almanac_obj, ("moon",))
    if _has_skyfield_marker(sun_obj) or _has_skyfield_marker(moon_obj):
        return "skyfield"

    if has_extras is True:
        return "pyephem"

    # If basic solar tags are available, we still have usable almanac data.
    sun_rise_raw = _safe_getattr_chain(almanac_obj, ("sun", "rise", "raw"))
    sun_set_raw = _safe_getattr_chain(almanac_obj, ("sun", "set", "raw"))
    if sun_rise_raw is not None or sun_set_raw is not None:
        return "pyephem"

    sunrise_raw = _safe_getattr_chain(almanac_obj, ("sunrise", "raw"))
    sunset_raw = _safe_getattr_chain(almanac_obj, ("sunset", "raw"))
    if sunrise_raw is not None or sunset_raw is not None:
        return "pyephem"

    next_solstice = _safe_getattr_chain(almanac_obj, ("next_solstice", "raw"))
    next_equinox = _safe_getattr_chain(almanac_obj, ("next_equinox", "raw"))
    if next_solstice is not None or next_equinox is not None:
        return "pyephem"

    sun_az = _safe_getattr_chain(almanac_obj, ("sun", "az"))
    sun_alt = _safe_getattr_chain(almanac_obj, ("sun", "alt"))
    if sun_az is not None or sun_alt is not None:
        return "pyephem"

    return "none"


def build_daylight_change_string(
    almanac_obj,
    current_ts,
    hour_short="h",
    minute_short="m",
    second_short="s",
    more_than_yesterday_label="more than yesterday",
    less_than_yesterday_label="less than yesterday",
):
    """Build daylight change-vs-yesterday string only."""

    if almanac_obj is None:
        return "Daylight: --"

    sunrise_ts = _safe_getattr_chain(almanac_obj, ("sun", "rise", "raw"))
    if sunrise_ts is None:
        sunrise_ts = _safe_getattr_chain(almanac_obj, ("sunrise", "raw"))

    sunset_ts = _safe_getattr_chain(almanac_obj, ("sun", "set", "raw"))
    if sunset_ts is None:
        sunset_ts = _safe_getattr_chain(almanac_obj, ("sunset", "raw"))

    if sunrise_ts is None or sunset_ts is None:
        # Polar fallback if sun altitude is available.
        sun_alt = _safe_float(_safe_getattr_chain(almanac_obj, ("sun", "alt")))
        if sun_alt is None:
            return "Daylight: --"
        if sun_alt < 0:
            return f"Daylight: 0{hour_short} 0{minute_short} 0{second_short} less than yesterday"
        return f"Daylight: 0{hour_short} 0{minute_short} 0{second_short} more than yesterday"

    try:
        today_daylight = int(round(float(sunset_ts) - float(sunrise_ts)))
    except Exception:
        return "Daylight: --"

    if today_daylight < 0:
        today_daylight = 0

    try:
        now_ts = int(current_ts)
    except Exception:
        now_ts = int(time.time())
    yesterday_ts = now_ts - 86400

    yesterday_snapshot = None
    try:
        yesterday_snapshot = almanac_obj(almanac_time=yesterday_ts)
    except Exception:
        yesterday_snapshot = None

    if yesterday_snapshot is None:
        return "Daylight: --"

    y_sunrise = _safe_getattr_chain(yesterday_snapshot, ("sun", "rise", "raw"))
    if y_sunrise is None:
        y_sunrise = _safe_getattr_chain(yesterday_snapshot, ("sunrise", "raw"))

    y_sunset = _safe_getattr_chain(yesterday_snapshot, ("sun", "set", "raw"))
    if y_sunset is None:
        y_sunset = _safe_getattr_chain(yesterday_snapshot, ("sunset", "raw"))

    if y_sunrise is None or y_sunset is None:
        return "Daylight: --"

    try:
        yesterday_daylight = int(round(float(y_sunset) - float(y_sunrise)))
    except Exception:
        return "Daylight: --"

    difference = today_daylight - yesterday_daylight
    if difference == 0:
        return "Daylight: no change from yesterday"

    delta = abs(difference)
    amt_minutes = (delta % 3600) // 60
    amt_seconds = delta % 60
    amt_str = f"{amt_minutes}{minute_short} {amt_seconds}{second_short}"
    if difference > 0:
        delta_str = f"{amt_str} {more_than_yesterday_label}"
    else:
        delta_str = f"{amt_str} {less_than_yesterday_label}"

    return f"Daylight: {delta_str}"


def build_almanac_diagram_payload(
    almanac_obj,
    current_ts,
    sample_step_minutes=ALMANAC_DIAGRAM_SAMPLE_STEP_MINUTES,
    moon_sample_step_minutes=ALMANAC_DIAGRAM_MOON_SAMPLE_STEP_MINUTES,
):
    """Compute almanac diagram payload in Python.

    Returns a dict with current body positions, rise/transit/set positions,
    sampled track points, and prebuilt SVG path `d` strings for sun and moon.
    """

    payload = {
        "sun_az_attr": "",
        "sun_alt_attr": "",
        "moon_az_attr": "",
        "moon_alt_attr": "",
        "sun_rise_az_attr": "",
        "sun_rise_alt_attr": "",
        "sun_transit_az_attr": "",
        "sun_transit_alt_attr": "",
        "sun_set_az_attr": "",
        "sun_set_alt_attr": "",
        "moon_rise_az_attr": "",
        "moon_rise_alt_attr": "",
        "moon_transit_az_attr": "",
        "moon_transit_alt_attr": "",
        "moon_set_az_attr": "",
        "moon_set_alt_attr": "",
        "sun_track_points_attr": "",
        "moon_track_points_attr": "",
        "sun_track_display_points_attr": "",
        "moon_track_display_points_attr": "",
        "sun_track_path_attr": "",
        "moon_track_path_attr": "",
        "diagram_vertical_scale_attr": _format_attr(_get_vertical_scale()),
        "diagram_object_radius_attr": _format_attr(
            ALMANAC_DIAGRAM_DEFAULTS.get("object_radius")
        ),
        "diagram_svg_width_attr": _format_attr(
            ALMANAC_DIAGRAM_DEFAULTS.get("svg_width")
        ),
        "diagram_svg_height_attr": _format_attr(
            ALMANAC_DIAGRAM_DEFAULTS.get("svg_height")
        ),
        "sun_x_offset_attr": _format_attr(0.0),
        "moon_x_offset_attr": _format_attr(0.0),
        "diagram_centering_mode_attr": _get_apex_center_mode(),
        "diagram_current_ts_attr": _format_attr(current_ts),
        "diagram_current_x_attr": _format_attr(_current_diagram_x(current_ts)),
        "almanac_svg_markup_attr": "",
    }

    if almanac_obj is None:
        return payload

    # Current body positions
    try:
        payload["sun_az_attr"] = _format_attr(getattr(almanac_obj.sun, "az", None))
        payload["sun_alt_attr"] = _format_attr(getattr(almanac_obj.sun, "alt", None))
    except Exception:
        pass

    try:
        payload["moon_az_attr"] = _format_attr(getattr(almanac_obj.moon, "az", None))
        payload["moon_alt_attr"] = _format_attr(getattr(almanac_obj.moon, "alt", None))
    except Exception:
        pass

    # Event epochs with fallback between modern and legacy tags
    sun_rise_raw = _safe_getattr_chain(almanac_obj, ("sun", "rise", "raw"))
    if sun_rise_raw is None:
        sun_rise_raw = _safe_getattr_chain(almanac_obj, ("sunrise", "raw"))

    sun_set_raw = _safe_getattr_chain(almanac_obj, ("sun", "set", "raw"))
    if sun_set_raw is None:
        sun_set_raw = _safe_getattr_chain(almanac_obj, ("sunset", "raw"))

    sun_transit_raw = _safe_getattr_chain(almanac_obj, ("sun", "transit", "raw"))
    moon_rise_raw = _safe_getattr_chain(almanac_obj, ("moon", "rise", "raw"))
    moon_set_raw = _safe_getattr_chain(almanac_obj, ("moon", "set", "raw"))
    moon_transit_raw = _safe_getattr_chain(almanac_obj, ("moon", "transit", "raw"))

    # Event alt/az snapshots
    def _fill_event(prefix, ts_raw, body_name):
        if ts_raw is None:
            return
        try:
            snapshot = almanac_obj(almanac_time=ts_raw)
            body = getattr(snapshot, body_name, None)
            if body is None:
                return
            payload[f"{prefix}_az_attr"] = _format_attr(getattr(body, "az", None))
            payload[f"{prefix}_alt_attr"] = _format_attr(getattr(body, "alt", None))
        except Exception:
            return

    _fill_event("sun_rise", sun_rise_raw, "sun")
    _fill_event("sun_transit", sun_transit_raw, "sun")
    _fill_event("sun_set", sun_set_raw, "sun")
    _fill_event("moon_rise", moon_rise_raw, "moon")
    _fill_event("moon_transit", moon_transit_raw, "moon")
    _fill_event("moon_set", moon_set_raw, "moon")

    # Sample tracks at fixed cadence from local midnight.
    sun_step = max(1, int(sample_step_minutes))
    moon_step = max(1, int(moon_sample_step_minutes))
    try:
        day_start = datetime.datetime.fromtimestamp(int(current_ts)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    except Exception:
        day_start = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    sun_track_points = []
    moon_track_points = []
    sample_minutes = sorted(
        set(range(0, 24 * 60, sun_step)) | set(range(0, 24 * 60, moon_step))
    )
    for minute_offset in sample_minutes:
        sample_dt = day_start + datetime.timedelta(minutes=minute_offset)
        sample_ts = int(sample_dt.timestamp())
        try:
            sample_snapshot = almanac_obj(almanac_time=sample_ts)
        except Exception:
            continue

        if minute_offset % sun_step == 0:
            try:
                sample_sun = sample_snapshot.sun
                saz = _safe_float(getattr(sample_sun, "az", None))
                salt = _safe_float(getattr(sample_sun, "alt", None))
                if saz is not None and salt is not None:
                    sun_track_points.append(f"{minute_offset:.0f},{salt:.3f}")
            except Exception:
                pass

        if minute_offset % moon_step == 0:
            try:
                sample_moon = sample_snapshot.moon
                maz = _safe_float(getattr(sample_moon, "az", None))
                malt = _safe_float(getattr(sample_moon, "alt", None))
                if maz is not None and malt is not None:
                    moon_track_points.append(f"{minute_offset:.0f},{malt:.3f}")
            except Exception:
                pass

    centering_mode = _get_apex_center_mode()
    use_x_offsets = centering_mode in ("now", "transit")
    sun_x_offset = 0.0
    moon_x_offset = 0.0

    if centering_mode == "now":
        shared_offset = _compute_current_x_offset(current_ts)
        sun_x_offset = shared_offset
        moon_x_offset = shared_offset
    elif centering_mode == "transit":
        if sun_track_points:
            sun_x_offset = _compute_apex_x_offset(sun_track_points)
        if moon_track_points:
            moon_x_offset = _compute_apex_x_offset(moon_track_points)

    payload["sun_x_offset_attr"] = _format_attr(sun_x_offset)
    payload["moon_x_offset_attr"] = _format_attr(moon_x_offset)
    payload["diagram_centering_mode_attr"] = centering_mode
    payload["diagram_current_ts_attr"] = _format_attr(current_ts)
    payload["diagram_current_x_attr"] = _format_attr(_current_diagram_x(current_ts))

    payload["sun_track_points_attr"] = "|".join(sun_track_points)
    payload["moon_track_points_attr"] = "|".join(moon_track_points)

    sun_display_points = []
    moon_display_points = []
    if use_x_offsets:
        (
            sun_display_points,
            sun_display_point_attrs,
        ) = _sample_continuous_display_track_points(
            almanac_obj,
            "sun",
            day_start,
            sun_step,
            x_offset=sun_x_offset,
            current_ts=current_ts,
        )
        (
            moon_display_points,
            moon_display_point_attrs,
        ) = _sample_continuous_display_track_points(
            almanac_obj,
            "moon",
            day_start,
            moon_step,
            x_offset=moon_x_offset,
            current_ts=current_ts,
        )
        payload["sun_track_display_points_attr"] = "|".join(sun_display_point_attrs)
        payload["moon_track_display_points_attr"] = "|".join(moon_display_point_attrs)

    if len(sun_display_points) >= 2:
        payload["sun_track_path_attr"] = _build_track_path_from_projected_points(
            sun_display_points
        )
    else:
        payload["sun_track_path_attr"] = _build_track_path_from_points(
            sun_track_points, x_offset=sun_x_offset, wrap_x=use_x_offsets
        )

    if len(moon_display_points) >= 2:
        payload["moon_track_path_attr"] = _build_track_path_from_projected_points(
            moon_display_points
        )
    else:
        payload["moon_track_path_attr"] = _build_track_path_from_points(
            moon_track_points, x_offset=moon_x_offset, wrap_x=use_x_offsets
        )

    if not payload["sun_track_path_attr"]:
        payload["sun_track_path_attr"] = _default_track_path()
    if not payload["moon_track_path_attr"]:
        payload["moon_track_path_attr"] = _default_track_path()

    payload["almanac_svg_markup_attr"] = _build_almanac_svg_markup(
        payload, current_ts=current_ts
    )

    return payload


def build_almanac_template_context(almanac_obj, current_ts, has_extras=None, image_root="."):
    """Return a template-ready almanac diagram context dictionary.

    This centralizes all variables previously assembled in
    ``almanac_diagram_data.inc`` so templates can consume a consistent set of
    attributes without relying on an extra include file.
    """

    defaults = get_almanac_diagram_defaults()

    context = {
        "almanac_data_source": "none",
        "sun_az_attr": "",
        "sun_alt_attr": "",
        "moon_az_attr": "",
        "moon_alt_attr": "",
        "sun_rise_az_attr": "",
        "sun_rise_alt_attr": "",
        "sun_transit_az_attr": "",
        "sun_transit_alt_attr": "",
        "sun_set_az_attr": "",
        "sun_set_alt_attr": "",
        "moon_rise_az_attr": "",
        "moon_rise_alt_attr": "",
        "moon_transit_az_attr": "",
        "moon_transit_alt_attr": "",
        "moon_set_az_attr": "",
        "moon_set_alt_attr": "",
        "sun_track_points_attr": "",
        "moon_track_points_attr": "",
        "sun_track_path_attr": str(defaults.get("sun_track_path_attr", "") or "").strip(),
        "moon_track_path_attr": str(defaults.get("moon_track_path_attr", "") or "").strip(),
        "diagram_vertical_scale_attr": str(defaults.get("vertical_scale", "") or "").strip(),
        "diagram_object_radius_attr": str(defaults.get("object_radius", "") or "").strip(),
        "almanac_svg_markup_attr": str(defaults.get("almanac_svg_markup_attr", "") or "").strip(),
        "sun_x_offset_attr": "0.000",
        "moon_x_offset_attr": "0.000",
        "diagram_centering_mode_attr": str(defaults.get("center_apex_mode", "off") or "off").strip().lower(),
        "diagram_current_ts_attr": _format_attr(current_ts),
        "diagram_current_x_attr": _format_attr(_current_diagram_x(current_ts)),
        "almanac_inline_markup_attr": "",
    }

    if not context["diagram_vertical_scale_attr"] or context["diagram_vertical_scale_attr"] == "None":
        context["diagram_vertical_scale_attr"] = "2.5"
    if not context["diagram_object_radius_attr"] or context["diagram_object_radius_attr"] == "None":
        context["diagram_object_radius_attr"] = "48.0"
    if not context["sun_track_path_attr"]:
        context["sun_track_path_attr"] = _default_track_path()
    if not context["moon_track_path_attr"]:
        context["moon_track_path_attr"] = _default_track_path()
    if not context["almanac_svg_markup_attr"] or context["almanac_svg_markup_attr"] == "None":
        context["almanac_svg_markup_attr"] = _build_almanac_svg_markup(context)
    context["almanac_inline_markup_attr"] = _build_almanac_inline_markup(
        context, image_root=image_root
    )
    if context["diagram_centering_mode_attr"] not in ("off", "now", "transit"):
        context["diagram_centering_mode_attr"] = "off"

    if has_extras is None:
        has_extras = bool(getattr(almanac_obj, "hasExtras", False))

    try:
        context["almanac_data_source"] = detect_almanac_source(almanac_obj, has_extras)
    except Exception:
        context["almanac_data_source"] = "none"

    if almanac_obj is None:
        return context

    payload = None
    try:
        payload = build_almanac_diagram_payload(almanac_obj, current_ts)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        payload_keys = (
            "sun_az_attr",
            "sun_alt_attr",
            "moon_az_attr",
            "moon_alt_attr",
            "sun_rise_az_attr",
            "sun_rise_alt_attr",
            "sun_transit_az_attr",
            "sun_transit_alt_attr",
            "sun_set_az_attr",
            "sun_set_alt_attr",
            "moon_rise_az_attr",
            "moon_rise_alt_attr",
            "moon_transit_az_attr",
            "moon_transit_alt_attr",
            "moon_set_az_attr",
            "moon_set_alt_attr",
            "sun_track_points_attr",
            "moon_track_points_attr",
            "sun_track_path_attr",
            "moon_track_path_attr",
            "diagram_vertical_scale_attr",
            "diagram_object_radius_attr",
            "almanac_svg_markup_attr",
            "sun_x_offset_attr",
            "moon_x_offset_attr",
            "diagram_centering_mode_attr",
            "diagram_current_ts_attr",
            "diagram_current_x_attr",
            "almanac_inline_markup_attr",
        )

        for key in payload_keys:
            if key in payload:
                value = payload.get(key)
                if value is None:
                    continue
                if isinstance(value, str):
                    context[key] = value
                else:
                    context[key] = str(value)

    if context["diagram_centering_mode_attr"] not in ("off", "now", "transit"):
        context["diagram_centering_mode_attr"] = "off"

    context["almanac_inline_markup_attr"] = _build_almanac_inline_markup(
        context, image_root=image_root
    )

    if context["almanac_data_source"] == "none":
        if (
            context["sun_az_attr"]
            or context["moon_az_attr"]
            or context["sun_track_path_attr"]
            or context["moon_track_path_attr"]
            or context["sun_track_points_attr"]
            or context["moon_track_points_attr"]
        ):
            context["almanac_data_source"] = "pyephem"

    return context


class getData(SearchList):
    """Collect all custom data and calculations, then return search list extension."""

    def __init__(self, generator):
        SearchList.__init__(self, generator)

    def get_gps_distance(self, pointA, pointB, distance_unit):
        """
        https://www.geeksforgeeks.org/program-distance-two-points-earth/ and
        https://stackoverflow.com/a/43960736 The math module contains a
        function named radians which converts from degrees to radians.
        """

        if not isinstance(pointA, tuple) or not isinstance(pointB, tuple):
            raise TypeError("Only tuples are supported as arguments")

        lat1r = radians(pointA[0])
        lon1r = radians(pointA[1])
        lat2r = radians(pointB[0])
        lon2r = radians(pointB[1])

        # Haversine formula (minimized repeated trig calls)
        dlat = lat2r - lat1r
        dlon = lon2r - lon1r
        sin_dlat_2 = sin(dlat * 0.5)
        sin_dlon_2 = sin(dlon * 0.5)
        a = sin_dlat_2 * sin_dlat_2 + cos(lat1r) * cos(lat2r) * sin_dlon_2 * sin_dlon_2
        c = 2 * asin(sqrt(a))

        # Radius of earth: kilometers or miles
        r = 6371 if distance_unit == "km" else 3956

        # Inline bearing calculation to avoid extra function call
        x = sin(dlon) * cos(lat2r)
        y = cos(lat1r) * sin(lat2r) - sin(lat1r) * cos(lat2r) * cos(dlon)
        initial_bearing = degrees(atan2(x, y))
        # Now we have the initial bearing but math.atan2 return values
        # from -180 to + 180 degrees which is not what we want for a compass bearing
        # The solution is to normalize the initial bearing as shown below
        bearing = (initial_bearing + 360) % 360

        # Returns distance (index 0), cardinal (index 1), raw bearing (index 2)
        return [(c * r), self.get_cardinal_direction(bearing), bearing]

    def get_cardinal_direction(self, degree, return_only_labels=False):
        """
        Divides compass into 16 wedges and returns direction label.
        """
        skin_dict = self.generator.skin_dict
        ordinate_names = (
            skin_dict.get("Units", {}).get("Ordinates", {}).get("directions", None)
        )

        if ordinate_names is not None:
            names = (
                ordinate_names if isinstance(ordinate_names, list)
                else weeutil.weeutil.option_as_list(ordinate_names)
            )
        else:
            names = DEFAULT_DIRECTION_LABELS

        if return_only_labels:
            return names

        try:
            idx = int(((float(degree) - 11.25) / 22.5) + 1) % 16
            return names[idx]
        except (ValueError, TypeError):
            return names[0]

    @staticmethod
    def _strip_wrapping_url_quotes(value, unescape_entities=True):
        """Strip accidental quote wrappers from copied iframe URLs."""
        cleaned = str(value or "").strip()
        if unescape_entities:
            cleaned = html.unescape(cleaned)

        while len(cleaned) >= 2:
            previous = cleaned
            for quote in ("'", '"'):
                escaped_quote = "\\" + quote
                if cleaned.startswith(escaped_quote) and cleaned.endswith(escaped_quote):
                    cleaned = cleaned[2:-2].strip()
                    break
                if cleaned.startswith(quote) and cleaned.endswith(quote):
                    cleaned = cleaned[1:-1].strip()
                    break
                if cleaned.startswith(escaped_quote) and cleaned.endswith(quote):
                    cleaned = cleaned[2:-1].strip()
                    break
                if cleaned.startswith(quote) and cleaned.endswith(escaped_quote):
                    cleaned = cleaned[1:-2].strip()
                    break
            if cleaned == previous:
                break

        return cleaned

    @staticmethod
    def _is_absolute_radar_url(value):
        value = str(value or "").lower()
        return value.startswith(("https://", "http://", "//"))

    def _normalize_radar_src(self, value):
        """Return a clean URL from a bare URL, quoted URL, or iframe snippet."""
        raw_src = str(value or "").strip()
        src_match = re.search(r"""(?is)\bsrc\s*=\s*(['"])(.*?)\1""", raw_src)
        if src_match:
            return self._strip_wrapping_url_quotes(src_match.group(2))

        src = self._strip_wrapping_url_quotes(raw_src)
        src_match = re.search(r"""(?is)\bsrc\s*=\s*(['"])(.*?)\1""", src)
        if src_match:
            src = self._strip_wrapping_url_quotes(src_match.group(2))
        return src

    def _build_radar_iframe_from_src(self, src, width, height):
        """Build an iframe from a normalized radar URL."""
        escaped_src = html.escape(self._normalize_radar_src(src), quote=True)
        escaped_width = html.escape(str(width), quote=True)
        escaped_height = html.escape(str(height), quote=True)
        return (
            f'<iframe width="{escaped_width}px" height="{escaped_height}px" '
            f'src="{escaped_src}" frameborder="0" loading="lazy" '
            f'title="Radar map"></iframe>'
        )

    def _normalize_custom_radar_html(self, value, width, height):
        """Accept custom radar HTML or a bare custom radar URL."""
        markup = self._strip_wrapping_url_quotes(value, unescape_entities=False)
        if not markup:
            return ""

        normalized_url = self._strip_wrapping_url_quotes(markup)
        if self._is_absolute_radar_url(normalized_url):
            return self._build_radar_iframe_from_src(normalized_url, width, height)

        def normalize_src_attr(match_obj):
            src = html.escape(
                self._normalize_radar_src(match_obj.group(3)),
                quote=True,
            )
            return f"{match_obj.group(1)}{match_obj.group(2)}{src}{match_obj.group(2)}"

        return re.sub(
            r"""(?is)(\bsrc\s*=\s*)(['"])(.*?)\2""",
            normalize_src_attr,
            markup,
            count=1,
        )

    def _get_radar_html(self, extras_dict, lat, lon, zoom, width, height,
                        rain, wind, temp, marker, overlay):
        """Generate radar HTML based on provider configuration."""
        custom = extras_dict.get("radar_html", "")
        if custom:
            return self._normalize_custom_radar_html(custom, width, height)
        
        if extras_dict.get("aeris_map") == "1":
            return self._build_aeris_radar(
                extras_dict, width, height, lat, lon, zoom, dark=False
            )
        return self._build_windy_radar(
            width, height, lat, lon, zoom, rain, wind, temp, marker == "true",
            overlay
        )

    def _get_radar_html_dark(self, extras_dict, lat, lon, zoom, overlay, width, height):
        """Generate dark mode radar HTML based on provider configuration."""
        custom = extras_dict.get("radar_html_dark", "")
        if custom:
            return self._normalize_custom_radar_html(custom, width, height)
        
        if extras_dict.get("aeris_map") == "1":
            return self._build_aeris_radar(
                extras_dict, width, height, lat, lon, zoom, dark=True
            )
        return "None"

    def _get_radar_html_kiosk(self, extras_dict, skin_dict):
        """Generate kiosk mode radar HTML."""
        width = extras_dict.get("radar_width_kiosk", "")
        height = extras_dict.get("radar_height_kiosk", "")
        src = skin_dict.get("Extras", {}).get("radar_html_kiosk", "")
        return self._build_radar_iframe_from_src(src, width, height)

    def _build_aeris_radar(self, extras_dict, width, height, lat, lon, zoom, dark=False):
        """Build Aeris API radar embed HTML."""
        theme = "flat-dk" if dark else "flat"
        blend = "lighten" if dark else "darken"
        city_suffix = "-dk" if dark else ""
        water_suffix = "-dk" if dark else ""
        
        return (
            f'<img style="object-fit:cover;width:{width}px;height:{height}px" '
            f'src="https://maps.aerisapi.com/{extras_dict["forecast_api_id"]}'
            f'_{extras_dict["forecast_api_secret"]}/{theme},water-depth{water_suffix},'
            f'counties:60,rivers,interstates:60,admin-cities{city_suffix},'
            f'alerts-severe:50:blend({blend}),radar:blend({blend})/'
            f'{width}x{height}/{lat},{lon},{zoom}/current.png" '
            f'alt="Radar map" loading="lazy" decoding="async" '
            f'fetchpriority="low" referrerpolicy="no-referrer"></img>'
        )

    def _build_windy_radar(self, width, height, lat, lon, zoom, rain, wind, temp, marker, overlay):
        """Build Windy.com embedded radar HTML."""
        marker_str = "true" if marker else "false"
        src = (
            f"https://embed.windy.com/embed2.html?lat={lat}&lon={lon}"
            f"&zoom={zoom}&level=surface"
            f"&overlay={overlay}"
            f"&menu=&message=true"
            f"&marker={marker_str}&calendar=&pressure=&type=map"
            f"&location=coordinates&detail=&detailLat={lat}&detailLon={lon}"
            f"&metricRain={rain}&metricWind={wind}&metricTemp={temp}"
            f"&radarRange=-1"
        )
        return self._build_radar_iframe_from_src(src, width, height)

    def _convert_temperature(self, value, from_unit, formatter):
        """Convert temperature value and format for display."""
        conversion_tuple = (value, from_unit, "group_temperature")
        converted = self.generator.converter.convert(conversion_tuple)[0]
        return formatter % converted

    def get_extension_list(self, timespan, db_lookup):
        """
        Build the data needed for the Belchertown skin
        """
        # Cache frequently accessed objects
        config_dict = self.generator.config_dict
        skin_dict = self.generator.skin_dict
        extras_dict = self.generator.skin_dict["Extras"]
        label_generic_dict = skin_dict.get("Labels", {}).get("Generic", None)
        if label_generic_dict is None:
            skin_dict.setdefault("Labels", {})["Generic"] = {}
            label_generic_dict = skin_dict["Labels"]["Generic"]

        # Pull user overrides directly from weewx.conf report stanza and
        # normalize any legacy keys there before copying into effective skin dict.
        report_name = skin_dict.get("skin", "Belchertown")
        report_dict = config_dict.get("StdReport", {}).get(report_name, {})
        report_extras_dict = report_dict.get("Extras", {})
        report_label_generic_dict = report_dict.get("Labels", {}).get("Generic", {})

        _apply_legacy_option_mappings(
            report_extras_dict,
            f"StdReport][{report_name}][Extras",
            EXTRAS_LEGACY_MAPPING,
        )
        _apply_legacy_option_mappings(
            report_label_generic_dict,
            f"StdReport][{report_name}][Labels][Generic",
            LABELS_GENERIC_LEGACY_MAPPING,
        )

        for key in EXTRAS_LEGACY_MAPPING.values():
            if key in report_extras_dict:
                extras_dict[key] = report_extras_dict[key]

        for key in LABELS_GENERIC_LEGACY_MAPPING.values():
            if key in report_label_generic_dict:
                label_generic_dict[key] = report_label_generic_dict[key]

        # Backward compatibility for users who put page headers under Extras.
        if "graphs_page_header" in report_extras_dict:
            label_generic_dict["charts_page_header"] = report_extras_dict[
                "graphs_page_header"
            ]
            log.warning(
                "Belchertown: Deprecated option 'graphs_page_header' found in "
                f"[StdReport][{report_name}][Extras]. Using it as "
                "'charts_page_header' for backward compatibility. "
                f"Please move it to [StdReport][{report_name}][Labels][Generic]."
            )
        elif "charts_page_header" in report_extras_dict:
            label_generic_dict["charts_page_header"] = report_extras_dict[
                "charts_page_header"
            ]
            log.warning(
                "Belchertown: Option 'charts_page_header' found in "
                f"[StdReport][{report_name}][Extras]. Using it, but this option "
                f"belongs under [StdReport][{report_name}][Labels][Generic]."
            )
        
        # Validate and fix any legacy configuration options
        extras_dict = _validate_and_fix_legacy_options(
            extras_dict, label_generic_dict
        )
        _apply_almanac_diagram_extras_overrides(extras_dict)
        
        db_binder = self.generator.db_binder

        # Look for the debug flag which can be used to show more logging
        weewx.debug = int(config_dict.get("debug", 0))

        # Setup label dict for text and titles
        try:
            d = skin_dict["Labels"]["Generic"]
        except KeyError:
            d = {}
        label_dict = weeutil.weeutil.KeyDict(d)

        # Setup database manager
        binding = config_dict["StdReport"].get("data_binding", "wx_binding")
        manager = db_binder.get_manager(binding)

        belchertown_debug = int(extras_dict.get("belchertown_debug", 0))

        if belchertown_debug > 0:
            log.info(f"'belchertown_debug' set to {belchertown_debug}")

        # Find the right HTML ROOT
        weewx_root = config_dict["WEEWX_ROOT"]
        if "HTML_ROOT" in skin_dict:
            html_root = os.path.join(
                weewx_root,
                skin_dict["HTML_ROOT"],
            )
        else:
            html_root = os.path.join(
                weewx_root,
                config_dict["StdReport"]["HTML_ROOT"],
            )

        # Setup UTC offset hours for moment.js in index.html
        moment_js_stop_struct = time.localtime(time.time())
        moment_js_utc_offset = (
            calendar.timegm(moment_js_stop_struct)
            - calendar.timegm(time.gmtime(time.mktime(moment_js_stop_struct)))
        ) / 60

        try:
            moment_js_tz = skin_dict["Units"]["TimeZone"].get("time_zone")
        except KeyError:
            moment_js_tz = ""

        # Highcharts UTC offset is the opposite of normal. Positive values are
        # west, negative values are east of UTC.
        # https://api.highcharts.com/highcharts/time.timezoneOffset Multiplying
        # by -1 will reverse the number sign and keep 0 (not -0).
        # https://stackoverflow.com/a/14053631/1177153
        highcharts_timezoneoffset = moment_js_utc_offset * -1

        # If theme locale is auto, get the system locale for use with
        # moment.js, and the system decimal for use with highcharts
        belchertown_locale = extras_dict["belchertown_locale"]
        if belchertown_locale == "auto":
            try:
                locale.setlocale(locale.LC_ALL, "")
                system_locale, locale_encoding = locale.getlocale()
            except Exception:
                system_locale, locale_encoding = None, None
        else:
            try:
                # Try setting the locale. Locale needs to be in locale.encoding
                # format. Example: "en_US.UTF-8", or "de_DE.UTF-8"
                locale.setlocale(
                    locale.LC_ALL,
                    belchertown_locale,
                )
                system_locale, locale_encoding = locale.getlocale()
            except Exception as e:
                # The system can't find the locale requested, so just set the
                # variables anyways for JavaScript's use.
                system_locale, locale_encoding = belchertown_locale.split(".")
                if belchertown_debug:
                    log.error(
                        f"Error using locale {belchertown_locale}. "
                        "This locale may not be installed on your system and you may see unexpected results. "
                        f"Python could not set the requested locale, but Belchertown skin JavaScript will attempt to use the provided locale string. Full error: {e}"
                    )

        if system_locale is None:
            # Unable to determine locale. Fallback to en_US
            system_locale = "en_US"

        if locale_encoding is None:
            # Unable to determine locale_encoding. Fallback to UTF-8
            locale_encoding = "UTF-8"

        try:
            system_locale_js = system_locale.replace(
                "_", "-"
            )  # Python's locale is underscore. JS uses dashes.
        except Exception:
            system_locale_js = "en-US"  # Error finding locale, set to en-US

        # Cache locale conversion for highcharts settings
        locale_conv = locale.localeconv()

        highcharts_decimal = extras_dict.get("highcharts_decimal", None)
        # Change the Highcharts decimal to the locale if the option is missing
        # or on auto mode, otherwise use whats defined in Extras
        if highcharts_decimal is None or highcharts_decimal == "auto":
            highcharts_decimal = locale_conv.get("decimal_point", ".")

        highcharts_thousands = extras_dict.get("highcharts_thousands", None)
        # Change the Highcharts thousands separator to the locale if the option
        # is missing or on auto mode, otherwise use whats defined in Extras
        if highcharts_thousands is None or highcharts_thousands == "auto":
            highcharts_thousands = locale_conv.get("thousands_sep", ",")

        # Get the archive interval for the highcharts gapsize
        try:
            archive_interval_ms = (
                int(config_dict["StdArchive"]["archive_interval"]) * 1000
            )
        except KeyError:
            archive_interval_ms = (
                300000  # 300*1000 for archive_interval emulated to millis
            )

        # Get the ordinal labels
        ordinate_names = self.get_cardinal_direction("", True)

        # Build the chart array for the HTML.  Outputs a dict of nested lists
        # which allow you to have different charts for different timespans on
        # the site in different order with different names.
        # OrderedDict([('day', ['chart1', 'chart2', 'chart3', 'chart4']),
        # ('week', ['chart1', 'chart5', 'chart6', 'chart2', 'chart3', 'chart4']),
        # ('month', ['this_is_chart1', 'chart2_is_here', 'chart3', 'windSpeed_and_windDir', 'chart5', 'chart6', 'chart7']),
        # ('year', ['chart1', 'chart2', 'chart3', 'chart4', 'chart5'])])
        skin_root_path = os.path.join(
            weewx_root,
            skin_dict["SKIN_ROOT"],
            skin_dict.get("skin", ""),
        )
        legacy_chart_config_path = os.path.join(skin_root_path, "graphs.conf")
        chart_config_path = os.path.join(skin_root_path, "charts.conf")
        default_chart_config_path = os.path.join(skin_root_path, "charts.conf.example")
        if os.path.exists(legacy_chart_config_path):
            log.warning(
                f"Belchertown: Found legacy chart config '{legacy_chart_config_path}'. "
                "Using it for backward compatibility. Please migrate to 'charts.conf'."
            )
            chart_dict = configobj.ConfigObj(legacy_chart_config_path, file_error=True)
        elif os.path.exists(chart_config_path):
            chart_dict = configobj.ConfigObj(chart_config_path, file_error=True)
        elif os.path.exists(default_chart_config_path):
            chart_dict = configobj.ConfigObj(default_chart_config_path, file_error=True)
        else:
            chart_dict = configobj.ConfigObj(default_chart_config_path, file_error=True)
        # Gather chart metadata for templates in one pass over charts.conf.
        charts = OrderedDict()
        chartpage_titles = OrderedDict()
        chartpage_content = OrderedDict()
        button_parts = []
        for chartgroup in chart_dict.sections:
            chart_group_config = chart_dict[chartgroup]
            charts[chartgroup] = list(chart_group_config.sections)
            chartpage_titles[chartgroup] = chart_group_config.get("title", chartgroup)

            if "page_content" in chart_group_config:
                chartpage_content[chartgroup] = chart_group_config["page_content"]

            if chart_group_config.get("show_button", "").lower() == "true":
                button_text = chart_group_config.get("button_text", chartgroup)
                button_parts.append(
                    f'<a href="./?chart={chartgroup}"><button type="button" class="btn btn-primary">{button_text}</button></a>'
                )
        chart_page_buttons = " ".join(button_parts)

        # Set a default radar URL using station's lat/lon
        lat = config_dict["Station"]["latitude"]
        lon = config_dict["Station"]["longitude"]
        radar_width = extras_dict["radar_width"]
        radar_height = extras_dict["radar_height"]
        radar_rain = extras_dict["radar_rain"]
        radar_temp = extras_dict["radar_temp"]
        radar_wind = extras_dict["radar_wind"]
        zoom = extras_dict.get("radar_zoom", "8")
        marker = "true" if (
            "radar_marker" in extras_dict and extras_dict["radar_marker"] == "1"
        ) else ""
        radar_overlay = "radar"
        if ("radar_overlay" in extras_dict and extras_dict["radar_overlay"] != ""):
          radar_overlay = extras_dict["radar_overlay"]

        radar_html = self._get_radar_html(
            extras_dict, lat, lon, zoom, radar_width, radar_height,
            radar_rain, radar_wind, radar_temp, marker, radar_overlay
        )
        radar_html_dark = self._get_radar_html_dark(
            extras_dict, lat, lon, zoom, radar_overlay, radar_width, radar_height
        )
        radar_html_kiosk = (
            self._get_radar_html_kiosk(extras_dict, skin_dict)
            if extras_dict.get("radar_html_kiosk") != ""
            else radar_html
        )

        # ==============================================================================
        # Build the all time stats.
        # ==============================================================================

        wx_manager = db_lookup()

        # Find the beginning of the current year
        now = datetime.datetime.now()
        year_start_epoch = int(datetime.datetime(now.year, 1, 1, 0, 0).timestamp())
        next_year_start_epoch = int(
            datetime.datetime(now.year + 1, 1, 1, 0, 0).timestamp()
        )
        month_start_epoch = int(datetime.datetime(now.year, now.month, 1, 0, 0).timestamp())
        today_start_epoch = int(
            datetime.datetime(now.year, now.month, now.day, 0, 0).timestamp()
        )
        week_start_epoch = today_start_epoch - (7 * 86400)
        yesterday_start_epoch = today_start_epoch - 86400

        # Setup the converter
        # Get the target unit nickname (something like 'US' or 'METRIC'):
        target_unit_nickname = config_dict["StdConvert"]["target_unit"]
        # Get the target unit: weewx.US, weewx.METRIC, weewx.METRICWX
        target_unit = weewx.units.unit_constants[target_unit_nickname.upper()]
        # Bind to the appropriate standard converter units
        converter = weewx.units.StdUnitConverters[target_unit]

        # Temperature Range Lookups
        # Use parameterized queries for safety and clarity
        temp_range_sql = """
            SELECT dateTime, (max - min) as total, min, max
            FROM archive_day_outTemp
            WHERE dateTime >= ? AND dateTime < ? AND min IS NOT NULL AND max IS NOT NULL
            ORDER BY total {order} LIMIT 1;
        """
        
        year_outTemp_max_range_query = wx_manager.getSql(
            temp_range_sql.format(order="DESC"), (year_start_epoch, today_start_epoch)
        )
        year_outTemp_min_range_query = wx_manager.getSql(
            temp_range_sql.format(order="ASC"), (year_start_epoch, today_start_epoch)
        )
        month_outTemp_max_range_query = wx_manager.getSql(
            temp_range_sql.format(order="DESC"), (month_start_epoch, today_start_epoch)
        )
        month_outTemp_min_range_query = wx_manager.getSql(
            temp_range_sql.format(order="ASC"), (month_start_epoch, today_start_epoch)
        )
        week_outTemp_max_range_query = wx_manager.getSql(
            temp_range_sql.format(order="DESC"), (week_start_epoch, today_start_epoch)
        )
        week_outTemp_min_range_query = wx_manager.getSql(
            temp_range_sql.format(order="ASC"), (week_start_epoch, today_start_epoch)
        )
        yesterday_outTemp_max_range_query = wx_manager.getSql(
            temp_range_sql.format(order="DESC"), (yesterday_start_epoch, today_start_epoch)
        )
        yesterday_outTemp_min_range_query = wx_manager.getSql(
            temp_range_sql.format(order="ASC"), (yesterday_start_epoch, today_start_epoch)
        )
        at_outTemp_max_range_query = wx_manager.getSql(
            temp_range_sql.format(order="DESC"), (0, today_start_epoch)
        )
        at_outTemp_min_range_query = wx_manager.getSql(
            temp_range_sql.format(order="ASC"), (0, today_start_epoch)
        )

        # Find the group_name for outTemp in database
        outTemp_unit = converter.group_unit_dict["group_temperature"]

        # Find the group_name for outTemp from the skin.conf
        skin_outTemp_unit = self.generator.converter.group_unit_dict[
            "group_temperature"
        ]

        # Find the number of decimals to round to based on the skin.conf
        outTemp_round = skin_dict["Units"]["StringFormats"].get(
            skin_outTemp_unit, "%.1f"
        )

        default_outTemp_range = [
            calendar.timegm(time.gmtime()),
            locale.format_string("%.1f", 0),
            locale.format_string("%.1f", 0),
            locale.format_string("%.1f", 0),
        ]

        def _convert_temp_range_result(query_row):
            if query_row is None:
                return list(default_outTemp_range)

            max_val = self._convert_temperature(query_row[3], outTemp_unit, outTemp_round)
            min_val = self._convert_temperature(query_row[2], outTemp_unit, outTemp_round)
            total = outTemp_round % (float(max_val) - float(min_val))

            return [
                query_row[0],
                locale.format_string("%g", float(total)),
                locale.format_string("%g", float(min_val)),
                locale.format_string("%g", float(max_val)),
            ]

        # Daily temperature-range records for each displayed period.
        year_outTemp_range_max = _convert_temp_range_result(year_outTemp_max_range_query)
        year_outTemp_range_min = _convert_temp_range_result(year_outTemp_min_range_query)
        month_outTemp_range_max = _convert_temp_range_result(month_outTemp_max_range_query)
        month_outTemp_range_min = _convert_temp_range_result(month_outTemp_min_range_query)
        week_outTemp_range_max = _convert_temp_range_result(week_outTemp_max_range_query)
        week_outTemp_range_min = _convert_temp_range_result(week_outTemp_min_range_query)
        yesterday_outTemp_range_max = _convert_temp_range_result(yesterday_outTemp_max_range_query)
        yesterday_outTemp_range_min = _convert_temp_range_result(yesterday_outTemp_min_range_query)
        at_outTemp_range_max = _convert_temp_range_result(at_outTemp_max_range_query)
        at_outTemp_range_min = _convert_temp_range_result(at_outTemp_min_range_query)

        rain_unit = converter.group_unit_dict["group_rain"]

        skin_rain_unit = self.generator.converter.group_unit_dict["group_rain"]

        rain_round = skin_dict["Units"]["StringFormats"].get(skin_rain_unit, "%.2f")

        sunshineDur_unit = converter.group_unit_dict["group_deltatime"]
        skin_sunshineDur_unit = self.generator.converter.group_unit_dict["group_deltatime"]
        sunshineDur_round = skin_dict["Units"]["StringFormats"].get(
            skin_sunshineDur_unit, "%.2f"
        )

        rainiest_day_sql = """
            SELECT dateTime, sum FROM archive_day_rain
            WHERE dateTime >= ? ORDER BY sum DESC LIMIT 1;
        """
        rainiest_day_query = wx_manager.getSql(rainiest_day_sql, (year_start_epoch,))
        if rainiest_day_query is not None:
            rainiest_day_tuple = (rainiest_day_query[1], rain_unit, "group_rain")
            rainiest_day_converted = (
                rain_round % self.generator.converter.convert(rainiest_day_tuple)[0]
            )
            rainiest_day = [
                rainiest_day_query[0],
                locale.format_string("%g", float(rainiest_day_converted)),
            ]
        else:
            rainiest_day = [
                calendar.timegm(time.gmtime()),
                locale.format_string("%.2f", 0),
            ]

        at_rainiest_day_sql = """
            SELECT dateTime, sum FROM archive_day_rain
            ORDER BY sum DESC LIMIT 1;
        """
        at_rainiest_day_query = wx_manager.getSql(at_rainiest_day_sql)
        if at_rainiest_day_query is not None:
            at_rainiest_day_tuple = (
                at_rainiest_day_query[1],
                rain_unit,
                "group_rain",
            )
            at_rainiest_day_converted = (
                rain_round % self.generator.converter.convert(at_rainiest_day_tuple)[0]
            )
            at_rainiest_day = [
                at_rainiest_day_query[0],
                locale.format_string("%g", float(at_rainiest_day_converted)),
            ]
        else:
            at_rainiest_day = [
                calendar.timegm(time.gmtime()),
                locale.format_string("%.2f", 0),
            ]

        # Find what kind of database we're working with and specify the
        # correctly tailored SQL Query for each type of database
        data_binding = config_dict["StdArchive"]["data_binding"]
        database = config_dict["DataBindings"][data_binding]["database"]
        database_type = config_dict["Databases"][database]["database_type"]
        driver = config_dict["DatabaseTypes"][database_type]["driver"]
        if driver == "weedb.sqlite":
            year_rainiest_month_sql = """
                SELECT strftime('%m', datetime(dateTime, 'unixepoch', 'localtime')) AS month, SUM(sum) AS total
                FROM archive_day_rain
                WHERE dateTime >= ? AND dateTime < ?
                GROUP BY month ORDER BY total DESC LIMIT 1;
            """
            at_rainiest_month_sql = """
                SELECT strftime('%m', datetime(dateTime, 'unixepoch', 'localtime')) AS month, strftime('%Y', datetime(dateTime, 'unixepoch', 'localtime')) AS year, SUM(sum) AS total
                FROM archive_day_rain
                GROUP BY month, year ORDER BY total DESC LIMIT 1;
            """
            year_rain_data_sql = """
                SELECT dateTime, sum, count FROM archive_day_rain
                WHERE dateTime >= ? AND dateTime < ?
                ORDER BY dateTime;
            """
            at_rain_highest_year_sql = """
                SELECT strftime('%Y', datetime(dateTime, 'unixepoch', 'localtime')) AS year, SUM(sum) AS total
                FROM archive_day_rain
                GROUP BY year ORDER BY total DESC LIMIT 1;
            """
        elif driver == "weedb.mysql":
            year_rainiest_month_sql = """
                SELECT FROM_UNIXTIME(dateTime, '%%m') AS month, ROUND(SUM(sum), 2) AS total
                FROM archive_day_rain
                WHERE dateTime >= ? AND dateTime < ?
                GROUP BY month ORDER BY total DESC LIMIT 1;
            """
            at_rainiest_month_sql = """
                SELECT FROM_UNIXTIME(dateTime, '%%m') AS month, FROM_UNIXTIME(dateTime, '%%Y') AS year, ROUND(SUM(sum), 2) AS total
                FROM archive_day_rain
                GROUP BY month, year ORDER BY total DESC LIMIT 1;
            """
            year_rain_data_sql = """
                SELECT dateTime, ROUND(sum, 2), count FROM archive_day_rain
                WHERE dateTime >= ? AND dateTime < ?
                ORDER BY dateTime;
            """
            at_rain_highest_year_sql = """
                SELECT FROM_UNIXTIME(dateTime, '%%Y') AS year, ROUND(SUM(sum), 2) AS total
                FROM archive_day_rain
                GROUP BY year ORDER BY total DESC LIMIT 1;
            """

        # Rainiest month
        year_rainiest_month_query = wx_manager.getSql(
            year_rainiest_month_sql, (year_start_epoch, next_year_start_epoch)
        )
        if year_rainiest_month_query is not None:
            year_rainiest_month_tuple = (
                year_rainiest_month_query[1],
                rain_unit,
                "group_rain",
            )
            year_rainiest_month_converted = (
                rain_round
                % self.generator.converter.convert(year_rainiest_month_tuple)[0]
            )
            year_rainiest_month_name = calendar.month_name[
                int(year_rainiest_month_query[0])
            ]
            year_rainiest_month = [
                year_rainiest_month_name,
                locale.format_string("%g", float(year_rainiest_month_converted)),
            ]
        else:
            year_rainiest_month = ["N/A", 0.0]

        # All time rainiest month
        at_rainiest_month_query = wx_manager.getSql(at_rainiest_month_sql)
        if at_rainiest_month_query is not None and len(at_rainiest_month_query) >= 3:
            at_rainiest_month_tuple = (at_rainiest_month_query[2], rain_unit, "group_rain")
            at_rainiest_month_converted = (
                rain_round % self.generator.converter.convert(at_rainiest_month_tuple)[0]
            )
            at_rainiest_month_name = calendar.month_name[int(at_rainiest_month_query[0])]
            at_rainiest_month = [
                f"{at_rainiest_month_name}, {at_rainiest_month_query[1]}",
                locale.format_string("%g", float(at_rainiest_month_converted)),
            ]
        else:
            at_rainiest_month = ["N/A", 0.0]

        # All time rainiest year
        at_rain_highest_year_query = wx_manager.getSql(at_rain_highest_year_sql)
        if at_rain_highest_year_query is not None and len(at_rain_highest_year_query) >= 2:
            at_rain_highest_year_tuple = (
                at_rain_highest_year_query[1],
                rain_unit,
                "group_rain",
            )
            at_rain_highest_year_converted = (
                rain_round % self.generator.converter.convert(at_rain_highest_year_tuple)[0]
            )
            at_rain_highest_year = [
                at_rain_highest_year_query[0],
                locale.format_string("%g", float(at_rain_highest_year_converted)),
            ]
        else:
            at_rain_highest_year = ["N/A", 0.0]

        try:
            suniest_day_sql = """
                SELECT dateTime, sum FROM archive_day_sunshineDur
                WHERE dateTime >= ? ORDER BY sum DESC LIMIT 1;
            """
            suniest_day_query = wx_manager.getSql(suniest_day_sql, (year_start_epoch,))
            if suniest_day_query is not None and len(suniest_day_query) >= 2:
                suniest_day_tuple = (
                    suniest_day_query[1],
                    sunshineDur_unit,
                    "group_deltatime",
                )
                suniest_day_converted = (
                    sunshineDur_round
                    % self.generator.converter.convert(suniest_day_tuple)[0]
                )
                suniest_day = [
                    suniest_day_query[0],
                    locale.format_string("%g", float(suniest_day_converted)),
                ]
            else:
                suniest_day = [
                    calendar.timegm(time.gmtime()),
                    locale.format_string("%.2f", 0),
                ]

            at_suniest_day_sql = """
                SELECT dateTime, sum FROM archive_day_sunshineDur
                ORDER BY sum DESC LIMIT 1;
            """
            at_suniest_day_query = wx_manager.getSql(at_suniest_day_sql)
            if at_suniest_day_query is not None and len(at_suniest_day_query) >= 2:
                at_suniest_day_tuple = (
                    at_suniest_day_query[1],
                    sunshineDur_unit,
                    "group_deltatime",
                )
                at_suniest_day_converted = (
                    sunshineDur_round
                    % self.generator.converter.convert(at_suniest_day_tuple)[0]
                )
                at_suniest_day = [
                    at_suniest_day_query[0],
                    locale.format_string("%g", float(at_suniest_day_converted)),
                ]
            else:
                at_suniest_day = [
                    calendar.timegm(time.gmtime()),
                    locale.format_string("%.2f", 0),
                ]

            data_binding = config_dict["StdArchive"]["data_binding"]
            database = config_dict["DataBindings"][data_binding]["database"]
            database_type = config_dict["Databases"][database]["database_type"]
            driver = config_dict["DatabaseTypes"][database_type]["driver"]
            if driver == "weedb.sqlite":
                year_suniest_month_sql = """
                    SELECT strftime('%m', datetime(dateTime, 'unixepoch', 'localtime')) AS month, SUM(sum) AS total
                    FROM archive_day_sunshineDur
                    WHERE dateTime >= ? AND dateTime < ?
                    GROUP BY month ORDER BY total DESC LIMIT 1;
                """
                at_suniest_month_sql = """
                    SELECT strftime('%m', datetime(dateTime, 'unixepoch', 'localtime')) AS month, strftime('%Y', datetime(dateTime, 'unixepoch', 'localtime')) AS year, SUM(sum) AS total
                    FROM archive_day_sunshineDur
                    GROUP BY month, year ORDER BY total DESC LIMIT 1;
                """
                at_sunshineDur_highest_year_sql = """
                    SELECT strftime('%Y', datetime(dateTime, 'unixepoch', 'localtime')) AS year, SUM(sum) AS total
                    FROM archive_day_sunshineDur
                    GROUP BY year ORDER BY total DESC LIMIT 1;
                """
            elif driver == "weedb.mysql":
                year_suniest_month_sql = """
                    SELECT FROM_UNIXTIME(dateTime, '%%m') AS month, ROUND(SUM(sum), 2) AS total
                    FROM archive_day_sunshineDur
                    WHERE dateTime >= ? AND dateTime < ?
                    GROUP BY month ORDER BY total DESC LIMIT 1;
                """
                at_suniest_month_sql = """
                    SELECT FROM_UNIXTIME(dateTime, '%%m') AS month, FROM_UNIXTIME(dateTime, '%%Y') AS year, ROUND(SUM(sum), 2) AS total
                    FROM archive_day_sunshineDur
                    GROUP BY month, year ORDER BY total DESC LIMIT 1;
                """
                at_sunshineDur_highest_year_sql = """
                    SELECT FROM_UNIXTIME(dateTime, '%%Y') AS year, ROUND(SUM(sum), 2) AS total
                    FROM archive_day_sunshineDur
                    GROUP BY year ORDER BY total DESC LIMIT 1;
                """

            year_suniest_month_query = wx_manager.getSql(
                year_suniest_month_sql, (year_start_epoch, next_year_start_epoch)
            )
            if year_suniest_month_query is not None and len(year_suniest_month_query) >= 2:
                year_suniest_month_tuple = (
                    year_suniest_month_query[1],
                    sunshineDur_unit,
                    "group_deltatime",
                )
                year_suniest_month_converted = (
                    sunshineDur_round
                    % self.generator.converter.convert(year_suniest_month_tuple)[0]
                )
                year_suniest_month_name = calendar.month_name[
                    int(year_suniest_month_query[0])
                ]
                year_suniest_month = [
                    year_suniest_month_name,
                    locale.format_string("%g", float(year_suniest_month_converted)),
                ]
            else:
                year_suniest_month = ["N/A", 0.0]

            at_suniest_month_query = wx_manager.getSql(at_suniest_month_sql)
            if at_suniest_month_query is not None and len(at_suniest_month_query) >= 3:
                at_suniest_month_tuple = (
                    at_suniest_month_query[2],
                    sunshineDur_unit,
                    "group_deltatime",
                )
                at_suniest_month_converted = (
                    sunshineDur_round
                    % self.generator.converter.convert(at_suniest_month_tuple)[0]
                )
                at_suniest_month_name = calendar.month_name[int(at_suniest_month_query[0])]
                at_suniest_month = [
                    f"{at_suniest_month_name} {at_suniest_month_query[1]}",
                    locale.format_string("%g", float(at_suniest_month_converted)),
                ]
            else:
                at_suniest_month = ["N/A", 0.0]

            at_sunshineDur_highest_year_query = wx_manager.getSql(
                at_sunshineDur_highest_year_sql
            )
            if at_sunshineDur_highest_year_query is not None and len(at_sunshineDur_highest_year_query) >= 2:
                at_sunshineDur_highest_year_tuple = (
                    at_sunshineDur_highest_year_query[1],
                    sunshineDur_unit,
                    "group_deltatime",
                )
                at_sunshineDur_highest_year_converted = (
                    sunshineDur_round
                    % self.generator.converter.convert(at_sunshineDur_highest_year_tuple)[0]
                )
                at_sunshineDur_highest_year = [
                    at_sunshineDur_highest_year_query[0],
                    locale.format_string(
                        "%g", float(at_sunshineDur_highest_year_converted)
                    ),
                ]
            else:
                at_sunshineDur_highest_year = ["N/A", 0.0]
        except Exception as e:
            # Missing sunshine extension table is expected on systems without
            # sunshineDur schema support.
            if "archive_day_sunshineDur" in str(e):
                log.debug(
                    "Sunshine duration stats not available: archive_day_sunshineDur table not found."
                )
            else:
                log.debug(f"Skipping sunshine duration stats: {e}")
            suniest_day = [
                calendar.timegm(time.gmtime()),
                locale.format_string("%.2f", 0),
            ]
            at_suniest_day = [
                calendar.timegm(time.gmtime()),
                locale.format_string("%.2f", 0),
            ]
            year_suniest_month = ["N/A", 0.0]
            at_suniest_month = ["N/A", 0.0]
            at_sunshineDur_highest_year = ["N/A", 0.0]

        # Consecutive days with/without rainfall (best streak in each period window).
        period_rain_data_sql = """
            SELECT dateTime, ROUND(sum, 2), count
            FROM archive_day_rain
            WHERE dateTime >= ? AND dateTime < ?
            ORDER BY dateTime;
        """

        def _compute_consecutive_rain_streaks(rows):
            best_with = (0, 0)
            best_without = (0, 0)
            streak_with = 0
            streak_without = 0
            prev_day = None

            for row in rows:
                day_index = round((row[0] / 86400))
                has_gap = prev_day is not None and (day_index - prev_day) != 1
                has_count = len(row) > 2 and row[2] is not None and row[2] != 0

                if has_gap or not has_count:
                    streak_with = 0
                    streak_without = 0

                prev_day = day_index

                if row[1] != 0:
                    streak_with += 1
                    streak_without = 0
                else:
                    streak_without += 1
                    streak_with = 0

                if streak_with > best_with[0]:
                    best_with = (streak_with, row[0])
                if streak_without > best_without[0]:
                    best_without = (streak_without, row[0])

            return best_with, best_without

        def _normalize_streak_result(streak_pair):
            if streak_pair[0] > 0:
                return [int(streak_pair[0]), int(streak_pair[1])]
            return [0, calendar.timegm(time.gmtime())]

        year_streaks = _compute_consecutive_rain_streaks(
            wx_manager.genSql(
                year_rain_data_sql, (year_start_epoch, next_year_start_epoch)
            )
        )
        year_days_with_rain = _normalize_streak_result(year_streaks[0])
        year_days_without_rain = _normalize_streak_result(year_streaks[1])

        month_streaks = _compute_consecutive_rain_streaks(
            wx_manager.genSql(
                period_rain_data_sql, (month_start_epoch, today_start_epoch)
            )
        )
        month_days_with_rain = _normalize_streak_result(month_streaks[0])
        month_days_without_rain = _normalize_streak_result(month_streaks[1])

        week_streaks = _compute_consecutive_rain_streaks(
            wx_manager.genSql(
                period_rain_data_sql, (week_start_epoch, today_start_epoch)
            )
        )
        week_days_with_rain = _normalize_streak_result(week_streaks[0])
        week_days_without_rain = _normalize_streak_result(week_streaks[1])

        yesterday_streaks = _compute_consecutive_rain_streaks(
            wx_manager.genSql(
                period_rain_data_sql, (yesterday_start_epoch, today_start_epoch)
            )
        )
        yesterday_days_with_rain = _normalize_streak_result(yesterday_streaks[0])
        yesterday_days_without_rain = _normalize_streak_result(yesterday_streaks[1])

        at_streaks = _compute_consecutive_rain_streaks(
            wx_manager.genSql(
                "SELECT dateTime, ROUND(sum, 2), count FROM archive_day_rain ORDER BY dateTime;"
            )
        )
        at_days_with_rain = _normalize_streak_result(at_streaks[0])
        at_days_without_rain = _normalize_streak_result(at_streaks[1])

        # This portion is right from the WeeWX sample
        # http://www.weewx.com/docs/customizing.htm

        all_stats = TimespanBinder(
            timespan,
            db_lookup,
            formatter=self.generator.formatter,
            converter=self.generator.converter,
            skin_dict=self.generator.skin_dict,
        )

        # Get the unit label from the skin dict for speed.
        windSpeed_unit = self.generator.skin_dict["Units"]["Groups"]["group_speed"]
        windSpeed_unit_label = self.generator.skin_dict["Units"]["Labels"][
            windSpeed_unit
        ]

        # ==============================================================================
        # Get NOAA Data
        # ==============================================================================
        years = set()
        noaa_header_html = ""
        default_noaa_file = ""
        noaa_dir = html_root + "/NOAA/"

        try:
            # Only process NOAA report files; ignore any other files (csv, etc.) in the directory
            noaa_file_list = [
                f for f in os.listdir(noaa_dir)
                if f.startswith("NOAA-") and f.endswith(".txt")
            ]
            noaa_file_set = set(noaa_file_list)  # O(1) membership tests

            # Generate a list of years based on file name
            for f in noaa_file_list:
                filename = f.split(".")[0]  # Drop the .txt
                year = filename.split("-")[1]
                years.add(year)

            years = sorted(years, reverse=True)

            # Build NOAA header HTML using list then join for efficiency
            noaa_parts = []
            for y in years:
                # Link to the year file
                if f"NOAA-{y}.txt" in noaa_file_set:
                    noaa_parts.append(
                        f"""<a href="?yr={y}" class="noaa_rep_nav"><b>{y}</b></a>:"""
                    )
                else:
                    noaa_parts.append(
                        f"""<span class="noaa_rep_nav"><b>{y}</b></span>:"""
                    )

                # Loop through all 12 months and find if the file exists.  If
                # the file doesn't exist, just show the month name in the
                # header without a href link.  There is no month 13, but we
                # need to loop to 12, so 13 is where it stops.
                month_links = []
                for i in range(1, 13):
                    month_num = f"{i:02d}"  # Pad the number with a 0 since the NOAA files use 2 digit month
                    month_abbr = calendar.month_abbr[i]
                    if f"NOAA-{y}-{month_num}.txt" in noaa_file_set:
                        month_links.append(
                            f"""<a href="?yr={y}&amp;mo={month_num}" class="noaa_rep_nav"><b>{month_abbr}</b></a>"""
                        )
                    else:
                        month_links.append(
                            f"""<span class="noaa_rep_nav"><b>{month_abbr}</b></span>"""
                        )

                noaa_parts.append(" ".join(month_links))
                noaa_parts.append("<br>")

            noaa_header_html = "".join(noaa_parts)

            # Find the current month's NOAA file for the default file to show
            # on JavaScript page load.  The NOAA files are generated as part of
            # this skin, but if for some reason that the month file doesn't
            # exist, use the year file.
            now = datetime.datetime.now()
            current_year = str(now.year)
            current_month = str(format(now.month, "02"))
            if f"NOAA-{current_year}-{current_month}.txt" in noaa_file_set:
                default_noaa_file = f"NOAA-{current_year}-{current_month}.txt"
            else:
                default_noaa_file = f"NOAA-{current_year}.txt"
        except Exception:
            # There's an error - I've seen this on first run and the NOAA
            # folder is not created yet. Skip this section.
            pass

        # ==============================================================================
        # Forecast Data
        # ==============================================================================

        # provider switch (default NWS)
        forecast_provider = extras_dict.get("forecast_provider", "nws").strip().lower()
        if forecast_provider in ("openmeteo", "open_meteo"):
            forecast_provider = "open-meteo"
        if forecast_provider not in (
            "pirateweather",
            "aeris",
            "xweather",
            "nws",
            "open-meteo",
        ):
            log.warning(
                "Unknown forecast_provider '%s'. Falling back to default 'nws'.",
                forecast_provider,
            )
            forecast_provider = "nws"

        # Forecast enabled default should be on when missing.
        forecast_enabled = str(extras_dict.get("forecast_enabled", "1")).strip()
        aqi_enabled = to_bool(extras_dict.get("aqi_enabled", "0"))

        # Ensure AQI variables are always defined to avoid NameError when forecast is disabled or fails
        # aqi and aqi_category are global so they can be used by Highcharts
        global aqi, aqi_category
        aqi = "No Data"
        aqi_category = ""
        aqi_location = ""
        aqi_time = ""

        # ----------------------------
        # Pirate Weather
        # ----------------------------

        try:
            if (
                forecast_enabled == "1"
                and (
                    forecast_provider == "nws"
                    or forecast_provider == "open-meteo"
                    or extras_dict.get("forecast_api_id", "") != ""
                )
                or "forecast_dev_file" in extras_dict
            ):

                # Setup variables common to both forecast sources
                forecast_file = f"{html_root}/json/forecast.json"
                current_conditions_file = f"{html_root}/json/current_conditions.json"
                forecast_json_dir = os.path.dirname(forecast_file)
                try:
                    os.makedirs(forecast_json_dir, exist_ok=True)
                except Exception as e:
                    log.error(
                        f"Unable to create forecast json directory {forecast_json_dir}: {e}"
                    )

                forecast_api_id = extras_dict.get("forecast_api_id", "")
                forecast_api_secret = extras_dict.get("forecast_api_secret", "")
                forecast_units = extras_dict.get("forecast_units", "us").lower()
                forecast_lang = extras_dict.get("forecast_lang", "en").lower()

                latitude = config_dict["Station"]["latitude"]
                longitude = config_dict["Station"]["longitude"]

                forecast_place = extras_dict.get("forecast_place", "")
                if forecast_place:
                    if belchertown_debug > 0:
                        log.info(
                            f"Forecast data using {forecast_place}, instead of [Station] longitude/latitude"
                        )
                else:
                    forecast_place = f"{latitude},{longitude}"
                if belchertown_debug > 0:
                    log.info(f"forecast_place set to {forecast_place}")

                def _refresh_openmeteo_aqi_fallback(force=False):
                    if not aqi_enabled:
                        return None

                    if not force:
                        cached_aqi = _load_aqi_payload_from_forecast_file(
                            forecast_file, require_success=True
                        )
                        if cached_aqi is not None:
                            return cached_aqi

                    aqi_lat, aqi_lon = _resolve_forecast_lat_lon(
                        latitude, longitude, forecast_place
                    )
                    if aqi_lat is None or aqi_lon is None:
                        return None

                    try:
                        aqi_payload = _fetch_openmeteo_aqi_payload(aqi_lat, aqi_lon)
                        if _merge_aqi_payload_into_forecast_file(
                            forecast_file, aqi_payload
                        ):
                            log.info(
                                "Open-Meteo AQI fallback cached to forecast.json"
                            )
                        return aqi_payload
                    except Exception as e:
                        log.warning(
                            "Open-Meteo AQI fallback update failed. "
                            f"Reason: {e}"
                        )
                        return _load_aqi_payload_from_forecast_file(forecast_file)

                def _apply_aqi_globals_from_forecast():
                    global aqi, aqi_category
                    nonlocal aqi_location, aqi_time
                    aqi_payload = _load_aqi_payload_from_forecast_file(forecast_file)
                    if aqi_payload is None:
                        return
                    (
                        aqi,
                        aqi_category,
                        aqi_location,
                        aqi_time,
                    ) = _extract_aqi_globals_from_payload(aqi_payload, label_dict)

                forecast_stale_timer = int(extras_dict["forecast_stale"])
                current_conditions_stale_timer = int(
                    extras_dict["current_conditions_stale"]
                )
                current_time = int(time.time())

                if os.path.isfile(forecast_file):
                    # belchertown.py is called 12 times per archive, so the last condition ensures forecast on the hour is only downloaded once
                    forecast_stat = os.stat(forecast_file)
                    file_modtime = int(forecast_stat.st_mtime)
                    archive_interval = int(
                        config_dict["StdArchive"]["archive_interval"]
                    )
                    forecast_is_stale = (
                        (current_time - file_modtime) > forecast_stale_timer
                        or forecast_stat.st_size == 0
                        or (
                            int(time.strftime("%M")) < archive_interval / 60
                            and (current_time - file_modtime) > archive_interval
                        )
                    )
                else:
                    forecast_is_stale = True
                current_conditions_is_stale = True
                if os.path.isfile(current_conditions_file):
                    current_conditions_stat = os.stat(current_conditions_file)
                    current_conditions_is_stale = (
                        current_time
                        - int(current_conditions_stat.st_mtime)
                    ) > current_conditions_stale_timer or (
                        current_conditions_stat.st_size == 0
                    )

                if forecast_provider == "pirateweather":
                    # Fetch → normalize → write forecast
                    if forecast_is_stale:
                        try:
                            url = f"https://api.pirateweather.net/forecast/{forecast_api_id}/{forecast_place}?units={forecast_units}&lang={forecast_lang}&exclude=minutely"
                            pw_raw = _http_get_json(url)
                            normalized = _pw_transform_to_belch(pw_raw)
                            _write_json_file(forecast_file, normalized)
                            log.debug(
                                f"New Pirate Weather forecast cached to {forecast_file}"
                            ),
                        except urllib.error.HTTPError as e:
                            log.error(
                                f"Pirate Weather HTTP error {e.code}: {e.reason}",
                            )
                        except ValueError as e:
                            log.error(f"Pirate Weather missing config: {e}")
                        except Exception as e:
                            log.error(f"Pirate Weather update failed: {e}")
                    else:
                        log.debug("Forecast is current, no update needed.")

                    # current_conditions.json (tiny file just with 'current')
                    if current_conditions_is_stale:
                        try:
                            _write_current_conditions_from_forecast(
                                forecast_file, current_conditions_file
                            )
                            log.info(
                                f"New Pirate Weather current conditions cached to {current_conditions_file}",
                            )
                        except Exception as e:
                            log.error(
                                f"Pirate Weather current-conditions write failed: {e}",
                            )
                    else:
                        log.debug("Current conditions are current, no update needed.")

                    # Read current_conditions.json and populate the variables used below
                    try:
                        (
                            current_obs_icon,
                            current_obs_summary,
                            visibility,
                            visibility_unit,
                            cloud_cover,
                        ) = _load_normalized_current_conditions(
                            current_conditions_file,
                            forecast_units,
                            cloud_cover_scale=100.0,
                        )
                    except Exception as e:
                        (
                            current_obs_icon,
                            current_obs_summary,
                            visibility,
                            visibility_unit,
                            cloud_cover,
                        ) = _default_current_conditions_values()
                        log.error(f"Pirate Weather parse error: {e}")

                    _refresh_openmeteo_aqi_fallback(force=forecast_is_stale)
                    _apply_aqi_globals_from_forecast()
                elif forecast_provider == "nws":
                    # NWS does not require API id/secret, but does expect a descriptive User-Agent.
                    nws_forecast_failed = False

                    nws_lat, nws_lon = _resolve_forecast_lat_lon(
                        latitude, longitude, forecast_place
                    )

                    # Forecast file (daily/hourly/current + alerts)
                    if forecast_is_stale:
                        try:
                            points_url = f"https://api.weather.gov/points/{nws_lat},{nws_lon}"
                            points_data = _http_get_json(
                                points_url, headers=HTTP_HEADERS["NWS_WEATHER"]
                            )
                            points_props = points_data.get("properties", {})

                            forecast_url = points_props.get("forecast")
                            forecast_hourly_url = points_props.get("forecastHourly")
                            stations_url = points_props.get("observationStations")

                            if not forecast_url or not forecast_hourly_url:
                                raise ValueError("NWS points response missing forecast URLs")

                            forecast_24_data = _http_get_json(
                                forecast_url, headers=HTTP_HEADERS["NWS_WEATHER"]
                            )
                            forecast_hourly_data = _http_get_json(
                                forecast_hourly_url,
                                headers=HTTP_HEADERS["NWS_WEATHER"],
                            )

                            observation_data = {}
                            station_id = extras_dict.get("nws_station_id", "").strip()
                            obs_latest_url = ""
                            if station_id:
                                obs_latest_url = (
                                    f"https://api.weather.gov/stations/{station_id}/observations/latest"
                                )
                            elif stations_url:
                                stations_data = _http_get_json(
                                    stations_url,
                                    headers=HTTP_HEADERS["NWS_WEATHER"],
                                )
                                stations = stations_data.get("features", [])
                                if stations:
                                    first_station_props = (
                                        (stations[0] or {}).get("properties") or {}
                                    )
                                    first_station = first_station_props.get(
                                        "stationIdentifier"
                                    )
                                    if first_station:
                                        obs_latest_url = (
                                            f"https://api.weather.gov/stations/{first_station}/observations/latest"
                                        )
                            if obs_latest_url:
                                observation_data = _http_get_json(
                                    obs_latest_url,
                                    headers=HTTP_HEADERS["NWS_WEATHER"],
                                )

                            alerts_data = {}
                            if extras_dict.get("forecast_alert_enabled") == "1":
                                alerts_url = (
                                    f"https://api.weather.gov/alerts/active?point={nws_lat},{nws_lon}"
                                )
                                alerts_data = _http_get_json(
                                    alerts_url,
                                    headers=HTTP_HEADERS["NWS_WEATHER"],
                                )

                            normalized = _nws_transform_to_belch(
                                forecast_payload=forecast_24_data,
                                hourly_payload=forecast_hourly_data,
                                observation_payload=observation_data,
                                alerts_payload=alerts_data,
                                forecast_units=forecast_units,
                            )
                            _write_json_file(forecast_file, normalized)
                            log.info(f"New NWS forecast cached to {forecast_file}")
                        except Exception as e:
                            nws_forecast_failed = True
                            log.warning(
                                "NWS forecast update failed; treating forecast_enabled as 0 for this cycle. "
                                f"Reason: {e}"
                            )
                    else:
                        log.debug("Forecast is current, no update needed.")

                    if not nws_forecast_failed and not os.path.isfile(forecast_file):
                        nws_forecast_failed = True
                        log.warning(
                            "NWS forecast data unavailable; treating forecast_enabled as 0 for this cycle."
                        )

                    # current_conditions.json (tiny file with current object)
                    if not nws_forecast_failed and current_conditions_is_stale:
                        try:
                            _write_current_conditions_from_forecast(
                                forecast_file, current_conditions_file
                            )
                            log.info(
                                f"New NWS current conditions cached to {current_conditions_file}"
                            )
                        except Exception as e:
                            nws_forecast_failed = True
                            log.warning(
                                "NWS current-conditions update failed; treating forecast_enabled as 0 for this cycle. "
                                f"Reason: {e}"
                            )
                    elif not nws_forecast_failed:
                        log.debug("Current conditions are current, no update needed.")

                    # Read current_conditions.json and populate variables used by templates
                    if not nws_forecast_failed:
                        try:
                            (
                                current_obs_icon,
                                current_obs_summary,
                                visibility,
                                visibility_unit,
                                cloud_cover,
                            ) = _load_normalized_current_conditions(
                                current_conditions_file,
                                forecast_units,
                                cloud_cover_scale=100.0,
                            )
                        except Exception as e:
                            nws_forecast_failed = True
                            log.warning(
                                "NWS current-conditions parse failed; treating forecast_enabled as 0 for this cycle. "
                                f"Reason: {e}"
                            )

                    if nws_forecast_failed:
                        log.warning(
                            "NWS forecast is unavailable for this cycle. Falling back to Open-Meteo."
                        )
                        forecast_provider = "open-meteo"
                    else:
                        _refresh_openmeteo_aqi_fallback(force=forecast_is_stale)
                        _apply_aqi_globals_from_forecast()
                if forecast_provider == "open-meteo":
                    openmeteo_forecast_failed = False

                    om_lat, om_lon = _resolve_forecast_lat_lon(
                        latitude, longitude, forecast_place
                    )

                    # Open-Meteo free API supports direct unit selection.
                    if forecast_units in ("si", "ca"):
                        om_temp_unit = "celsius"
                        om_wind_unit = "kmh"
                        om_precip_unit = "mm"
                    else:
                        om_temp_unit = "fahrenheit"
                        om_wind_unit = "mph"
                        om_precip_unit = "inch"

                    if forecast_is_stale:
                        try:
                            om_url = (
                                "https://api.open-meteo.com/v1/forecast"
                                f"?latitude={om_lat}&longitude={om_lon}"
                                "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
                                "pressure_msl,surface_pressure,wind_speed_10m,wind_gusts_10m,wind_direction_10m,"
                                "cloud_cover,visibility,dew_point_2m,precipitation,rain,showers,snowfall,"
                                "weather_code,is_day"
                                "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,"
                                "dew_point_2m,pressure_msl,surface_pressure,visibility,precipitation_probability,"
                                "precipitation,rain,showers,snowfall,weather_code,is_day,cloud_cover,"
                                "wind_speed_10m,wind_gusts_10m,wind_direction_10m"
                                "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
                                "apparent_temperature_max,apparent_temperature_min,precipitation_sum,"
                                "rain_sum,showers_sum,snowfall_sum,precipitation_hours,"
                                "precipitation_probability_max,cloud_cover_mean,relative_humidity_2m_mean,"
                                "dew_point_2m_mean,wind_speed_10m_max,wind_gusts_10m_max,"
                                "wind_direction_10m_dominant,sunrise,sunset,uv_index_max"
                                f"&temperature_unit={om_temp_unit}"
                                f"&wind_speed_unit={om_wind_unit}"
                                f"&precipitation_unit={om_precip_unit}"
                                "&timezone=auto&forecast_days=7"
                            )
                            om_raw = _http_get_json(
                                om_url, headers=HTTP_HEADERS["OPEN_METEO"]
                            )
                            normalized = _openmeteo_transform_to_belch(
                                om_raw, forecast_units
                            )
                            (
                                normalized["alerts"],
                                alert_provider,
                            ) = _fetch_openmeteo_alerts(om_lat, om_lon, extras_dict)
                            if alert_provider:
                                normalized["alert_provider"] = alert_provider
                            _write_json_file(forecast_file, normalized)
                            log.info(f"New Open-Meteo forecast cached to {forecast_file}")
                        except Exception as e:
                            openmeteo_forecast_failed = True
                            log.warning(
                                "Open-Meteo forecast update failed; treating forecast_enabled as 0 for this cycle. "
                                f"Reason: {e}"
                            )
                    else:
                        log.debug("Forecast is current, no update needed.")

                    if not openmeteo_forecast_failed and not os.path.isfile(forecast_file):
                        openmeteo_forecast_failed = True
                        log.warning(
                            "Open-Meteo forecast data unavailable; treating forecast_enabled as 0 for this cycle."
                        )

                    if not openmeteo_forecast_failed and current_conditions_is_stale:
                        try:
                            _write_current_conditions_from_forecast(
                                forecast_file, current_conditions_file
                            )
                            log.info(
                                f"New Open-Meteo current conditions cached to {current_conditions_file}"
                            )
                        except Exception as e:
                            openmeteo_forecast_failed = True
                            log.warning(
                                "Open-Meteo current-conditions update failed; treating forecast_enabled as 0 for this cycle. "
                                f"Reason: {e}"
                            )
                    elif not openmeteo_forecast_failed:
                        log.debug("Current conditions are current, no update needed.")

                    if not openmeteo_forecast_failed:
                        try:
                            (
                                current_obs_icon,
                                current_obs_summary,
                                visibility,
                                visibility_unit,
                                cloud_cover,
                            ) = _load_normalized_current_conditions(
                                current_conditions_file,
                                forecast_units,
                                cloud_cover_scale=1.0,
                            )
                        except Exception as e:
                            openmeteo_forecast_failed = True
                            log.warning(
                                "Open-Meteo current-conditions parse failed; treating forecast_enabled as 0 for this cycle. "
                                f"Reason: {e}"
                            )

                    if openmeteo_forecast_failed:
                        (
                            current_obs_icon,
                            current_obs_summary,
                            visibility,
                            visibility_unit,
                            cloud_cover,
                        ) = _default_current_conditions_values()
                    else:
                        _refresh_openmeteo_aqi_fallback(force=forecast_is_stale)
                        _apply_aqi_globals_from_forecast()
                elif forecast_provider not in ("pirateweather", "nws"):
                    aeris_icon_map = _load_aeris_icon_map(config_dict, skin_dict)

                    current_conditions = extras_dict["current_conditions"]
                    if current_conditions == "obs":
                        if belchertown_debug > 0:
                            log.info(
                                "Current conditions based on /observations endpoint"
                            )
                    elif current_conditions == "conds":
                        if belchertown_debug > 0:
                            log.info("Current conditions based on /conditions endpoint")
                    elif current_conditions == "obs-on-fail-conds":
                        if belchertown_debug > 0:
                            log.info(
                                "Current conditions based on /observations, if no data, use /conditions endpoint"
                            )
                    else:  # W0t?
                        log.info(
                            f"Setting current_conditions to obs due to unknown value: {current_conditions}"
                        )
                        current_conditions = "obs"

                    if (
                        extras_dict["forecast_aeris_use_metar"] == "1"
                    ):  # filter on METAR
                        current_obs_url = f"https://data.api.xweather.com/observations/{forecast_place}?format=json&filter=metar&limit=1&client_id={forecast_api_id}&client_secret={forecast_api_secret}"
                    else:  # filter on All stations
                        current_obs_url = f"https://data.api.xweather.com/observations/{forecast_place}?format=json&filter=allstations&limit=1&client_id={forecast_api_id}&client_secret={forecast_api_secret}"

                    current_conds_url = f"https://data.api.xweather.com/conditions/{forecast_place}?format=json&plimit=1&filter=1min&client_id={forecast_api_id}&client_secret={forecast_api_secret}"
                    forecast_24hr_url = f"https://data.api.xweather.com/forecasts/{forecast_place}?format=json&filter=day&limit=7&client_id={forecast_api_id}&client_secret={forecast_api_secret}"
                    forecast_3hr_url = f"https://data.api.xweather.com/forecasts/{forecast_place}?format=json&filter=3hr&limit=8&client_id={forecast_api_id}&client_secret={forecast_api_secret}"
                    forecast_1hr_url = f"https://data.api.xweather.com/forecasts/{forecast_place}?format=json&filter=1hr&limit=16&client_id={forecast_api_id}&client_secret={forecast_api_secret}"
                    aqi_url = f"https://data.api.xweather.com/airquality/{forecast_place}?format=json&client_id={forecast_api_id}&client_secret={forecast_api_secret}"

                    if extras_dict["forecast_alert_limit"]:
                        forecast_alert_limit = extras_dict["forecast_alert_limit"]
                    else:  # Default to 1 alerts to show if the option is missing. Can go up to 10
                        forecast_alert_limit = 1

                    forecast_alerts_url = f"https://data.api.xweather.com/alerts/{forecast_place}?format=json&limit={forecast_alert_limit}&lang={forecast_lang}&client_id={forecast_api_id}&client_secret={forecast_api_secret}"

                    # Avoid potential unbound-local access
                    forecast_file_result = None

                    # File is stale, download a new copy
                    if forecast_is_stale:
                        forecast_file_result = None
                        try:
                            if "forecast_dev_file" in extras_dict:
                                # Hidden option to use a pre-downloaded forecast file
                                # rather than using API calls for no reason
                                dev_forecast_file = extras_dict["forecast_dev_file"]
                                req = Request(
                                    dev_forecast_file,
                                    None,
                                    HTTP_HEADERS["AERIS_WEATHER"],
                                )
                                with urlopen(
                                    req, timeout=DEFAULT_HTTP_TIMEOUT
                                ) as response:
                                    forecast_file_result = response.read()
                                dev_payload = _parse_aeris_json(forecast_file_result)
                                if dev_payload.get("schema") == "belchertown.forecast.v1":
                                    forecast_file_result = json.dumps(dev_payload)
                                else:
                                    forecast_file_result = json.dumps(
                                        _aeris_transform_to_belch(
                                            dev_payload,
                                            forecast_units,
                                            label_dict,
                                            aeris_icon_map,
                                        )
                                    )
                            else:
                                # 24hr forecast (was Forecast)
                                req = Request(
                                    forecast_24hr_url,
                                    None,
                                    HTTP_HEADERS["AERIS_WEATHER"],
                                )
                                with urlopen(
                                    req, timeout=DEFAULT_HTTP_TIMEOUT
                                ) as response:
                                    forecast_24hr_page = response.read()
                                if belchertown_debug > 1:
                                    log.info(f"Forecast 24hr URL: {forecast_24hr_url}")
                                # 3hr forecast
                                req = Request(
                                    forecast_3hr_url,
                                    None,
                                    HTTP_HEADERS["AERIS_WEATHER"],
                                )
                                with urlopen(
                                    req, timeout=DEFAULT_HTTP_TIMEOUT
                                ) as response:
                                    forecast_3hr_page = response.read()
                                if belchertown_debug > 1:
                                    log.info(f"Forecast 3hr URL: {forecast_3hr_url}")
                                # 1hr forecast
                                req = Request(
                                    forecast_1hr_url,
                                    None,
                                    HTTP_HEADERS["AERIS_WEATHER"],
                                )
                                with urlopen(
                                    req, timeout=DEFAULT_HTTP_TIMEOUT
                                ) as response:
                                    forecast_1hr_page = response.read()
                                if belchertown_debug > 1:
                                    log.info(f"Forecast 1hr URL: {forecast_1hr_url}")
                                # AQI
                                req = Request(
                                    aqi_url, None, HTTP_HEADERS["AERIS_WEATHER"]
                                )
                                with urlopen(
                                    req, timeout=DEFAULT_HTTP_TIMEOUT
                                ) as response:
                                    aqi_page = response.read()
                                if belchertown_debug > 1:
                                    log.info(f"AQI URL: {aqi_url}")
                                if extras_dict["forecast_alert_enabled"] == "1":
                                    # Alerts
                                    req = Request(
                                        forecast_alerts_url,
                                        None,
                                        HTTP_HEADERS["AERIS_WEATHER"],
                                    )
                                    with urlopen(
                                        req, timeout=DEFAULT_HTTP_TIMEOUT
                                    ) as response:
                                        alerts_page = response.read()
                                    if belchertown_debug > 1:
                                        log.info(f"Alerts URL: {forecast_alerts_url}")

                                # Combine all into 1 file - simplified parsing helper

                                data = {
                                    "timestamp": int(time.time()),
                                    "forecast_24hr": [
                                        _parse_aeris_json(forecast_24hr_page)
                                    ],
                                    "forecast_3hr": [
                                        _parse_aeris_json(forecast_3hr_page)
                                    ],
                                    "forecast_1hr": [
                                        _parse_aeris_json(forecast_1hr_page)
                                    ],
                                    "aqi": [_parse_aeris_json(aqi_page)],
                                }
                                if extras_dict.get("forecast_alert_enabled") == "1":
                                    data["alerts"] = [_parse_aeris_json(alerts_page)]
                                forecast_file_result = json.dumps(
                                    _aeris_transform_to_belch(
                                        data,
                                        forecast_units,
                                        label_dict,
                                        aeris_icon_map,
                                    )
                                )
                        except Exception as e:
                            log.error(f"Error downloading forecast data: {e}")

                        # Save forecast data to file. w+ creates the file if it doesn't
                        # exist, and truncates the file and re-writes it everytime
                        if forecast_file_result is not None:
                            try:
                                with open(forecast_file, "wb+") as file:
                                    file.write(forecast_file_result.encode("utf-8"))
                                    log.info(
                                        f"New forecast file downloaded to {forecast_file}"
                                    )
                            except FileNotFoundError:
                                log.info(
                                    "Belchertown JSON folder does not exist. Usually this "
                                    "is an error that only occurs on the first run. If it "
                                    "is appearing repeatedly, check file permissions."
                                )
                            except IOError as e:
                                log.error(
                                    f"Error writing forecast info to {forecast_file}. Reason: {e}"
                                )
                        else:
                            log.info(
                                "Forecast download failed; keeping existing forecast file if present."
                            )

                    # File is stale, download a new copy
                    if current_conditions_is_stale:
                        forecast_file_result = None
                        try:
                            if "current_conditions_dev_file" in extras_dict:
                                # Hidden option to use a pre-downloaded forecast file
                                # rather than using API calls for no reason
                                dev_forecast_file = extras_dict[
                                    "current_conditions_dev_file"
                                ]
                                req = Request(
                                    dev_forecast_file,
                                    None,
                                    HTTP_HEADERS["AERIS_WEATHER"],
                                )
                                with urlopen(
                                    req, timeout=DEFAULT_HTTP_TIMEOUT
                                ) as response:
                                    forecast_file_result = response.read()
                                current_payload = _parse_aeris_json(forecast_file_result)
                                if current_payload.get("schema") == "belchertown.current.v1":
                                    forecast_file_result = json.dumps(current_payload)
                                else:
                                    forecast_file_result = json.dumps(
                                        _aeris_current_to_common(
                                            current_payload,
                                            current_conditions,
                                            forecast_units,
                                            label_dict,
                                            aeris_icon_map,
                                        )
                                    )
                            else:
                                # Current conditions
                                if current_conditions == "obs":
                                    req = Request(
                                        current_obs_url,
                                        None,
                                        HTTP_HEADERS["AERIS_WEATHER"],
                                    )
                                    with urlopen(
                                        req, timeout=DEFAULT_HTTP_TIMEOUT
                                    ) as response:
                                        current_page = response.read()
                                    if belchertown_debug > 1:
                                        log.info(f"Obs URL: {current_obs_url}")
                                elif current_conditions == "conds":
                                    req = Request(
                                        current_conds_url,
                                        None,
                                        HTTP_HEADERS["AERIS_WEATHER"],
                                    )
                                    with urlopen(
                                        req, timeout=DEFAULT_HTTP_TIMEOUT
                                    ) as response:
                                        current_page = response.read()
                                    if belchertown_debug > 1:
                                        log.info(f"Conditions URL: {current_conds_url}")
                                else:  # current_conditions == "obs-on-fail-conds":
                                    req = Request(
                                        current_obs_url,
                                        None,
                                        HTTP_HEADERS["AERIS_WEATHER"],
                                    )
                                    with urlopen(
                                        req, timeout=DEFAULT_HTTP_TIMEOUT
                                    ) as response:
                                        current_page = response.read()
                                    try:  # Obs okay?
                                        obs_payload = _parse_aeris_json(current_page)
                                        if not (
                                            isinstance(obs_payload.get("response"), dict)
                                            and obs_payload["response"].get("ob")
                                        ):
                                            raise ValueError("No usable observation data")
                                    except Exception:  # Nope, try Conds
                                        if belchertown_debug > 0:
                                            log.info("No good Obs data, using Conds")
                                        req = Request(
                                            current_conds_url,
                                            None,
                                            HTTP_HEADERS["AERIS_WEATHER"],
                                        )
                                        with urlopen(
                                            req, timeout=DEFAULT_HTTP_TIMEOUT
                                        ) as response:
                                            current_page = response.read()
                                # Stash in a file
                                data = {
                                    "timestamp": int(time.time()),
                                    "current": [_parse_aeris_json(current_page)],
                                }
                                forecast_file_result = json.dumps(
                                    _aeris_current_to_common(
                                        data,
                                        current_conditions,
                                        forecast_units,
                                        label_dict,
                                        aeris_icon_map,
                                    )
                                )
                        except Exception as e:
                            if current_conditions == "obs":
                                log.error(
                                    "Error downloading forecast Current Conditions data. "
                                    "Check the URL in your configuration and try again. "
                                    f"You are trying to use URL: {current_obs_url}, "
                                    f"and the error is: {e}"
                                )
                            elif current_conditions == "conds":
                                log.error(
                                    "Error downloading forecast Current Conditions data. "
                                    "Check the URL in your configuration and try again. "
                                    f"You are trying to use URL: {current_conds_url}, "
                                    f"and the error is: {e}"
                                )
                            elif current_conditions == "obs-on-fail-conds":
                                log.error(
                                    "Error downloading forecast Current Conditions data. "
                                    "Check the URL in your configuration and try again. "
                                    f"You are trying to use URL: {current_conds_url}, "
                                    f"and the error is: {e}"
                                )

                        # Save forecast Current Conditions data to file. w+ creates the file if it doesn't
                        # exist, and truncates the file and re-writes it everytime
                        if forecast_file_result is not None:
                            try:
                                with open(current_conditions_file, "wb+") as file:
                                    file.write(forecast_file_result.encode("utf-8"))
                                    log.info(
                                        f"New forecast Current Conditions file downloaded to {current_conditions_file}"
                                    )
                            except FileNotFoundError:
                                log.info(
                                    "Belchertown JSON folder does not exist. Usually this "
                                    "is an error that only occurs on the first run. If it "
                                    "is appearing repeatedly, check file permissions."
                                )
                            except IOError as e:
                                log.error(
                                    "Error writing forecast Current Conditions info to "
                                    f"{current_conditions_file}. Reason: {e}"
                                )
                            except Exception as e:
                                log.error(f"Current Conditions error: {e}")
                        else:
                            log.info(
                                "Current conditions download failed; keeping existing current conditions file if present."
                            )

                    try:
                        (
                            current_obs_icon,
                            current_obs_summary,
                            visibility,
                            visibility_unit,
                            cloud_cover,
                        ) = _load_normalized_current_conditions(
                            current_conditions_file,
                            forecast_units,
                            cloud_cover_scale=1.0,
                        )
                    except Exception as e:
                        (
                            current_obs_icon,
                            current_obs_summary,
                            visibility,
                            visibility_unit,
                            cloud_cover,
                        ) = _default_current_conditions_values()
                        log.error(f"Aeris/Xweather current-conditions parse error: {e}")

                    # Process the normalized forecast file.
                    with open(forecast_file, "r", encoding="utf-8") as read_file:
                        data = json.load(read_file)

                    try:
                        aqi_payload = data["aqi"][0]
                        if aqi_payload["response"]:
                            if aqi_payload["error"]:
                                log.error(
                                    f"Error getting AQI from Xweather weather. The error was: {data['aqi']}"
                                )
                            else:
                                (
                                    aqi,
                                    aqi_category,
                                    aqi_location,
                                    aqi_time,
                                ) = _extract_aqi_globals_from_payload(
                                    aqi_payload, label_dict
                                )
                    except KeyError:
                        pass  # aqi key missing from forecast data (e.g. aqi disabled or older file)
                    except Exception as e:
                        log.error(
                            f"Error getting AQI from Xweather weather. The error was: {e}. Data: {data['aqi']}"
                        )
                        pass
            else:
                current_obs_icon = ""
                current_obs_summary = ""
                visibility = "N/A"
                visibility_unit = ""
                cloud_cover = ""
        except Exception as e:
            current_obs_icon = ""
            current_obs_summary = ""
            visibility = "N/A"
            visibility_unit = ""
            cloud_cover = ""
            if forecast_provider == "pirateweather":
                log.error(f"Pirate Weather error: {e}")
            elif forecast_provider == "nws":
                log.error(f"NWS error: {e}")
            elif forecast_provider == "open-meteo":
                log.error(f"Open-Meteo error: {e}")
            else:
                log.error(f"Aeris/Xweather error: {e}")

        # ==============================================================================
        # Earthquake Data
        # ==============================================================================

        # Only process if Earthquake data is enabled
        if extras_dict["earthquake_enabled"] == "1":
            earthquake_file = html_root + "/json/earthquake.json"
            earthquake_stale_timer = extras_dict["earthquake_stale"]
            latitude = config_dict["Station"]["latitude"]
            longitude = config_dict["Station"]["longitude"]
            distance_unit = self.generator.converter.group_unit_dict["group_distance"]
            eq_distance_label = skin_dict["Units"]["Labels"].get(distance_unit, "")
            eq_distance_round = skin_dict["Units"]["StringFormats"].get(
                distance_unit, "%.1f"
            )
            earthquake_maxradiuskm = extras_dict["earthquake_maxradiuskm"]
            earthquake_minmag = extras_dict.get("earthquake_minmag", "2")
            if extras_dict["earthquake_server"] == "ReNaSS":
                log.error("Belchertown: earthquake_server 'ReNaSS' is no longer supported. Automatically switching to 'EMSC'. Please update your skin.conf.")
                extras_dict["earthquake_server"] = "EMSC"
            # Sample URL from Belchertown Weather:
            # http://earthquake.usgs.gov/fdsnws/event/1/query?limit=1&lat=42.223&lon=-72.374&maxradiuskm=1000&format=geojson&nodata=204&minmagnitude=2
            if extras_dict["earthquake_server"] == "USGS":
                earthquake_url = f"http://earthquake.usgs.gov/fdsnws/event/1/query?limit=1&lat={latitude}&lon={longitude}&maxradiuskm={earthquake_maxradiuskm}&format=geojson&nodata=204&minmagnitude={earthquake_minmag}"
            elif extras_dict["earthquake_server"] == "GeoNet":
                earthquake_url = f"https://api.geonet.org.nz/fdsnws/event/1/query?latitude={latitude}&longitude={longitude}&maxradiuskm={earthquake_maxradiuskm}&minmagnitude={earthquake_minmag}&format=geojson&limit=1&orderby=time"
            elif extras_dict["earthquake_server"] == "EMSC":
                # EMSC supports a native circle query; convert km radius to degrees (1 deg ≈ 111.1 km)
                maxradius_deg = float(earthquake_maxradiuskm) / 111.1
                earthquake_url = f"https://www.seismicportal.eu/fdsnws/event/1/query?latitude={latitude}&longitude={longitude}&maxradius={maxradius_deg:.2f}&minmagnitude={earthquake_minmag}&format=json&limit=1&orderby=time"

            earthquake_is_stale = False

            # Determine if the file exists and get its modified time
            if os.path.isfile(earthquake_file):
                earthquake_stat = os.stat(earthquake_file)
                earthquake_age = int(time.time()) - int(earthquake_stat.st_mtime)
                earthquake_is_stale = (
                    earthquake_stat.st_size == 0
                    or earthquake_age > int(earthquake_stale_timer)
                )
            else:
                # File doesn't exist or is blank, download a new copy
                earthquake_is_stale = True

            # File is stale, download a new copy
            if earthquake_is_stale:
                # Download new earthquake data
                try:
                    user_agent = "Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_4; en-US) AppleWebKit/534.3 (KHTML, like Gecko) Chrome/6.0.472.63 Safari/534.3"
                    headers = {"User-Agent": user_agent}
                    req = Request(earthquake_url, None, headers)
                    with urlopen(req, timeout=DEFAULT_HTTP_TIMEOUT) as response:
                        page = response.read()
                    if weewx.debug:
                        log.debug(
                            "Downloading earthquake data using urllib2 was successful"
                        )
                except Exception as forecast_error:
                    if weewx.debug:
                        log.debug(
                            f"Error downloading earthquake data with urllib2, reverting to curl and subprocess. "
                            f"Full error: {forecast_error}"
                        )
                    # Nested try - only execute if the urllib2 method fails
                    try:
                        import subprocess

                        p = subprocess.Popen(
                            ["curl", "-L", "--silent", earthquake_url],
                            shell=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                        )
                        page = p.communicate()[0]
                        if weewx.debug:
                            log.debug(
                                "Downloading earthquake data with curl was successful."
                            )
                    except Exception as e:
                        log.error(
                            f"Error downloading earthquake data using urllib2 and subprocess curl. "
                            f"Your software may need to be updated, or the URL is incorrect. "
                            f"You are trying to use URL: {earthquake_url}, and the error is: {e}"
                        )

                # Save earthquake data to file. w+ creates the file if it
                # doesn't exist, and truncates the file and re-writes it
                # everytime
                try:
                    with open(earthquake_file, "wb+") as file:
                        try:
                            file.write(page.encode("utf-8"))
                        except Exception:
                            # Catch errors caused by ASCII characters
                            file.write(page)
                        if weewx.debug:
                            log.debug(f"Earthquake data saved to {earthquake_file}")
                except IOError as e:
                    log.error(
                        f"Error writing earthquake data to {earthquake_file}. Reason: {e}"
                    )

            # Process the earthquake file
            with open(earthquake_file, "r", encoding="utf-8") as read_file:
                try:
                    eqdata = json.load(read_file)
                except Exception:
                    eqdata = ""

            try:
                if extras_dict["earthquake_server"] == "USGS":
                    eqtime = eqdata["features"][0]["properties"]["time"] / 1000
                    equrl = eqdata["features"][0]["properties"]["url"]
                    if distance_unit == "km":
                        eqplace = eqdata["features"][0]["properties"]["place"]
                    else:  # assume miles
                        try:
                            eqmatched = match(
                                "(?P<distance>[0-9]*\\.?[0-9]+) km(?P<rest>.*)$",
                                eqdata["features"][0]["properties"]["place"],
                            )
                            eqdist_km = eqmatched.group("distance")
                            eqdist_miles = round(float(eqdist_km) / 1.609, 1)
                            eqplace = (
                                str(eqdist_miles) + " miles" + eqmatched.group("rest")
                            )
                        except Exception:
                            eqplace = eqdata["features"][0]["properties"]["place"]
                    eqmag = locale.format_string(
                        "%g", float(eqdata["features"][0]["properties"]["mag"])
                    )
                elif extras_dict["earthquake_server"] == "EMSC":
                    eqtime = eqdata["features"][0]["properties"]["time"]
                    # convert time to UNIX format
                    eqtime = datetime.datetime.strptime(eqtime, "%Y-%m-%dT%H:%M:%S.%fZ")
                    eqtime = int(
                        (eqtime - datetime.datetime(1970, 1, 1)).total_seconds()
                    )
                    equrl = (
                        "https://www.seismicportal.eu/eventdetails.html?unid="
                        + eqdata["features"][0]["properties"]["unid"]
                    )
                    eqplace = eqdata["features"][0]["properties"]["flynn_region"].title()
                    eqmag = format(eqdata["features"][0]["properties"]["mag"], ".1f")
                elif extras_dict["earthquake_server"] == "GeoNet":
                    eqtime = eqdata["features"][0]["properties"]["time"] / 1000
                    equrl = (
                        "https://www.geonet.org.nz/earthquake/"
                        + eqdata["features"][0]["id"].split("/")[-1]
                    )
                    if distance_unit == "km":
                        eqplace = eqdata["features"][0]["properties"]["place"]
                    else:  # assume miles
                        try:
                            eqmatched = match(
                                r"(?P<distance>[0-9]*\.?[0-9]+) km(?P<rest>.*)$",
                                eqdata["features"][0]["properties"]["place"],
                            )
                            eqdist_km = eqmatched.group("distance")
                            eqdist_miles = round(float(eqdist_km) / 1.609, 1)
                            eqplace = (
                                str(eqdist_miles) + " miles" + eqmatched.group("rest")
                            )
                        except Exception:
                            eqplace = eqdata["features"][0]["properties"]["place"]
                    eqmag = locale.format_string(
                        "%g", float(eqdata["features"][0]["properties"]["mag"])
                    )
                eqlat = str(
                    round(eqdata["features"][0]["geometry"]["coordinates"][1], 4)
                )
                eqlon = str(
                    round(eqdata["features"][0]["geometry"]["coordinates"][0], 4)
                )
                eqdistance_bearing = self.get_gps_distance(
                    (float(latitude), float(longitude)),
                    (float(eqlat), float(eqlon)),
                    distance_unit,
                )
                eqdistance = locale.format_string(
                    "%g", float(eq_distance_round % eqdistance_bearing[0])
                )
                eqbearing = eqdistance_bearing[1]
                eqbearing_raw = eqdistance_bearing[2]
            except Exception:
                # No earthquake data
                eqtime = label_dict["earthquake_no_data"]
                equrl = ""
                eqplace = ""
                eqmag = ""
                eqlat = ""
                eqlon = ""
                eqdistance = ""
                eqbearing = ""
                eqbearing_raw = ""

        else:
            eqtime = ""
            equrl = ""
            eqplace = ""
            eqmag = ""
            eqlat = ""
            eqlon = ""
            eqdistance = ""
            eqbearing = ""
            eqbearing_raw = ""
            eq_distance_label = ""

        # ==============================================================================
        # Get Current Station Observation Data for the table html
        # ==============================================================================

        station_obs_binding = None
        station_obs_json = OrderedDict()
        station_obs_source_json = OrderedDict()
        station_obs_parts = []
        station_observations = extras_dict["station_observations"]
        # Check if this is a list. If not then we have 1 item, so force it into a list
        if not isinstance(station_observations, list):
            station_observations = station_observations.split()
        current_stamp = manager.lastGoodStamp()
        current_record = manager.getRecord(current_stamp)
        current = weewx.tags.CurrentObj(
            db_lookup,
            station_obs_binding,
            current_stamp,
            self.generator.formatter,
            self.generator.converter,
            None,
            current_record,
        )
        for obs in station_observations:
            obs_source = None
            if "data_binding" in obs:
                station_obs_binding = obs[obs.find("(") + 1 : obs.rfind(")")].split(
                    "="
                )[
                    1
                ]  # Thanks https://stackoverflow.com/a/40811994/1177153
                obs = obs.split("(")[0]
            if station_obs_binding is not None:
                obs_binding_manager = db_binder.get_manager(station_obs_binding)
                current_stamp = obs_binding_manager.lastGoodStamp()
                current_record = obs_binding_manager.getRecord(current_stamp)
                current = weewx.tags.CurrentObj(
                    db_lookup,
                    station_obs_binding,
                    current_stamp,
                    self.generator.formatter,
                    self.generator.converter,
                    None,
                    current_record,
                )

            if obs == "visibility":
                # Using .strip() automatically returns "N/A" for invalid observations
                obs_output = f"{visibility} {visibility_unit}".strip()
                obs_source = EXTERNAL_STATION_OBSERVATION_SOURCES.get(obs)
            elif obs == "rainWithRainRate":
                # rainWithRainRate Rain shows rain daily sum and rain rate
                obs_binder = weewx.tags.ObservationBinder(
                    "rain",
                    archiveDaySpan(current_stamp),
                    db_lookup,
                    None,
                    "day",
                    self.generator.formatter,
                    self.generator.converter,
                )
                dayRain_sum = getattr(obs_binder, "sum")
                # Need to use dayRain for class name since that is weewx-mqtt
                # payload's name
                obs_rain_output = (
                    f"<span class='dayRain'>{dayRain_sum}</span>"
                )
                obs_rain_output += "&nbsp;<span class='border-left'>&nbsp;</span>"
                obs_rain_output += f"<span class='rainRate'>{getattr(current, 'rainRate')}</span>"

                # Empty field for the JSON "current" output
                obs_output = ""
            elif obs == "cloud_cover":
                obs_output = cloud_cover
                obs_source = EXTERNAL_STATION_OBSERVATION_SOURCES.get(obs)
            elif obs == "aqi":
                aqi_unit = aqi_category if aqi_category else label_dict["aqi_unknown"]
                obs_output = f"{aqi} ({aqi_unit})"
                obs_source = EXTERNAL_STATION_OBSERVATION_SOURCES.get(obs)
            else:
                # Only call getattr for observations not handled above.
                try:
                    obs_output = getattr(current, obs)
                    obs_output_str = str(obs_output)
                except Exception:
                    obs_output = "N/A"
                    obs_output_str = "N/A"
                if "?" in obs_output_str:
                    obs_output = "Invalid observation"

            try:
                obs_output_str = str(obs_output)
            except Exception:
                obs_output = "N/A"
                obs_output_str = "N/A"

            # Build the json "current" array for weewx_data.json for JavaScript
            if obs not in station_obs_json:
                station_obs_json[obs] = obs_output_str
            if obs_source is not None and obs not in station_obs_source_json:
                station_obs_source_json[obs] = dict(obs_source)

            # Build the HTML for the front page (accumulate into list, join later)
            row_parts = [
                f"<tr data-observation='{html.escape(obs, quote=True)}'>",
                f"<td class='station-observations-label'>{label_dict[obs]}</td>",
                "<td>",
            ]
            if obs == "rainWithRainRate":
                # Add special rain + rainRate one liner
                row_parts.append(obs_rain_output)
            elif obs == "cloud_cover" and obs_output_str not in ("", "N/A"):
                cloud_cover_unit_label = skin_dict["Units"]["Labels"].get(
                    "percent", "%"
                )
                row_parts.append(
                    f"<span class={obs}>{obs_output_str}{cloud_cover_unit_label}</span>"
                )
            else:
                row_parts.append(f"<span class={obs}>{obs_output_str}</span>")
            if obs in ("barometer", "pressure", "altimeter"):
                # Append the trend arrow to the pressure observation. Need this
                # for non-mqtt pages
                trend = weewx.tags.TrendObj(
                    10800,
                    300,
                    db_lookup,
                    None,
                    current_stamp,
                    self.generator.formatter,
                    self.generator.converter,
                )
                obs_trend = getattr(trend, obs)
                row_parts.append(' <span class="pressure-trend">')
                if str(obs_trend) == "N/A":
                    pass
                elif "-" in str(obs_trend):
                    row_parts.append('<i class="fa fa-arrow-down barometer-down"></i>')
                else:
                    row_parts.append('<i class="fa fa-arrow-up barometer-up"></i>')
                row_parts.append("</span>")

            if obs=='outHumidity':
                humabs_output = getattr(current,'outHumAbs',None)
                humabs_val = None
                if humabs_output is not None:
                    try:
                        humabs_val = humabs_output.gram_per_meter_cubed
                    except Exception:
                        humabs_val = None
                if humabs_val is not None:
                    obs_humabs_output = "&nbsp;<span class='border-left'>&nbsp;</span>"
                    obs_humabs_output += (
                        "<span class='outHumAbs'>%s</span>" % humabs_val
                    )
                    row_parts.append(obs_humabs_output)
            if obs=='radiation':
                maxSolarRad_output = getattr(current,'maxSolarRad',None)
                maxSolarRad_val = None
                if maxSolarRad_output is not None:
                    try:
                        maxSolarRad_val = maxSolarRad_output.watt_per_meter_squared
                    except Exception:
                        maxSolarRad_val = None
                if maxSolarRad_val is not None:
                    obs_maxSolarRad_output = "&nbsp;<span class='border-left'>&nbsp;</span>"
                    obs_maxSolarRad_output += (
                        "<span class='maxSolarRad'>%s</span>" % maxSolarRad_val
                    )
                    row_parts.append(obs_maxSolarRad_output)
            row_parts.append("</td>")
            row_parts.append("</tr>")
            station_obs_parts.append("".join(row_parts))

        station_obs_html = "".join(station_obs_parts)

        # ==============================================================================
        # Get all observations and their rounding values
        # ==============================================================================

        all_obs_rounding_json = OrderedDict()
        all_obs_unit_labels_json = OrderedDict()
        for obs in sorted(weewx.units.obs_group_dict):
            try:
                # Find the unit from group (like group_temperature = degree_F)
                obs_group = weewx.units.obs_group_dict[obs]
                obs_unit = self.generator.converter.group_unit_dict[obs_group]
            except Exception:
                # Something's wrong. Continue this loop to ignore this group
                # (like group_dust or something non-standard)
                continue
            try:
                # Find the number of decimals to round to based on group name
                obs_round = skin_dict["Units"]["StringFormats"].get(obs_unit, "0")[2]
            except Exception:
                obs_round = skin_dict["Units"]["StringFormats"].get(obs_unit, "0")
            # Add to the rounding array
            if obs not in all_obs_rounding_json:
                all_obs_rounding_json[obs] = str(obs_round)
            # Get the unit's label
            # Add to label array and strip whitespace if possible
            if obs not in all_obs_unit_labels_json:
                obs_unit_label = weewx.units.get_label_string(
                    self.generator.formatter, self.generator.converter, obs
                )
                all_obs_unit_labels_json[obs] = obs_unit_label

        # Special handling: visibility is set once after the loop
        if visibility:
            all_obs_rounding_json["visibility"] = "2"
            all_obs_unit_labels_json["visibility"] = visibility_unit
        else:
            all_obs_rounding_json["visibility"] = ""
            all_obs_unit_labels_json["visibility"] = ""
        all_obs_rounding_json["cloud_cover"] = "0"
        all_obs_unit_labels_json["cloud_cover"] = skin_dict["Units"]["Labels"].get(
            "percent", "%"
        )

        # ==============================================================================
        # Social Share
        # ==============================================================================

        facebook_enabled = extras_dict["facebook_enabled"]
        twitter_enabled = extras_dict["twitter_enabled"]
        social_share_html = extras_dict["social_share_html"]
        twitter_text = label_dict["twitter_text"]
        twitter_owner = label_dict["twitter_owner"]
        twitter_hashtags = label_dict["twitter_hashtags"]

        if facebook_enabled == "1":
            facebook_html = (
                """
                <div id="fb-root"></div>
                <script>(function(d, s, id) {
                var js, fjs = d.getElementsByTagName(s)[0];
                if (d.getElementById(id)) return;
                js = d.createElement(s); js.id = id;
                js.src = "//connect.facebook.net/en_US/sdk.js#xfbml=1&version=v2.5";
                fjs.parentNode.insertBefore(js, fjs);
                }(document, 'script', 'facebook-jssdk'));</script>
                <div class="fb-like" data-href="%s" data-width="500px" data-layout="button_count" data-action="like" data-show-faces="false" data-share="true"></div>
            """
                % social_share_html
            )
        else:
            facebook_html = ""

        if twitter_enabled == "1":
            twitter_html = f"""
                <script>
                    !function(d,s,id){{var js,fjs=d.getElementsByTagName(s)[0],p=/^http:/.test(d.location)?'http':'https';if(!d.getElementById(id)){{js=d.createElement(s);js.id=id;js.src=p+'://platform.twitter.com/widgets.js';fjs.parentNode.insertBefore(js,fjs);}}}}(document, 'script', 'twitter-wjs');
                </script>
                <a href="https://twitter.com/share" class="twitter-share-button" data-url="{social_share_html}" data-text="{twitter_text}" data-via="{twitter_owner}" data-hashtags="{twitter_hashtags}">Tweet</a>
            """
        else:
            twitter_html = ""

        # Build the output
        social_html = ""
        if facebook_html != "" or twitter_html != "":
            social_html = '<div class="wx-stn-share">'
            # Facebook first
            if facebook_html != "":
                social_html += facebook_html
            # Add a separator margin if both are enabled
            if facebook_html != "" and twitter_html != "":
                social_html += '<div class="wx-share-sep"></div>'
            # Twitter second
            if twitter_html != "":
                social_html += twitter_html
            social_html += "</div>"

        # ==============================================================================
        # MQTT settings for Kiosk page
        # ==============================================================================

        if extras_dict["mqtt_websockets_host_kiosk"] != "":
            if extras_dict["mqtt_websockets_port_kiosk"] != "":
                mqtt_websockets_port_kiosk = extras_dict["mqtt_websockets_port_kiosk"]
            else:
                mqtt_websockets_port_kiosk = extras_dict["mqtt_websockets_port"]
            if extras_dict["mqtt_websockets_ssl_kiosk"] != "":
                mqtt_websockets_ssl_kiosk = extras_dict["mqtt_websockets_ssl_kiosk"]
            else:
                mqtt_websockets_ssl_kiosk = extras_dict["mqtt_websockets_ssl"]
        else:
            mqtt_websockets_port_kiosk = extras_dict["mqtt_websockets_host"]
            mqtt_websockets_port_kiosk = extras_dict["mqtt_websockets_port"]
            mqtt_websockets_ssl_kiosk = extras_dict["mqtt_websockets_ssl"]

        # Include custom.css if it exists in the HTML_ROOT folder
        custom_css_file = html_root + "/custom.css"
        # Determine if the file exists
        custom_css_exists = os.path.isfile(custom_css_file)

        minify_requested = to_bool(extras_dict.get("minify", "0"))
        asset_suffix = ".min" if minify_requested else ""
        if minify_requested:
            minify_deps_ok, missing_modules = _get_minifier_dependency_status()
            if not minify_deps_ok:
                _log_minifier_missing_error_once(missing_modules)

        # Build the search list with the new values
        search_list_extension = {
            "belchertown_version": VERSION,
            "asset_suffix": asset_suffix,
            "belchertown_debug": belchertown_debug,
            "moment_js_utc_offset": moment_js_utc_offset,
            "moment_js_tz": moment_js_tz,
            "highcharts_timezoneoffset": highcharts_timezoneoffset,
            "system_locale": system_locale,
            "system_locale_js": system_locale_js,
            "locale_encoding": locale_encoding,
            "highcharts_decimal": highcharts_decimal,
            "highcharts_thousands": highcharts_thousands,
            "radar_html": radar_html,
            "radar_overlay": radar_overlay,            
            "radar_html_dark": radar_html_dark,
            "radar_html_kiosk": radar_html_kiosk,
            "archive_interval_ms": archive_interval_ms,
            "ordinate_names": ordinate_names,
            "windrose_categories": json.dumps(ordinate_names[:16]),
            "charts": json.dumps(charts),
            "chartpage_titles": json.dumps(chartpage_titles),
            "chartpage_titles_dict": chartpage_titles,
            "chartpage_content": json.dumps(chartpage_content),
            "chart_page_buttons": chart_page_buttons,
            "alltime": all_stats,
            "yesterday_outTemp_range_max": yesterday_outTemp_range_max,
            "yesterday_outTemp_range_min": yesterday_outTemp_range_min,
            "week_outTemp_range_max": week_outTemp_range_max,
            "week_outTemp_range_min": week_outTemp_range_min,
            "month_outTemp_range_max": month_outTemp_range_max,
            "month_outTemp_range_min": month_outTemp_range_min,
            "year_outTemp_range_max": year_outTemp_range_max,
            "year_outTemp_range_min": year_outTemp_range_min,
            "at_outTemp_range_max": at_outTemp_range_max,
            "at_outTemp_range_min": at_outTemp_range_min,
            "rainiest_day": rainiest_day,
            "at_rainiest_day": at_rainiest_day,
            "suniest_day": suniest_day,
            "at_suniest_day": at_suniest_day,
            "year_rainiest_month": year_rainiest_month,
            "at_rainiest_month": at_rainiest_month,
            "year_suniest_month": year_suniest_month,
            "at_suniest_month": at_suniest_month,
            "at_rain_highest_year": at_rain_highest_year,
            "at_sunshineDur_highest_year": at_sunshineDur_highest_year,
            "yesterday_days_with_rain": yesterday_days_with_rain,
            "yesterday_days_without_rain": yesterday_days_without_rain,
            "week_days_with_rain": week_days_with_rain,
            "week_days_without_rain": week_days_without_rain,
            "month_days_with_rain": month_days_with_rain,
            "month_days_without_rain": month_days_without_rain,
            "year_days_with_rain": year_days_with_rain,
            "year_days_without_rain": year_days_without_rain,
            "at_days_with_rain": at_days_with_rain,
            "at_days_without_rain": at_days_without_rain,
            "windSpeedUnitLabel": windSpeed_unit_label,
            "noaa_header_html": noaa_header_html,
            "default_noaa_file": default_noaa_file,
            "current_obs_icon": current_obs_icon,
            "current_obs_summary": current_obs_summary,
            "visibility": visibility,
            "visibility_unit": visibility_unit,
            "cloud_cover": cloud_cover,
            "station_obs_json": json.dumps(station_obs_json),
            "station_obs_source_json": json.dumps(station_obs_source_json),
            "station_obs_html": station_obs_html,
            "all_obs_rounding_json": json.dumps(all_obs_rounding_json),
            "all_obs_unit_labels_json": json.dumps(all_obs_unit_labels_json),
            "earthquake_time": eqtime,
            "earthquake_url": equrl,
            "earthquake_place": eqplace,
            "earthquake_magnitude": eqmag,
            "earthquake_lat": eqlat,
            "earthquake_lon": eqlon,
            "earthquake_distance_away": eqdistance,
            "earthquake_distance_label": eq_distance_label,
            "earthquake_bearing": eqbearing,
            "earthquake_bearing_raw": eqbearing_raw,
            "social_html": social_html,
            "custom_css_exists": custom_css_exists,
            "aqi": aqi,
            "aqi_category": aqi_category,
            "aqi_location": aqi_location,
            "aqi_time": aqi_time,
            "nav_charts_label": label_generic_dict.get(
                "nav_charts", label_dict["nav_charts"]
            ),
            "charts_page_header_label": label_generic_dict.get(
                "charts_page_header", label_dict["charts_page_header"]
            ),
            "homepage_charts_link_label": label_generic_dict.get(
                "homepage_charts_link", label_dict["homepage_charts_link"]
            ),
            "charts_page_all_button_label": label_generic_dict.get(
                "charts_page_all_button", label_dict["charts_page_all_button"]
            ),
            "charts_windrose_frequency_label": label_generic_dict.get(
                "charts_windrose_frequency", label_dict["charts_windrose_frequency"]
            ),
            "charts_windDir_ordinals_label": label_generic_dict.get(
                "charts_windDir_ordinals", label_dict["charts_windDir_ordinals"]
            ),
            "beaufort0": label_dict["beaufort0"],
            "beaufort1": label_dict["beaufort1"],
            "beaufort2": label_dict["beaufort2"],
            "beaufort3": label_dict["beaufort3"],
            "beaufort4": label_dict["beaufort4"],
            "beaufort5": label_dict["beaufort5"],
            "beaufort6": label_dict["beaufort6"],
            "beaufort7": label_dict["beaufort7"],
            "beaufort8": label_dict["beaufort8"],
            "beaufort9": label_dict["beaufort9"],
            "beaufort10": label_dict["beaufort10"],
            "beaufort11": label_dict["beaufort11"],
            "beaufort12": label_dict["beaufort12"],
            "mqtt_websockets_port_kiosk": mqtt_websockets_port_kiosk,
            "mqtt_websockets_ssl_kiosk": mqtt_websockets_ssl_kiosk,
        }
        # Finally, return our extension as a list:
        return [search_list_extension]


# ======================================================================================
# PostRenderMinifyGenerator
# ======================================================================================


class PostRenderMinifyGenerator(weewx.reportengine.ReportGenerator):
    """Generate minified JS/CSS assets after templates are rendered.

    This keeps repository source files readable while producing optimized
    runtime assets in HTML_ROOT.
    """

    DEFAULT_INCLUDE_GLOBS = (
        "js/*.js",
        "*.css",
    )

    DEFAULT_EXCLUDE_GLOBS = (
        "*.min.js",
        "*.min.css",
    )

    def run(self):
        extras = self.skin_dict.get("Extras", {})
        minify_requested = to_bool(extras.get("minify", "0"))
        if not minify_requested:
            log.debug("Belchertown minify: disabled by Extras.minify")
            return

        minify_deps_ok, missing_modules = _get_minifier_dependency_status()
        if not minify_deps_ok:
            _log_minifier_missing_error_once(missing_modules)

        html_root = os.path.join(
            self.config_dict["WEEWX_ROOT"],
            self.skin_dict["HTML_ROOT"],
        )

        self._jsmin_func = None
        self._cssmin_func = None
        try:
            self._jsmin_func = __import__("rjsmin").jsmin
        except Exception:
            pass
        try:
            self._cssmin_func = __import__("rcssmin").cssmin
        except Exception:
            pass

        if not os.path.isdir(html_root):
            log.debug(f"Belchertown minify: HTML_ROOT does not exist yet: {html_root}")
            return

        include_globs = list(self.DEFAULT_INCLUDE_GLOBS)
        exclude_globs = list(self.DEFAULT_EXCLUDE_GLOBS)

        processed = 0
        skipped = 0
        errors = 0

        for root, _dirs, files in os.walk(html_root):
            for filename in files:
                source_path = os.path.join(root, filename)

                relative_path = os.path.relpath(source_path, html_root).replace("\\", "/")

                if not self._matches_any(relative_path, include_globs):
                    continue
                if self._matches_any(relative_path, exclude_globs):
                    continue

                base, ext = os.path.splitext(source_path)
                ext = ext.lower()
                if ext not in (".js", ".css"):
                    continue

                minified_path = f"{base}.min{ext}"

                try:
                    if (
                        os.path.exists(minified_path)
                        and os.path.getmtime(minified_path)
                        >= os.path.getmtime(source_path)
                    ):
                        skipped += 1
                        continue

                    with open(source_path, "r", encoding="utf-8") as src_fh:
                        source_text = src_fh.read()

                    if ext == ".js":
                        minified_text = self._minify_js(source_text)
                    else:
                        minified_text = self._minify_css(source_text)

                    if not isinstance(minified_text, str) or not minified_text:
                        minified_text = source_text

                    with open(minified_path, "w", encoding="utf-8") as dst_fh:
                        dst_fh.write(minified_text)

                    processed += 1
                except Exception as e:
                    errors += 1
                    log.error(
                        f"Belchertown minify failed for {source_path}: {e}"
                    )

        if errors:
            log.warning(
                f"Belchertown minify finished with {errors} errors; "
                f"{processed} files processed; {skipped} unchanged"
            )
        else:
            log.info(
                f"Belchertown minify processed {processed} files; {skipped} unchanged"
            )

    def _matches_any(self, relative_path, globs):
        if not globs:
            return False
        return any(fnmatch.fnmatch(relative_path, pattern) for pattern in globs)

    def _minify_js(self, source_text):
        """Minify JavaScript text.

        Prefer rjsmin when available; otherwise apply a safe whitespace-only
        fallback that preserves semantics.
        """

        if self._jsmin_func is None:
            return source_text
        return self._jsmin_func(source_text)

    def _minify_css(self, source_text):
        """Minify CSS text.

        Prefer rcssmin when available; otherwise apply a safe whitespace-only
        fallback that preserves semantics.
        """

        if self._cssmin_func is not None:
            return self._cssmin_func(source_text)
        return self._minify_css_fallback(source_text)

    def _minify_css_fallback(self, source_text):
        """Small dependency-free CSS minifier that preserves quoted strings."""

        output = []
        in_string = None
        escape_next = False
        pending_space = False
        i = 0

        while i < len(source_text):
            char = source_text[i]
            next_char = source_text[i + 1] if i + 1 < len(source_text) else ""

            if in_string:
                output.append(char)
                if escape_next:
                    escape_next = False
                elif char == "\\":
                    escape_next = True
                elif char == in_string:
                    in_string = None
                i += 1
                continue

            if char in ("'", '"'):
                if pending_space and output and output[-1] not in "{[:;,>+~(":
                    output.append(" ")
                pending_space = False
                in_string = char
                output.append(char)
                i += 1
                continue

            if char == "/" and next_char == "*":
                i += 2
                while i + 1 < len(source_text) and source_text[i:i + 2] != "*/":
                    i += 1
                i += 2
                continue

            if char.isspace():
                pending_space = True
                i += 1
                continue

            if pending_space and output:
                prev = output[-1]
                if prev not in "{[:;,>+~(" and char not in "}]:;,>+~)":
                    output.append(" ")
            pending_space = False

            output.append(char)
            i += 1

        return "".join(output).replace(";}", "}").strip()


# ======================================================================================
# HighchartsJsonGenerator
# ======================================================================================


class HighchartsJsonGenerator(weewx.reportengine.ReportGenerator):
    """Class for generating JSON files for the Highcharts.
    Adapted from the ImageGenerator class.

    Useful attributes (some inherited from ReportGenerator):

        config_dict:      The WeeWX configuration dictionary
        skin_dict:        The dictionary for this skin
        gen_ts:           The generation time
        first_run:        Is this the first time the generator has been run?
        stn_info:         An instance of weewx.station.StationInfo
        record:           A copy of the "current" record. May be None.
        formatter:        An instance of weewx.units.Formatter
        converter:        An instance of weewx.units.Converter
        search_list_objs: A list holding search list extensions
        db_binder:        An instance of weewx.manager.DBBinder from which the data should be extracted
    """

    def run(self):
        """Main entry point for file generation."""

        legacy_chart_config_path = os.path.join(
            self.config_dict["WEEWX_ROOT"],
            self.skin_dict["SKIN_ROOT"],
            self.skin_dict.get("skin", ""),
            "graphs.conf",
        )
        chart_config_path = os.path.join(
            self.config_dict["WEEWX_ROOT"],
            self.skin_dict["SKIN_ROOT"],
            self.skin_dict.get("skin", ""),
            "charts.conf",
        )
        default_chart_config_path = os.path.join(
            self.config_dict["WEEWX_ROOT"],
            self.skin_dict["SKIN_ROOT"],
            self.skin_dict.get("skin", ""),
            "charts.conf.example",
        )
        if os.path.exists(legacy_chart_config_path):
            log.warning(
                f"Belchertown: Found legacy chart config '{legacy_chart_config_path}'. "
                "Using it for backward compatibility. Please migrate to 'charts.conf'."
            )
            self.chart_dict = configobj.ConfigObj(legacy_chart_config_path, file_error=True)
        elif os.path.exists(chart_config_path):
            self.chart_dict = configobj.ConfigObj(chart_config_path, file_error=True)
        elif os.path.exists(default_chart_config_path):
            self.chart_dict = configobj.ConfigObj(
                default_chart_config_path, file_error=True
            )
        else:
            self.chart_dict = configobj.ConfigObj(
                default_chart_config_path, file_error=True
            )

        self.converter = weewx.units.Converter.fromSkinDict(self.skin_dict)
        self.formatter = weewx.units.Formatter.fromSkinDict(self.skin_dict)

        # Setup title dict for plot titles
        try:
            d = self.skin_dict["Labels"]["Generic"]
        except KeyError:
            d = {}
        label_dict = weeutil.weeutil.KeyDict(d)

        # Final output dict
        output = {}
        html_dest_dir = os.path.join(
            self.config_dict["WEEWX_ROOT"], self.skin_dict["HTML_ROOT"], "json"
        )
        current_time = int(time.time())
        generated_timestamp = time.strftime("%m/%d/%Y %H:%M:%S")

        # Loop through each [section]. This is the first bracket group of
        # options including global options.
        for chart_group in self.chart_dict.sections:
            output[chart_group] = (
                OrderedDict()
            )  # This retains the order in which to load the charts on the page.
            chart_options = accumulateLeaves(self.chart_dict[chart_group])

            output[chart_group]["belchertown_version"] = VERSION
            output[chart_group]["generated_timestamp"] = generated_timestamp

            # Setup the JSON file name for each chart group
            json_filename = html_dest_dir + "/" + chart_group + ".json"

            # Default back to Highcharts standards
            colors = chart_options.get(
                "colors",
                "#7cb5ec, #b2df8a, #f7a35c, #8c6bb1, #dd3497, #e4d354, #268bd2, #f45b5b, #6a3d9a, #33a02c",
            )
            output[chart_group]["colors"] = colors

            # chartgroup_title is used on the charts page
            chartgroup_title = chart_options.get("title", None)
            if chartgroup_title:
                output[chart_group]["chartgroup_title"] = chartgroup_title

            # Define the default tooltip datetime format from the global options
            tooltip_date_format = chart_options.get("tooltip_date_format", "LLLL")
            output[chart_group]["tooltip_date_format"] = tooltip_date_format

            # Credits Text
            credits = chart_options.get("credits", "highcharts_default")
            output[chart_group]["credits"] = credits

            # Credits URL
            credits_url = chart_options.get("credits_url", "highcharts_default")
            output[chart_group]["credits_url"] = credits_url

            # Credits position
            credits_position = chart_options.get(
                "credits_position", "highcharts_default"
            )
            output[chart_group]["credits_position"] = credits_position

            # Check if there are any user override on generation periods.
            # Takes the crontab approach. If the words hourly, daily, monthly,
            # yearly are present use them, otherwise use an integer interval if
            # available.  Since WeeWX could be restarted, we'll lose our
            # end-timestamp to trigger off of for chart staleness.  So we have
            # to use the timestamp of the file to generate this. If the file
            # does not exist, we need to create it first.  Once created we use
            # that to see if we need to generate a fresh data set for the
            # chart.
            generate = chart_options.get("generate", None)
            if generate is not None:
                # Default to not making a new chart
                create_new_chart = False

                # Get our intervals. Minus 60 seconds so that it'll run a
                # little more reliably on the next interval.
                if generate.lower() == "hourly":
                    chart_stale_timer = 3540
                elif generate.lower() == "daily":
                    chart_stale_timer = 86340
                elif generate.lower() == "weekly":
                    chart_stale_timer = 604740
                elif generate.lower() == "monthly":
                    chart_stale_timer = 2629686
                elif generate.lower() == "yearly":
                    chart_stale_timer = 31556892
                else:
                    chart_stale_timer = int(generate)

                if not os.path.isfile(json_filename):
                    # File doesn't exist. Chart is stale no matter what.
                    create_new_chart = True
                else:
                    # The file exists get timestamp to compare against what the
                    # user wants for an interval
                    if (current_time - int(os.path.getmtime(json_filename))) >= int(
                        chart_stale_timer
                    ):
                        create_new_chart = True

                # Chart isn't stale, so continue to next chart (this current
                # chart_group is skipped and not generated)
                if not create_new_chart:
                    continue

            # Loop through each [[chart_group]] within the section.
            for plotname in self.chart_dict[chart_group].sections:
                output[chart_group][plotname] = {}

                # This retains the observation position in the dictionary to
                # match the order in the conf so the chart is in the right
                # user-defined order
                output[chart_group][plotname]["series"] = OrderedDict()

                output[chart_group][plotname]["options"] = {}
                # output[chart_group][plotname]["options"]["renderTo"] = chart_group + plotname # daychart1, weekchart1, etc.
                # Used for the charts page and the different chart_groups
                output[chart_group][plotname]["options"][
                    "renderTo"
                ] = plotname  # daychart1, weekchart1, etc. Used for the charts page and the different chart_groups
                output[chart_group][plotname]["options"]["chart_group"] = chart_group

                plot_options = accumulateLeaves(self.chart_dict[chart_group][plotname])

                # Setup the database binding, default to weewx.conf's binding
                # if none supplied.
                binding = plot_options.get(
                    "data_binding",
                    self.config_dict["StdReport"].get("data_binding", "wx_binding"),
                )
                archive = self.db_binder.get_manager(binding)

                # Generate timespan for the string time windows
                start_ts = archive.firstGoodStamp()
                stop_ts = archive.lastGoodStamp()
                timespan = weeutil.weeutil.TimeSpan(start_ts, stop_ts)

                # Find timestamps for the rolling window
                plotgen_ts = self.gen_ts
                if not plotgen_ts:
                    plotgen_ts = stop_ts
                    if not plotgen_ts:
                        plotgen_ts = time.time()

                chart_title = plot_options.get("title", "")
                output[chart_group][plotname]["options"]["title"] = chart_title

                chart_subtitle = plot_options.get("subtitle", "")
                output[chart_group][plotname]["options"]["subtitle"] = chart_subtitle

                # Get the type of plot ("bar', 'line', 'spline', or 'scatter')
                plottype = plot_options.get("type", "line")
                output[chart_group][plotname]["options"]["type"] = plottype

                # gapsize has to be in milliseconds. Take the charts.conf value
                # and multiply by 1000.
                # Also ensure gapsize is never smaller than the chart's own
                # aggregate_interval: if a parent section sets gapsize=86400 and a
                # child chart overrides aggregate_interval=week (604800 s), the
                # inherited gapsize would cause every weekly data-point gap to be
                # treated as a break and the line series would disappear entirely.
                gapsize = int(plot_options.get("gapsize", 300))  # default 5 minutes
                chart_agg_interval_raw = plot_options.get("aggregate_interval", None)
                if chart_agg_interval_raw:
                    try:
                        chart_agg_interval_s = int(
                            weeutil.weeutil.nominal_spans(chart_agg_interval_raw)
                        )
                        if chart_agg_interval_s > gapsize:
                            gapsize = chart_agg_interval_s
                    except Exception:
                        pass
                if gapsize:
                    output[chart_group][plotname]["options"]["gapsize"] = (
                        gapsize * 1000
                    )

                connectNulls = plot_options.get("connectNulls", "false")
                output[chart_group][plotname]["options"]["connectNulls"] = connectNulls

                xAxis_groupby = plot_options.get("xAxis_groupby", None)
                xAxis_categories = plot_options.get("xAxis_categories", "")
                # Check if this is a list. If not then we have 1 item, so force
                # it into a list
                if not isinstance(xAxis_categories, list):
                    xAxis_categories = xAxis_categories.split()
                output[chart_group][plotname]["options"][
                    "xAxis_categories"
                ] = xAxis_categories

                # Grab any per-chart tooltip date format overrides
                plot_tooltip_date_format = plot_options.get("tooltip_date_format", None)
                output[chart_group][plotname]["options"][
                    "plot_tooltip_date_format"
                ] = plot_tooltip_date_format

                # Width and height specific CSS overrides
                output[chart_group][plotname]["options"]["css_width"] = (
                    plot_options.get("width", "")
                )
                output[chart_group][plotname]["options"]["css_height"] = (
                    plot_options.get("height", "")
                )

                # Setup legend option
                legend = plot_options.get("legend", None)
                if legend is None:
                    # Default to true if the option is missing
                    output[chart_group][plotname]["options"]["legend"] = "true"
                else:
                    output[chart_group][plotname]["options"]["legend"] = legend

                # Setup exporting option
                exporting = plot_options.get("exporting", None)
                if exporting is not None and to_bool(exporting):
                    # Only turn on exporting if it's not none and it's true (1 or True)
                    output[chart_group][plotname]["options"]["exporting"] = "true"
                else:
                    output[chart_group][plotname]["options"]["exporting"] = "false"

                # Loop through each [[[observation]]] within the chart_group.
                for line_name in self.chart_dict[chart_group][plotname].sections:
                    output[chart_group][plotname]["series"][line_name] = {}
                    output[chart_group][plotname]["series"][line_name][
                        "obsType"
                    ] = line_name

                    line_options = accumulateLeaves(
                        self.chart_dict[chart_group][plotname][line_name]
                    )

                    # Look for any keyword timespans first and default to those
                    # start/stop times for the chart
                    time_length = line_options.get("time_length", 86400)
                    time_ago = int(line_options.get("time_ago", 1))
                    day_specific = line_options.get(
                        "day_specific", 1
                    )  # Force a day so we don't error out
                    month_specific = line_options.get(
                        "month_specific", 8
                    )  # Force a month so we don't error out
                    year_specific = line_options.get(
                        "year_specific", 2019
                    )  # Force a year so we don't error out
                    start_at_midnight = to_bool(
                        line_options.get("start_at_midnight", False)
                    )  # Should our timespan start at midnight?
                    start_at_whole_hour = to_bool(
                        line_options.get("start_at_whole_hour", False)
                    )  # Should our timespan start at a whole hour?
                    start_at_beginning_of_month = to_bool(
                        line_options.get("start_at_beginning_of_month", False)
                    )  # Should our timespan start at the beginning of a month?
                    if time_length == "today":
                        minstamp, maxstamp = archiveDaySpan(timespan.stop)
                    elif time_length == "week":
                        week_start = to_int(
                            self.config_dict["Station"].get("week_start", 6)
                        )
                        minstamp, maxstamp = archiveWeekSpan(timespan.stop, week_start)
                    elif time_length == "month":
                        minstamp, maxstamp = archiveMonthSpan(timespan.stop)
                    elif time_length == "year":
                        minstamp, maxstamp = archiveYearSpan(timespan.stop)
                    elif time_length == "days_ago":
                        minstamp, maxstamp = archiveDaySpan(
                            timespan.stop, days_ago=time_ago
                        )
                    elif time_length == "weeks_ago":
                        week_start = to_int(
                            self.config_dict["Station"].get("week_start", 6)
                        )
                        minstamp, maxstamp = archiveWeekSpan(
                            timespan.stop, week_start, weeks_ago=time_ago
                        )
                    elif time_length == "months_ago":
                        minstamp, maxstamp = archiveMonthSpan(
                            timespan.stop, months_ago=time_ago
                        )
                    elif time_length == "years_ago":
                        minstamp, maxstamp = archiveYearSpan(
                            timespan.stop, years_ago=time_ago
                        )
                    elif time_length == "day_specific":
                        # Set an arbitrary hour within the specific day to get
                        # that full day timespan and not the day before.
                        # e.g. 1pm
                        day_dt = datetime.datetime.strptime(
                            str(year_specific)
                            + "-"
                            + str(month_specific)
                            + "-"
                            + str(day_specific)
                            + " 13",
                            "%Y-%m-%d %H",
                        )
                        daystamp = int(time.mktime(day_dt.timetuple()))
                        minstamp, maxstamp = archiveDaySpan(daystamp)
                    elif time_length == "month_specific":
                        # Set an arbitrary day within the specific month to get
                        # that full month timespan and not the day before.
                        # e.g. 5th day
                        month_dt = datetime.datetime.strptime(
                            str(year_specific) + "-" + str(month_specific) + "-5",
                            "%Y-%m-%d",
                        )
                        monthstamp = int(time.mktime(month_dt.timetuple()))
                        minstamp, maxstamp = archiveMonthSpan(monthstamp)
                    elif time_length == "year_specific":
                        # Get a date in the middle of the year to get the full
                        # year epoch so WeeWX can find the year timespan.
                        year_dt = datetime.datetime.strptime(
                            str(year_specific) + "-8-1", "%Y-%m-%d"
                        )
                        yearstamp = int(time.mktime(year_dt.timetuple()))
                        minstamp, maxstamp = archiveYearSpan(yearstamp)
                    elif time_length == "year_to_now":
                        minstamp, maxstamp = self.timespan_year_to_now(timespan.stop)
                    elif time_length == "hour_ago_to_now":
                        if start_at_midnight:
                            span_start, span_stop = archiveSpanSpan(
                                timespan.stop, hour_delta=time_ago
                            )
                            minstamp, maxstamp = TimeSpan(
                                startOfDay(span_start), span_stop
                            )
                        else:
                            minstamp, maxstamp = archiveSpanSpan(
                                timespan.stop, hour_delta=time_ago
                            )
                    elif time_length == "day_ago_to_now":
                        if start_at_midnight:
                            span_start, span_stop = archiveSpanSpan(
                                timespan.stop, day_delta=time_ago
                            )
                            minstamp, maxstamp = TimeSpan(
                                startOfDay(span_start), span_stop
                            )
                        else:
                            minstamp, maxstamp = archiveSpanSpan(
                                timespan.stop, day_delta=time_ago
                            )
                    elif time_length == "week_ago_to_now":
                        if start_at_midnight:
                            span_start, span_stop = archiveSpanSpan(
                                timespan.stop, week_delta=time_ago
                            )
                            minstamp, maxstamp = TimeSpan(
                                startOfDay(span_start), span_stop
                            )
                        else:
                            minstamp, maxstamp = archiveSpanSpan(
                                timespan.stop, week_delta=time_ago
                            )
                    elif time_length == "month_ago_to_now":
                        if start_at_midnight:
                            span_start, span_stop = archiveSpanSpan(
                                timespan.stop, month_delta=time_ago
                            )
                            minstamp, maxstamp = TimeSpan(
                                startOfDay(span_start), span_stop
                            )
                        else:
                            minstamp, maxstamp = archiveSpanSpan(
                                timespan.stop, day_delta=time_ago * 31
                            )
                    elif time_length == "year_ago_to_now":
                        if start_at_midnight:
                            span_start, span_stop = archiveSpanSpan(
                                timespan.stop, year_delta=time_ago
                            )
                            minstamp, maxstamp = TimeSpan(
                                startOfDay(span_start), span_stop
                            )
                        else:
                            minstamp, maxstamp = archiveSpanSpan(
                                timespan.stop, day_delta=time_ago * 365
                            )
                    elif time_length == "timestamp_ago_to_now":
                        if start_at_midnight:
                            minstamp, maxstamp = TimeSpan(
                                startOfDay(time_ago), timespan.stop
                            )
                        else:
                            minstamp, maxstamp = TimeSpan(time_ago, timespan.stop)
                    elif time_length == "timespan_specific":
                        minstamp = line_options.get("timespan_start", None)
                        maxstamp = line_options.get("timespan_stop", None)
                        if minstamp is None or maxstamp is None:
                            log.error(
                                "Error trying to create timespan_specific chart. "
                                "You are missing either timespan_start or timespan_stop options."
                            )
                    elif time_length == "all":
                        minstamp = start_ts
                        maxstamp = stop_ts
                    else:
                        # Rolling timespans using seconds

                        # Convert to int() for minstamp math and for
                        # point_timestamp conditional later
                        time_length = int(time_length)

                        # Take the generation time and subtract the time_length
                        # to get our start time
                        if start_at_midnight:
                            span_start = plotgen_ts - time_length
                            minstamp = startOfDay(span_start)
                        else:
                            minstamp = plotgen_ts - time_length
                        maxstamp = plotgen_ts

                    if start_at_whole_hour:
                        minstamp -= minstamp % 3600

                    if start_at_beginning_of_month:
                        start_ts, stop_ts = archiveMonthSpan(minstamp)
                        minstamp = start_ts

                    # Find if this chart is using a new database binding.
                    # Default to the binding set in plot_options
                    binding = line_options.get("data_binding", binding)
                    archive = self.db_binder.get_manager(binding)

                    # Find the observation type if specified (e.g. more than 1
                    # of the same on a chart). (e.g. outTemp, rainFall,
                    # windDir, etc.)
                    observation_type = line_options.get("observation_type", line_name)

                    # If we have a weather range, define what the actual
                    # observation type to lookup in the db is, and to use for
                    # yAxis labels
                    weatherRange_obs_lookup = line_options.get("range_type", None)

                    # Get any custom names for this observation
                    name = line_options.get("name", None)
                    if not name:
                        # No explicit name. Look up a generic one. NB:
                        # label_dict is a KeyDict which will substitute the key
                        # if the value is not in the dictionary.
                        if weatherRange_obs_lookup is not None:
                            name = label_dict[weatherRange_obs_lookup]
                        else:
                            name = label_dict[observation_type]

                    # Look for aggregation type:
                    aggregate_type = line_options.get("aggregate_type")
                    if aggregate_type in (None, "", "None", "none"):
                        # No aggregation specified.
                        aggregate_type = aggregate_interval = None
                    else:
                        try:
                            # Aggregation specified. Get the interval.
                            aggregate_interval = weeutil.weeutil.nominal_spans(
                                line_options.get("aggregate_interval")
                            )
                        except KeyError:
                            log.error(
                                f"HighchartsJsonGenerator: aggregate interval required for aggregate type {aggregate_type}",
                            )
                            log.error(
                                f"HighchartsJsonGenerator: line type {observation_type} skipped",
                            )
                            continue

                    # use different target unit
                    special_target_unit = line_options.get("unit", None)

                    # Get the unit label
                    if observation_type in ("rainTotal", "rainDurTotal", "hailDurTotal", "sunshineDurTotal", "ETTotal"):
                        obs_label = observation_type[:-5]  # e.g. "rain", "rainDur", "hailDur", "sunshineDur"
                    elif (
                        observation_type == "weatherRange"
                        and weatherRange_obs_lookup is not None
                    ):
                        obs_label = weatherRange_obs_lookup
                    elif observation_type == "windBarb":
                        wind_obs = line_options.get("wind_obs", "windSpeed")
                        if wind_obs not in ("windSpeed", "windGust"):
                            wind_obs = "windSpeed"
                        obs_label = wind_obs
                        name = label_dict[wind_obs]
                    else:
                        wind_obs = "windSpeed"
                        obs_label = observation_type
                    unit_label = line_options.get(
                        "yAxis_label_unit",
                        self.formatter.get_label_string(
                            special_target_unit
                            if special_target_unit
                            else self.converter.getTargetUnit(
                                obs_label, aggregate_type
                            )[0]
                        ),
                    )

                    # Set the yAxis label. Place into series for custom
                    # JavaScript. Highcharts will ignore these by default
                    yAxisLabel_config = line_options.get("yAxis_label", None)
                    # Set a default yAxis label if charts.conf yAxis_label is
                    # none and there's a unit_label - e.g. Temperature (F)
                    if yAxisLabel_config is None and unit_label:
                        yAxis_label = name + " (" + unit_label.strip() + ")"
                    elif yAxisLabel_config and unit_label:
                        yAxis_label = (
                            yAxisLabel_config + " (" + unit_label.strip() + ")"
                        )
                    elif yAxisLabel_config:
                        yAxis_label = yAxisLabel_config
                    else:
                        # Unknown observation, set the default label to ""
                        yAxis_label = ""
                    output[chart_group][plotname]["options"][
                        "yAxis_label"
                    ] = yAxis_label
                    output[chart_group][plotname]["series"][line_name][
                        "yAxis_label"
                    ] = yAxis_label

                    # AQI gauge "unit" should be category text (Good,
                    # Unhealthy, etc.) when available.
                    if observation_type == "aqi":
                        try:
                            output[chart_group][plotname]["series"][line_name][
                                "yAxis_label_unit"
                            ] = aqi_category if aqi_category else label_dict["aqi_unknown"]
                        except Exception:
                            pass

                    # Check for average type:
                    average_type = line_options.get("average_type")
                    if average_type in (None, "", "None", "none"):
                        # No average type specified so force to none.
                        average_type = None

                    # Mirrored charts
                    mirrored_value = line_options.get("mirrored_value", None)

                    # Custom CSS
                    css_class = line_options.get("css_class", None)
                    output[chart_group][plotname]["options"]["css_class"] = css_class

                    # Setup polar charts
                    polar = line_options.get("polar", None)
                    if polar is not None and to_bool(polar):
                        # Only turn on polar if it's not none and it's true (1 or True)
                        output[chart_group][plotname]["series"][line_name][
                            "polar"
                        ] = "true"
                    else:
                        output[chart_group][plotname]["series"][line_name][
                            "polar"
                        ] = "false"

                    # This for loop is to get any user provided highcharts
                    # series config data. Built-in highcharts variable names
                    # accepted.
                    for highcharts_config, highcharts_value in self.chart_dict[
                        chart_group
                    ][plotname][line_name].items():
                        output[chart_group][plotname]["series"][line_name][
                            highcharts_config
                        ] = highcharts_value

                    # Override any highcharts series configs with standardized
                    # data, then generate the data output
                    output[chart_group][plotname]["series"][line_name]["name"] = name

                    # Set the yAxis min and max if present. Useful for the
                    # rxCheckPercent plots
                    yAxis_min = line_options.get("yAxis_min", None)
                    if yAxis_min is not None and yAxis_min != "":
                        output[chart_group][plotname]["series"][line_name][
                            "yAxis_min"
                        ] = yAxis_min
                    yAxis_max = line_options.get("yAxis_max", None)
                    if yAxis_max is not None and yAxis_max != "":
                        output[chart_group][plotname]["series"][line_name][
                            "yAxis_max"
                        ] = yAxis_max

                    # data rounding
                    obs_round = None
                    if (
                        obs_round is None
                        and self.chart_dict[chart_group][plotname][line_name]
                        .get("numberFormat", dict())
                        .get("decimals")
                        is not None
                    ):
                        # The user specified decimals. Use them for rounding,
                        # too.
                        try:
                            obs_round = float(
                                self.chart_dict[chart_group][plotname][line_name][
                                    "numberFormat"
                                ]["decimals"]
                            )
                        except (ValueError, TypeError):
                            log.error(
                                f"""cannot use numberFormat decimals {self.chart_dict[chart_group][plotname][line_name]["numberFormat"]["decimals"]} for rounding"""
                            )
                    if obs_round is None:
                        # Add rounding from weewx.conf/skin.conf so Highcharts can use it
                        if observation_type in ("rainTotal", "rainDurTotal", "hailDurTotal", "sunshineDurTotal", "ETTotal"):
                            rounding_obs_lookup = observation_type[:-5]  # e.g. "rain", "rainDur", "hailDur", "sunshineDur", "ET"
                        elif observation_type == "weatherRange":
                            rounding_obs_lookup = weatherRange_obs_lookup
                        elif observation_type == "haysChart":
                            rounding_obs_lookup = "windSpeed"
                        elif observation_type == "windBarb":
                            rounding_obs_lookup = wind_obs
                        else:
                            rounding_obs_lookup = observation_type
                        try:
                            obs_group = weewx.units.obs_group_dict[rounding_obs_lookup]
                            obs_unit = self.converter.group_unit_dict[obs_group]
                            obs_round = self.skin_dict["Units"]["StringFormats"].get(
                                obs_unit, "0"
                            )[2]
                        except Exception:
                            # Not a valid WeeWX schema name - maybe this is
                            # windRose or something?
                            obs_round = -1
                    output[chart_group][plotname]["series"][line_name][
                        "rounding"
                    ] = obs_round

                    wind_rose_color = {}
                    if observation_type == "windRose":
                        def get_rainbow_color(value, min, max):

                            # If value is off-scale high/low, assign max/min color
                            if value < min:
                                value = min
                            elif value > max:
                                value = max

                            # Using sine waves to generate rainbow colors (see
                            # below). Set the value to range from 8π/7 (blue)
                            # to 3π (purple).
                            i = (value - min) / (max - min) * 5.83 + 3.59

                            # https://krazydad.com/tutorials/makecolors.php
                            # Creating sine waves for red, green, and blue,
                            # and then offsetting by 2π/3 and 4π/3, creates
                            # a loop of rainbow colors. The sine waves are
                            # centered at 255/2 and have an amplitude of
                            # 255/2, so they vary from 0 to 255.
                            n = sin(i) * 127.5 + 127.5
                            red = format(int(n), "x")  # convert to hex
                            n = sin(i + 2.09) * 127.5 + 127.5
                            green = format(int(n), "x")  # convert to hex
                            n = sin(i + 4.19) * 127.5 + 127.5
                            blue = format(int(n), "x")  # convert to hex
                            return "#" + red + green + blue

                        # Set default colors, unless the user has specified
                        # otherwise in charts.conf
                        for x in range(7):
                            wind_rose_color[x] = line_options.get(
                                f"beauford{x}", get_rainbow_color(x, 0, 6)
                            )

                    # Build series data
                    series_data = self.get_observation_data(
                        binding,
                        archive,
                        observation_type,
                        minstamp,
                        maxstamp,
                        aggregate_type,
                        aggregate_interval,
                        average_type,
                        time_length,
                        xAxis_groupby,
                        xAxis_categories,
                        mirrored_value,
                        weatherRange_obs_lookup,
                        wind_rose_color,
                        special_target_unit,
                        obs_round,
                        wind_obs=wind_obs if observation_type == "windBarb" else "windSpeed",
                    )

                    # Build the final series data JSON
                    if isinstance(series_data, dict):
                        # If the returned type is a dict, then it's from the
                        # xAxis groupby section containing labels. Need to
                        # repack data, and update xAxis_categories.

                        # Use SQL Labels?
                        if "use_sql_labels" in series_data:
                            if series_data["use_sql_labels"]:
                                output[chart_group][plotname]["options"][
                                    "xAxis_categories"
                                ] = series_data["xAxis_groupby_labels"]
                        elif "weatherRange" in series_data:
                            output[chart_group][plotname]["series"][line_name][
                                "range_unit"
                            ] = series_data["range_unit"]
                            output[chart_group][plotname]["series"][line_name][
                                "range_unit_label"
                            ] = series_data["range_unit_label"]

                        elif "windBarb" in series_data:
                            output[chart_group][plotname]["series"][line_name][
                                "windBarb"
                            ] = True
                            output[chart_group][plotname]["series"][line_name][
                                "obs_unit"
                            ] = series_data["obs_unit"]
                            output[chart_group][plotname]["series"][line_name][
                                "obs_unit_label"
                            ] = series_data["obs_unit_label"]
                            output[chart_group][plotname]["series"][line_name][
                                "windspeedData"
                            ] = list(series_data["windspeedData"])

                        # No matter what, reset data back to just the series
                        # data and not a dict of values
                        output[chart_group][plotname]["series"][line_name]["data"] = (
                            list(series_data["obsdata"])
                        )
                    else:
                        # No custom series data overrides, so just add
                        # series_data to the chart series data
                        output[chart_group][plotname]["series"][line_name]["data"] = (
                            list(series_data)
                        )

                    # Final pass through
                    # self.highcharts_series_options_to_float() to convert the
                    # remaining options with numeric values to float such that
                    # Highcharts can make use of them.
                    output[chart_group][plotname]["series"][line_name] = (
                        self.highcharts_series_options_to_float(
                            output[chart_group][plotname]["series"][line_name]
                        )
                    )

            # Write the output to the JSON file
            with open(json_filename, mode="w", encoding="utf-8") as jf:
                jf.write(json.dumps(output[chart_group], indent=4))

        # Save the charts.conf to a json file for future debugging.
        chart_json_filename = html_dest_dir + "/charts.json"
        with open(chart_json_filename, mode="w", encoding="utf-8") as cjf:
            cjf.write(json.dumps(self.chart_dict, indent=4))

    def _get_forecast_aqi_point(self, observation, fallback_ts=None):
        """Return a single [timestamp_ms, value] point for AQI observations
        sourced from current_conditions.json first, then forecast.json, or
        None if unavailable.

        Extraction contracts used here are strict and provider-specific:
        - Xweather/Aeris AQI/pollutants use response[].periods[] schema keys.

        Supported observation names:
        - aqi
        - pm2_5
        - pm10
        - o3
        - co
        - no2
        - so2
        """

        obs_map = AQI_OBS_MAP

        if observation not in obs_map:
            return None

        try:
            current_point = self._get_current_conditions_aqi_point(
                observation, fallback_ts
            )
            if current_point is not None:
                return current_point

            html_root = os.path.join(
                self.config_dict["WEEWX_ROOT"],
                self.skin_dict["HTML_ROOT"],
            )
            forecast_file = os.path.join(html_root, "json", "forecast.json")
            if not os.path.isfile(forecast_file):
                return None

            with open(forecast_file, "r", encoding="utf-8") as fh:
                forecast_data = json.load(fh)

            aqi_array = forecast_data.get("aqi") or []
            if not aqi_array:
                return None

            aqi_payload = aqi_array[0] or {}
            if not aqi_payload.get("success"):
                return None

            response = aqi_payload.get("response") or []
            if not response:
                return None

            periods = response[0].get("periods") or []
            if not periods:
                return None

            # Prefer the period closest to "now" so we only use the current
            # air-quality snapshot rather than an older or future forecast.
            now_ts = int(fallback_ts or time.time())
            current_window = 6 * 3600  # generous enough for stale cache drift
            valid_periods = []
            for period in periods:
                period_ts = period.get("timestamp")
                try:
                    period_ts = int(period_ts)
                except (TypeError, ValueError):
                    continue
                if abs(period_ts - now_ts) <= current_window:
                    valid_periods.append(period)

            if valid_periods:
                period = min(
                    valid_periods,
                    key=lambda p: abs(int(p.get("timestamp", now_ts)) - now_ts),
                )
            else:
                period = periods[0]

            point_ts = period.get("timestamp") or forecast_data.get("timestamp") or now_ts

            value = self._extract_aqi_value_from_period(period, observation, obs_map)

            if value is None:
                return None

            return [float(point_ts) * 1000, float(value)]
        except Exception:
            return None

    def _get_current_conditions_aqi_point(self, observation, fallback_ts=None):
        """Return AQI data from current_conditions.json if it is available.

        This is intentionally limited to the current snapshot rather than any
        historical forecast periods.
        """

        try:
            html_root = os.path.join(
                self.config_dict["WEEWX_ROOT"],
                self.skin_dict["HTML_ROOT"],
            )
            current_conditions_file = os.path.join(
                html_root, "json", "current_conditions.json"
            )
            if not os.path.isfile(current_conditions_file):
                return None

            with open(current_conditions_file, "r", encoding="utf-8") as fh:
                current_data = json.load(fh)

            current_payload = (current_data.get("current") or [{}])[0] or {}
            point_ts = current_data.get("timestamp") or fallback_ts or int(time.time())

            # Start from the top-level current payload. Nested response/ob/periods
            # structures are traversed recursively by _extract_aqi_value_from_container.
            if isinstance(current_payload, list):
                for item in current_payload:
                    if not isinstance(item, dict):
                        continue
                    point = self._extract_aqi_value_from_container(item, observation, point_ts)
                    if point is not None:
                        return point
            elif isinstance(current_payload, dict):
                point = self._extract_aqi_value_from_container(current_payload, observation, point_ts)
                if point is not None:
                    return point

            return None
        except Exception:
            return None

    def _extract_aqi_value_from_period(self, period, observation, obs_map):
        """Extract a value from an AQI period or snapshot payload.

        This function intentionally uses exact keys from obs_map and does not
        perform multi-key alias probing.
        """

        obs_def = obs_map.get(observation)
        if obs_def is None:
            return None

        if obs_def["pollutant"] is None:
            return period.get(obs_def["value_key"])

        pollutants = period.get("pollutants") or []
        pollutant = next(
            (
                p
                for p in pollutants
                if str(p.get("type", "")).lower() == obs_def["pollutant"]
            ),
            None,
        )
        if pollutant is None:
            return None
        return pollutant.get(obs_def["value_key"])

    def _extract_aqi_value_from_container(
        self,
        container,
        observation,
        point_ts,
        obs_map=None,
    ):
        """Extract an AQI point from a container that may hold current data."""

        if obs_map is None:
            obs_map = AQI_OBS_MAP

        if observation not in obs_map:
            return None

        # Direct value on the container
        direct_value = self._extract_aqi_value_from_period(
            container, observation, obs_map
        )
        if direct_value is not None:
            return [float(point_ts) * 1000, float(direct_value)]

        # Nested current observation/forecast structures
        if "periods" in container and container["periods"]:
            value = self._extract_aqi_value_from_period(
                container["periods"][0], observation, obs_map
            )
            if value is not None:
                return [float(point_ts) * 1000, float(value)]

        if "response" in container:
            response = container["response"]
            if isinstance(response, dict):
                if response.get("ob"):
                    return self._extract_aqi_value_from_container(
                        response["ob"],
                        observation,
                        point_ts,
                        obs_map,
                    )
                if response.get("periods"):
                    return self._extract_aqi_value_from_container(
                        {"periods": response["periods"]},
                        observation,
                        point_ts,
                        obs_map,
                    )
            elif isinstance(response, list) and response:
                for item in response:
                    if not isinstance(item, dict):
                        continue
                    point = self._extract_aqi_value_from_container(
                        item,
                        observation,
                        point_ts,
                        obs_map,
                    )
                    if point is not None:
                        return point

        return None

    def get_observation_data(
        self,
        binding,
        archive,
        observation,
        start_ts,
        end_ts,
        aggregate_type,
        aggregate_interval,
        average_type,
        time_length,
        xAxis_groupby,
        xAxis_categories,
        mirrored_value,
        weatherRange_obs_lookup,
        wind_rose_color,
        special_target_unit,
        obs_round,
        wind_obs="windSpeed",
    ):
        """
        Get the SQL vectors for the observation, the aggregate type and the
        interval of time
        """

        # Cache frequently accessed attributes
        skin_dict = self.skin_dict
        converter = self.converter
        config_dict = self.config_dict

        if observation == "windRose":
            # Special Belchertown wind rose with Highcharts aggregator Wind
            # speeds are split into the first 7 beaufort groups.
            # https://en.wikipedia.org/wiki/Beaufort_scale

            # Force no aggregate_type
            if aggregate_type:
                aggregate_type = None

            # Force no aggregate_interval
            if aggregate_interval:
                aggregate_interval = None

            # Get windDir and windSpeed observations
            timespan = TimeSpan(start_ts, end_ts)

            (time_start_vt, time_stop_vt, windDir_vt) = weewx.xtypes.get_series(
                "windDir",
                timespan,
                archive,
                aggregate_type,
                aggregate_interval,
            )
            windDir_vals = list(windDir_vt[0])

            (time_start_vt, time_stop_vt, windSpeed_vt) = weewx.xtypes.get_series(
                "windSpeed",
                timespan,
                archive,
                aggregate_type,
                aggregate_interval,
            )
            windSpeed_vt = self.converter.convert(windSpeed_vt)
            usage_round = int(
                skin_dict["Units"]["StringFormats"].get(windSpeed_vt[2], "2f")[-2]
            )
            windSpeed_vals = [
                round(x, usage_round) if x is not None else None
                for x in windSpeed_vt[0]
            ]

            # Exit if the vectors are None
            if windDir_vt[1] is None or windSpeed_vt[1] is None:
                empty_windrose = [{"name": "", "data": []}]
                return empty_windrose

            # Get the unit label from the skin dict for speed.
            windSpeed_unit = windSpeed_vt[1]
            windSpeed_unit_label = skin_dict["Units"]["Labels"][windSpeed_unit]
            windSpeed_unit_key = WINDROSE_UNIT_ALIASES.get(
                windSpeed_unit, "mile_per_hour"
            )

            thresholds = WINDROSE_THRESHOLDS[windSpeed_unit_key]
            series_data = [[0.0] * 16 for _ in range(7)]

            for windDir, windSpeed in zip(windDir_vals, windSpeed_vals):
                if windDir is not None and windSpeed is not None:
                    # Determine group index based on thresholds
                    group_idx = 6  # Default to highest group
                    for i, threshold in enumerate(thresholds):
                        if windSpeed < threshold:
                            group_idx = i
                            break

                    dir_idx = int((windDir + 11.25) / 22.5) % 16
                    series_data[group_idx][dir_idx] += windSpeed

            series_data = [[round(v, 1) for v in data] for data in series_data]

            # Calculate wind frequency percentages
            wind_sum = sum(sum(data) for data in series_data)
            if wind_sum > 0:
                series_data = [
                    [round(val / wind_sum * 100) for val in data]
                    for data in series_data
                ]

            labels = WINDROSE_SPEED_RANGE_LABELS[windSpeed_unit_key]

            # Build series data efficiently using list comprehension
            series = [
                {
                    "name": f"{labels[i]} {windSpeed_unit_label}",
                    "type": "column",
                    "color": wind_rose_color[i],
                    "zIndex": 106 - i,
                    "stacking": "normal",
                    "fillOpacity": 0.75,
                    "data": series_data[i],
                }
                for i in range(7)
            ]

            return series

        # Special Belchertown Weather Range (radial)
        # https://www.highcharts.com/blog/tutorials/209-the-art-of-the-chart-weather-radials/
        if observation == "weatherRange":

            # Define what we are looking up
            if weatherRange_obs_lookup is not None:
                obs_lookup = weatherRange_obs_lookup
            else:
                log.error(
                    "Error trying to create the weather range chart. "
                    "You are missing the range_type configuration item."
                )

            # Force 1 day if aggregate_interval. These charts are meant to show
            # a column range for high, low and average for a full day.
            if not aggregate_interval:
                aggregate_interval = 86400

            # Get min values
            aggregate_type = "min"
            try:
                (time_start_vt, time_stop_vt, obs_vt) = weewx.xtypes.get_series(
                    obs_lookup,
                    TimeSpan(start_ts, end_ts),
                    archive,
                    aggregate_type,
                    aggregate_interval,
                )
            except Exception as e:
                log.error(
                    f"Error trying to use database binding {binding} to chart observation {obs_lookup}. "
                    f"Error was: {e}."
                )

            self.insert_null_value_timestamps_to_end_ts(
                time_start_vt,
                time_stop_vt,
                obs_vt,
                start_ts,
                end_ts,
                aggregate_interval,
            )

            min_obs_vt = self.converter.convert(obs_vt)

            # Get max values
            aggregate_type = "max"
            try:
                (time_start_vt, time_stop_vt, obs_vt) = weewx.xtypes.get_series(
                    obs_lookup,
                    TimeSpan(start_ts, end_ts),
                    archive,
                    aggregate_type,
                    aggregate_interval,
                )
            except Exception as e:
                log.error(
                    f"Error trying to use database binding {binding} to chart observation {obs_lookup}. "
                    f"Error was: {e}."
                )

            self.insert_null_value_timestamps_to_end_ts(
                time_start_vt,
                time_stop_vt,
                obs_vt,
                start_ts,
                end_ts,
                aggregate_interval,
            )

            max_obs_vt = self.converter.convert(obs_vt)

            # Get avg values
            aggregate_type = "avg"
            try:
                (time_start_vt, time_stop_vt, obs_vt) = weewx.xtypes.get_series(
                    obs_lookup,
                    TimeSpan(start_ts, end_ts),
                    archive,
                    aggregate_type,
                    aggregate_interval,
                )
            except Exception as e:
                log.error(
                    f"Error trying to use database binding {binding} to chart observation {obs_lookup}. "
                    f"Error was: {e}."
                )

            self.insert_null_value_timestamps_to_end_ts(
                time_start_vt,
                time_stop_vt,
                obs_vt,
                start_ts,
                end_ts,
                aggregate_interval,
            )

            avg_obs_vt = self.converter.convert(obs_vt)

            obs_unit = avg_obs_vt[1]
            obs_unit_label = skin_dict["Units"]["Labels"].get(obs_unit, "")

            # Convert to millis and zip all together
            time_ms = [float(x) * 1000 for x in time_start_vt[0]]
            output_data = list(zip(time_ms, min_obs_vt[0], max_obs_vt[0], avg_obs_vt[0]))

            data = {
                "weatherRange": True,
                "obsdata": output_data,
                "range_unit": obs_unit,
                "range_unit_label": obs_unit_label,
            }

            return data

        # Hays chart
        if observation == "haysChart":

            start_ts = int(start_ts)
            end_ts = int(end_ts)

            # Set aggregate interval based on timespan and make sure it is
            # between 5 minutes and 1 day
            logging.debug(f"Start time is {start_ts} and end time is {end_ts}")
            aggregate_interval = (end_ts - start_ts) / 360
            if aggregate_interval < 300:
                aggregate_interval = 300
            elif aggregate_interval > 86400:
                aggregate_interval = 86400
            logging.debug(f"Interval is: {aggregate_interval}")

            aggregate_type = "max"
            # Get min values
            obs_lookup = "windSpeed"
            try:
                (time_start_vt, time_stop_vt, obs_vt) = weewx.xtypes.get_series(
                    obs_lookup,
                    TimeSpan(start_ts, end_ts),
                    archive,
                    aggregate_type,
                    aggregate_interval,
                )
            except Exception as e:
                log.error(
                    f"Error trying to use database binding {binding} to chart observation {obs_lookup}. "
                    f"Error was: {e}."
                )

            self.insert_null_value_timestamps_to_end_ts(
                time_start_vt,
                time_stop_vt,
                obs_vt,
                start_ts,
                end_ts,
                aggregate_interval,
            )

            min_obs_vt = self.converter.convert(obs_vt)

            # Get max values
            obs_lookup = "windGust"
            try:
                (time_start_vt, time_stop_vt, obs_vt) = weewx.xtypes.get_series(
                    obs_lookup,
                    TimeSpan(start_ts, end_ts),
                    archive,
                    aggregate_type,
                    aggregate_interval,
                )
            except Exception as e:
                log.error(
                    f"Error trying to use database binding {binding} to chart observation {obs_lookup}. "
                    f"Error was: {e}."
                )

            self.insert_null_value_timestamps_to_end_ts(
                time_start_vt,
                time_stop_vt,
                obs_vt,
                start_ts,
                end_ts,
                aggregate_interval,
            )

            max_obs_vt = self.converter.convert(obs_vt)

            obs_unit = max_obs_vt[1]
            obs_unit_label = skin_dict["Units"]["Labels"].get(obs_unit, "")

            # Convert to millis and zip all together
            time_ms = [float(x) * 1000 for x in time_start_vt[0]]
            output_data = zip(time_ms, min_obs_vt[0], max_obs_vt[0])

            data = {
                "haysChart": True,
                "obsdata": output_data,
                "range_unit": obs_unit,
                "range_unit_label": obs_unit_label,
            }

            return data

        # Belchertown wind barb chart
        if observation == "windBarb":
            start_ts = int(start_ts)
            end_ts = int(end_ts)
            timespan = TimeSpan(start_ts, end_ts)

            # Fetch wind speed (windSpeed or windGust based on wind_obs option)
            try:
                (time_start_vt, time_stop_vt, windSpeed_vt) = weewx.xtypes.get_series(
                    wind_obs,
                    timespan,
                    archive,
                    aggregate_type,
                    aggregate_interval,
                )
            except Exception as e:
                log.error(
                    f"Error trying to use database binding {binding} to chart "
                    f"observation {wind_obs} (windBarb). Error was: {e}."
                )
                return []

            self.insert_null_value_timestamps_to_end_ts(
                time_start_vt,
                time_stop_vt,
                windSpeed_vt,
                start_ts,
                end_ts,
                aggregate_interval,
            )

            # Convert windSpeed to the user's display unit (used for the line series)
            display_vt = self.converter.convert(windSpeed_vt)
            obs_unit = display_vt[1]
            obs_unit_label = skin_dict["Units"]["Labels"].get(obs_unit, "")
            windSpeed_display = list(display_vt[0])

            # Highcharts uses m/s to determine the number of barbs drawn.
            # When aggregating, always use the *maximum* speed in each interval
            # so the barb count reflects the peak conditions rather than an
            # average.
            ms_converter = weewx.units.Converter({"group_speed": "meter_per_second"})
            if aggregate_interval and aggregate_type != "max":
                try:
                    (_, _, windSpeed_max_vt) = weewx.xtypes.get_series(
                        wind_obs,
                        timespan,
                        archive,
                        "max",
                        aggregate_interval,
                    )
                    ms_vt = ms_converter.convert(windSpeed_max_vt)
                except Exception:
                    ms_vt = ms_converter.convert(windSpeed_vt)
            else:
                ms_vt = ms_converter.convert(windSpeed_vt)
            windSpeed_ms = list(ms_vt[0])

            # Fetch windDir. When aggregating:
            #   - "vecdir" is requested: use vecdir (speed-weighted vector mean direction),
            #     which correctly handles the 0/360 wraparound and is the most
            #     meteorologically accurate mean-wind direction aggregate.
            #   - otherwise: use "gustdir" (direction at the time of the peak gust),
            #     which avoids max(degrees) picking 360° purely because it is
            #     numerically largest. Falls back to "avg" if gustdir is unsupported.
            if aggregate_interval:
                winddir_agg_type = "vecdir" if aggregate_type == "vecdir" else "gustdir"
            else:
                winddir_agg_type = aggregate_type
            try:
                (_, _, windDir_vt) = weewx.xtypes.get_series(
                    "windDir",
                    timespan,
                    archive,
                    winddir_agg_type,
                    aggregate_interval,
                )
            except Exception:
                # vecdir failed (e.g. custom binding without windSpeed) → try gustdir
                # gustdir failed (e.g. no windGust column) → try avg
                if winddir_agg_type == "vecdir":
                    winddir_agg_type = "gustdir"
                else:
                    winddir_agg_type = "avg" if aggregate_interval else aggregate_type
                try:
                    (_, _, windDir_vt) = weewx.xtypes.get_series(
                        "windDir",
                        timespan,
                        archive,
                        winddir_agg_type,
                        aggregate_interval,
                    )
                except Exception:
                    # Second fallback: avg
                    winddir_agg_type = "avg" if aggregate_interval else aggregate_type
                    try:
                        (_, _, windDir_vt) = weewx.xtypes.get_series(
                            "windDir",
                            timespan,
                            archive,
                            winddir_agg_type,
                            aggregate_interval,
                        )
                    except Exception as e:
                        log.error(
                            f"Error trying to use database binding {binding} to chart "
                            f"observation windDir (windBarb). Error was: {e}."
                        )
                        return []

            windDir_vals = list(windDir_vt[0])

            # Convert timestamps to milliseconds
            time_ms = [float(x) * 1000 for x in time_start_vt[0]]

            # Wind speed pairs for the line series: [ts_ms, display_speed]
            windspeed_data = [
                [ts, spd]
                for ts, spd in zip(time_ms, windSpeed_display)
            ]

            # Windbarb triples: [ts_ms, m/s_speed, direction]
            # Keep calm points (speed < 2.5 knots) even if windDir is None so the
            # frontend windbarb series can render the standard calm circle.
            # Exclude missing speeds (None) to avoid rendering false calm points.
            calm_threshold_ms = 2.5 * 0.514444
            windbarb_data = [
                [ts, spd_ms, dr]
                for ts, spd_ms, dr in zip(time_ms, windSpeed_ms, windDir_vals)
                if spd_ms is not None and (dr is not None or spd_ms < calm_threshold_ms)
            ]

            return {
                "windBarb": True,
                "obsdata": windbarb_data,
                "windspeedData": windspeed_data,
                "obs_unit": obs_unit,
                "obs_unit_label": obs_unit_label,
            }

        # Special Belchertown Skin rain counter
        if observation in ("rainTotal", "rainDurTotal", "hailDurTotal", "sunshineDurTotal", "ETTotal"):
            obs_lookup = observation[:-5]  # e.g. "rain", "rainDur", "hailDur", "sunshineDur", "ET"
            # Force sum on this observation
            if aggregate_interval:
                aggregate_type = "sum"
        elif observation == "rainRate":
            obs_lookup = "rainRate"
            # Force max on this observation
            if aggregate_interval:
                aggregate_type = "max"
        else:
            obs_lookup = observation

        #   Special aggregation_subtype measures to enable average rainfall, max and min temperatures to be calculated

        if (
            aggregate_type == "avg"
            and observation == "avgRainfall"
            and aggregate_interval == 86400
        ):
            obs_lookup = "rain"

        if xAxis_groupby or len(xAxis_categories) >= 1:
            # Setup the converter - for some reason converter doesn't work
            # for the group_unit_dict in this section Get the target unit
            # nickname (something like 'US' or 'METRIC'):
            target_unit_nickname = config_dict["StdConvert"]["target_unit"]
            # Get the target unit: weewx.US, weewx.METRIC, weewx.METRICWX
            target_unit = weewx.units.unit_constants[target_unit_nickname.upper()]
            # Bind to the appropriate standard converter units
            converter = weewx.units.StdUnitConverters[target_unit]

            # Find what kind of database we're working with and specify the
            # correctly tailored SQL Query for each type of database
            data_binding = config_dict["StdArchive"]["data_binding"]
            database = config_dict["DataBindings"][data_binding]["database"]
            database_type = config_dict["Databases"][database]["database_type"]
            driver = config_dict["DatabaseTypes"][database_type]["driver"]
            xAxis_labels = []
            obsvalues = []

            # Define the xAxis group by for the sql query. Default to month
            if xAxis_groupby == "hour":
                strformat = "%H"
            elif xAxis_groupby == "day":
                strformat = "%d"
            elif xAxis_groupby == "month":
                strformat = "%m"
            elif xAxis_groupby == "year":
                strformat = "%Y"
            elif xAxis_groupby == "":
                strformat = "%m"
            else:
                strformat = "%m"

            # Default catch all in case the aggregate_type isn't defined, default to sum
            if aggregate_type is None:
                aggregate_type = "sum"

            if isinstance(time_length, int):
                order_sql = " ORDER BY dateTime ASC"
            else:
                order_sql = ""

            # Special case for time_length = all, force to use complete days only
            if time_length == "all":
                start_ts = startOfDay(archive.firstGoodStamp()) + 86400
                end_ts = startOfDay(archive.lastGoodStamp())

            # Set up subquery groupby clause
            if xAxis_groupby == "year":
                subqry_groupby = '"%Y"'
            elif xAxis_groupby == "month":
                subqry_groupby = '"%Y%m"'
            elif xAxis_groupby == "day":
                subqry_groupby = '"%Y%m%d"'
            elif xAxis_groupby == "hour":
                subqry_groupby = '"%Y%m%d%H"'
            else:
                subqry_groupby = ""

            if driver == "weedb.sqlite":
                # Use daily summaries where possible - MUST BE FOR WHOLE DAYS determined by start and stop times otherwise use archive
                if (
                    xAxis_groupby != "hour"
                    and isStartOfDay(start_ts)
                    and isStartOfDay(end_ts)
                    and end_ts - start_ts > 0
                ):  # 1 or more exact days
                    # Avg is a special case
                    if aggregate_type == "avg":
                        # Avg(sum) requires a subquery with the correct group by clause
                        if average_type is not None and average_type == "sum":
                            sql_lookup = f"""
                                SELECT dt1 AS {xAxis_groupby}, 
                                AVG(obs1) AS obs 
                                FROM (SELECT strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')) AS dt1, SUM(sum) AS obs1 
                                FROM archive_day_{obs_lookup} WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                                GROUP BY strftime({subqry_groupby}, datetime(dateTime, "unixepoch", "localtime"))) 
                                GROUP BY dt1{order_sql};
                            """
                        # avg cases with an average_type
                        elif average_type is not None:
                            sql_lookup = f"""
                                SELECT strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')) AS {xAxis_groupby}, 
                                {aggregate_type}({average_type}) AS obs 
                                FROM archive_day_{obs_lookup} WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                                GROUP BY strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')){order_sql};
                            """
                        # remaining avg cases without an average_type use weighted average
                        else:
                            sql_lookup = f"""
                                SELECT strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')) AS {xAxis_groupby}, 
                                SUM(wsum)/SUM(sumtime) AS obs 
                                FROM archive_day_{obs_lookup} WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                                GROUP BY strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')){order_sql};
                            """
                    # other aggregate_type cases use direct interrogation of daily summary
                    else:
                        sql_lookup = f"""
                            SELECT strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')) AS {xAxis_groupby}, 
                            {aggregate_type}({aggregate_type}) AS obs 
                            FROM archive_day_{obs_lookup} 
                            WHERE dateTime >= {start_ts} AND dateTime < {end_ts} GROUP BY strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')){order_sql};
                        """
                else:
                    # archive access with no average_type
                    if average_type is None:
                        sql_lookup = f"""
                            SELECT strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')) AS {xAxis_groupby}, 
                            IFNULL({aggregate_type}({obs_lookup}),0) AS obs 
                            FROM archive WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                            GROUP BY strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')){order_sql};
                        """

                    # average_type requiring a subquery
                    else:
                        sql_lookup = f"""
                            SELECT dt1 AS {xAxis_groupby}, 
                            {aggregate_type}(obs1) AS obs 
                            FROM (SELECT strftime('{strformat}', datetime(dateTime, 'unixepoch', 'localtime')) AS dt1, 
                            IFNULL({average_type}({obs_lookup}),0) AS obs1 
                            FROM archive WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                            GROUP BY strftime({subqry_groupby}, datetime(dateTime, 'unixepoch', 'localtime'))) 
                            GROUP BY dt1{order_sql};
                        """

            elif driver == "weedb.mysql":
                # Use daily summaries where possible - MUST BE FOR WHOLE DAYS determined by start and stop times otherwise use archive
                if (
                    xAxis_groupby != "hour"
                    and isStartOfDay(start_ts)
                    and isStartOfDay(end_ts)
                    and end_ts - start_ts > 0
                ):  # 1 or more exact days
                    # Avg is a special case
                    if aggregate_type == "avg":
                        # Avg(sum) requires a subquery with the correct group by clause
                        if average_type is not None and average_type == "sum":
                            sql_lookup = f"""
                                SELECT dt1 AS {xAxis_groupby}, 
                                AVG(obs1) AS obs 
                                FROM (SELECT FROM_UNIXTIME(dateTime, '%{strformat}') AS dt1, SUM(sum) AS obs1 
                                FROM archive_day_{obs_lookup} WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                                GROUP BY FROM_UNIXTIME(dateTime, '{subqry_groupby.strip("%")}') ) AS subq 
                                GROUP BY dt1{order_sql};
                            """
                        # avg cases with an average_type
                        elif average_type is not None:
                            sql_lookup = f"""
                                SELECT FROM_UNIXTIME(dateTime, '%{strformat}') AS {xAxis_groupby}, 
                                {aggregate_type}({average_type}) AS obs 
                                FROM archive_day_{obs_lookup} WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                                GROUP BY FROM_UNIXTIME(dateTime, '%{strformat}'){order_sql};
                            """
                        # remaining avg cases without an average_type use weighted average
                        else:
                            sql_lookup = f"""
                                SELECT FROM_UNIXTIME(dateTime, '%{strformat}') AS {xAxis_groupby}, 
                                SUM(wsum)/SUM(sumtime) AS obs 
                                FROM archive_day_{obs_lookup} WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                                GROUP BY FROM_UNIXTIME(dateTime, '%{strformat}'){order_sql};
                            """
                    # other aggregate_type cases use direct interrogation of daily summary
                    else:
                        sql_lookup = f"""
                            SELECT FROM_UNIXTIME(dateTime, '%{strformat}') AS {xAxis_groupby}, 
                            {aggregate_type}({aggregate_type}) AS obs 
                            FROM archive_day_{obs_lookup} 
                            WHERE dateTime >= {start_ts} AND dateTime < {end_ts} GROUP BY FROM_UNIXTIME(dateTime, '%{strformat}'){order_sql};
                        """
                else:
                    # archive access with no average_type
                    if average_type is None:
                        sql_lookup = f"""
                            SELECT FROM_UNIXTIME(dateTime, '%{strformat}') AS {xAxis_groupby}, 
                            IFNULL({aggregate_type}({obs_lookup}),0) AS obs 
                            FROM archive WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                            GROUP BY FROM_UNIXTIME(dateTime, '%{strformat}'){order_sql};
                        """

                    # average_type requiring a subquery
                    else:
                        sql_lookup = f"""
                            SELECT dt1 AS {xAxis_groupby}, 
                            {aggregate_type}(obs1) AS obs 
                            FROM (SELECT FROM_UNIXTIME(dateTime, '%{strformat}') AS dt1, 
                            IFNULL({average_type}({obs_lookup}),0) AS obs1 
                            FROM archive WHERE dateTime >= {start_ts} AND dateTime < {end_ts} 
                            GROUP BY FROM_UNIXTIME(dateTime, '{subqry_groupby.strip("%")}')) AS subq 
                            GROUP BY dt1{order_sql};
                        """

            # Setup values for the converter
            try:
                obs_group = weewx.units.obs_group_dict[obs_lookup]
                obs_unit_from_target_unit = converter.group_unit_dict[obs_group]
            except Exception:
                # This observation doesn't exist within WeeWX schema so nothing
                # to convert, so set None type
                obs_group = None
                obs_unit_from_target_unit = None

            # introduce test to catch any sql errors; a try / except sequence

            try:
                query = archive.genSql(sql_lookup)
            except Exception as e:
                log.error(f"SQL error in sql_lookup. The error is: {e}")

            for row in query:
                xAxis_labels.append(row[0])
                row_tuple = (row[1], obs_unit_from_target_unit, obs_group)
                if special_target_unit:
                    row_converted = weewx.units.convert(row_tuple, special_target_unit)
                else:
                    row_converted = self.converter.convert(row_tuple)
                obsvalues.append(row_converted[0])

            # If the values are to be mirrored, we need to make them negative
            if mirrored_value:
                for i in obsvalues:
                    if i is not None:
                        i = -i

            # Return a dict which has the value for if we need to add labels
            # from sql or not.
            if len(xAxis_categories) == 0:
                data = {
                    "use_sql_labels": True,
                    "xAxis_groupby_labels": xAxis_labels,
                    "obsdata": obsvalues,
                }
            else:
                data = {
                    "use_sql_labels": False,
                    "xAxis_groupby_labels": "",
                    "obsdata": obsvalues,
                }
            return data

        # Begin standard observation lookups
        try:
            (time_start_vt, time_stop_vt, obs_vt) = weewx.xtypes.get_series(
                obs_lookup,
                TimeSpan(start_ts, end_ts),
                archive,
                aggregate_type,
                aggregate_interval,
            )
        except Exception as e:
            forecast_point = self._get_forecast_aqi_point(observation, end_ts)
            if forecast_point is not None:
                log.info(
                    f"Using forecast.json AQI fallback for observation '{observation}'"
                )
                return [forecast_point]
            log.error(
                f"Error trying to use database binding {binding} to chart observation {obs_lookup}. Error was: {e}."
            )
            return []

        self.insert_null_value_timestamps_to_end_ts(
            time_start_vt, time_stop_vt, obs_vt, start_ts, end_ts, aggregate_interval
        )

        if special_target_unit:
            log.debug(
                f"unit_group={obs_vt[2]} source_unit={obs_vt[1]} special_target_unit={special_target_unit}"
            )
            obs_vt = weewx.units.Converter({obs_vt[2]: special_target_unit}).convert(
                obs_vt
            )
        else:
            obs_vt = self.converter.convert(obs_vt)

        # Special handling for running totals (rain, rainDur, hailDur, sunshineDur).
        # The WeeWX "rain" observation is really "bucket tips"; this counter
        # accumulates them over the timespan to return a running total. The
        # same pattern applies to duration observations.
        # None/"" values are passed through so full-length charts
        # (like WeeWX v4 archiveYearSpan) don't extend past the last actual plot.
        if observation in ("rainTotal", "rainDurTotal", "hailDurTotal", "sunshineDurTotal", "ETTotal"):
            running_count = 0
            obs_round_vt = []
            for val in obs_vt[0]:
                if val is None or val == "":
                    obs_round_vt.append(val)
                    continue
                running_count = running_count + val
                obs_round_vt.append(round(running_count, 2))
        else:
            # Send all other observations through the usual process, except
            # Barometer for finer detail
            if observation == "barometer":
                usage_round = int(
                    skin_dict["Units"]["StringFormats"].get(obs_vt[1], "1f")[-2]
                )
                obs_round_vt = [
                    round(x, usage_round) if x is not None else None for x in obs_vt[0]
                ]
            else:
                try:
                    if obs_round is None:
                        usage_round = int(
                            skin_dict["Units"]["StringFormats"].get(obs_vt[1], "2f")[-2]
                        )
                    else:
                        usage_round = int(obs_round) + 1
                except ValueError:
                    log.info(
                        f"Observation {observation} is using unit {obs_vt[1]} "
                        f"""that returns {skin_dict["Units"]["StringFormats"].get(obs_vt[1])} """
                        "for StringFormat, rather than float point decimal format value - using 0 as rounding"
                    )
                    usage_round = 0

                obs_round_vt = [self.round_none(x, usage_round) for x in obs_vt[0]]

        # "Today" charts, "timespan_specific" charts and floating timespan
        # charts have the point timestamp on the stop time so we don't see the
        # previous minute in the tooltip. (e.g. 4:59 instead of 5:00)
        # Everything else has it on the start time so we don't see the next day
        # in the tooltip (e.g. Jan 2 instead of Jan 1)
        try:
            if not aggregate_type:
                point_timestamp = time_stop_vt
            elif aggregate_interval and (
                aggregate_interval == 3600 or aggregate_interval == 2629800
            ):
                point_timestamp = time_start_vt
            else:
                point_timestamp = (
                    [(x + y) / 2.0 for x, y in zip(time_start_vt[0], time_stop_vt[0])],
                    time_start_vt[1],
                    time_start_vt[2],
                )
        except Exception:
            point_timestamp = time_stop_vt

        # If the values are to be mirrored, we need to make them negative
        if mirrored_value:
            obs_round_vt = [-x if x is not None else None for x in obs_round_vt]

        # If the archive lookup produced no usable data, fall back to the
        # forecast-backed AQI observations when available. This covers the
        # common case where the observation is intentionally not stored in the
        # archive database, but the value is present in forecast.json.
        forecast_point = self._get_forecast_aqi_point(observation, end_ts)
        if forecast_point is not None and not any(x is not None for x in obs_round_vt):
            log.info(
                f"Using forecast.json AQI fallback for observation '{observation}' after empty archive result"
            )
            return [forecast_point]

        time_ms = [float(x) * 1000 for x in point_timestamp[0]]
        data = zip(time_ms, obs_round_vt)

        return data

    def insert_null_value_timestamps_to_end_ts(
        self, time_start_vt, time_stop_vt, obs_vt, start_ts, end_ts, interval
    ):
        """
        In WeeWX 4.5.1 xtypes.py was modified to not return any data points which didn't exist in the archive database.
        This function adds the 'future' data points from the last timestamp in the list up until end_ts with None entries.
        This means that charts still have the option of showing a full day or month or year on the x axis depending on the time_length specfied.
        """
        if interval is not None:
            try:
                ts = time_start_vt[0][-1] + interval
            except Exception:
                ts = start_ts

            while ts < end_ts:
                time_start_vt[0].append(ts)
                time_stop_vt[0].append(ts)
                obs_vt[0].append(None)
                ts += interval

    def round_none(self, value, places):
        """Round value to 'places' places but also permit a value of None"""
        if value is not None:
            try:
                value = round(value, places)
            except Exception:
                value = None
        return value

    def timespan_year_to_now(self, time_ts, grace=1, years_ago=0):
        """
        In WeeWX 4 the get_series() for archiveYearSpan returns the full 365
        day chart.  if users do not want a full year (with empty data) and
        would rather a Jan 1 to "now", then they can use this custom timespan

        This is taken right from weewx, but adapted to end at the current
        timestamp, and not the following Jan 1.
        """
        if time_ts is None:
            return None
        time_ts -= grace
        _day_date = datetime.date.fromtimestamp(time_ts)
        return TimeSpan(
            int(time.mktime((_day_date.year - years_ago, 1, 1, 0, 0, 0, 0, 0, -1))),
            int(float(time_ts)),
        )

    def create_windrose_data(self, windDir_list, windSpeed_list):
        windrose_list = [0.0] * 16
        for wind_dir, wind_speed in zip(windDir_list, windSpeed_list):
            if wind_speed is not None and wind_dir is not None:
                windrose_list[int((wind_dir + 11.25) / 22.5) % 16] += wind_speed
        return [round(v, 1) for v in windrose_list]

    def highcharts_series_options_to_float(self, d):
        """
        Recurse through all the series options and set any strings that
        should be numbers to float.
        https://stackoverflow.com/a/54565277/1177153
        """

        if not isinstance(d, dict):
            return d

        for k, v in d.items():
            if isinstance(v, dict):
                self.highcharts_series_options_to_float(v)
                continue

            try:
                d[k] = to_float(v)
            except Exception:
                pass
        return d
