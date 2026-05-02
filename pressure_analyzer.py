"""
Options Pressure Analyzer

Builds a multi-factor pressure score for each option contract using activity,
open-interest change, price movement, implied volatility, and spread quality.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import math
from typing import Dict, List, Optional, Tuple

from config import (
    LOOKBACK_PERIODS,
    PRESSURE_FADE_THRESHOLD,
    PRESSURE_HOT_THRESHOLD,
    PRESSURE_SPIKE_THRESHOLD,
    PRESSURE_WATCH_THRESHOLD,
    STRIKE_INTERVAL,
    STRIKE_RANGE,
)


@dataclass
class OptionSnapshot:
    """Single point-in-time data for a contract."""

    timestamp: datetime
    strike: float
    option_type: str
    volume: int
    oi: int
    ltp: float
    iv: Optional[float]
    pressure_score: float


@dataclass
class PressureAnalysis:
    """Scored analysis result for a single option contract."""

    timestamp: datetime
    strike: float
    option_type: str
    volume: int
    oi: int
    ltp: float
    iv: Optional[float]
    spread_pct: float
    oi_change_abs: Optional[int]
    oi_change_pct: Optional[float]
    price_change_pct: Optional[float]
    pressure_score: float
    pressure_score_then: Optional[float]
    pressure_change: Optional[float]
    activity_score: float
    oi_score: float
    price_score: float
    iv_score: float
    spread_score: float
    signal: str
    is_pressure_leader: bool = False
    leader_shifted: bool = False


class OptionsPressureAnalyzer:
    """Analyze options through a composite pressure score."""

    def __init__(self, lookback_periods: int = LOOKBACK_PERIODS):
        self.lookback_periods = lookback_periods
        self.rolling_buffer: Dict[Tuple[float, str], deque] = {}
        self.prev_call_leader: Optional[float] = None
        self.prev_put_leader: Optional[float] = None

    def analyze_all_strikes(
        self, parsed_data: List[Dict], atm_strike: float
    ) -> Tuple[List[PressureAnalysis], List[PressureAnalysis]]:
        timestamp = datetime.now()
        min_strike = atm_strike - STRIKE_RANGE
        max_strike = atm_strike + STRIKE_RANGE

        call_analyses = []
        put_analyses = []

        for strike_data in parsed_data:
            strike = strike_data.get("strike_price")
            if strike is None or strike < min_strike or strike > max_strike:
                continue

            if strike_data.get("call"):
                call_analyses.append(
                    self.analyze_contract(strike, "CE", strike_data["call"], timestamp)
                )

            if strike_data.get("put"):
                put_analyses.append(
                    self.analyze_contract(strike, "PE", strike_data["put"], timestamp)
                )

        self._identify_pressure_leader(call_analyses, "call")
        self._identify_pressure_leader(put_analyses, "put")
        return call_analyses, put_analyses

    def analyze_contract(
        self, strike: float, option_type: str, option_data: Dict, timestamp: datetime
    ) -> PressureAnalysis:
        volume = int(option_data.get("volume") or 0)
        oi = int(option_data.get("oi") or 0)
        prev_oi = option_data.get("prev_oi")
        ltp = float(option_data.get("ltp") or 0)
        bid_price = float(option_data.get("bid_price") or 0)
        ask_price = float(option_data.get("ask_price") or 0)
        iv = option_data.get("iv")

        historical = self.get_historical_snapshot(strike, option_type)
        oi_change_abs, oi_change_pct = self._get_oi_change(oi, prev_oi, historical)
        price_change_pct = self._safe_pct_change(
            ltp, historical.ltp if historical else None
        )
        spread_pct = self._spread_pct(bid_price, ask_price, ltp)

        activity_score = self._activity_score(volume, oi)
        oi_score = self._bounded(abs(oi_change_pct or 0) * 7.0)
        price_score = self._bounded(abs(price_change_pct or 0) * 9.0)
        iv_score = self._bounded(self._normalized_iv(iv) * 1.8)
        spread_score = self._bounded(100 - spread_pct * 9.0)

        pressure_score = round(
            activity_score * 0.35
            + oi_score * 0.25
            + price_score * 0.20
            + iv_score * 0.10
            + spread_score * 0.10,
            2,
        )

        pressure_score_then = historical.pressure_score if historical else None
        pressure_change = (
            round(pressure_score - pressure_score_then, 2)
            if pressure_score_then is not None
            else None
        )

        signal = self._classify_signal(
            pressure_score=pressure_score,
            oi_change_pct=oi_change_pct,
            price_change_pct=price_change_pct,
            pressure_change=pressure_change,
        )

        analysis = PressureAnalysis(
            timestamp=timestamp,
            strike=strike,
            option_type=option_type,
            volume=volume,
            oi=oi,
            ltp=ltp,
            iv=iv,
            spread_pct=spread_pct,
            oi_change_abs=oi_change_abs,
            oi_change_pct=oi_change_pct,
            price_change_pct=price_change_pct,
            pressure_score=pressure_score,
            pressure_score_then=pressure_score_then,
            pressure_change=pressure_change,
            activity_score=activity_score,
            oi_score=oi_score,
            price_score=price_score,
            iv_score=iv_score,
            spread_score=spread_score,
            signal=signal,
        )

        self.add_snapshot(
            strike=strike,
            option_type=option_type,
            volume=volume,
            oi=oi,
            ltp=ltp,
            iv=iv,
            pressure_score=pressure_score,
            timestamp=timestamp,
        )
        return analysis

    def get_pressure_alerts(
        self, call_analyses: List[PressureAnalysis], put_analyses: List[PressureAnalysis]
    ) -> List[Dict]:
        alerts = []

        for analysis in call_analyses + put_analyses:
            if analysis.pressure_change is not None:
                if analysis.pressure_change >= PRESSURE_SPIKE_THRESHOLD:
                    alerts.append(self._alert("PRESSURE_SPIKE", analysis))
                elif analysis.pressure_change <= PRESSURE_FADE_THRESHOLD:
                    alerts.append(self._alert("PRESSURE_FADE", analysis))

            if analysis.pressure_score >= PRESSURE_HOT_THRESHOLD:
                alerts.append(self._alert("HOT_CONTRACT", analysis))

            if analysis.leader_shifted:
                alerts.append(self._alert("LEADER_SHIFT", analysis))

        # Highest-signal alerts first.
        return sorted(
            alerts,
            key=lambda item: (item.get("pressure_score", 0), abs(item.get("pressure_change") or 0)),
            reverse=True,
        )

    def add_snapshot(
        self,
        strike: float,
        option_type: str,
        volume: int,
        oi: int,
        ltp: float,
        iv: Optional[float],
        pressure_score: float,
        timestamp: datetime,
    ) -> None:
        key = (strike, option_type)
        if key not in self.rolling_buffer:
            self.rolling_buffer[key] = deque(maxlen=self.lookback_periods)
        self.rolling_buffer[key].append(
            OptionSnapshot(
                timestamp=timestamp,
                strike=strike,
                option_type=option_type,
                volume=volume,
                oi=oi,
                ltp=ltp,
                iv=iv,
                pressure_score=pressure_score,
            )
        )

    def get_historical_snapshot(
        self, strike: float, option_type: str
    ) -> Optional[OptionSnapshot]:
        key = (strike, option_type)
        buffer = self.rolling_buffer.get(key)
        if not buffer or len(buffer) < self.lookback_periods:
            return None
        return buffer[0]

    def _identify_pressure_leader(
        self, analyses: List[PressureAnalysis], side: str
    ) -> None:
        if not analyses:
            return

        leader = max(analyses, key=lambda item: item.pressure_score)
        if leader.pressure_score <= 0:
            return

        leader.is_pressure_leader = True
        previous = self.prev_call_leader if side == "call" else self.prev_put_leader
        if previous is not None and previous != leader.strike:
            leader.leader_shifted = True

        if side == "call":
            self.prev_call_leader = leader.strike
        else:
            self.prev_put_leader = leader.strike

    def _alert(self, alert_type: str, analysis: PressureAnalysis) -> Dict:
        return {
            "type": alert_type,
            "strike": analysis.strike,
            "option_type": analysis.option_type,
            "pressure_score": analysis.pressure_score,
            "pressure_change": analysis.pressure_change,
            "oi_change_abs": analysis.oi_change_abs,
            "oi_change_pct": analysis.oi_change_pct,
            "price_change_pct": analysis.price_change_pct,
            "signal": analysis.signal,
        }

    def _get_oi_change(
        self, oi: int, prev_oi: Optional[float], historical: Optional[OptionSnapshot]
    ) -> Tuple[Optional[int], Optional[float]]:
        previous = prev_oi
        if previous in (None, 0) and historical:
            previous = historical.oi
        if previous in (None, 0):
            return None, None

        previous = int(previous)
        absolute = oi - previous
        pct = round((absolute / previous) * 100, 2)
        return absolute, pct

    def _classify_signal(
        self,
        pressure_score: float,
        oi_change_pct: Optional[float],
        price_change_pct: Optional[float],
        pressure_change: Optional[float],
    ) -> str:
        oi_pct = oi_change_pct or 0
        price_pct = price_change_pct or 0

        if pressure_score >= PRESSURE_HOT_THRESHOLD:
            if oi_pct >= 5 and price_pct >= 1:
                return "LONG_BUILDUP"
            if oi_pct >= 5 and price_pct <= -1:
                return "SHORT_BUILDUP"
            if oi_pct <= -5 and price_pct >= 1:
                return "SHORT_COVER"
            if oi_pct <= -5 and price_pct <= -1:
                return "LONG_UNWIND"
            return "HOT_FLOW"

        if pressure_change is not None and pressure_change >= PRESSURE_SPIKE_THRESHOLD:
            return "SPIKE"

        if pressure_score >= PRESSURE_WATCH_THRESHOLD:
            return "WATCH"

        return "CALM"

    def _activity_score(self, volume: int, oi: int) -> float:
        volume_score = math.log1p(max(volume, 0)) / math.log1p(250000) * 70
        turnover_score = min((volume / max(oi, 1)) * 500, 30)
        return self._bounded(volume_score + turnover_score)

    def _spread_pct(self, bid_price: float, ask_price: float, ltp: float) -> float:
        if bid_price <= 0 or ask_price <= 0:
            return 100.0
        mid = (bid_price + ask_price) / 2
        if mid <= 0:
            mid = ltp
        if mid <= 0:
            return 100.0
        return round(((ask_price - bid_price) / mid) * 100, 2)

    def _normalized_iv(self, iv: Optional[float]) -> float:
        if iv is None:
            return 0.0
        iv_value = float(iv)
        if iv_value <= 1:
            iv_value *= 100
        return max(iv_value, 0)

    def _safe_pct_change(
        self, current: float, previous: Optional[float]
    ) -> Optional[float]:
        if previous in (None, 0):
            return None
        return round(((current - previous) / previous) * 100, 2)

    def _bounded(self, value: float, lower: float = 0, upper: float = 100) -> float:
        return round(max(lower, min(upper, value)), 2)
