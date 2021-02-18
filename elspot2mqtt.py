"""Elspot to MQTT bridge"""

import argparse
import calendar
import json
import logging
import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Optional

import paho.mqtt.client as mqtt
from dataclasses_json import dataclass_json
from nordpool import elspot

CURRENCY = "SEK"
DEFAULT_CONF_FILENAME = "elspot2mqtt.json"

TIMEZONE = None

elspot.Prices.API_URL = "https://www.nordpoolgroup.com/api/marketdata/page/%i"

logger = logging.getLogger(__name__)


@dataclass
class PriceMarkup:
    grid: float
    cert: float
    tax: float
    vat_percentage: float

    def total_cost(self, c: float) -> float:
        base_cost = self.grid + self.cert + self.tax
        vat = c * self.vat_percentage / 100
        return c + vat + base_cost / 100

    def vat_cost(self, c: float) -> float:
        vat = c * self.vat_percentage / 100
        return c + vat


@dataclass_json
@dataclass
class MqttConfig:
    host: str = "127.0.0.1"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    client_id: Optional[str] = None
    topic: Optional[str] = None
    retain: bool = False
    publish: bool = True


class PricesDatabase(object):
    def __init__(self, filename: str):
        self.conn = sqlite3.connect(filename)
        self.table = "nordpool"
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} (timestamp INTEGER PRIMARY KEY, value REAL);"
        )

    def get_prices(self, d: date):
        d1 = datetime.fromisoformat(d.isoformat()).astimezone(tz=TIMEZONE)
        t1 = calendar.timegm(d1.utctimetuple())
        t2 = t1 + 86400
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT timestamp,value FROM {self.table} WHERE timestamp>=? and timestamp<?",
            (t1, t2),
        )
        rows = cur.fetchall()
        if len(rows) != 24:
            return None
        return {
            datetime.fromtimestamp(r[0]).astimezone(tz=TIMEZONE): r[1] for r in rows
        }

    def store_prices(self, prices):
        cur = self.conn.cursor()
        for dt, v in prices.items():
            ts = calendar.timegm(dt.utctimetuple())
            cur.execute(
                f"REPLACE INTO {self.table} (timestamp,value) VALUES(?,?)", (ts, v)
            )
        self.conn.commit()


def get_prices_nordpool(end_date: datetime, area: str, currency=CURRENCY) -> {}:
    spot = elspot.Prices(currency=currency)
    prices = {}
    data = spot.hourly(areas=[area], end_date=end_date)
    for entry in data["areas"][area]["values"]:
        cost = entry["value"]
        if math.isinf(cost):
            raise ValueError
        ts = entry["start"].astimezone(tz=TIMEZONE)
        prices[ts] = cost / 1000
    return prices


def percentage_to_level(p: float) -> str:
    if p >= 20:
        return "VERY_EXPENSIVE"
    elif p >= 10:
        return "EXPENSIVE"
    elif p <= -20:
        return "VERY_CHEAP"
    elif p <= -10:
        return "CHEAP"
    else:
        return "NORMAL"


def look_ahead(prices, pm: PriceMarkup, avg_window_size=120):
    present = datetime.now().astimezone(tz=TIMEZONE) - timedelta(hours=1)
    now_offset = 0
    res = {}

    dt_spot_prices = {t: pm.vat_cost(v) for t, v in prices.items()}
    dt_total_prices = {t: pm.total_cost(v) for t, v in prices.items()}
    costs = []

    for dt, cost in dt_total_prices.items():
        costs.append(cost)

        if dt < present:
            continue

        if len(costs) >= avg_window_size:
            avg = mean(costs[len(costs) - avg_window_size : len(costs)])
            relpt = round((cost / avg - 1) * 100, 0)
            level = percentage_to_level(relpt)
        else:
            avg = 0
            relpt = 0
            level = None

        res[f"now+{now_offset}"] = {
            "timestamp": dt.isoformat(),
            "energy_price": round(dt_spot_prices[dt], 2),
            "price": round(cost, 2),
            f"avg{avg_window_size}": round(avg, 2),
            "relpt": relpt,
            "level": level,
        }
        now_offset += 1

    return res


def main():
    """Main function"""

    parser = argparse.ArgumentParser(description="elspot2mqtt")
    parser.add_argument(
        "--conf",
        dest="conf_filename",
        default=DEFAULT_CONF_FILENAME,
        metavar="filename",
        help="configuration file",
        required=False,
    )
    parser.add_argument(
        "--debug", dest="debug", action="store_true", help="Print debug information"
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    with open(args.conf_filename, "rt") as config_file:
        config = json.load(config_file)

    db = PricesDatabase(config["database"])

    prices = {}
    for offset in range(-5, 2):
        if offset == 1 and datetime.now().hour < 13:
            logger.debug("Tomorrows prices not yet available")
            continue
        end_date = date.today() + timedelta(days=offset)
        logger.debug("Processing %s, offset=%d", end_date, offset)
        p = db.get_prices(end_date)
        if p is None:
            logger.debug("Fetching data for %s from Nordpool", end_date)
            try:
                p = get_prices_nordpool(end_date=end_date, area=config["AREA"])
                db.store_prices(p)
            except ValueError:
                pass
        else:
            logger.debug("Using cached data for %s", end_date)
        prices.update(p)

    pm = PriceMarkup(
        grid=config["markup"]["grid"],
        cert=config["markup"]["cert"],
        tax=config["markup"]["tax"],
        vat_percentage=config["markup"]["vat_percentage"],
    )

    avg_window_size = config.get("avg_window_size", 120)
    res = look_ahead(prices, pm, avg_window_size)
    print(json.dumps(res, indent=4))

    mqtt_config = MqttConfig.from_dict(config["mqtt"])
    if mqtt_config.publish:
        client = mqtt.Client(mqtt_config.client_id)
        if mqtt_config.username:
            client.username_pw_set(
                username=mqtt_config.username, password=mqtt_config.password
            )
        client.connect(host=mqtt_config.host, port=mqtt_config.port)
        client.loop_start()
        client.publish(mqtt_config.topic, json.dumps(res), retain=mqtt_config.retain)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
