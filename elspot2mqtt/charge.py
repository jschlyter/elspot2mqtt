from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple

import pandas as pd
from dataclasses_json import dataclass_json

from . import DEFAULT_ROUND
from .costs import ExtraCosts


@dataclass_json
@dataclass(frozen=True)
class ChargeWindow:
    start: str
    end: str
    max_price: float
    min_price: float
    avg_price: float


def find_charge_window(
    prices: Dict[int, float],
    pm: ExtraCosts,
    window: Tuple[str, str],
    threshold: float,
) -> ChargeWindow:
    total_prices = {t: pm.total_cost(v) for t, v in prices.items()}

    pds = pd.Series(total_prices, index=total_prices.keys())
    pdf = pd.DataFrame(pds, columns=["cost"])
    pdf["abs_min"] = pdf.min().cost
    pdf["datetime"] = (
        pd.to_datetime(pdf.index, unit="s")
        .tz_localize("UTC")
        .tz_convert("Europe/Stockholm")
    )

    pdf["charge"] = pdf["datetime"].isin(
        pdf.set_index("datetime").between_time(*window).index
    )
    pdf.loc[pdf.cost <= (pdf.abs_min + threshold), "charge"] = True

    a = pdf.set_index("datetime").between_time(datetime.now().time(), window[0])[
        "charge"
    ]
    start = a.ne(a.shift()).cumsum().drop_duplicates(keep="first").idxmax()

    b = pdf.set_index("datetime").between_time(
        window[0],
        (datetime.now() - timedelta(hours=1)).time(),
        inclusive="left",
    )["charge"]
    end = b.ne(b.shift()).cumsum().drop_duplicates(keep="last").idxmin()

    res = pdf.set_index("datetime").between_time(start.time(), end.time())

    return ChargeWindow(
        start=f"{start.hour:02}:00",
        end=f"{end.hour:02}:00",
        min_price=round(res.min().cost, DEFAULT_ROUND),
        max_price=round(res.max().cost, DEFAULT_ROUND),
        avg_price=round(res.mean().cost, DEFAULT_ROUND),
    )
