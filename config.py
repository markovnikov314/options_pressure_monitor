"""
Configuration settings for the NIFTY Options Pressure Monitor.
"""
import os
from datetime import datetime, timedelta

# =============================================================================
# API Configuration
# =============================================================================
UPSTOX_ACCESS_TOKEN = os.getenv(
    "UPSTOX_ACCESS_TOKEN",
    ""
)

# Instrument settings
INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"
STRIKE_INTERVAL = 100  # Round to nearest 100 for ATM

# =============================================================================
# Monitoring Parameters
# =============================================================================
STRIKE_RANGE = 300  # Points above and below ATM to monitor
UPDATE_INTERVAL_SECONDS = 20  # Data refresh interval
LOOKBACK_PERIODS = 10  # Number of periods for trend analysis (20s * 10)

# =============================================================================
# Pressure Score Thresholds
# =============================================================================
PRESSURE_HOT_THRESHOLD = 70.0
PRESSURE_WATCH_THRESHOLD = 50.0
PRESSURE_SPIKE_THRESHOLD = 15.0
PRESSURE_FADE_THRESHOLD = -15.0

# =============================================================================
# Market Hours (IST)
# =============================================================================
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30
RUN_ONLY_DURING_MARKET_HOURS = False

# =============================================================================
# Output Settings
# =============================================================================
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_CSV_PATH = os.path.join(OUTPUT_DIR, "pressure_data.csv")
SUMMARY_CSV_PATH = os.path.join(OUTPUT_DIR, "pressure_alerts.csv")

# =============================================================================
# Helper Functions
# =============================================================================
def get_nearest_tuesday_expiry():
    """
    Get the nearest Tuesday expiry date for NIFTY weekly options.
    If today is Tuesday, returns today's date.
    """
    today = datetime.now().date()
    days_until_tuesday = (1 - today.weekday()) % 7  # Tuesday is weekday 1
    if days_until_tuesday == 0 and datetime.now().hour >= 15:
        # If it's Tuesday after market close, get next Tuesday
        days_until_tuesday = 7
    next_tuesday = today + timedelta(days=days_until_tuesday)
    return next_tuesday.strftime("%Y-%m-%d")


def is_market_open() -> bool:
    """
    Check if the market is currently open.
    Market hours: 9:15 AM to 3:30 PM IST (Monday-Friday)
    """
    now = datetime.now()
    
    # Check if weekend (Saturday=5, Sunday=6)
    if now.weekday() >= 5:
        return False
    
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    
    return market_open <= now <= market_close


def get_time_until_market_open() -> timedelta:
    """
    Get time remaining until market opens.
    Returns timedelta, or timedelta(0) if market is open.
    """
    now = datetime.now()
    today_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0)
    
    if now < today_open and now.weekday() < 5:
        return today_open - now
    
    # Find next trading day
    days_ahead = 1
    if now.weekday() == 4:  # Friday
        days_ahead = 3
    elif now.weekday() == 5:  # Saturday
        days_ahead = 2
    
    next_open = (now + timedelta(days=days_ahead)).replace(
        hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0, microsecond=0
    )
    return next_open - now


def get_strikes_in_range(atm_strike: float) -> list:
    """
    Get list of strikes within the monitoring range.
    Returns strikes from (ATM - STRIKE_RANGE) to (ATM + STRIKE_RANGE)
    """
    num_strikes_each_side = STRIKE_RANGE // STRIKE_INTERVAL
    strikes = []
    for i in range(-num_strikes_each_side, num_strikes_each_side + 1):
        strike = atm_strike + (i * STRIKE_INTERVAL)
        strikes.append(strike)
    return strikes


def round_to_nearest_strike(price: float) -> float:
    """Round price to nearest 100 for ATM calculation"""
    return round(price / 100) * 100
