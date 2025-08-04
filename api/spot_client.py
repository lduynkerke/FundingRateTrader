"""
MEXC Spot API client module.

This module provides functionality for interacting with the MEXC spot market API.
It handles retrieving OHLCV (candlestick) data for spot trading pairs with proper
error handling and logging.

The module extends the base client functionality to work specifically with
the spot market endpoints of the MEXC exchange.
"""

from typing import List
from api.base_client import BaseMEXCClient


class MEXCSpotClient(BaseMEXCClient):
    """
    Client for MEXC spot market data (public endpoints).
    """

    def __init__(self, config: dict):
        super().__init__(config=config, market="spot")

    def get_spot_ohlcv(self, symbol: str, interval: str = "1m", limit: int = 1) -> List[list]:
        """
        Fetches OHLCV (candlestick) data for a given spot symbol.

        :param symbol: Symbol name (e.g., 'BTCUSDT').
        :type symbol: str
        :param interval: Interval string like '1m', '5m'.
        :type interval: str
        :param limit: Number of candles to retrieve.
        :type limit: int
        :return: List of [timestamp, open, high, low, close, volume]
        :rtype: list[list]
        """
        endpoint = f"{self.base_url}/api/v3/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return self._get(endpoint, params=params)
