import argparse
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

import paho.mqtt.client as mqtt
from dataclasses_json import dataclass_json

from .charge import find_charge_window
from .costs import ExtraCosts, look_ahead, look_behind
from .prices import PricesDatabase

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

DEFAULT_CHARGE_WINDOW_START = "00:00"
DEFAULT_CHARGE_WINDOW_END = "05:59"
DEFAULT_CHARGE_THRESHOLD = 0


logger = logging.getLogger(__name__)


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

    db = PricesDatabase(filename=config["database"], area=config["area"])

    prices = db.get_prices()
    levels = config.get("levels", DEFAULT_LEVELS)

    pm = ExtraCosts(
        markup=config["costs"]["markup"],
        grid=config["costs"]["grid"],
        energy_tax=config["costs"]["energy_tax"],
        vat_percentage=config["costs"]["vat_percentage"],
        export_grid=config["costs"].get("export_grid", 0),
        export_tax=config["costs"].get("export_tax", 0),
    )

    avg_window_size = config.get("avg_window_size", 120)
    minima_lookahead = config.get("minima_lookahead", 4)
    look_ahead_result = look_ahead(
        prices=prices,
        pm=pm,
        levels=levels,
        avg_window_size=avg_window_size,
        minima_lookahead=minima_lookahead,
    )
    look_behind_result = look_behind(prices=prices, pm=pm)

    mqtt_payload = {"ahead": look_ahead_result, "behind": look_behind_result}

    if charge_config := config.get("charge_window"):
        t1 = charge_config.get("start", DEFAULT_CHARGE_WINDOW_START)
        t2 = charge_config.get("end", DEFAULT_CHARGE_WINDOW_END)
        threshold = charge_config.get("threshold", DEFAULT_CHARGE_THRESHOLD)

        t = time.time()
        prices_next_24h = dict(
            filter(lambda elem: elem[0] > t and elem[0] < (t + 86400), prices.items())
        )
        try:
            res = find_charge_window(
                prices=prices_next_24h, pm=pm, window=(t1, t2), threshold=threshold
            )
            mqtt_payload["charge_window"] = res.to_dict()
        except ValueError:
            logger.warning("No charge window possible")
            mqtt_payload["charge_window"] = None
            pass

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
