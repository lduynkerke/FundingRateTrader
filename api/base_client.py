"""
Base API client module for MEXC exchange interactions.

This module provides the foundation for making authenticated and unauthenticated
requests to the MEXC exchange API. It handles request signing, error handling,
and logging of API interactions.
"""

import hmac
import hashlib
import time
import requests
from utils.logger import get_logger


class BaseMEXCClient:
    """
    Base class for MEXC clients, providing configuration loading and request signing.
    """

    def __init__(self, config: dict, market: str = "contract"):
        """
        Initializes the base client by loading API credentials and base URLs.

        :param config: Loaded config dict with api settings.
        :type config: dict
        :param market: Either 'spot' or 'contract'.
        :type market: str
        """
        self.logger = get_logger()
        self.api_key = config.get("api_key")
        self.secret_key = config.get("secret_key")
        self.base_url = config.get("base_urls", {}).get(market)
        self.market = market
        self.timeout = config.get("timeout", 10)

        self.logger.info(f"Initializing {market} client with base URL: {self.base_url}")

        if not (self.api_key and self.secret_key and self.base_url):
            error_msg = f"Missing API credentials or base URL in config for market type: {market}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

    def _get(self, endpoint: str, params: dict = None, headers: dict = None) -> any:
        """
        Performs an HTTP GET request with optional parameters and headers, including a timeout.

        :param endpoint: Full URL endpoint for the GET request.
        :type endpoint: str
        :param params: Query parameters to include in the request.
        :type params: dict
        :param headers: Optional HTTP headers (e.g., for authentication).
        :type headers: dict
        :return: JSON-decoded response (can be dict, list, or other JSON types).
        :rtype: any
        :raises RuntimeError: If the HTTP request fails or returns a non-200 status code.
        """
        self.logger.debug(f"Making GET request to {endpoint} with params: {params}")
        try:
            response = requests.get(endpoint, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            self.logger.debug(f"Successful response from {endpoint}: status_code={response.status_code}")
            return response.json()
        except requests.RequestException as e:
            error_msg = f"GET request failed for {endpoint}: {e}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)
        except ValueError as e:
            error_msg = f"Invalid JSON response from {endpoint}: {e}"
            self.logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _sign_request(self, method: str, endpoint: str, params: str = "") -> dict:
        """
        Creates signed headers for authenticated requests.

        :param method: HTTP method (GET, POST, etc.).
        :type method: str
        :param endpoint: Request path, e.g., '/api/v1/private/funding_rate/latest'.
        :type endpoint: str
        :param params: Query string parameters (sorted and URL encoded).
        :type params: str
        :return: Dictionary of headers including ApiKey, Request-Time, and Signature.
        :rtype: dict
        """
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{endpoint}{params}"
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return {
            "ApiKey": self.api_key,
            "Request-Time": timestamp,
            "Signature": signature
        }
