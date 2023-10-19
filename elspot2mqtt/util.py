import time
from datetime import date, datetime
from typing import Dict

import pandas as pd


def find_minimas(dataset: Dict[int, float]) -> Dict[int, bool]:
    """Find local minimas in dataset dictionary"""
    res = {}
    pairs = [(t, p) for t, p in dataset.items()]
    count = len(pairs)
    for i in range(0, count):
        (t, x) = pairs[i]
        if i == 0:
            res[t] = False
            next
        elif i == count - 1:
            res[t] = False
            next
        else:
            (_, a) = pairs[i - 1]
            (_, b) = pairs[i + 1]
            res[t] = a > x < b
    return res


def find_minimas_lookahead(
    dataset: Dict[int, float], minima_lookahead: int
) -> Dict[int, bool]:
    """Find local minimas in dataset dictionary (with pandas)"""
    pds = pd.Series(dataset, dtype=float, index=dataset.keys())
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
