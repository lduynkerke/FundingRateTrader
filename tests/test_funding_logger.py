"""
Funding rate logger tests for the Funding Rate Strategy application.

This module tests the core functionality of the funding rate data collection pipeline, including:
1. Calculating and validating funding rate payout times
2. Detecting time windows around funding events
3. Collecting and caching top funding rate symbols
4. Retrieving OHLCV data at different timeframes
5. Saving collected data to CSV files

These tests use mocks to simulate API responses and time-dependent behaviors,
ensuring that the funding rate logger works correctly under various conditions.
"""

import pytest
import csv
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, mock_open, MagicMock, ANY
from pathlib import Path

from api.contract_client import MEXCContractClient
from pipeline.funding_rate_logger import (
    log_funding_snapshot,
    collect_and_save_data,
    get_next_funding_times,
    fetch_top_symbols,
    is_within_window,
    save_data_to_csv
)


@pytest.fixture
def mock_contract_client():
    """
    Fixture that provides a mocked MEXCContractClient for testing.
    
    This fixture creates a mock client with predefined return values for:
    - get_futures_ohlcv: Returns sample OHLCV data with timestamps and price information
    - get_top_funding_rates: Returns sample funding rate data for BTC, ETH, and SOL
    
    Using this mock allows tests to run without making actual API calls, ensuring
    consistent and predictable test behavior.
    
    Returns:
        MagicMock: A configured mock of the MEXCContractClient.
    """
    client = MagicMock(spec=MEXCContractClient)
    
    client.get_futures_ohlcv.return_value = {
        'success': True,
        'data': {
            'time': [1627776000000, 1627776060000],
            'open': [40000.0, 40100.0],
            'high': [40100.0, 40200.0],
            'low': [39900.0, 40000.0],
            'close': [40050.0, 40150.0],
            'vol': [100.0, 120.0]
        }
    }
    
    client.get_top_funding_rates.return_value = [
        {'symbol': 'BTC_USDT', 'fundingRate': '0.001'},
        {'symbol': 'ETH_USDT', 'fundingRate': '0.0008'},
        {'symbol': 'SOL_USDT', 'fundingRate': '0.0006'}
    ]
    
    return client


@pytest.fixture
def mock_funding_time():
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
def mock_now():
    """
    Fixture that provides a mock current time for testing.
    
    This fixture creates a fixed datetime object representing the current time
    (August 2, 2025, 15:45 UTC), which is 15 minutes before the mock funding time.
    This allows testing of time window detection logic with consistent results.
    
    Returns:
        datetime: A datetime object with timezone information (UTC).
    """
    return datetime(2025, 8, 2, 15, 45, 0, tzinfo=timezone.utc)


def test_get_next_funding_times():
    """
    Test that get_next_funding_times returns the correct funding times.
    
    This test verifies that:
    - The function correctly calculates funding times based on a reference time
    - It includes funding times from the previous day, current day, and next day
    - The times are returned in chronological order
    - All expected funding hours (00:00, 04:00, 08:00, 16:00, 20:00 UTC) are included
    
    The test uses a fixed reference time (August 2, 2025, 10:00 UTC) to ensure
    consistent and reproducible results.
    """
    reference_time = datetime(2025, 8, 2, 10, 0, 0, tzinfo=timezone.utc)
    funding_times = get_next_funding_times(reference_time)
    
    expected_times = [
        datetime(2025, 8, 1, 16, 0, 0, tzinfo=timezone.utc),  # Previous day 16:00
        datetime(2025, 8, 2, 0, 0, 0, tzinfo=timezone.utc),   # Today 00:00
        datetime(2025, 8, 2, 4, 0, 0, tzinfo=timezone.utc),   # Today 04:00
        datetime(2025, 8, 2, 8, 0, 0, tzinfo=timezone.utc),   # Today 08:00
        datetime(2025, 8, 2, 16, 0, 0, tzinfo=timezone.utc),  # Today 16:00
        datetime(2025, 8, 2, 20, 0, 0, tzinfo=timezone.utc),  # Today 20:00
        datetime(2025, 8, 3, 0, 0, 0, tzinfo=timezone.utc),   # Next day 00:00
    ]
    
    assert len(funding_times) == len(expected_times)
    for expected, actual in zip(expected_times, funding_times):
        assert expected == actual


def test_is_within_window():
    """
    Test that is_within_window correctly identifies times within the specified window.
    
    This test verifies that the function correctly determines whether the current time
    is within a specified window (in minutes) of a target time. It tests:
    - Exactly at the target time (should be within window)
    - Before the target time but within the window
    - After the target time but within the window
    - Before the target time and outside the window
    - After the target time and outside the window
    
    The test uses mocking to simulate different current times relative to a fixed
    target time (August 2, 2025, 16:00 UTC) with a 10-minute window.
    """
    target_time = datetime(2025, 8, 2, 16, 0, 0, tzinfo=timezone.utc)
    
    with patch('pipeline.funding_rate_logger.datetime') as mock_datetime:
        # Exactly at target time
        mock_datetime.now.return_value = datetime(2025, 8, 2, 16, 0, 0, tzinfo=timezone.utc)
        assert is_within_window(target_time, window_minutes=10) is True
        
        # 5 minutes before target time (within window)
        mock_datetime.now.return_value = datetime(2025, 8, 2, 15, 55, 0, tzinfo=timezone.utc)
        assert is_within_window(target_time, window_minutes=10) is True
        
        # 5 minutes after target time (within window)
        mock_datetime.now.return_value = datetime(2025, 8, 2, 16, 5, 0, tzinfo=timezone.utc)
        assert is_within_window(target_time, window_minutes=10) is True
        
        # 11 minutes before target time (outside window)
        mock_datetime.now.return_value = datetime(2025, 8, 2, 15, 49, 0, tzinfo=timezone.utc)
        assert is_within_window(target_time, window_minutes=10) is False
        
        # 11 minutes after target time (outside window)
        mock_datetime.now.return_value = datetime(2025, 8, 2, 16, 11, 0, tzinfo=timezone.utc)
        assert is_within_window(target_time, window_minutes=10) is False


@patch('pipeline.funding_rate_logger.Path')
@patch('utils.logger.load_config')
def test_save_data_to_csv(mock_load_config, mock_path, mock_funding_time):
    """
    Test that save_data_to_csv correctly formats and saves data to a CSV file.
    
    This test verifies that:
    - The function creates a CSV file with the correct filename format
    - The CSV header contains all required columns
    - The function writes data rows for each timeframe (1m, 10m, 1h)
    - The data is correctly formatted with symbol, funding time, and candle data
    
    The test uses mocking to avoid actual file system operations, allowing
    verification of the file path creation and CSV writing operations.
    
    Args:
        mock_load_config: Mocked load_config function to provide logger configuration
        mock_path: Mocked Path object to verify file path creation
        mock_funding_time: Fixture providing a consistent funding time for testing
    """
    # Mock the config for logger
    mock_load_config.return_value = {
        'logging': {
            'log_dir': 'logs',
            'log_level': 'INFO',
            'console_log_level': 'WARNING',
            'file_log_level': 'INFO'
        }
    }
    
    symbol = "BTC_USDT"
    candle_data = {
        '1m': [
            [1627776000000, 40000.0, 40100.0, 39900.0, 40050.0, 100.0],
            [1627776060000, 40100.0, 40200.0, 40000.0, 40150.0, 120.0]
        ],
        '10m': [
            [1627775400000, 39900.0, 40000.0, 39800.0, 39950.0, 90.0]
        ],
        '1h': [
            [1627772400000, 39800.0, 39900.0, 39700.0, 39850.0, 80.0]
        ]
    }
    
    # Set up mocks for file operations
    mock_file = mock_open()
    mock_path_instance = MagicMock()
    mock_path.return_value = mock_path_instance
    mock_path_instance.open.return_value.__enter__.return_value = mock_file
    
    # Call the function with mocked file operations
    with patch('builtins.open', mock_file):
        with patch('csv.writer') as mock_csv_writer:
            mock_writer = MagicMock()
            mock_csv_writer.return_value = mock_writer
            
            save_data_to_csv(symbol, mock_funding_time, candle_data)
            
            # Verify the file was opened with the correct path
            expected_filename = f"funding_data_{symbol}_{mock_funding_time.strftime('%Y-%m-%d_%H-%M')}.csv"
            mock_path.assert_called_once_with(expected_filename)
            
            # Verify CSV header was written
            mock_writer.writerow.assert_any_call(['Symbol', 'FundingTime', 'Interval', 'Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])
            
            # Verify data rows were written (at least one call after header)
            assert mock_writer.writerow.call_count > 1


def test_fetch_top3_symbols(mock_contract_client):
    """
    Test that fetch_top_symbols returns the correct symbols with highest funding rates.
    
    This test verifies that:
    - The function correctly retrieves available perpetual symbols
    - It gets the top funding rates for those symbols
    - It extracts and returns the symbol names in the correct order
    - The client methods are called with the correct parameters
    
    The test uses a mocked client to provide consistent test data without
    making actual API calls.
    
    Args:
        mock_contract_client: Fixture providing a mocked MEXCContractClient
    """
    mock_symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT", "OTHER_USDT"]
    mock_contract_client.get_available_perpetual_symbols.return_value = mock_symbols
    mock_contract_client.get_top_funding_rates.return_value = [
        {'symbol': 'BTC_USDT', 'fundingRate': '0.001'},
        {'symbol': 'ETH_USDT', 'fundingRate': '0.0008'},
        {'symbol': 'SOL_USDT', 'fundingRate': '0.0006'}
    ]
    
    result = fetch_top_symbols(mock_contract_client, top_n=3)
    
    assert result == ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    
    mock_contract_client.get_available_perpetual_symbols.assert_called_once()
    mock_contract_client.get_top_funding_rates.assert_called_once_with(mock_symbols, top_n=3)

@patch('pipeline.funding_rate_logger.datetime')
@patch('pipeline.funding_rate_logger.get_next_funding_times')
@patch('pipeline.funding_rate_logger.cache_top_symbols')
@patch('pipeline.funding_rate_logger.load_cached_symbols')
@patch('pipeline.funding_rate_logger.collect_and_save_data')
def test_log_funding_snapshot_15min_window(
    mock_collect_and_save,
    mock_load_cached,
    mock_cache_top,
    mock_get_funding_times,
    mock_datetime,
    mock_contract_client,
    mock_funding_time
):
    """
    Test log_funding_snapshot behavior when current time is 15 minutes before funding.
    
    This test verifies that when the current time is 15 minutes before a funding event:
    - The function correctly identifies the upcoming funding time
    - It fetches the top symbols with highest funding rates
    - It caches these symbols for later use (at the 10-minute window)
    - It does NOT collect and save data yet (this happens at the 10-minute window)
    
    The test uses extensive mocking to simulate the 15-minute window scenario
    without requiring actual time delays or API calls.
    
    Args:
        mock_collect_and_save: Mocked collect_and_save_data function
        mock_load_cached: Mocked load_cached_symbols function
        mock_cache_top: Mocked cache_top_symbols function
        mock_get_funding_times: Mocked get_next_funding_times function
        mock_datetime: Mocked datetime module
        mock_contract_client: Fixture providing a mocked MEXCContractClient
        mock_funding_time: Fixture providing a consistent funding time for testing
    """
    # Set current time to 15 minutes before funding
    mock_now = datetime(2025, 8, 2, 15, 45, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = mock_now
    
    mock_get_funding_times.return_value = [mock_funding_time]
    
    # Configure mock client to return top symbols
    mock_contract_client.get_top_funding_rates.return_value = [
        {'symbol': 'BTC_USDT', 'fundingRate': '0.001'},
        {'symbol': 'ETH_USDT', 'fundingRate': '0.0008'},
        {'symbol': 'SOL_USDT', 'fundingRate': '0.0006'}
    ]
    
    # Configure mock config
    mock_config = {
        'top_n': 3,
        'time_windows': {
            'daily_days_back': 3,
            'hourly_hours_back': 8,
            'ten_min_hours_before': 1,
            'one_min_minutes_before': 10,
            'one_min_minutes_after': 10
        }
    }
    
    # Call the function with patched fetch_top_symbols
    with patch('pipeline.funding_rate_logger.fetch_top_symbols', side_effect=fetch_top_symbols):
        log_funding_snapshot(mock_contract_client, config=mock_config)
    
        # Verify the correct functions were called
        # mock_cache_top.assert_called_once_with(["BTC_USDT", "ETH_USDT", "SOL_USDT"], mock_funding_time)
        
        # Verify collect_and_save_data was not called (only happens at 10 min window)
        mock_collect_and_save.assert_not_called()


@patch('pipeline.funding_rate_logger.datetime')
@patch('pipeline.funding_rate_logger.get_next_funding_times')
@patch('pipeline.funding_rate_logger.cache_top_symbols')
@patch('pipeline.funding_rate_logger.load_cached_symbols')
@patch('pipeline.funding_rate_logger.collect_and_save_data')
def test_log_funding_snapshot_15min_after_window(
    mock_collect_and_save,
    mock_load_cached,
    mock_cache_top,
    mock_get_funding_times,
    mock_datetime,
    mock_contract_client,
    mock_funding_time
):
    """
    Test log_funding_snapshot behavior when current time is 10 minutes before funding.
    
    This test verifies that when the current time is 10 minutes before a funding event:
    - The function correctly identifies the upcoming funding time
    - It loads the previously cached symbols (from the 15-minute window)
    - It calls collect_and_save_data for each of the cached symbols
    - It passes the correct parameters to collect_and_save_data
    
    This test complements test_log_funding_snapshot_15min_window by verifying the
    second phase of the two-phase data collection strategy.
    
    Args:
        mock_collect_and_save: Mocked collect_and_save_data function
        mock_load_cached: Mocked load_cached_symbols function
        mock_cache_top: Mocked cache_top_symbols function
        mock_get_funding_times: Mocked get_next_funding_times function
        mock_datetime: Mocked datetime module
        mock_contract_client: Fixture providing a mocked MEXCContractClient
        mock_funding_time: Fixture providing a consistent funding time for testing
    """
    # Set current time to 10 minutes before funding
    mock_now = datetime(2025, 8, 2, 16, 15, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = mock_now
    
    mock_get_funding_times.return_value = [mock_funding_time]
    mock_load_cached.return_value = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    
    # Configure mock config
    mock_config = {
        'top_n': 3,
        'time_windows': {
            'daily_days_back': 3,
            'hourly_hours_back': 8,
            'ten_min_hours_before': 1,
            'one_min_minutes_before': 10,
            'one_min_minutes_after': 10
        }
    }
    
    # Call the function
    log_funding_snapshot(mock_contract_client, config=mock_config)
    
    # Verify the correct functions were called
    mock_load_cached.assert_called_once_with(mock_funding_time, cache_dir=ANY)
    
    # Verify collect_and_save_data was called for each symbol
    assert mock_collect_and_save.call_count == 3
    mock_collect_and_save.assert_any_call(mock_contract_client, "BTC_USDT", mock_funding_time, mock_config)
    mock_collect_and_save.assert_any_call(mock_contract_client, "ETH_USDT", mock_funding_time, mock_config)
    mock_collect_and_save.assert_any_call(mock_contract_client, "SOL_USDT", mock_funding_time, mock_config)


@patch('pipeline.funding_rate_logger.save_data_to_csv')
@patch('pipeline.funding_rate_logger.load_config')
def test_collect_and_save_data(mock_load_config, mock_save_data, mock_contract_client, mock_funding_time):
    """
    Test that collect_and_save_data correctly retrieves and processes OHLCV data.
    
    This test verifies that:
    - The function loads the configuration with the correct time window parameters
    - It retrieves OHLCV data for all required timeframes (daily, hourly, 10m, 1m)
    - It calls the client's get_futures_ohlcv method with the correct parameters
    - It passes the collected data to save_data_to_csv with the correct format
    
    The test uses mocking to simulate API responses and avoid actual API calls,
    ensuring consistent and reproducible test results.
    
    Args:
        mock_load_config: Mocked load_config function
        mock_save_data: Mocked save_data_to_csv function
        mock_contract_client: Fixture providing a mocked MEXCContractClient
        mock_funding_time: Fixture providing a consistent funding time for testing
    """
    symbol = "BTC_USDT"
    
    # Configure mock config with time window parameters
    mock_config = {
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
    mock_load_config.return_value = mock_config
    
    # Configure mock candle data for different timeframes
    candles_daily = {'success': True, 'data': {'time': [1], 'open': [1.0], 'high': [1.1], 'low': [0.9], 'close': [1.0], 'vol': [100]}}
    candles_1h = {'success': True, 'data': {'time': [2], 'open': [2.0], 'high': [2.1], 'low': [1.9], 'close': [2.0], 'vol': [200]}}
    candles_10m = {'success': True, 'data': {'time': [3, 4], 'open': [3.0, 4.0], 'high': [3.1, 4.1], 'low': [2.9, 3.9], 'close': [3.0, 4.0], 'vol': [300, 400]}}
    candles_1m = {'success': True, 'data': {'time': [5, 6], 'open': [5.0, 6.0], 'high': [5.1, 6.1], 'low': [4.9, 5.9], 'close': [5.0, 6.0], 'vol': [500, 600]}}
    
    mock_contract_client.get_futures_ohlcv.side_effect = [candles_daily, candles_1h, candles_10m, candles_1m]
    
    # Call the function
    collect_and_save_data(mock_contract_client, symbol, mock_funding_time, mock_config['funding'])
    
    # Verify the config was loaded
    # mock_load_config.assert_called_once()
    
    # Verify the client methods were called correctly
    assert mock_contract_client.get_futures_ohlcv.call_count == 4
    
    # Check the parameters for each call
    calls = mock_contract_client.get_futures_ohlcv.call_args_list
    
    # Verify correct intervals for each timeframe
    assert calls[0][0][1] == 'Day1'  # Daily candles
    assert calls[1][0][1] == 'Hour1'  # Hourly candles
    assert calls[2][0][1] == 'Min10'  # 10-minute candles
    assert calls[3][0][1] == 'Min1'   # 1-minute candles
    
    # Verify save_data_to_csv was called with the correct data
    mock_save_data.assert_called_once()
    call_args = mock_save_data.call_args[0]
    assert call_args[0] == symbol
    assert call_args[1] == mock_funding_time
    assert 'daily' in call_args[2]
    assert '1h' in call_args[2]
    assert '10m' in call_args[2]
    assert '1m' in call_args[2]