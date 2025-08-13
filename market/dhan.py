import math
from datetime import datetime, timedelta, date
from pandas.tseries.offsets import BDay

import matplotlib
import matplotlib.dates as mdates
import pandas as pd
import time
from requests import HTTPError
import csv
import io
import numpy as np
import requests
from typing import List, Dict, Union, Any, Tuple

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

    def get_symbols(self) -> Union[Dict[str, Union[int, Any]], List[Dict[str, str]]]:
        """
        Fetch and return a list of dicts with trading symbol and security ID from Dhan scrip master CSV.
        Only includes NSE equity symbols (excludes futures/options).
        """
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"

        try:
            resp = requests.get(url)
            resp.raise_for_status()
            csv_text = resp.text

            reader = csv.DictReader(io.StringIO(csv_text))

            instrument_list = []

            for row in reader:
                exch = row.get("SEM_EXM_EXCH_ID")
                symbol = row.get("SEM_TRADING_SYMBOL", "").strip()
                security_id = row.get("SEM_SMST_SECURITY_ID", "").strip()
                segment = row.get("SEM_SEGMENT", "").strip()
                instrument_type = row.get("SEM_EXCH_INSTRUMENT_TYPE", "").strip()

                if not (exch == "NSE" and symbol and security_id):
                    continue

                # Exclude futures (common indicators)
                if segment == "D" or "FUT" in symbol.upper() or "FUT" in instrument_type.upper():
                    continue

                instrument_list.append({
                    "symbol": symbol,
                    "security_id": security_id
                })

            return {'status_code': 200, 'instrument_list': instrument_list}

        except requests.exceptions.HTTPError as http_err:
            return {'status_code': 400, 'error_description': str(http_err)}
        except Exception as e:
            return {'status_code': 500, 'error_description': str(e)}

    # def get_symbols(self) -> Union[List[Any], Dict[str, Union[int, Any]]]:
    #     """Return union of available stock symbols."""
    #     try:
    #         # https://images.dhan.co/api-data/api-scrip-master.csv # TODO get short code name from here
    #         # resp = self.session.get(f"{self.BASE_URL}instrument/NSE_EQ/")
    #         resp = self.session.get(f"{self.BASE_URL}instrument/NSE_EQ/")
    #         resp.raise_for_status()
    #         text = resp.text
    #
    #         # 2a. parse as CSV into a list of dictionaries
    #         reader = csv.DictReader(io.StringIO(text))
    #         instrument_list = [{'symbol': row['SYMBOL_NAME'], 'security_id': row['SECURITY_ID']} for row in reader if
    #                            any(row.values())]  # drop empty rows
    #         return {'status_code': resp.status_code, 'instrument_list': instrument_list}
    #     except HTTPError:
    #         return {'status_code': resp.status_code, 'error_description': resp.text}

    def get_ticker_data(
        self,
        security_id: Union[str, int],
        from_date: str,
        max_retries: int = 3,
        retry_delay: int = 10  # seconds
    ) -> pd.DataFrame:
        """
        Fetches OHLC data from `from_date` until today with retry handling.
        Returns a DataFrame or empty DataFrame on failure.
        """
        url = f"{self.BASE_URL}charts/historical"
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date,
            "toDate": datetime.today().strftime("%Y-%m-%d"),
            # "toDate": (datetime.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
        }

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.post(url, json=payload)

                if resp.status_code == 429:
                    print(f"[Attempt {attempt}] Rate limit hit. Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    continue

                resp.raise_for_status()

                try:
                    data = resp.json()
                except Exception as e:
                    print(f"Failed to parse JSON: {e}")
                    print(resp.text)
                    return pd.DataFrame()

                # if isinstance(data, dict) and data.get("errorCode"):
                #     print(f"Dhan API error: {data.get('errorCode')} - {data.get('errorMessage')}")
                #     return pd.DataFrame()

                # if not isinstance(data, list) or not data:
                #     print("Empty or invalid OHLC data received.")
                #     print(f"Full response: {data}")
                #     time.sleep(retry_delay)
                #     continue

                df = pd.DataFrame(data)
                df["timestamp"] = (
                    pd.to_datetime(df["timestamp"], unit="s", utc=True)
                    .dt.tz_convert("Asia/Kolkata")
                    .dt.tz_localize(None)
                )
                df.set_index("timestamp", inplace=True)
                return df[["open", "high", "low", "close", "volume"]]

            except requests.exceptions.RequestException as e:
                print(f"[Attempt {attempt}] Request failed: {e}")
                print(resp.text)
                time.sleep(retry_delay)

        print("All retry attempts failed. Returning empty DataFrame.")
        return pd.DataFrame()

    def get_intraday_ohlc(
            self,
            security_id: Union[str, int],
            start_date: str,
            end_date: str,
            interval: int = 15,
            max_retries: int = 3,
            retry_delay: int = 10,  # seconds
    ) -> pd.DataFrame:
        """
        Returns a DataFrame of intraday OHLCV bars for the given security_id.
        Handles rate limiting (HTTP 429) and known error codes like DH-905.
        """
        url = f"{self.BASE_URL}charts/intraday"
        payload = {
            "securityId": str(security_id),
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "oi": False,
            "fromDate": start_date,
            "toDate": end_date,
            "interval": str(interval),
        }

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.post(url, json=payload)

                if resp.status_code == 429:
                    print(f"[Attempt {attempt}] Rate limit hit. Retrying in {retry_delay} sec...")
                    time.sleep(retry_delay)
                    continue

                data = resp.json()

                if data.get("errorCode") == "DH-905":
                    print("No data available (holiday or non-trading day).")
                    return pd.DataFrame()

                resp.raise_for_status()

                df = pd.DataFrame(data)
                if df.empty:
                    return df

                df["timestamp"] = (
                    pd.to_datetime(df["timestamp"], unit="s", utc=True)
                    .dt.tz_convert("Asia/Kolkata")
                    .dt.tz_localize(None)
                )
                df.set_index("timestamp", inplace=True)
                return df[["open", "high", "low", "close", "volume"]]

            except requests.exceptions.RequestException as e:
                print(f"[Attempt {attempt}] Request failed: {e}")
                time.sleep(retry_delay)

        # All retries failed
        print("Failed to fetch intraday OHLC after retries.")
        return pd.DataFrame()

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
        # self.start_bar = df.index.get_indexer([ts], method="nearest")[0]
        self.start_bar = self._nearest_pos_to_timestamp(df.index, ts)
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

    def _nearest_pos_to_timestamp(self, index, ts) -> int:
        """
        Return the integer row position in `index` nearest to `ts`.
        Works even if the index has duplicates and even if it's not sorted.
        """
        idx = pd.to_datetime(index, errors="coerce")

        # Align timezone between index and ts
        ts = pd.Timestamp(ts)
        if isinstance(idx, pd.DatetimeIndex):
            if idx.tz is not None:
                if ts.tzinfo is None:
                    ts = ts.tz_localize(idx.tz)
                elif ts.tzinfo != idx.tz:
                    ts = ts.tz_convert(idx.tz)
            else:
                if ts.tzinfo is not None:
                    ts = ts.tz_localize(None)

            # Compute absolute nanosecond distance and take argmin
            # .asi8 gives int64 nanoseconds since epoch; may contain NaT (-9223372036854775808)
            vals = idx.asi8
            # Replace NaT with a very large number to avoid breaking argmin
            nat_mask = (vals == np.iinfo(np.int64).min)
            if nat_mask.any():
                vals = vals.copy()
                vals[nat_mask] = np.iinfo(np.int64).max

            return int(np.abs(vals - ts.value).argmin())

        # If index couldn't be converted to datetime, just fall back to the first row.
        return 0

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

