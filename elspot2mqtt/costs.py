import logging
import statistics
import time
from datetime import datetime, timedelta

from pydantic import AliasChoices, BaseModel, Field

from . import DEFAULT_ROUND
from .prices import PriceDict
from .util import find_minimas_lookahead

logger = logging.getLogger(__name__)

TIMEZONE = None
DEFAULT_OFFSET = 15 * 60


class Result(BaseModel):
    timestamp: str
    market_price: float
    spot_price: float
    grid_price: float
    total_price: float
    export_price: float


class ResultBehind(Result):
    pass


class ResultAhead(Result):
    avg: float
    relpt: float
    level: str | None
    level_index: int | None
    minima: bool


class ExtraCosts(BaseModel):
    import_markup: float = Field(
        validation_alias=AliasChoices("import_markup", "markup")
    )
    import_grid: float = Field(validation_alias=AliasChoices("import_grid", "grid"))
    import_tax: float = Field(validation_alias=AliasChoices("import_tax", "energy_tax"))

    export_markup: float = Field(default=0)
    export_grid: float = Field(default=0)
    export_tax: float = Field(default=0)

    vat_percentage: float

    def get_total(self, c: float) -> float:
        """Total price for import"""
        return self.get_spot(c) + self.get_grid(c)

    def get_spot(self, c: float) -> float:
        """Total energy price for import"""
        cost = c + self.import_markup
        vat = cost * self.vat_percentage / 100
        return cost + vat

    def get_grid(self, c: float) -> float:
        """Total grid price for import"""
        cost = self.import_grid + self.import_tax
        vat = cost * self.vat_percentage / 100
        return cost + vat

    def get_export(self, c: float) -> float:
        """Total price for export"""
        return c + self.export_grid + self.export_tax + self.export_markup


def average_bucket(prices: dict[int, float], size: int) -> dict[int, float]:
    p = [(k, v) for k, v in prices.items()]
    res = {}
    for i in range(0, len(p), size):
        t = p[i][0]
        res[t] = statistics.fmean([x[1] for x in p[i : i + size]])
    return res


def to_level(p: float, c: float, levels: list[dict[str, str | int]]) -> tuple[str, int]:
    res = "NORMAL", 0
    for rule in levels:
        if "floor" in rule and c < rule["floor"]:
            return rule["level"], rule.get("index")
        if "ceiling" in rule and c >= rule["ceiling"]:
            return rule["level"], rule.get("index")
        if "gte" in rule and p >= rule["gte"]:
            return rule["level"], rule.get("index")
        elif "lte" in rule and p <= rule["lte"]:
            res = rule["level"], rule.get("index")
    return res


def look_ahead(
    prices: PriceDict,
    pm: ExtraCosts,
    levels: list[dict[str, str | int]],
    avg_window_size: int = 120,
    minima_lookahead: int = 4,
    offset: int = DEFAULT_OFFSET,
) -> list[ResultAhead]:
    present = time.time() - offset
    res = []

    spot_prices = {t: pm.get_spot(v) for t, v in prices.items()}
    grid_prices = {t: pm.get_grid(v) for t, v in prices.items()}
    total_prices = {t: pm.get_total(v) for t, v in prices.items()}
    export_prices = {t: pm.get_export(v) for t, v in prices.items()}

    spot_costs = []

    minimas = find_minimas_lookahead(
        dataset=spot_prices, minima_lookahead=minima_lookahead
    )

    for t, cost in spot_prices.items():
        dt = datetime.fromtimestamp(t).astimezone(tz=TIMEZONE)

        spot_costs.append(cost)

        if t < present:
            continue

        if len(spot_costs) >= avg_window_size:
            spot_avg = statistics.fmean(
                spot_costs[len(spot_costs) - avg_window_size : len(spot_costs)]
            )
            relpt = round((cost / spot_avg - 1) * 100, 1)
            level, level_index = to_level(relpt, cost, levels)
            logger.debug(f"{cost=} {level=} {level_index=}")
        else:
            spot_avg = 0
            relpt = 0
            level = None
            level_index = None

        r = ResultAhead(
            timestamp=dt.isoformat(),
            market_price=round(prices[t], DEFAULT_ROUND),
            spot_price=round(spot_prices[t], DEFAULT_ROUND),
            grid_price=round(grid_prices[t], DEFAULT_ROUND),
            total_price=round(total_prices[t], DEFAULT_ROUND),
            export_price=round(export_prices[t], DEFAULT_ROUND),
            avg=round(spot_avg, DEFAULT_ROUND),
            relpt=relpt,
            level=level,
            level_index=level_index,
            minima=minimas.get(t, False),
        )

        res.append(r)

    return res


def look_behind(
    prices: PriceDict,
    pm: ExtraCosts,
    offset: int = DEFAULT_OFFSET,
) -> list[ResultBehind]:
    res = []

    spot_prices = {t: pm.get_spot(v) for t, v in prices.items()}
    grid_prices = {t: pm.get_grid(v) for t, v in prices.items()}
    total_prices = {t: pm.get_total(v) for t, v in prices.items()}
    export_prices = {t: pm.get_export(v) for t, v in prices.items()}

    now = datetime.now().astimezone(tz=TIMEZONE) - timedelta(seconds=offset)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    for t in total_prices:
        dt = datetime.fromtimestamp(t).astimezone(tz=TIMEZONE)
        if dt < start or dt >= now:
            continue

        r = ResultBehind(
            timestamp=dt.isoformat(),
            market_price=round(prices[t], DEFAULT_ROUND),
            spot_price=round(spot_prices[t], DEFAULT_ROUND),
            grid_price=round(grid_prices[t], DEFAULT_ROUND),
            total_price=round(total_prices[t], DEFAULT_ROUND),
            export_price=round(export_prices[t], DEFAULT_ROUND),
        )

        res.append(r)

    return res
