"""
MEXC Futures (Contract) API client module.

This module provides specialized functionality for interacting with the MEXC
futures market API. It handles retrieving funding rates, OHLCV data, and
available trading pairs with proper error handling and logging.

The module implements both synchronous and asynchronous request methods to
efficiently fetch data from multiple endpoints, especially for funding rates.
"""

import requests
import time
import asyncio
import httpx
from typing import List, Dict
from api.base_client import BaseMEXCClient
from utils.logger import get_logger


class MEXCContractClient(BaseMEXCClient):
    """
    Client for MEXC futures (contract) market data.
    """

    def __init__(self, config: dict):
        super().__init__(config=config, market="contract")

    async def _fetch_funding_rate(self, symbol: str, semaphore: asyncio.Semaphore) -> Dict[str, any]:
        """
        Asynchronously fetches funding rate data for a single symbol.

        :param symbol: Contract symbol (e.g., 'BTC_USDT').
        :type symbol: str
        :param semaphore: Asyncio semaphore to control request concurrency.
        :type semaphore: asyncio.Semaphore
        :return: Dictionary with funding rate data or empty dict on failure.
        :rtype: dict
        """
        url = f"{self.base_url}/api/v1/contract/funding_rate/{symbol}"
        self.logger.debug(f"Fetching funding rate for {symbol} from {url}")
        async with semaphore:
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.get(url, timeout=10.0)
                    response.raise_for_status()
                    result = response.json()
                    data = result.get("data")
                    self.logger.debug(f"Successfully fetched funding rate for {symbol}")
                    return data
                except Exception as e:
                    self.logger.error(f"Failed to fetch funding rate for {symbol}: {e}")
                    return {}

    async def _gather_funding_rates(self, symbols: List[str], max_concurrent_requests: int = 10) -> List[Dict[str, any]]:
        """
        Gathers funding rates for all provided symbols asynchronously.

        :param symbols: List of contract symbols.
        :type symbols: list[str]
        :param max_concurrent_requests: Max number of concurrent requests.
        :type max_concurrent_requests: int
        :return: List of funding rate dictionaries.
        :rtype: list[dict]
        """
        semaphore = asyncio.Semaphore(max_concurrent_requests)
        tasks = [self._fetch_funding_rate(symbol, semaphore) for symbol in symbols]
        results = await asyncio.gather(*tasks)
        return [res for res in results if res]

    def get_futures_ohlcv(self, symbol: str, interval: str = "Min1", start: int = None, end: int = None) -> List[list]:
        """
        Fetches OHLCV (kline) data for a given futures symbol using start/end timestamps.

        :param symbol: Symbol name (e.g., 'BTC_USDT').
        :type symbol: str
        :param interval: Interval for the kline data (e.g., 'Min1', 'Hour4').
        :type interval: str
        :param start: Start timestamp in seconds. Defaults to now - 60.
        :type start: int
        :param end: End timestamp in seconds. Defaults to now.
        :type end: int
        :return: List of [timestamp, open, high, low, close, volume]
        :rtype: list[list]
        """
        now = int(time.time())
        if start is None:
            start = now - 60
        if end is None:
            end = now

        self.logger.debug(f"Fetching OHLCV data for {symbol}, interval={interval}, start={start}, end={end}")
        
        try:
            endpoint = f"{self.base_url}/api/v1/contract/kline/{symbol}"
            params = {"interval": interval, "start": start, "end": end}
            result = self._get(endpoint, params=params)
            self.logger.debug(f"Successfully fetched {len(result)} OHLCV candles for {symbol}")
            return result
        except Exception as e:
            self.logger.error(f"Error fetching OHLCV data for {symbol}: {e}")
            raise

    def get_available_perpetual_symbols(self) -> List[str]:
        """
        Retrieves all available USDT perpetual futures symbols from MEXC.

        This method queries the public endpoint for contract details and extracts the symbol names.

        :return: List of perpetual contract symbols (e.g., ['BTC_USDT', 'ETH_USDT']).
        :rtype: list[str]
        """
        self.logger.debug("Fetching available perpetual symbols")
        endpoint = f"{self.base_url}/api/v1/contract/detail"
        try:
            result = self._get(endpoint, headers=None)
            data = result.get("data")
            symbols = [entry['symbol']
                    for entry in data
                    if 'symbol' in entry and entry.get('quoteCoin') == 'USDT'
                    ]
            self.logger.debug(f"Successfully fetched {len(symbols)} perpetual symbols")
            return symbols
        except Exception as e:
            self.logger.error(f"Error fetching perpetual symbols: {e}")
            return []

    def get_all_funding_rates_async(self, symbols: List[str], max_concurrent_requests: int = 10) -> List[Dict[str, any]]:
        """
        Public method to fetch funding rates for multiple symbols asynchronously.

        :param symbols: List of contract symbols.
        :type symbols: list[str]
        :param max_concurrent_requests: Max concurrent requests (default 10 to respect rate limit).
        :type max_concurrent_requests: int
        :return: List of funding rate dictionaries.
        :rtype: list[dict]
        """
        self.logger.debug(f"Fetching funding rates for {len(symbols)} symbols with max {max_concurrent_requests} concurrent requests")
        try:
            results = asyncio.run(self._gather_funding_rates(symbols, max_concurrent_requests))
            self.logger.debug(f"Successfully fetched {len(results)} funding rates")
            return results
        except Exception as e:
            self.logger.error(f"Error fetching funding rates asynchronously: {e}")
            return []

    def get_top_funding_rates(self, symbols: List[str], top_n: int = 3) -> List[Dict[str, any]]:
        """
        Returns the top N perpetual pairs with the highest absolute funding rates.

        :param symbols: List of symbols to consider.
        :type symbols: list[str]
        :param top_n: Number of top symbols to return.
        :type top_n: int
        :return: List of symbol dicts sorted by descending abs(funding rate).
        :rtype: list[dict]
        """
        self.logger.debug(f"Getting top {top_n} funding rates from {len(symbols)} symbols")
        try:
            all_rates = self.get_all_funding_rates_async(symbols)
            sorted_rates = sorted(all_rates, key=lambda x: abs(float(x['fundingRate'])), reverse=True)
            top_rates = sorted_rates[:top_n]
            self.logger.debug(f"Successfully identified top {len(top_rates)} funding rates")
            return top_rates
        except Exception as e:
            self.logger.error(f"Error getting top funding rates: {e}")
            return []
