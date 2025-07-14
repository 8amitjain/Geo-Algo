import math
from datetime import datetime, timedelta
from typing import List, Tuple, Union, Any, Dict
import threading
from dateutil.relativedelta import relativedelta
from pandas.tseries.offsets import BDay

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
import uuid

matplotlib.use("Agg")  # headless plotting


class DHANClient:
    BASE_URL = "https://api.dhan.co/v2/"

    def __init__(self, access_token: str, dhan_client_id=None):
        self.access_token = access_token
        # self.dhan_client_id = dhan_client_id
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
            # https://images.dhan.co/api-data/api-scrip-master.csv # TODO get short code name from here
            # resp = self.session.get(f"{self.BASE_URL}instrument/NSE_EQ/")
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

    def place_order(
            self,
            dhan_client_id: str,
            security_id: str,
            transaction_type: str,  # "BUY" or "SELL"
            quantity: int,
            price: float = None,
            order_type: str = "MARKET",  # or "LIMIT"
            product_type: str = "CNC",  # or "CNC" or "MARGIN" or "INTRADAY"
            exchange_segment: str = "NSE_EQ",  # or "BSE"
            validity: str = "DAY"
    ) -> dict:
        url = f"{self.BASE_URL}/orders"
        payload = {
            "dhanClientId": dhan_client_id,
            "transactionType": transaction_type.upper(),
            "exchangeSegment": exchange_segment,
            "productType": product_type,
            "orderType": order_type,
            "validity": validity,
            "securityId": security_id,
            "quantity": quantity,
            "price": float(price),
            "triggerPrice": float(price),
            "afterMarketOrder": False,
            # "amoTime": "PRE_OPEN"
            # "amoTime": "",
            # "boProfitValue": "",
            # "boStopLossValue": ""
        }
        print(payload)
        response = self.session.post(url, json=payload)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Order placement failed: {response.status_code} – {response.text}")
            raise Exception(f"Order placement failed: {response.status_code} – {response.text}")

    def sell_stock(
            self,
            risk_per_unit: float,
            cross_price: float,
            security_id: str,
            symbol: str,
            dhan_access_token: str,
            dhan_client_id: str,
            max_risk: float = 500.0,
    ) -> None:
        """
        Places a SELL order using the Dhan API.

        Args:
            risk_per_unit (float): Difference between sell price and SL.
            cross_price (float): Market price to sell at.
            security_id (str): Dhan security ID.
            symbol (str): Human-readable symbol (for logs/emails).
            dhan_access_token (str): Auth token for Dhan client.
            dhan_client_id (str): Dhan client ID.
            max_risk (float): Total capital risked (default: ₹500).
        """
        try:
            if risk_per_unit <= 0:
                print(f"[❌] Invalid risk_per_unit={risk_per_unit}. Cannot sell {symbol}.")
                return

            qty = math.floor(max_risk / risk_per_unit)
            if qty == 0:
                print(f"[❌] Calculated quantity is 0 for {symbol}; skipping.")
                return

            client = DHANClient(access_token=dhan_access_token)
            client.place_order(
                dhan_client_id=dhan_client_id,
                security_id=security_id,
                transaction_type="SELL",
                quantity=qty,
                price=cross_price,
                order_type="MARKET",  # Can change to "LIMIT"
                product_type="CNC",  # Or INTRADAY/MARGIN if needed
                exchange_segment="NSE_EQ",
                validity="DAY"
            )

            print(f"[✅] SELL order placed for {qty} shares of {symbol} at approx ₹{cross_price:.2f}")

        except Exception as e:
            print(f"[⚠️] Failed to place SELL order for {symbol}: {e}")


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

        # 2) find the nearest bar for the user’s start_date
        ts = pd.to_datetime(start_date)
        self.start_bar = df.index.get_indexer([ts], method="nearest")[0]
        self.start_ts = df.index[self.start_bar]
        self.start_price = float(df["low"].iat[self.start_bar])

        # 3) last historical bar
        self.end_bar = len(df) - 1

        # 4) slope in price‐per‐bar
        self.angle_deg = angle_deg
        self.slope = math.tan(math.radians(angle_deg)) * float(price_to_bar_ratio)

        # 5) slice dates from start → end
        hist_dates = df.index[self.start_bar: self.end_bar + 1]
        if hist_dates.empty:
            raise ValueError(f"No data on or after {start_date!r}")

        # 6) extend by 7 business days
        #    start = one business day after last historical date
        future_start = hist_dates[-1] + BDay(1)
        future_dates = pd.bdate_range(start=future_start, periods=7)

        # 7) combine historical + future
        #    this will be used by get_points()
        self.dates = hist_dates.append(future_dates)

    def get_points(self) -> Tuple[List[float], List[float]]:
        """
        Returns:
          xs: list of matplotlib date‐numbers (for all dates)
          ys: list of trend prices = start_price + slope * bar_offset
        """
        # 1) convert all dates → matplotlib float days
        xs = mdates.date2num(self.dates.to_pydatetime())

        # 2) bar offsets 0,1,2,… up through history + 7 days
        offsets = list(range(len(xs)))

        # 3) compute each price
        ys = [self.start_price + off * self.slope for off in offsets]

        return xs, ys

