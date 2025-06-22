import math
from datetime import datetime, timedelta
from typing import List, Tuple, Union, Any, Dict
import threading
from dateutil.relativedelta import relativedelta

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.dates import DateFormatter
from mplfinance.original_flavor import candlestick_ohlc
import pandas as pd
import requests
import io
import csv
import websocket
import json
from requests import HTTPError

matplotlib.use("Agg")  # headless plotting


class DHANClient:
    BASE_URL = "https://api.dhan.co/v2/"

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.session = requests.Session()
        self.session.headers.update({"access-token": access_token})

    def get_full_history(self, security_id: Union[str, int]) -> pd.DataFrame:
        """
        Fetches all available daily OHLC bars from the earliest possible date.
        (You may replace the hard‐coded '1900-01-01' with a real listing date
         from a metadata endpoint if available.)
        """
        early = "1900-01-01"
        return self.get_ticker_data(security_id, early)

    def get_symbols(self) -> Union[List[Any], Dict[str, Union[int, Any]]]:
        """Return union of available stock symbols."""
        try:
            resp = self.session.get(f"{self.BASE_URL}instrument/NSE_EQ/")
            resp.raise_for_status()
            text = resp.text

            # 2a. parse as CSV into a list of dictionaries
            reader = csv.DictReader(io.StringIO(text))
            instrument_list = [{'symbol': row['SYMBOL_NAME'], 'security_id': row['SECURITY_ID']} for row in reader if
                               any(row.values())]  # drop empty rows
            return {'status_code': resp.status_code, 'instrument_list': instrument_list}
        except HTTPError:
            return {'status_code': resp.status_code, 'error_description': resp.text}

    def get_ticker_data(self, security_id: Union[str, int], from_date: str) -> pd.DataFrame:
        """
        Fetches OHLC data from `from_date` until today.
        """
        resp = self.session.post(
            f"{self.BASE_URL}charts/historical",
            json={
                "securityId": str(security_id),
                "exchangeSegment": "NSE_EQ",
                "instrument": "EQUITY",
                "expiryCode": 0,
                "oi": False,
                "fromDate": from_date,
                "toDate": datetime.today().strftime("%Y-%m-%d"),
            }
        )
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data)
        # df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        # df.set_index("timestamp", inplace=True)
        df["timestamp"] = (
            pd.to_datetime(df["timestamp"], unit="s", utc=True)
            .dt.tz_convert("Asia/Kolkata")
            .dt.tz_localize(None)
        )

        df.set_index("timestamp", inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    def get_intraday_ohlc(
        self,
        security_id: Union[str, int],
        start_date: str,
        end_date: str,
        interval: int = 15,
    ) -> pd.DataFrame:
        """
        Returns a DataFrame of today's intraday OHLCV bars for the given
        security_id, at the specified interval in minutes (default=15).
        """

        resp = self.session.post(
            f"{self.BASE_URL}charts/intraday",
            json={
                "securityId": str(security_id),
                "exchangeSegment": "NSE_EQ",
                "instrument": "EQUITY",
                "oi": False,
                "fromDate": start_date,
                "toDate": end_date,
                "interval": str(interval),
            },
        )

        # print(resp.json())
        resp.raise_for_status()
        data = resp.json()

        df = pd.DataFrame(data)
        # convert UNIX seconds → IST local time, drop tzinfo
        df["timestamp"] = (
            pd.to_datetime(df["timestamp"], unit="s", utc=True)
            .dt.tz_convert("Asia/Kolkata")
            .dt.tz_localize(None)
        )
        df.set_index("timestamp", inplace=True)

        return df[["open", "high", "low", "close", "volume"]]


class TrendLine:
    """
    True-angle trend-line in 'price per bar' space,
    where bar 0 is the very first row of the full history,
    and the line always extends through the last bar.
    """

    def __init__(
        self,
        full_df: pd.DataFrame,
        start_date: Union[str, pd.Timestamp],
        angle_deg: float,
        price_to_bar_ratio: float,
    ) -> None:
        # 1) anchor on the full-history index
        df = full_df.copy()
        df.index = pd.to_datetime(df.index)

        # 2) figure out which bar the user wants
        ts = pd.to_datetime(start_date)
        self.start_bar = df.index.get_indexer([ts], method="nearest")[0]
        self.start_ts = df.index[self.start_bar]
        self.start_price = float(df["low"].iat[self.start_bar])

        # 3) now force the end bar to be the very last bar
        self.end_bar = len(df) - 1

        # 4) compute slope = tan(angle) * price_to_bar_ratio
        self.angle_deg = angle_deg
        self.slope = math.tan(math.radians(angle_deg)) * price_to_bar_ratio

        # 5) slice the dates from start through end
        self.dates = df.index[self.start_bar : self.end_bar + 1]
        if self.dates.empty:
            raise ValueError(f"No data on or after {start_date!r}")

    def get_points(self) -> Tuple[List[float], List[float]]:
        """
        Returns:
          xs: list of matplotlib date-numbers from start to last bar
          ys: list of trend prices = start_price + slope * bar_offset
        """
        # number of bars from start through end
        length = self.end_bar - self.start_bar + 1

        # 1) build your offsets 0,1,2,...,length-1
        offsets = list(range(length))

        # 2) compute each price exactly as Pine does
        ys = [self.start_price + off * self.slope
               for off in offsets]

        # 3) convert the timestamp slice into date-numbers
        xs = mdates.date2num(self.dates.to_pydatetime())
        return xs, ys

