import matplotlib.dates as mdates
from decimal import Decimal
import pandas as pd
from typing import List, Union

from .models import TrendLine
from .dhan import TrendLine as CoreTrendLine


class TrendLinePersistenceService:
    """
    Given a DataFrame and chart inputs, compute each TrendLine,
    serialize its (date, price) points, and save them, avoiding duplicates.
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
                start_date=self.start_date,
                angle_deg=angle,
                price_to_bar_ratio=self.ratio,
                full_df=self.df,
                # max_extension=500,
            )

            raw_xs, raw_ys = core_tl.get_points()

            payload = []
            for raw_x, raw_y in zip(raw_xs, raw_ys):
                dt = mdates.num2date(raw_x) if isinstance(raw_x, (float, int)) else pd.to_datetime(raw_x)
                payload.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "value": round(float(raw_y), 2),
                })

            # Check for existing TrendLine with same key fields
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
