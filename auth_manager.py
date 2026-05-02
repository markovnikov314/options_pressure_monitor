"""
Authentication manager for Upstox access tokens.
"""
from datetime import date, datetime
import json
import logging
from pathlib import Path
import time

import requests

from config import UPSTOX_ACCESS_TOKEN

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = Path(__file__).parent / "credentials.json"
TOKEN_CACHE_FILE = Path(__file__).parent / "token_cache.json"
TOKEN_REQUEST_URL = "https://api.upstox.com/v3/login/auth/token/request"


class AuthManager:
    """Load an Upstox access token from cache, env, worker flow, or prompt."""

    def __init__(self):
        self.credentials = self._load_credentials()
        self.access_token = None

    def _load_credentials(self) -> dict:
        if not CREDENTIALS_FILE.exists():
            return {}
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _load_cached_token(self) -> str | None:
        if not TOKEN_CACHE_FILE.exists():
            return None
        try:
            with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as handle:
                cache = json.load(handle)
            if cache.get("date") == str(date.today()):
                return cache.get("access_token")
        except Exception as exc:
            logger.debug("Token cache read failed: %s", exc)
        return None

    def _save_token_cache(self, token: str):
        with open(TOKEN_CACHE_FILE, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "date": str(date.today()),
                    "access_token": token,
                    "cached_at": datetime.now().isoformat(),
                },
                handle,
                indent=2,
            )

    def _get_env_token(self) -> str | None:
        if UPSTOX_ACCESS_TOKEN and len(UPSTOX_ACCESS_TOKEN) > 20:
            return UPSTOX_ACCESS_TOKEN
        return None

    def _send_token_request(self) -> bool:
        client_id = self.credentials.get("client_id")
        client_secret = self.credentials.get("client_secret")
        if not client_id or not client_secret:
            return False

        try:
            response = requests.post(
                f"{TOKEN_REQUEST_URL}/{client_id}",
                headers={"Content-Type": "application/json", "accept": "application/json"},
                json={"client_secret": client_secret},
                timeout=30,
            )
            if response.status_code == 200 and response.json().get("status") == "success":
                print("Token request sent to Upstox.")
                return True

            print(f"Token request failed: {response.text}")
            return False
        except Exception as exc:
            print(f"Token request error: {exc}")
            return False

    def _poll_worker_for_token(self, worker_url: str, timeout: int = 120) -> str | None:
        token_endpoint = f"{worker_url.rstrip('/')}/token"
        start_time = time.time()
        print(f"Polling worker for token for up to {timeout}s...")

        while time.time() - start_time < timeout:
            try:
                response = requests.get(token_endpoint, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    token = data.get("access_token")
                    timestamp = data.get("timestamp")
                    if data.get("status") == "success" and token:
                        if not timestamp:
                            return token
                        token_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                        now = datetime.now(token_time.tzinfo)
                        if (now - token_time).total_seconds() < 300:
                            return token
            except Exception as exc:
                logger.debug("Worker polling error: %s", exc)

            print(".", end="", flush=True)
            time.sleep(2)

        return None

    def get_access_token(self, force_refresh: bool = False, timeout: int = 120) -> str | None:
        if not force_refresh:
            cached = self._load_cached_token()
            if cached:
                print("Using cached token from today.")
                self.access_token = cached
                return cached

        env_token = self._get_env_token()
        if env_token:
            print("Using token from UPSTOX_ACCESS_TOKEN.")
            self._save_token_cache(env_token)
            self.access_token = env_token
            return env_token

        worker_url = self.credentials.get("worker_url")
        if worker_url and self._send_token_request():
            print("Approve the token request in Upstox, then wait here.")
            token = self._poll_worker_for_token(worker_url, timeout)
            if token:
                self._save_token_cache(token)
                self.access_token = token
                print("\nToken received and cached.")
                return token

        print("\nEnter access token (or 'cancel'): ", end="")
        try:
            token = input().strip()
            if token and token.lower() != "cancel":
                self._save_token_cache(token)
                self.access_token = token
                return token
        except Exception as exc:
            logger.debug("Manual token entry failed: %s", exc)

        return None


def get_token() -> str | None:
    auth = AuthManager()
    return auth.get_access_token()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    token = get_token()
    print(f"\n{'Token: ' + token[:20] + '...' if token else 'No token'}")
