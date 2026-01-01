import argparse
import asyncio
import datetime
import json
import logging
import math
import sqlite3

import aiohttp
from pynordpool import Currency, NordPoolClient

from .util import date2timestamp

CURRENCY = Currency.SEK
MAX_WINDOW = 5

DEFAULT_CONF_FILENAME = "elspot2mqtt.json"


logger = logging.getLogger(__name__)


type PriceDict = dict[int, float]


class PricesDatabase:
    def __init__(self, filename: str, area: str):
        self.conn = sqlite3.connect(filename)
        self.table = "nordpool"
        self.area = area
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS {self.table} (timestamp INTEGER PRIMARY KEY, value REAL);")
        self.logger = logger.getChild(self.__class__.__name__)

    def get(self, d: datetime.date) -> PriceDict | None:
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

    def store(self, prices: PriceDict) -> None:
        cur = self.conn.cursor()
        for t, v in prices.items():
            cur.execute(f"REPLACE INTO {self.table} (timestamp,value) VALUES(?,?)", (t, v))
        self.conn.commit()

    def prune(self, days_retention: int = 31) -> None:
        d = datetime.date.today() - datetime.timedelta(days=days_retention)
        t = date2timestamp(d)
        cur = self.conn.cursor()
        cur.execute(f"DELETE FROM {self.table} WHERE timestamp<?", (t,))
        self.conn.commit()

    async def update(self, window: int = MAX_WINDOW) -> None:
        for offset in range(-window, 2):
            end_date = datetime.date.today() + datetime.timedelta(days=offset)
            if offset == 1 and datetime.datetime.now().hour < 13:
                self.logger.debug("Data for %s skipped until 13.00", end_date)
                continue
            p = self.get(end_date)
            if p is None:
                self.logger.debug("Fetching data for %s from Nordpool", end_date)
                p = await get_prices_nordpool(end_date, self.area)
                self.store(p)
            else:
                self.logger.debug("Using cached data for %s", end_date)

    async def get_prices(self, window: int = MAX_WINDOW) -> PriceDict:
        self.prune(window)
        await self.update(window)
        prices = {}
        for offset in range(-window, 2):
            end_date = datetime.date.today() + datetime.timedelta(days=offset)
            self.logger.debug("Get prices for %s, offset=%d", end_date, offset)
            p = self.get(end_date)
            if p is not None:
                prices.update(p)
        return prices


async def get_prices_nordpool(dt: datetime.date, area: str) -> PriceDict:
    prices: PriceDict = {}

    period_start_date = datetime.datetime.combine(dt, datetime.time(hour=0, minute=0))

    async with aiohttp.ClientSession() as session:
        client = NordPoolClient(session)
        delivery_period_data = await client.async_get_delivery_period(period_start_date, CURRENCY, [area])

    for entry in delivery_period_data.entries:
        cost = entry.entry[area]
        if math.isinf(cost):
            continue
        t = int(entry.start.timestamp())
        prices[t] = cost / 1000
    return prices


def main():
    """Main function"""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--conf",
        dest="conf_filename",
        default=DEFAULT_CONF_FILENAME,
        metavar="filename",
        help="configuration file",
        required=False,
    )
    parser.add_argument("--debug", dest="debug", action="store_true", help="Print debug information")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    with open(args.conf_filename) as config_file:
        config = json.load(config_file)

    db = PricesDatabase(filename=config["database"], area=config["area"])

    db.prune(MAX_WINDOW)
    asyncio.run(db.update(MAX_WINDOW))


if __name__ == "__main__":
    main()
