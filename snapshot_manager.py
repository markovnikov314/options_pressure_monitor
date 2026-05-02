"""
Snapshot Manager - Saves complete option chain data with greeks at each interval
Creates dated folders with timestamped CSV files
"""
import pandas as pd
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Any
import logging
import os

logger = logging.getLogger(__name__)

# Snapshot directory configuration
SNAPSHOT_BASE_DIR = Path(__file__).parent / "snapshots"


class SnapshotManager:
    """Manages daily snapshots of option chain data with greeks"""
    
    def __init__(self, base_dir: Path = SNAPSHOT_BASE_DIR):
        """
        Initialize snapshot manager.
        
        Args:
            base_dir: Base directory for all snapshots
        """
        self.base_dir = base_dir
        self.current_date = None
        self.current_dir = None
        self._ensure_base_dir()
        
    def _ensure_base_dir(self):
        """Create base directory if it doesn't exist"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
    def _get_daily_dir(self) -> Path:
        """Get or create directory for today's snapshots"""
        today = date.today()
        
        if self.current_date != today:
            self.current_date = today
            self.current_dir = self.base_dir / today.strftime("%Y-%m-%d")
            self.current_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created/using snapshot directory: {self.current_dir}")
            
        return self.current_dir
    
    def _generate_filename(self, timestamp: datetime = None) -> str:
        """Generate snapshot filename with timestamp"""
        if timestamp is None:
            timestamp = datetime.now()
        return f"snapshot_{timestamp.strftime('%H-%M-%S')}.csv"
    
    def save_snapshot(self, parsed_data: List[Dict[str, Any]], 
                      spot_price: float = None,
                      expiry: str = None) -> Path:
        """
        Save complete option chain snapshot with all available data.
        
        Args:
            parsed_data: Parsed option chain data from API
            spot_price: Current spot price
            expiry: Expiry date string
            
        Returns:
            Path to saved snapshot file
        """
        timestamp = datetime.now()
        daily_dir = self._get_daily_dir()
        filename = self._generate_filename(timestamp)
        filepath = daily_dir / filename
        
        rows = []
        
        for strike_data in parsed_data:
            strike = strike_data.get('strike_price')
            spot = strike_data.get('spot_price') or spot_price
            
            # Process calls
            if strike_data.get('call'):
                call = strike_data['call']
                row = self._create_row(
                    timestamp=timestamp,
                    strike=strike,
                    spot_price=spot,
                    option_type='CE',
                    option_data=call,
                    expiry=expiry
                )
                rows.append(row)
            
            # Process puts
            if strike_data.get('put'):
                put = strike_data['put']
                row = self._create_row(
                    timestamp=timestamp,
                    strike=strike,
                    spot_price=spot,
                    option_type='PE',
                    option_data=put,
                    expiry=expiry
                )
                rows.append(row)
        
        # Create DataFrame and save
        df = pd.DataFrame(rows)
        df.to_csv(filepath, index=False)
        
        logger.debug(f"Saved snapshot with {len(rows)} records to {filepath}")
        return filepath
    
    def _create_row(self, timestamp: datetime, strike: float, spot_price: float,
                    option_type: str, option_data: Dict, expiry: str = None) -> Dict:
        """
        Create a single row with all option data including greeks.
        
        Args:
            timestamp: Snapshot timestamp
            strike: Strike price
            spot_price: Underlying spot price
            option_type: 'CE' or 'PE'
            option_data: Option data dictionary
            expiry: Expiry date string
            
        Returns:
            Dictionary representing one row of data
        """
        # Basic data
        row = {
            'timestamp': timestamp.isoformat(),
            'date': timestamp.strftime('%Y-%m-%d'),
            'time': timestamp.strftime('%H:%M:%S'),
            'strike': strike,
            'spot_price': spot_price,
            'option_type': option_type,
            'expiry': expiry,
            
            # Market data
            'volume': option_data.get('volume', 0),
            'oi': option_data.get('oi', 0),
            'ltp': option_data.get('ltp', 0),
            'bid_price': option_data.get('bid_price', 0),
            'ask_price': option_data.get('ask_price', 0),
            'prev_oi': option_data.get('prev_oi', 0),
            
            # Greeks (if available)
            'delta': option_data.get('delta'),
            'gamma': option_data.get('gamma'),
            'theta': option_data.get('theta'),
            'vega': option_data.get('vega'),
            'iv': option_data.get('iv'),  # Implied Volatility
            
            # Calculated fields
            'liquidity_ratio': self._safe_divide(option_data.get('volume', 0),
                                                 option_data.get('oi', 0)),
            'oi_change': (option_data.get('oi', 0) - option_data.get('prev_oi', 0)) 
                         if option_data.get('prev_oi') else None,
            'moneyness': self._calculate_moneyness(strike, spot_price, option_type),
        }
        
        return row
    
    def _safe_divide(self, numerator: float, denominator: float) -> float:
        """Safe division with zero handling"""
        if denominator == 0 or denominator is None:
            return 0.0
        return round(numerator / denominator, 4)
    
    def _calculate_moneyness(self, strike: float, spot: float, 
                             option_type: str) -> str:
        """Calculate moneyness status"""
        if spot is None or strike is None:
            return 'UNKNOWN'
            
        if option_type == 'CE':
            if strike < spot:
                return 'ITM'
            elif strike > spot:
                return 'OTM'
            else:
                return 'ATM'
        else:  # PE
            if strike > spot:
                return 'ITM'
            elif strike < spot:
                return 'OTM'
            else:
                return 'ATM'
    
    def get_today_snapshots(self) -> List[Path]:
        """Get list of all snapshots from today"""
        daily_dir = self._get_daily_dir()
        return sorted(daily_dir.glob("snapshot_*.csv"))
    
    def get_snapshot_count(self) -> int:
        """Get count of snapshots saved today"""
        return len(self.get_today_snapshots())
    
    def get_latest_snapshot(self) -> pd.DataFrame | None:
        """Load the most recent snapshot as DataFrame"""
        snapshots = self.get_today_snapshots()
        if not snapshots:
            return None
        return pd.read_csv(snapshots[-1])
    
    def cleanup_old_snapshots(self, keep_days: int = 7):
        """
        Remove snapshot directories older than specified days.
        
        Args:
            keep_days: Number of days of snapshots to retain
        """
        from datetime import timedelta
        
        cutoff = date.today() - timedelta(days=keep_days)
        
        for dir_path in self.base_dir.iterdir():
            if dir_path.is_dir():
                try:
                    dir_date = datetime.strptime(dir_path.name, "%Y-%m-%d").date()
                    if dir_date < cutoff:
                        # Remove directory and contents
                        import shutil
                        shutil.rmtree(dir_path)
                        logger.info(f"Removed old snapshot directory: {dir_path}")
                except ValueError:
                    # Not a date-formatted directory, skip
                    pass


# Convenience function
def save_option_chain_snapshot(parsed_data: List[Dict], 
                                spot_price: float = None,
                                expiry: str = None) -> Path:
    """Save a single snapshot using default manager"""
    manager = SnapshotManager()
    return manager.save_snapshot(parsed_data, spot_price, expiry)
