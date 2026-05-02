"""
CSV export functionality for options pressure data.
"""
from datetime import datetime
import logging
from pathlib import Path
from typing import List

import pandas as pd

from config import OUTPUT_CSV_PATH, SUMMARY_CSV_PATH
from pressure_analyzer import PressureAnalysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataExporter:
    """Handles CSV export of pressure analyses and alerts."""

    def __init__(self, output_path: str = OUTPUT_CSV_PATH, summary_path: str = SUMMARY_CSV_PATH):
        self.output_path = output_path
        self.summary_path = summary_path
        self._ensure_headers()

    def _ensure_headers(self):
        if not Path(self.output_path).exists():
            pd.DataFrame(
                columns=[
                    "timestamp",
                    "strike",
                    "option_type",
                    "volume",
                    "oi",
                    "ltp",
                    "iv",
                    "spread_pct",
                    "oi_change_abs",
                    "oi_change_pct",
                    "price_change_pct",
                    "pressure_score",
                    "pressure_score_then",
                    "pressure_change",
                    "activity_score",
                    "oi_score",
                    "price_score",
                    "iv_score",
                    "spread_score",
                    "signal",
                    "is_pressure_leader",
                    "leader_shifted",
                ]
            ).to_csv(self.output_path, index=False)
            logger.info("Created data file: %s", self.output_path)

        if not Path(self.summary_path).exists():
            pd.DataFrame(
                columns=[
                    "timestamp",
                    "alert_type",
                    "strike",
                    "option_type",
                    "pressure_score",
                    "pressure_change",
                    "oi_change_abs",
                    "oi_change_pct",
                    "price_change_pct",
                    "signal",
                    "message",
                ]
            ).to_csv(self.summary_path, index=False)
            logger.info("Created alert file: %s", self.summary_path)

    def export_analyses(
        self, call_analyses: List[PressureAnalysis], put_analyses: List[PressureAnalysis]
    ):
        all_analyses = call_analyses + put_analyses
        if not all_analyses:
            logger.warning("No analyses to export")
            return

        rows = []
        for analysis in all_analyses:
            rows.append(
                {
                    "timestamp": analysis.timestamp.isoformat(),
                    "strike": analysis.strike,
                    "option_type": analysis.option_type,
                    "volume": analysis.volume,
                    "oi": analysis.oi,
                    "ltp": analysis.ltp,
                    "iv": analysis.iv,
                    "spread_pct": analysis.spread_pct,
                    "oi_change_abs": analysis.oi_change_abs,
                    "oi_change_pct": analysis.oi_change_pct,
                    "price_change_pct": analysis.price_change_pct,
                    "pressure_score": analysis.pressure_score,
                    "pressure_score_then": analysis.pressure_score_then,
                    "pressure_change": analysis.pressure_change,
                    "activity_score": analysis.activity_score,
                    "oi_score": analysis.oi_score,
                    "price_score": analysis.price_score,
                    "iv_score": analysis.iv_score,
                    "spread_score": analysis.spread_score,
                    "signal": analysis.signal,
                    "is_pressure_leader": analysis.is_pressure_leader,
                    "leader_shifted": analysis.leader_shifted,
                }
            )

        pd.DataFrame(rows).to_csv(self.output_path, mode="a", header=False, index=False)
        logger.debug("Exported %s pressure rows to %s", len(rows), self.output_path)

    def export_alerts(self, alerts: List[dict]):
        if not alerts:
            return

        timestamp = datetime.now().isoformat()
        rows = []
        for alert in alerts:
            rows.append(
                {
                    "timestamp": timestamp,
                    "alert_type": alert.get("type"),
                    "strike": alert.get("strike"),
                    "option_type": alert.get("option_type"),
                    "pressure_score": alert.get("pressure_score"),
                    "pressure_change": alert.get("pressure_change"),
                    "oi_change_abs": alert.get("oi_change_abs"),
                    "oi_change_pct": alert.get("oi_change_pct"),
                    "price_change_pct": alert.get("price_change_pct"),
                    "signal": alert.get("signal"),
                    "message": self._format_alert_message(alert),
                }
            )

        pd.DataFrame(rows).to_csv(self.summary_path, mode="a", header=False, index=False)
        logger.info("Exported %s alerts to %s", len(rows), self.summary_path)

    def get_recent_data(self, minutes: int = 5) -> pd.DataFrame:
        try:
            df = pd.read_csv(self.output_path)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            cutoff = datetime.now() - pd.Timedelta(minutes=minutes)
            return df[df["timestamp"] >= cutoff]
        except Exception as exc:
            logger.error("Error reading recent data: %s", exc)
            return pd.DataFrame()

    def clear_old_data(self, keep_hours: int = 24):
        try:
            for path in [self.output_path, self.summary_path]:
                if Path(path).exists():
                    df = pd.read_csv(path)
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    cutoff = datetime.now() - pd.Timedelta(hours=keep_hours)
                    df = df[df["timestamp"] >= cutoff]
                    df.to_csv(path, index=False)
                    logger.info("Cleaned old data from %s, kept %s rows", path, len(df))
        except Exception as exc:
            logger.error("Error cleaning old data: %s", exc)

    def _format_alert_message(self, alert: dict) -> str:
        strike = alert.get("strike")
        option_type = alert.get("option_type")
        score = alert.get("pressure_score")
        change = alert.get("pressure_change")
        signal = alert.get("signal")
        alert_type = alert.get("type")

        if alert_type == "HOT_CONTRACT":
            return f"{strike} {option_type} hot pressure score {score:.1f} ({signal})"
        if alert_type == "PRESSURE_SPIKE":
            return f"{strike} {option_type} pressure spiked {change:+.1f} to {score:.1f}"
        if alert_type == "PRESSURE_FADE":
            return f"{strike} {option_type} pressure faded {change:+.1f} to {score:.1f}"
        if alert_type == "LEADER_SHIFT":
            return f"Pressure leader shifted to {strike} {option_type} ({score:.1f})"
        return str(alert)
