import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import List

from . import DEFAULT_ROUND
from .util import find_minimas


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


def percentage_to_level(p: float, levels: List) -> str:
    res = "NORMAL"
    for rule in levels:
        if "gte" in rule and p >= rule["gte"]:
            return rule["level"]
        elif "lte" in rule and p <= rule["lte"]:
            res = rule["level"]
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