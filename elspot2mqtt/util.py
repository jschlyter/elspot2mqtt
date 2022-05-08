import time
from datetime import date, datetime
from typing import Dict


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


def date2timestamp(d: date) -> int:
    """Get unix timestamp of midnight of date"""
    dt = datetime(year=d.year, month=d.month, day=d.day, tzinfo=None).astimezone(
        tz=None
    )
    return int(time.mktime(dt.timetuple()))
