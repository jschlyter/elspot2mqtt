import argparse
import asyncio
import json
import logging
import time

import aiomqtt
from pydantic import BaseModel, Field

from .charge import ChargeWindow, find_charge_window
from .costs import ExtraCosts, ResultAhead, ResultBehind, look_ahead, look_behind
from .prices import PricesDatabase

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
DEFAULT_AVG_WINDOW_SIZE = 120
DEFAULT_MINIMA_LOOKAHEAD = 4

logger = logging.getLogger(__name__)


class MqttConfig(BaseModel):
    host: str = Field(default="127.0.0.1")
    port: int = Field(default=1883)
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    topic: str = Field(default="elspot2mqtt")
    retain: bool = False
    publish: bool = True


class Response(BaseModel):
    ahead: list[ResultAhead]
    behind: list[ResultBehind]
    charge_window: ChargeWindow | None


async def mqtt_publish(config: MqttConfig, payload: str) -> None:
    """Publish payload via MQTT"""

    async with aiomqtt.Client(
        hostname=config.host,
        port=config.port,
        identifier=config.client_id,
        username=config.username,
        password=config.password,
    ) as client:
        await client.publish(
            topic=config.topic,
            payload=payload,
            retain=config.retain,
        )


async def async_main():
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

    with open(args.conf_filename) as config_file:
        config = json.load(config_file)

    db = PricesDatabase(filename=config["database"], area=config["area"])

    prices = await db.get_prices()
    levels = config.get("levels", DEFAULT_LEVELS)

    pm = ExtraCosts.model_validate(config["costs"])

    avg_window_size = config.get("avg_window_size", DEFAULT_AVG_WINDOW_SIZE)
    minima_lookahead = config.get("minima_lookahead", DEFAULT_MINIMA_LOOKAHEAD)

    look_ahead_result = look_ahead(
        prices=prices,
        pm=pm,
        levels=levels,
        avg_window_size=avg_window_size,
        minima_lookahead=minima_lookahead,
    )

    look_behind_result = look_behind(prices=prices, pm=pm)

    charge_window: ChargeWindow | None = None

    if charge_config := config.get("charge_window"):
        t1 = charge_config.get("start", DEFAULT_CHARGE_WINDOW_START)
        t2 = charge_config.get("end", DEFAULT_CHARGE_WINDOW_END)
        threshold = charge_config.get("threshold", DEFAULT_CHARGE_THRESHOLD)

        t = time.time()
        prices_next_24h = dict(
            filter(lambda elem: elem[0] > t and elem[0] < (t + 86400), prices.items())
        )
        try:
            charge_window = find_charge_window(
                prices=prices_next_24h, pm=pm, window=(t1, t2), threshold=threshold
            )
        except ValueError as exc:
            logger.warning("No charge window possible")
            logger.debug(str(exc))

    response = Response(
        ahead=look_ahead_result,
        behind=look_behind_result,
        charge_window=charge_window,
    )

    if args.stdout:
        print(response.model_dump_json(indent=4))
    else:
        mqtt_config = MqttConfig.model_validate(config.get("mqtt"))
        if mqtt_config.publish:
            await mqtt_publish(config=mqtt_config, payload=response.model_dump_json())


def main() -> None:
    """Main function"""
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
