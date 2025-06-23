import pandas as pd
import matplotlib.dates as mdates
from decimal import Decimal
from typing import List, Union
from .models import TrendLine
from .dhan import TrendLine as CoreTrendLine


class TrendLinePersistenceService:
    """
    Given a DataFrame and chart inputs, compute each TrendLine,
    serialize its (date, price) points (historical + next 7 biz days),
    and save them, avoiding duplicates.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        symbol: str,
        security_id: str,
        start_date: Union[str, pd.Timestamp],
        price_to_bar_ratio: float,
        angles: List[float],
    ) -> None:
        self.df = df
        self.symbol = symbol
        self.security_id = security_id
        self.start_date = pd.to_datetime(start_date)
        self.ratio = price_to_bar_ratio
        self.angles = angles

    def persist(self) -> None:
        for angle in self.angles:
            core_tl = CoreTrendLine(
                full_df=self.df,
                start_date=self.start_date,
                angle_deg=angle,
                price_to_bar_ratio=self.ratio,
            )

            # 1) get the historical xs/ys
            hist_xs, hist_ys = core_tl.get_points()
            # convert xs back to datetime for payload
            hist_dates = core_tl.dates

            # 2) build payload entries for history
            payload = [
                {"date": dt.strftime("%Y-%m-%d"), "value": round(float(y), 2)}
                for dt, y in zip(hist_dates, hist_ys)
            ]

            # 3) now extend for T+1…T+7 business days
            last_bar_index = len(hist_xs) - 1
            last_date = hist_dates[-1]
            # next 7 business days (skipping weekends)
            future_dates = pd.bdate_range(
                start=last_date + pd.Timedelta(days=1),
                periods=7
            )
            for i, fdate in enumerate(future_dates, start=1):
                offset = last_bar_index + i
                future_y = core_tl.start_price + core_tl.slope * offset
                payload.append({
                    "date": fdate.strftime("%Y-%m-%d"),
                    "value": round(float(future_y), 2),
                })

            # 4) upsert only if not exists
            exists = TrendLine.objects.filter(
                symbol=self.symbol,
                security_id=self.security_id,
                start_date=self.start_date.date(),
                angles=[angle],
                price_to_bar_ratio=self.ratio,
                start_price=Decimal(str(core_tl.start_price)),
            ).exists()

            if not exists:
                TrendLine.objects.create(
                    symbol=self.symbol,
                    security_id=self.security_id,
                    start_date=self.start_date.date(),
                    angles=[angle],
                    price_to_bar_ratio=self.ratio,
                    start_price=Decimal(str(core_tl.start_price)),
                    line_data=payload,
                )
            else:
                # if already exists, just update the line_data to include future points
                tl = TrendLine.objects.get(
                    symbol=self.symbol,
                    security_id=self.security_id,
                    start_date=self.start_date.date(),
                    angles=[angle],
                    price_to_bar_ratio=self.ratio,
                    start_price=Decimal(str(core_tl.start_price)),
                )
                tl.line_data = payload
                tl.save(update_fields=["line_data"])
