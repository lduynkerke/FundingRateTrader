"""
API client tests for the Funding Rate Strategy application.

This module tests the functionality of both spot and contract API clients, including:
1. Retrieving OHLCV (candlestick) data from spot and futures markets
2. Fetching available perpetual contract symbols
3. Getting and sorting funding rates for trading pairs
4. Validating response formats and data structures

These tests ensure that the API clients correctly interact with the MEXC exchange
and handle the responses appropriately.
"""

import pytest
import time
from typing import List

from api.spot_client import MEXCSpotClient
from api.contract_client import MEXCContractClient
from utils.config_loader import load_config


@pytest.fixture(scope="module")
def config() -> dict:
    """
    Fixture that provides the MEXC configuration from config.yaml.
    
    This fixture loads the configuration once per test module and makes it
    available to all tests, improving test performance.
    
    Returns:
        dict: The MEXC section of the configuration.
    """
    return load_config("config.yaml")['mexc']


@pytest.fixture(scope="module")
def spot_client(config) -> MEXCSpotClient:
    """
    Fixture that provides an initialized MEXCSpotClient.
    
    Creates a spot market client using the config fixture and makes it
    available to all tests in the module.
    
    Args:
        config: The MEXC configuration dictionary.
        
    Returns:
        MEXCSpotClient: An initialized spot market client.
    """
    return MEXCSpotClient(config)


@pytest.fixture(scope="module")
def contract_client(config) -> MEXCContractClient:
    """
    Fixture that provides an initialized MEXCContractClient.
    
    Creates a futures/contract market client using the config fixture and makes it
    available to all tests in the module.
    
    Args:
        config: The MEXC configuration dictionary.
        
    Returns:
        MEXCContractClient: An initialized contract market client.
    """
    return MEXCContractClient(config)

# Spot Client Tests
def test_fetch_ohlcv_spot(spot_client):
    """
    Test retrieving OHLCV (candlestick) data from the spot market.
    
    This test verifies that:
    - The client can successfully retrieve candlestick data
    - The response is a list with the requested number of candles
    - Each candle has the correct format with 8 elements (timestamp, open, high, 
      low, close, volume, close time, quote asset volume)
    
    Args:
        spot_client: The initialized spot client fixture.
    """
    data = spot_client.get_spot_ohlcv("BTCUSDT", interval="1m", limit=2)
    assert isinstance(data, list)
    assert len(data) == 2
    for candle in data:
        assert isinstance(candle, list)
        assert len(candle) == 8

# Contract Client Tests
def test_get_available_perpetual_symbols(contract_client):
    """
    Test retrieving available perpetual futures symbols from the contract market.
    
    This test verifies that:
    - The client can successfully retrieve a list of available symbols
    - The list contains at least one symbol
    - Each symbol is a string with the correct format (e.g., 'BTC_USDT')
    
    Args:
        contract_client: The initialized contract client fixture.
    """
    symbols = contract_client.get_available_perpetual_symbols()
    assert isinstance(symbols, list)
    assert len(symbols) > 0
    for sym in symbols:
        assert isinstance(sym, str)
        assert "_" in sym

def test_fetch_ohlcv_futures(contract_client):
    """
    Test retrieving OHLCV (candlestick) data from the futures market.
    
    This test verifies that:
    - The client can successfully retrieve futures candlestick data
    - The response has the correct structure (dictionary with success flag)
    - The data contains all required fields (time, open, high, low, close, volume)
    - All data arrays have the same length and contain numeric values
    
    Args:
        contract_client: The initialized contract client fixture.
    """
    now = int(time.time())
    start = now - 120
    end = now

    response = contract_client.get_futures_ohlcv("BTC_USDT", interval="Min1", start=start, end=end)
    assert isinstance(response, dict)
    assert response.get('success') is True
    data = response.get('data')
    assert isinstance(data, dict)

    keys_required = {"time", "open", "high", "low", "close", "vol"}
    assert keys_required.issubset(data.keys())

    num_entries = len(data["time"])
    for key in keys_required:
        assert len(data[key]) == num_entries
        assert isinstance(data[key][0], (int, float))

def test_get_top_funding_rates_async(contract_client):
    """
    Test retrieving and sorting top funding rates asynchronously.
    
    This test verifies that:
    - The client can successfully retrieve funding rates for multiple symbols
    - The top N symbols with highest absolute funding rates are returned
    - The returned list has the correct length
    - The funding rates are properly sorted in descending order by absolute value
    
    Args:
        contract_client: The initialized contract client fixture.
    """
    symbols = contract_client.get_available_perpetual_symbols()
    limited_symbols = symbols[:30]  # Limit to avoid long runtimes in test
    top_n = 3

    top_rates = contract_client.get_top_funding_rates(limited_symbols, top_n=top_n)
    assert isinstance(top_rates, list)
    assert len(top_rates) == top_n

    funding_values = [abs(float(entry['fundingRate'])) for entry in top_rates]
    assert funding_values == sorted(funding_values, reverse=True)
