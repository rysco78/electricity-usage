"""
Parse a Green Button XML file downloaded from smartmetertexas.com.
Downloads: My Account → Green Button → Download My Data (select date range + XML format).
Values in Green Button are in Wh; we convert to kWh.
Day = 6am–9:59pm local (Central); Night = 10pm–5:59am local.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")


def parse_greenbutton(path: str) -> tuple[list[dict], list[float]]:
    """
    Parse a Green Button XML file and return:
      - daily: list of {"date": "MM/DD/YYYY", "kwh": float, "day_kwh": float, "night_kwh": float}
      - hourly_avg: list of 24 floats — average kWh consumed in each hour of the day (0–23)
    """
    tree = ET.parse(path)
    root = tree.getroot()

    readings: list[tuple[int, float]] = []
    for block in root.iter("{http://naesb.org/espi}IntervalBlock"):
        for reading in block.iter("{http://naesb.org/espi}IntervalReading"):
            start_el = reading.find("{http://naesb.org/espi}timePeriod/{http://naesb.org/espi}start")
            value_el = reading.find("{http://naesb.org/espi}value")
            if start_el is not None and value_el is not None:
                readings.append((int(start_el.text), float(value_el.text)))

    if not readings:
        raise ValueError("No IntervalReading entries found. Check the file is a valid Green Button XML.")

    daily_kwh: dict[str, float] = defaultdict(float)
    daily_day: dict[str, float] = defaultdict(float)
    daily_night: dict[str, float] = defaultdict(float)

    # Hourly accumulators: total kWh and number of interval readings per hour-of-day
    hour_total = [0.0] * 24
    hour_count = [0] * 24

    for ts, wh in readings:
        dt = datetime.fromtimestamp(ts, tz=TZ)
        day_key = dt.strftime("%m/%d/%Y")
        kwh = wh / 1000.0

        daily_kwh[day_key] += kwh

        if 6 <= dt.hour <= 21:  # 6am–9:59pm = day
            daily_day[day_key] += kwh
        else:
            daily_night[day_key] += kwh

        hour_total[dt.hour] += kwh
        hour_count[dt.hour] += 1

    daily = [
        {
            "date": k,
            "kwh": round(daily_kwh[k], 3),
            "day_kwh": round(daily_day[k], 3),
            "night_kwh": round(daily_night[k], 3),
        }
        for k in sorted(daily_kwh.keys(), key=lambda x: datetime.strptime(x, "%m/%d/%Y"))
    ]

    hourly_avg = [
        round(hour_total[h] / hour_count[h], 4) if hour_count[h] > 0 else 0.0
        for h in range(24)
    ]

    return daily, hourly_avg
