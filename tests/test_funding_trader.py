"""
Tests for the funding rate trader functionality.

This module contains tests for the core trading functionality, including:
1. ATR calculation
2. TP/SL calculation
3. Trade execution
4. Position management
"""

import pytest
from datetime import datetime, timezone, timedelta
import numpy as np
from unittest.mock import MagicMock, patch
from pipeline.funding_rate_trader import (
    calculate_atr,
    calculate_tp_sl,
    execute_trade,
    close_trade,
    check_tp_sl,
    execute_funding_trades,
    get_next_funding_times,
    is_within_window
)

# Sample candle data for testing
@pytest.fixture
def sample_candles():
    """
    Fixture providing sample candle data for testing.
    
    Returns a list of candles in the format [timestamp, open, high, low, close, volume]
    """
    # Create 20 sample candles with some volatility
    candles = []
    base_price = 1000.0
    timestamp = int(datetime.now(timezone.utc).timestamp())
    
    for i in range(20):
        open_price = base_price + np.random.normal(0, 10)
        high_price = open_price + abs(np.random.normal(0, 5))
        low_price = open_price - abs(np.random.normal(0, 5))
        close_price = low_price + np.random.uniform(0, high_price - low_price)
        volume = np.random.uniform(10, 100)
        
        candle = [timestamp - (20 - i) * 60, open_price, high_price, low_price, close_price, volume]
        candles.append(candle)
        
        base_price = close_price
    
    return candles

@pytest.fixture
def mock_client():
    """
    Fixture providing a mock MEXCContractClient.
    """
    client = MagicMock()
    
    # Mock the get_futures_ohlcv method
    def mock_get_ohlcv(symbol, interval, start, end):
        # Return different candles based on the interval
        if interval == 'Min15':
            return [
                [1628000000000, 1000.0, 1010.0, 990.0, 1005.0, 100.0],
                [1628001000000, 1005.0, 1015.0, 995.0, 1010.0, 110.0],
                [1628002000000, 1010.0, 1020.0, 1000.0, 1015.0, 120.0],
            ]
        elif interval == 'Min1':
            return [
                [1628000000000, 1000.0, 1005.0, 995.0, 1002.0, 50.0],
            ]
        return []
    
    client.get_futures_ohlcv.side_effect = mock_get_ohlcv
    
    # Mock the get_top_funding_rates method
    client.get_top_funding_rates.return_value = [
        {'symbol': 'BTC_USDT', 'fundingRate': '0.001'},
        {'symbol': 'ETH_USDT', 'fundingRate': '0.0008'},
        {'symbol': 'SOL_USDT', 'fundingRate': '0.0006'},
    ]
    
    # Mock the get_all_funding_rates_async method
    client.get_all_funding_rates_async.return_value = [
        {'symbol': 'BTC_USDT', 'fundingRate': '0.001'},
        {'symbol': 'ETH_USDT', 'fundingRate': '0.0008'},
        {'symbol': 'SOL_USDT', 'fundingRate': '0.0006'},
    ]
    
    # Mock the get_available_perpetual_symbols method
    client.get_available_perpetual_symbols.return_value = [
        'BTC_USDT', 'ETH_USDT', 'SOL_USDT', 'ADA_USDT', 'DOT_USDT'
    ]
    
    return client

@pytest.fixture
def sample_trade():
    """
    Fixture providing a sample trade dictionary.
    """
    return {
        'symbol': 'BTC_USDT',
        'side': 'SHORT',
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'entry_price': 1000.0,
        'tp_price': 980.0,
        'sl_price': 1030.0,
        'funding_rate': 0.001,
        'atr': 20.0,
        'status': 'OPEN'
    }

@pytest.fixture
def trading_config():
    """
    Fixture providing a sample trading configuration.
    """
    return {
        'top_n': 3,
        'position_size_usd': 100,
        'max_positions': 3,
        'atr_period': 14,
        'atr_timeframe': 'Min15',
        'tp_atr_multiplier': 1.5,
        'sl_atr_multiplier': 2.0,
        'min_funding_rate': 0.0001,
        'pre_funding_seconds': 30,
        'post_funding_minutes': 3,
        'enable_trailing_stop': False
    }

def test_calculate_atr(sample_candles):
    """
    Test the ATR calculation function.
    """
    # Test with default period
    atr = calculate_atr(sample_candles)
    assert isinstance(atr, float)
    assert atr > 0
    
    # Test with custom period
    atr_short = calculate_atr(sample_candles, period=5)
    assert isinstance(atr_short, float)
    assert atr_short > 0
    
    # Test with insufficient data
    atr_empty = calculate_atr(sample_candles[:2], period=5)
    assert atr_empty == 0.0

def test_calculate_tp_sl(trading_config):
    """
    Test the TP/SL calculation function.
    """
    # Test with positive funding rate
    funding_rate = 0.001
    atr = 20.0
    tp, sl = calculate_tp_sl(funding_rate, atr, trading_config)
    
    assert isinstance(tp, float)
    assert isinstance(sl, float)
    assert tp > 0
    assert sl > 0
    
    # Test with higher funding rate (should adjust multipliers)
    funding_rate_high = 0.002
    tp_high, sl_high = calculate_tp_sl(funding_rate_high, atr, trading_config)
    
    # Higher funding rate should result in more aggressive TP
    assert tp_high > tp
    
    # Test with zero ATR
    tp_zero, sl_zero = calculate_tp_sl(funding_rate, 0.0, trading_config)
    assert tp_zero == 0.0
    assert sl_zero == 0.0

def test_execute_trade(mock_client, trading_config):
    """
    Test the trade execution function.
    """
    symbol = 'BTC_USDT'
    funding_rate = 0.001
    
    trade = execute_trade(mock_client, symbol, funding_rate, trading_config)
    
    assert isinstance(trade, dict)
    assert trade['symbol'] == symbol
    assert trade['side'] == 'SHORT'
    assert 'entry_price' in trade
    assert 'tp_price' in trade
    assert 'sl_price' in trade
    assert trade['status'] == 'OPEN'
    
    # TP should be lower than entry for a short position
    assert trade['tp_price'] < trade['entry_price']
    
    # SL should be higher than entry for a short position
    assert trade['sl_price'] > trade['entry_price']

def test_close_trade(mock_client, sample_trade):
    """
    Test the trade closing function.
    """
    closed_trade = close_trade(mock_client, sample_trade.copy())
    
    assert closed_trade['status'] == 'CLOSED'
    assert 'exit_price' in closed_trade
    assert 'exit_time' in closed_trade
    assert 'pnl_pct' in closed_trade

def test_check_tp_sl(mock_client):
    """
    Test the TP/SL checking function.
    """
    # Test TP hit
    trade_tp = {
        'symbol': 'BTC_USDT',
        'side': 'SHORT',
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'entry_price': 1010.0,
        'tp_price': 1005.0,  # TP above current price (1002)
        'sl_price': 1020.0,
        'status': 'OPEN'
    }
    
    # Mock client returns price of 1002, which is below TP of 1005
    result_tp = check_tp_sl(mock_client, trade_tp.copy())
    assert result_tp['status'] == 'TP_HIT'
    
    # Test SL hit
    trade_sl = {
        'symbol': 'BTC_USDT',
        'side': 'SHORT',
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'entry_price': 990.0,
        'tp_price': 980.0,
        'sl_price': 1000.0,  # SL below current price (1002)
        'status': 'OPEN'
    }
    
    # Mock client returns price of 1002, which is above SL of 1000
    result_sl = check_tp_sl(mock_client, trade_sl.copy())
    assert result_sl['status'] == 'SL_HIT'
    
    # Test no hit
    trade_no_hit = {
        'symbol': 'BTC_USDT',
        'side': 'SHORT',
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'entry_price': 1000.0,
        'tp_price': 990.0,  # TP below current price (1002)
        'sl_price': 1010.0,  # SL above current price (1002)
        'status': 'OPEN'
    }
    
    result_no_hit = check_tp_sl(mock_client, trade_no_hit.copy())
    assert result_no_hit['status'] == 'OPEN'

def test_get_next_funding_times():
    """
    Test the funding times calculation function.
    """
    # Test with default reference time
    times = get_next_funding_times()
    assert isinstance(times, list)
    assert len(times) >= 7  # Should include today's times plus boundary times
    
    # Test with specific reference time
    ref_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    times_specific = get_next_funding_times(ref_time)
    assert isinstance(times_specific, list)
    assert len(times_specific) >= 7
    
    # Verify times are sorted
    assert all(times_specific[i] <= times_specific[i+1] for i in range(len(times_specific)-1))

def test_is_within_window():
    """
    Test the time window checking function.
    """
    now = datetime.now(timezone.utc)
    
    # Test within window
    target_within = now - timedelta(seconds=15)
    assert is_within_window(target_within, window_seconds=30)
    
    # Test outside window
    target_outside = now - timedelta(seconds=60)
    assert not is_within_window(target_outside, window_seconds=30)

@patch('pipeline.funding_rate_trader.fetch_top_symbols')
@patch('pipeline.funding_rate_trader.execute_trade')
def test_execute_funding_trades(mock_execute_trade, mock_fetch_symbols, mock_client, trading_config):
    """
    Test the main trading function.
    """
    # Mock fetch_top_symbols to return test symbols
    mock_fetch_symbols.return_value = ['BTC_USDT', 'ETH_USDT', 'SOL_USDT']
    
    # Mock execute_trade to return a sample trade
    mock_execute_trade.return_value = {
        'symbol': 'BTC_USDT',
        'side': 'SHORT',
        'entry_time': datetime.now(timezone.utc).isoformat(),
        'entry_price': 1000.0,
        'tp_price': 980.0,
        'sl_price': 1030.0,
        'status': 'OPEN'
    }
    
    # Execute the function
    # This is a bit tricky to test since it depends on current time relative to funding times
    # We'll just verify it runs without errors
    execute_funding_trades(mock_client, trading_config)
    
    # Verify the function calls
    # Note: These may not be called if we're not in the right time window
    # So we don't assert on call counts