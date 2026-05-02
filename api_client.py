"""
Upstox API Client Wrapper for Option Chain Data
"""
import upstox_client
from upstox_client.rest import ApiException
from typing import Optional, Dict, List, Any
import logging
from datetime import datetime

from config import UPSTOX_ACCESS_TOKEN, INSTRUMENT_KEY, get_nearest_tuesday_expiry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class UpstoxOptionClient:
    """Wrapper class for Upstox Options API"""
    
    def __init__(self, access_token: str = None):
        """
        Initialize the Upstox client with access token.
        
        Args:
            access_token: Upstox API access token. Uses config default if not provided.
        """
        self.access_token = access_token or UPSTOX_ACCESS_TOKEN
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = self.access_token
        self.api_client = upstox_client.ApiClient(self.configuration)
        self.options_api = upstox_client.OptionsApi(self.api_client)
        
    def get_option_chain(self, expiry_date: str = None) -> Optional[Dict[str, Any]]:
        """
        Fetch the put/call option chain for NIFTY 50.
        
        Args:
            expiry_date: Expiry date in YYYY-MM-DD format. Uses nearest Tuesday if not provided.
            
        Returns:
            Option chain data dictionary or None if API call fails.
        """
        if expiry_date is None:
            expiry_date = get_nearest_tuesday_expiry()
            
        try:
            logger.info(f"Fetching option chain for {INSTRUMENT_KEY}, expiry: {expiry_date}")
            api_response = self.options_api.get_put_call_option_chain(
                INSTRUMENT_KEY, 
                expiry_date
            )
            return api_response
        except ApiException as e:
            logger.error(f"API Exception when fetching option chain: {e.body}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching option chain: {str(e)}")
            return None
    
    def parse_option_chain_data(self, api_response) -> List[Dict[str, Any]]:
        """
        Parse the API response into a structured list of option data.
        
        Args:
            api_response: Raw API response from get_option_chain
            
        Returns:
            List of dictionaries containing strike data for calls and puts
        """
        if api_response is None:
            return []
        
        parsed_data = []
        
        try:
            # Handle different response formats
            if hasattr(api_response, 'data'):
                chain_data = api_response.data
            elif isinstance(api_response, dict) and 'data' in api_response:
                chain_data = api_response['data']
            else:
                chain_data = api_response
            
            # The chain_data is a list of strike items
            # Each strike item contains underlying_spot_price
            option_chain = chain_data if isinstance(chain_data, list) else []
            
            # Get spot price from first strike item
            spot_price = None
            if option_chain:
                first_strike = option_chain[0]
                if hasattr(first_strike, 'underlying_spot_price'):
                    spot_price = first_strike.underlying_spot_price
                elif isinstance(first_strike, dict):
                    spot_price = first_strike.get('underlying_spot_price')
            
            for strike_data in option_chain:
                strike_info = self._extract_strike_info(strike_data, spot_price)
                if strike_info:
                    parsed_data.append(strike_info)
                    
        except Exception as e:
            logger.error(f"Error parsing option chain data: {str(e)}")
            
        return parsed_data
    
    def _extract_strike_info(self, strike_data, spot_price: float = None) -> Optional[Dict[str, Any]]:
        """
        Extract relevant information from a single strike's data.
        
        Args:
            strike_data: Raw strike data from API
            spot_price: Underlying spot price
            
        Returns:
            Dictionary with call and put data for the strike
        """
        try:
            # Handle object or dict format
            if hasattr(strike_data, 'strike_price'):
                strike_price = strike_data.strike_price
                call_data = strike_data.call_options if hasattr(strike_data, 'call_options') else None
                put_data = strike_data.put_options if hasattr(strike_data, 'put_options') else None
            elif isinstance(strike_data, dict):
                strike_price = strike_data.get('strike_price')
                call_data = strike_data.get('call_options')
                put_data = strike_data.get('put_options')
            else:
                return None
            
            result = {
                'strike_price': strike_price,
                'spot_price': spot_price,
                'timestamp': datetime.now().isoformat(),
                'call': self._extract_option_data(call_data) if call_data else None,
                'put': self._extract_option_data(put_data) if put_data else None
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting strike info: {str(e)}")
            return None
    
    def _extract_option_data(self, option_data) -> Dict[str, Any]:
        """
        Extract volume, OI, greeks, and other relevant data from an option.
        
        Args:
            option_data: Raw option data (call or put)
            
        Returns:
            Dictionary with volume, OI, greeks, and market data
        """
        try:
            if hasattr(option_data, 'market_data'):
                market_data = option_data.market_data
            elif isinstance(option_data, dict) and 'market_data' in option_data:
                market_data = option_data['market_data']
            else:
                market_data = option_data
            
            # Get greeks data if available
            if hasattr(option_data, 'option_greeks'):
                greeks = option_data.option_greeks
            elif isinstance(option_data, dict) and 'option_greeks' in option_data:
                greeks = option_data['option_greeks']
            else:
                greeks = None
            
            # Extract values handling both object and dict formats
            def get_value(obj, key, default=None):
                if obj is None:
                    return default
                if hasattr(obj, key):
                    val = getattr(obj, key)
                    return val if val is not None else default
                elif isinstance(obj, dict):
                    val = obj.get(key, default)
                    return val if val is not None else default
                return default
            
            result = {
                # Market data
                'volume': get_value(market_data, 'volume', 0),
                'oi': get_value(market_data, 'oi', 0),
                'ltp': get_value(market_data, 'ltp', 0),
                'bid_price': get_value(market_data, 'bid_price', 0),
                'ask_price': get_value(market_data, 'ask_price', 0),
                'prev_oi': get_value(market_data, 'prev_oi', 0),
                
                # Greeks
                'delta': get_value(greeks, 'delta'),
                'gamma': get_value(greeks, 'gamma'),
                'theta': get_value(greeks, 'theta'),
                'vega': get_value(greeks, 'vega'),
                'iv': get_value(greeks, 'iv'),  # Implied Volatility
                'rho': get_value(greeks, 'rho'),
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Error extracting option data: {str(e)}")
            return {
                'volume': 0, 'oi': 0, 'ltp': 0, 'bid_price': 0, 'ask_price': 0, 'prev_oi': 0,
                'delta': None, 'gamma': None, 'theta': None, 'vega': None, 'iv': None, 'rho': None
            }


def test_connection():
    """Test the API connection and fetch one response"""
    client = UpstoxOptionClient()
    expiry = get_nearest_tuesday_expiry()
    print(f"Testing connection with expiry: {expiry}")
    
    response = client.get_option_chain(expiry)
    if response:
        print("✅ API connection successful!")
        parsed = client.parse_option_chain_data(response)
        print(f"✅ Parsed {len(parsed)} strikes from option chain")
        if parsed:
            first_record = parsed[0]
            print(f"First strike: {first_record['strike_price']}")
            if first_record['call']:
                print(f"  Call Volume: {first_record['call']['volume']}, OI: {first_record['call']['oi']}")
            if first_record['put']:
                print(f"  Put Volume: {first_record['put']['volume']}, OI: {first_record['put']['oi']}")
        return True
    else:
        print("❌ API connection failed!")
        return False


if __name__ == "__main__":
    test_connection()
