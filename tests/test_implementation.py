"""
Implementation tests for the Funding Rate Strategy application.

This module tests the core implementation of the funding rate data collection pipeline,
focusing on:
1. Data collection and saving functionality
2. Funding rate snapshot timing and processing
3. Symbol selection and caching around funding events

These tests ensure that the application correctly identifies funding times and
collects the appropriate data for analysis.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from api.contract_client import MEXCContractClient
from pipeline.funding_rate_logger import collect_and_save_data, log_funding_snapshot


@pytest.fixture
def mock_client():
    """
    Fixture that provides a mocked MEXCContractClient for testing.
    
    This fixture creates a mock client with predefined return values for:
    - get_futures_ohlcv: Returns sample OHLCV data with timestamps and price information
    - get_top_funding_rates: Returns sample funding rate data for BTC, ETH, and SOL
    - get_available_perpetual_symbols: Returns a list of available trading pairs
    
    Using this mock allows tests to run without making actual API calls, ensuring
    consistent and predictable test behavior.
    
    Returns:
        MagicMock: A configured mock of the MEXCContractClient.
    """
    client = MagicMock(spec=MEXCContractClient)
    
    client.get_futures_ohlcv.return_value = [
        [1627776000000, 40000.0, 40100.0, 39900.0, 40050.0, 100.0],
        [1627776060000, 40100.0, 40200.0, 40000.0, 40150.0, 120.0]
    ]
    
    client.get_top_funding_rates.return_value = [
        {'symbol': 'BTC_USDT', 'fundingRate': '0.001'},
        {'symbol': 'ETH_USDT', 'fundingRate': '0.0008'},
        {'symbol': 'SOL_USDT', 'fundingRate': '0.0006'}
    ]
    
    client.get_available_perpetual_symbols.return_value = [
        "BTC_USDT", "ETH_USDT", "SOL_USDT", "OTHER_USDT"
    ]
    
    return client


@pytest.fixture
def funding_time():
    """
    Fixture that provides a mock funding time for testing.
    
    This fixture creates a fixed datetime object representing a funding time
    (August 2, 2025, 16:00 UTC), which is used consistently across tests to
    ensure reproducible results when testing time-dependent functions.
    
    Returns:
        datetime: A datetime object with timezone information (UTC).
    """
    return datetime(2025, 8, 2, 16, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def mock_config():
    """
    Fixture that provides a mock configuration for testing.
    
    This fixture creates a configuration dictionary with time window settings
    for different timeframes (daily, hourly, 10-minute, and 1-minute candles).
    These settings control how far back in time the data collection goes for
    each timeframe.
    
    Returns:
        dict: A configuration dictionary with time window settings.
    """
    return {
        'funding': {
            'time_windows': {
                'daily_days_back': 3,
                'hourly_hours_back': 8,
                'ten_min_hours_before': 1,
                'one_min_minutes_before': 10,
                'one_min_minutes_after': 10
            }
        }
    }


def test_collect_and_save_data(mock_client, funding_time, mock_config):
    """
    Test that collect_and_save_data correctly fetches and saves all required candle types.
    
    This test verifies that:
    - The function retrieves OHLCV data for all required timeframes (daily, hourly, 10m, 1m)
    - It calls the client's get_futures_ohlcv method the correct number of times
    - It passes the collected data to save_data_to_csv with the correct format
    - All timeframe data is included in the saved data
    
    Args:
        mock_client: Fixture providing a mocked MEXCContractClient
        funding_time: Fixture providing a consistent funding time for testing
        mock_config: Fixture providing a mock configuration with time window settings
    """
    with patch('pipeline.funding_rate_logger.save_data_to_csv') as mock_save:
        with patch('pipeline.funding_rate_logger.load_config', return_value=mock_config):
            collect_and_save_data(mock_client, "BTC_USDT", funding_time, mock_config['funding'])
        
        assert mock_client.get_futures_ohlcv.call_count == 4, "Should call get_futures_ohlcv 4 times for different timeframes"
        
        mock_save.assert_called_once()
        call_args = mock_save.call_args[0]
        assert call_args[0] == "BTC_USDT", "Symbol should be passed correctly to save_data_to_csv"
        assert call_args[1] == funding_time, "Funding time should be passed correctly to save_data_to_csv"
        assert 'daily' in call_args[2], "Daily candles should be included in saved data"
        assert '1h' in call_args[2], "Hourly candles should be included in saved data"
        assert '10m' in call_args[2], "10-minute candles should be included in saved data"
        assert '1m' in call_args[2], "1-minute candles should be included in saved data"


def test_log_funding_snapshot_15min_window(mock_client, funding_time, mock_config):
    """
    Test that log_funding_snapshot correctly identifies and handles 15-minute window before funding.
    
    This test verifies that when the current time is 15 minutes before a funding event:
    - The function correctly identifies the upcoming funding time
    - It caches the top symbols with highest funding rates for later use
    - It passes the correct parameters to the cache_top_symbols function
    
    This test focuses on the first phase of the two-phase data collection strategy,
    where symbols are identified and cached 15 minutes before funding.
    
    Args:
        mock_client: Fixture providing a mocked MEXCContractClient
        funding_time: Fixture providing a consistent funding time for testing
        mock_config: Fixture providing a mock configuration with time window settings
    """
    with patch('pipeline.funding_rate_logger.datetime') as mock_datetime:
        with patch('pipeline.funding_rate_logger.cache_top_symbols') as mock_cache:
            # Set the current time to 15 minutes before funding
            mock_now = datetime(2025, 8, 2, 15, 45, 0, tzinfo=timezone.utc)
            mock_datetime.now.return_value = mock_now
            
            with patch('pipeline.funding_rate_logger.get_next_funding_times', return_value=[funding_time]):
                log_funding_snapshot(mock_client, config=mock_config['funding'])
                
                mock_cache.assert_called_once(), "cache_top_symbols should be called once"
                assert mock_cache.call_args[0][0] == ["BTC_USDT", "ETH_USDT", "SOL_USDT"], "Top symbols should be passed correctly to cache_top_symbols"
                assert mock_cache.call_args[0][1] == funding_time, "Funding time should be passed correctly to cache_top_symbols"


def test_log_funding_snapshot_10min_window(mock_client, funding_time, mock_config):
    """
    Test that log_funding_snapshot correctly identifies and handles 10-minute window before funding.
    
    This test verifies that when the current time is 10 minutes before a funding event:
    - The function correctly identifies the upcoming funding time
    - It loads the previously cached symbols (from the 15-minute window)
    - It calls collect_and_save_data for each of the cached symbols
    - It passes the correct parameters to each function
    
    This test focuses on the second phase of the two-phase data collection strategy,
    where previously cached symbols are retrieved and data is collected 10 minutes
    before funding.
    
    Args:
        mock_client: Fixture providing a mocked MEXCContractClient
        funding_time: Fixture providing a consistent funding time for testing
        mock_config: Fixture providing a mock configuration with time window settings
    """
    with patch('pipeline.funding_rate_logger.datetime') as mock_datetime:
        with patch('pipeline.funding_rate_logger.load_cached_symbols') as mock_load:
            with patch('pipeline.funding_rate_logger.collect_and_save_data') as mock_collect:
                # Set the current time to 20 minutes after funding
                mock_now = datetime(2025, 8, 2, 16, 20, 0, tzinfo=timezone.utc)
                mock_datetime.now.return_value = mock_now
                
                with patch('pipeline.funding_rate_logger.get_next_funding_times', return_value=[funding_time]):
                    mock_load.return_value = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
                    
                    log_funding_snapshot(mock_client, config=mock_config['funding'])
                    
                    # Check that load_cached_symbols was called with the correct funding_time
                    assert mock_load.call_count == 1, "load_cached_symbols should be called once"
                    assert mock_load.call_args[0][0] == funding_time, "Funding time should be passed correctly to load_cached_symbols"
                    
                    assert mock_collect.call_count == 3, "collect_and_save_data should be called for each symbol"
                    mock_collect.assert_any_call(mock_client, "BTC_USDT", funding_time, mock_config['funding']), "collect_and_save_data should be called for BTC_USDT"
                    mock_collect.assert_any_call(mock_client, "ETH_USDT", funding_time, mock_config['funding']), "collect_and_save_data should be called for ETH_USDT"
                    mock_collect.assert_any_call(mock_client, "SOL_USDT", funding_time, mock_config['funding']), "collect_and_save_data should be called for SOL_USDT"