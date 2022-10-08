import time
from datetime import date, datetime
from typing import Dict

import pandas as pd


def find_minimas(dataset: Dict[int, float], minima_lookahead: int) -> Dict[int, bool]:
    """Find local minimas in dataset dictionary"""
    pds = pd.Series(dataset, index=dataset.keys())
    pdf = pd.DataFrame(pds, columns=["cost"])
    pdf["date"] = pd.to_datetime(pdf.index, unit="s")
    pdf["min_cost"] = pdf.cost[
        (pdf.cost.shift(1) > pdf.cost) & (pdf.cost.shift(-1) > pdf.cost)
    ]
    pdf["min_ahead"] = pdf["cost"].rolling(window=minima_lookahead).min()
    pdf["min_ahead"] = pdf["min_ahead"].shift(-minima_lookahead)
    pdf["minima"] = pdf.min_cost <= pdf.min_ahead
    return pdf.to_dict()["minima"]


def date2timestamp(d: date) -> int:
    """Get unix timestamp of midnight of date"""
    dt = datetime(year=d.year, month=d.month, day=d.day, tzinfo=None).astimezone(
        tz=None
    )
    return int(time.mktime(dt.timetuple()))
