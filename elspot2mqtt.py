"""Elspot to MQTT bridge"""

import argparse
import json
import logging
import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt
from dataclasses_json import dataclass_json
from nordpool import elspot

CURRENCY = "SEK"
MAX_WINDOW = 5
DEFAULT_ROUND = 5

DEFAULT_CONF_FILENAME = "elspot2mqtt.json"
DEFAULT_LEVELS = [
    {"gte": 10, "level": "VERY_EXPENSIVE"},
    {"gte": 5, "level": "EXPENSIVE"},
    {"lte": -5, "level": "CHEAP"},
    {"lte": -10, "level": "VERY_CHEAP"},
]

elspot.Prices.API_URL = "https://www.nordpoolgroup.com/api/marketdata/page/%i"

logger = logging.getLogger(__name__)


@dataclass
class ExtraCosts:
    markup: float
    grid: float
    energy_tax: float
    vat_percentage: float

    def total_cost(self, c: float) -> float:
        base_cost = self.grid + self.energy_tax
        c = c + self.markup
        vat = (c + base_cost) * self.vat_percentage / 100
        return c + vat + base_cost

    def spot_cost(self, c: float) -> float:
        c = c + self.markup
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


def date2timestamp(d: date) -> int:
    """Get unix timestamp of midnight of date"""
    dt = datetime(year=d.year, month=d.month, day=d.day, tzinfo=None).astimezone(
        tz=None
    )
    return int(time.mktime(dt.timetuple()))


class PricesDatabase(object):
    def __init__(self, filename: str):
        self.conn = sqlite3.connect(filename)
        self.table = "nordpool"
        self.conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.table} (timestamp INTEGER PRIMARY KEY, value REAL);"
        )

    def get(self, d: date):
        t1 = date2timestamp(d)
        t2 = t1 + 86400
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT timestamp,value FROM {self.table} WHERE timestamp>=? and timestamp<?",
            (t1, t2),
        )
        rows = cur.fetchall()
        if len(rows) < 23:
            return None
        return {r[0]: r[1] for r in rows}

    def store(self, prices):
        cur = self.conn.cursor()
        for t, v in prices.items():
            cur.execute(
                f"REPLACE INTO {self.table} (timestamp,value) VALUES(?,?)", (t, v)
            )
        self.conn.commit()

    def prune(self, days_retention=7):
        d = date.today() - timedelta(days=days_retention)
        t = date2timestamp(d)
        cur = self.conn.cursor()
        cur.execute(f"DELETE FROM {self.table} WHERE timestamp<?", (t,))
        self.conn.commit()


def get_prices_nordpool(end_date: datetime, area: str, currency=CURRENCY) -> {}:
    spot = elspot.Prices(currency=currency)
    prices = {}
    data = spot.hourly(areas=[area], end_date=end_date)
    for entry in data["areas"][area]["values"]:
        cost = entry["value"]
        if math.isinf(cost):
            continue
        dt = entry["start"].astimezone(tz=None)
        t = int(time.mktime(dt.timetuple()))
        prices[t] = cost / 1000
    return prices


def percentage_to_level(p: float, levels: List) -> str:
    res = "NORMAL"
    for rule in levels:
        if "gte" in rule and p >= rule["gte"]:
            return rule["level"]
        elif "lte" in rule and p <= rule["lte"]:
            res = rule["level"]
    return res


def find_minimas(dataset: Dict[int, float]) -> Dict[int, bool]:
    """Find local minimas in dataset dictionary"""
    res = {}
    pairs = [(t, p) for t, p in dataset.items()]
    l = len(pairs)
    for i in range(0, l):
        (t, x) = pairs[i]
        if i == 0:
            res[t] = False
            next
        elif i == l - 1:
            res[t] = False
            next
        else:
            (_, a) = pairs[i - 1]
            (_, b) = pairs[i + 1]
            res[t] = a > x < b
    return res


def look_ahead(prices, pm: ExtraCosts, levels: List, avg_window_size: int = 120):
    present = time.time() - 3600
    res = []

    spot_prices = {t: pm.spot_cost(v) for t, v in prices.items()}
    total_prices = {t: pm.total_cost(v) for t, v in prices.items()}
    costs = []

    minimas = find_minimas(total_prices)

    for t, cost in total_prices.items():
        dt = datetime.fromtimestamp(t).astimezone(tz=None)

        costs.append(cost)

        if t < present:
            continue

        if len(costs) >= avg_window_size:
            avg = mean(costs[len(costs) - avg_window_size : len(costs)])
            relpt = round((cost / avg - 1) * 100, 1)
            level = percentage_to_level(relpt, levels)
        else:
            avg = 0
            relpt = 0
            level = None

        r = {
            "timestamp": dt.isoformat(),
            "market_price": round(prices[t], DEFAULT_ROUND),
            "spot_price": round(spot_prices[t], DEFAULT_ROUND),
            "total_price": round(total_prices[t], DEFAULT_ROUND),
            f"avg{avg_window_size}": round(avg, DEFAULT_ROUND),
            "relpt": relpt,
            "level": level,
            "minima": minimas.get(t, False),
        }

        res.append(r)

    return res


def look_behind(prices, pm: ExtraCosts):
    res = []

    spot_prices = {t: pm.spot_cost(v) for t, v in prices.items()}
    total_prices = {t: pm.total_cost(v) for t, v in prices.items()}

    now = datetime.now().astimezone(tz=None) - timedelta(hours=1)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for t, cost in total_prices.items():
        dt = datetime.fromtimestamp(t).astimezone(tz=None)
        if dt < start or dt >= now:
            continue

        res.append(
            {
                "timestamp": dt.isoformat(),
                "market_price": round(prices[t], DEFAULT_ROUND),
                "spot_price": round(spot_prices[t], DEFAULT_ROUND),
                "total_price": round(total_prices[t], DEFAULT_ROUND),
            }
        )

    return res


def get_prices_database(db, area):
    prices = {}
    for offset in range(-MAX_WINDOW, 2):
        end_date = date.today() + timedelta(days=offset)
        if offset == 1 and datetime.now().hour < 13:
            logger.debug("Data for %s skipped until 13.00", end_date)
            continue
        logger.debug("Processing %s, offset=%d", end_date, offset)
        p = db.get(end_date)
        if p is None:
            logger.debug("Fetching data for %s from Nordpool", end_date)
            p = get_prices_nordpool(end_date=end_date, area=area)
            db.store(p)
        else:
            logger.debug("Using cached data for %s", end_date)
        if p is not None:
            prices.update(p)
    return prices


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
        "--stdout", dest="stdout", action="store_true", help="Print result"
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

    db.prune(MAX_WINDOW)
    logger.debug("Pruned prices older than %d days", MAX_WINDOW)

    prices = get_prices_database(db=db, area=config["area"])
    levels = config.get("levels", DEFAULT_LEVELS)

    pm = ExtraCosts(
        markup=config["costs"]["markup"],
        grid=config["costs"]["grid"],
        energy_tax=config["costs"]["energy_tax"],
        vat_percentage=config["costs"]["vat_percentage"],
    )

    avg_window_size = config.get("avg_window_size", 120)
    look_ahead_result = look_ahead(
        prices=prices, pm=pm, levels=levels, avg_window_size=avg_window_size
    )
    look_behind_result = look_behind(prices=prices, pm=pm)

    mqtt_payload = {"ahead": look_ahead_result, "behind": look_behind_result}

    if args.stdout:
        print(json.dumps(mqtt_payload, indent=4))

    mqtt_config = MqttConfig.from_dict(config["mqtt"])
    if mqtt_config.publish:
        client = mqtt.Client(mqtt_config.client_id)
        if mqtt_config.username:
            client.username_pw_set(
                username=mqtt_config.username, password=mqtt_config.password
            )
        client.connect(host=mqtt_config.host, port=mqtt_config.port)
        client.loop_start()
        client.publish(
            mqtt_config.topic, json.dumps(mqtt_payload), retain=mqtt_config.retain
        )
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
