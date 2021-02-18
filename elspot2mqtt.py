"""Elspot to MQTT bridge"""

import argparse
import json
import logging
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Optional

import paho.mqtt.client as mqtt
from dataclasses_json import dataclass_json
from nordpool import elspot

AREA = "SE3"
CURRENCY = "SEK"

DEFAULT_CONF_FILENAME = "elspot2mqtt.json"
DEFAULT_CACHE_FILENAME = "nordpool.json"
DEFAULT_CACHE_TTL = 3600

TIMEZONE = None

elspot.Prices.API_URL = "https://www.nordpoolgroup.com/api/marketdata/page/%i"
API_PAGE_WEEKHOURLY = 29

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


def get_prices_days(days=5) -> {}:
    spot = elspot.Prices(currency=CURRENCY)
    prices = {}

    for delta in range(-days, 2):
        end_date = date.today() + timedelta(days=delta)
        data = spot.hourly(areas=[AREA], end_date=end_date)
        for entry in data["areas"][AREA]["values"]:
            cost = entry["value"]
            if math.isinf(cost):
                continue
            ts = entry["start"].astimezone(tz=TIMEZONE).isoformat()
            prices[ts] = cost / 1000
    return prices


def get_prices() -> {}:
    spot = elspot.Prices(currency=CURRENCY)
    prices = {}
    end_date = date.today() + timedelta(days=1)
    data = spot.fetch(data_type=API_PAGE_WEEKHOURLY, areas=[AREA], end_date=end_date)
    for entry in data["areas"][AREA]["values"]:
        cost = entry["value"]
        if math.isinf(cost):
            continue
        ts = entry["start"].astimezone(tz=TIMEZONE).isoformat()
        prices[ts] = cost / 1000
    return prices


def get_prices_cached(cache_filename: str, cache_ttl: int):
    try:
        statinfo = os.stat(cache_filename)
        mtime = statinfo.st_mtime
        with open(cache_filename, "rt") as data_file:
            prices = json.load(data_file)
    except FileNotFoundError:
        prices = None
        mtime = 0

    if prices is None or time.time() - mtime > cache_ttl:
        prices = get_prices_days()
        with open(cache_filename, "wt") as data_file:
            json.dump(prices, data_file)

    return prices


def percentage_to_level(p: float) -> str:
    if p > 20:
        return "VERY_EXPENSIVE"
    elif p > 10:
        return "EXPENSIVE"
    else:
        return "NORMAL"


def look_ahead(prices, pm: PriceMarkup):
    present = datetime.now().astimezone(tz=TIMEZONE) - timedelta(hours=1)
    now_offset = 0
    res = {}

    dt_prices = {datetime.fromisoformat(t): v for t, v in prices.items()}
    dt_total_prices = {
        datetime.fromisoformat(t): pm.total_cost(v) for t, v in prices.items()
    }
    costs = []

    for dt, cost in dt_total_prices.items():
        costs.append(cost)

        if len(costs) >= 120:
            avg120 = mean(costs[len(costs) - 120 : len(costs)])
            relpt = round((cost / avg120 - 1) * 100, 0)
            level = percentage_to_level(relpt)
        else:
            avg120 = 0
            relpt = 0
            level = None

        # publish data in the future
        if dt >= present:
            res[f"now+{now_offset}"] = {
                "timestamp": dt.isoformat(),
                "cost": round(cost, 2),
                "avg120": round(avg120, 2),
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

    # prices = get_prices()
    # prices = get_prices_days()
    prices = get_prices_cached(
        cache_filename=config.get("cache_file", DEFAULT_CACHE_FILENAME),
        cache_ttl=config.get("cache_ttl", DEFAULT_CACHE_TTL),
    )

    pm = PriceMarkup(
        grid=config["markup"]["grid"],
        cert=config["markup"]["cert"],
        tax=config["markup"]["tax"],
        vat_percentage=config["markup"]["vat_percentage"],
    )

    res = look_ahead(prices, pm)
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
