"""
NIFTY Options Pressure Monitor

Main orchestration loop for the Upstox-backed live monitor.
"""
import argparse
import logging
import signal
import sys
import time

from api_client import UpstoxOptionClient
from auth_manager import AuthManager
from config import (
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    RUN_ONLY_DURING_MARKET_HOURS,
    UPDATE_INTERVAL_SECONDS,
    get_nearest_tuesday_expiry,
    get_time_until_market_open,
    is_market_open,
    round_to_nearest_strike,
)
from data_exporter import DataExporter
from pressure_analyzer import OptionsPressureAnalyzer
from snapshot_manager import SnapshotManager
from visualizer import Visualizer


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("options_pressure_monitor.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class OptionsPressureMonitor:
    """Main orchestrator for options pressure monitoring."""

    def __init__(
        self,
        access_token: str | None = None,
        clear_screen: bool = True,
        expiry: str | None = None,
    ):
        if access_token is None:
            auth = AuthManager()
            access_token = auth.get_access_token()
            if not access_token:
                raise RuntimeError("Failed to obtain access token. Cannot start monitor.")
        self.client = UpstoxOptionClient(access_token=access_token)

        self.analyzer = OptionsPressureAnalyzer()
        self.exporter = DataExporter()
        self.visualizer = Visualizer(clear_screen=clear_screen)
        self.snapshot_manager = SnapshotManager()

        self.expiry = expiry or get_nearest_tuesday_expiry()
        self.update_count = 0
        self.running = True
        self.last_spot_price = None
        self.last_atm_strike = None

        signal.signal(signal.SIGINT, self._signal_handler)

    def _signal_handler(self, signum, frame):
        logger.info("Shutdown signal received. Stopping monitor...")
        self.running = False

    def _get_spot_and_atm(self, parsed_data) -> tuple:
        if not parsed_data:
            return self.last_spot_price, self.last_atm_strike

        spot_price = parsed_data[0].get("spot_price")
        if spot_price is None:
            strikes = [item.get("strike_price", 0) for item in parsed_data if item.get("strike_price")]
            spot_price = (min(strikes) + max(strikes)) / 2 if strikes else self.last_spot_price or 25000

        atm_strike = round_to_nearest_strike(spot_price)
        self.last_spot_price = spot_price
        self.last_atm_strike = atm_strike
        return spot_price, atm_strike

    def run_single_update(self, screenshot_path: str | None = None) -> bool:
        try:
            logger.debug("Fetching option chain for expiry: %s", self.expiry)
            api_response = self.client.get_option_chain(self.expiry)
            if api_response is None:
                logger.warning("Failed to fetch option chain data")
                return False

            parsed_data = self.client.parse_option_chain_data(api_response)
            if not parsed_data:
                logger.warning("No data parsed from API response")
                return False

            spot_price, atm_strike = self._get_spot_and_atm(parsed_data)
            if atm_strike is None:
                logger.warning("Could not determine ATM strike")
                return False

            call_analyses, put_analyses = self.analyzer.analyze_all_strikes(
                parsed_data, atm_strike
            )
            alerts = self.analyzer.get_pressure_alerts(call_analyses, put_analyses)

            self.exporter.export_analyses(call_analyses, put_analyses)
            if alerts:
                self.exporter.export_alerts(alerts)

            try:
                snapshot_path = self.snapshot_manager.save_snapshot(
                    parsed_data=parsed_data,
                    spot_price=spot_price,
                    expiry=self.expiry,
                )
                logger.debug("Saved snapshot: %s", snapshot_path)
            except Exception as snap_err:
                logger.warning("Failed to save snapshot: %s", snap_err)

            self.update_count += 1
            snapshot_count = self.snapshot_manager.get_snapshot_count()
            self.visualizer.render_dashboard(
                call_analyses=call_analyses,
                put_analyses=put_analyses,
                alerts=alerts,
                spot_price=spot_price,
                atm_strike=atm_strike,
                expiry=self.expiry,
                update_count=self.update_count,
                snapshot_count=snapshot_count,
            )

            if screenshot_path:
                saved = self.visualizer.save_screenshot(
                    path=screenshot_path,
                    call_analyses=call_analyses,
                    put_analyses=put_analyses,
                    alerts=alerts,
                    spot_price=spot_price,
                    atm_strike=atm_strike,
                    expiry=self.expiry,
                    update_count=self.update_count,
                    snapshot_count=snapshot_count,
                )
                logger.info("Saved screenshot: %s", saved)

            return True

        except Exception as exc:
            logger.error("Error in update cycle: %s", exc, exc_info=True)
            self.visualizer.print_error(f"Update failed: {exc}")
            return False

    def run_once(self, screenshot_path: str | None = None) -> bool:
        self.visualizer.print_startup_message(self.expiry)
        return self.run_single_update(screenshot_path=screenshot_path)

    def run(self):
        logger.info("=" * 60)
        logger.info("Options Pressure Monitor Starting")
        logger.info("Expiry: %s", self.expiry)
        logger.info("Update Interval: %s seconds", UPDATE_INTERVAL_SECONDS)
        logger.info(
            "Market Hours: %s:%02d - %s:%02d IST",
            MARKET_OPEN_HOUR,
            MARKET_OPEN_MINUTE,
            MARKET_CLOSE_HOUR,
            MARKET_CLOSE_MINUTE,
        )
        logger.info("=" * 60)

        self.visualizer.print_startup_message(self.expiry)

        if not self._wait_for_market_open():
            return

        time.sleep(1)

        while self.running:
            if RUN_ONLY_DURING_MARKET_HOURS and not is_market_open():
                logger.info("Market closed. Stopping monitor.")
                print("\nMarket closed at 3:30 PM. Monitor stopped.")
                break

            start_time = time.time()
            success = self.run_single_update()
            if not success:
                logger.warning("Update cycle failed, will retry next interval")

            elapsed = time.time() - start_time
            sleep_time = max(0, UPDATE_INTERVAL_SECONDS - elapsed)
            if sleep_time > 0 and self.running:
                time.sleep(sleep_time)

        logger.info("Monitor stopped")
        print("\nOptions Pressure Monitor stopped. Data saved to CSV files.")
        print("   - Detailed data: pressure_data.csv")
        print("   - Alerts: pressure_alerts.csv")

    def _wait_for_market_open(self):
        if not RUN_ONLY_DURING_MARKET_HOURS or is_market_open():
            return True

        time_until = get_time_until_market_open()
        hours, remainder = divmod(int(time_until.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)

        print(f"\nMarket is closed. Opens at {MARKET_OPEN_HOUR}:{MARKET_OPEN_MINUTE:02d} IST")
        print(f"   Time until market open: {hours}h {minutes}m {seconds}s")
        print("   Waiting for market to open... (Ctrl+C to exit)\n")

        while not is_market_open() and self.running:
            time.sleep(30)

        return self.running


def parse_args():
    parser = argparse.ArgumentParser(description="NIFTY Options Pressure Monitor")
    parser.add_argument("--once", action="store_true", help="Run one update and exit")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear the terminal before rendering")
    parser.add_argument(
        "--screenshot",
        help="Write a PNG screenshot of the rendered dashboard to this path",
    )
    parser.add_argument("--expiry", help="Override expiry date in YYYY-MM-DD format")
    parser.add_argument("--token", help="Use this Upstox access token for the run")
    return parser.parse_args()


def main():
    args = parse_args()

    print("\n" + "=" * 60)
    print("  NIFTY Options Pressure Monitor")
    print("=" * 60 + "\n")

    try:
        monitor = OptionsPressureMonitor(
            access_token=args.token,
            clear_screen=not args.no_clear,
            expiry=args.expiry,
        )
        if args.once or args.screenshot:
            success = monitor.run_once(screenshot_path=args.screenshot)
            sys.exit(0 if success else 1)
        monitor.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as exc:
        logger.error("Fatal error: %s", exc, exc_info=True)
        print(f"\nFatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
