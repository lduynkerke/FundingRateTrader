"""
Funding rate trading strategy implementation.

This module implements the core functionality for trading based on cryptocurrency funding rates.
It handles:

1. Identifying upcoming funding rate payout times
2. Finding the highest funding rate symbols before each payout
3. Entering short positions 30 seconds before funding events
4. Setting take profit and stop loss based on funding rate and 15-minute ATR
5. Closing positions 3 minutes after funding events if TP/SL hasn't been hit

The module is designed to be called periodically and will automatically determine
when to execute trades based on proximity to funding times.
"""

import csv
import os
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone
import numpy as np
from api.contract_client import MEXCContractClient
from utils.funding_rate_cache import cache_top_symbols, load_cached_symbols, cleanup_old_caches
from utils.config_loader import load_config
from utils.logger import get_logger

CACHE_DIR = Path("cache/funding_rates")

def fetch_top_symbols(client: MEXCContractClient, top_n: int = 3) -> list[str]:
    """
    Fetches the top N symbols with highest absolute funding rates.

    :param client: Initialized MEXCContractClient.
    :type client: MEXCContractClient
    :param top_n: Number of top symbols to return.
    :type top_n: int
    :return: List of top N symbols.
    :rtype: list[str]
    """
    logger = get_logger()
    logger.info(f"Fetching top {top_n} symbols with highest funding rates")
    try:
        symbols = client.get_available_perpetual_symbols()
        top_rates = client.get_top_funding_rates(symbols, top_n=top_n)
        top_symbols = [entry['symbol'] for entry in top_rates]
        logger.info(f"Successfully fetched top {len(top_symbols)} symbols: {', '.join(top_symbols)}")
        return top_symbols
    except Exception as e:
        logger.error(f"Error fetching top symbols: {e}")
        return []

def calculate_atr(candles: List[list], period: int = 14) -> float:
    """
    Calculate the Average True Range (ATR) from a list of candles.
    
    :param candles: List of candles in format [timestamp, open, high, low, close, volume]
    :type candles: List[list]
    :param period: Period for ATR calculation
    :type period: int
    :return: ATR value
    :rtype: float
    """
    if not candles or len(candles) < period:
        return 0.0
    
    highs = np.array([float(candle[2]) for candle in candles])
    lows = np.array([float(candle[3]) for candle in candles])
    closes = np.array([float(candle[4]) for candle in candles])
    
    # Calculate True Range
    tr1 = np.abs(highs[1:] - lows[1:])
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    
    true_ranges = np.maximum(tr1, np.maximum(tr2, tr3))
    
    # Calculate ATR
    atr = np.mean(true_ranges[-period:])
    return atr

def calculate_tp_sl(funding_rate: float, atr: float, config: Dict) -> Tuple[float, float]:
    """
    Calculate take profit and stop loss levels based on funding rate and ATR.
    
    :param funding_rate: Current funding rate
    :type funding_rate: float
    :param atr: Average True Range
    :type atr: float
    :param config: Configuration dictionary
    :type config: Dict
    :return: Tuple of (take_profit_pct, stop_loss_pct)
    :rtype: Tuple[float, float]
    """
    # Base TP on funding rate (higher funding rate = higher potential profit)
    tp_multiplier = config.get('tp_atr_multiplier', 1.5)
    sl_multiplier = config.get('sl_atr_multiplier', 2.0)
    
    # Adjust multipliers based on funding rate magnitude
    funding_rate_abs = abs(funding_rate)
    if funding_rate_abs > 0.001:  # 0.1%
        tp_multiplier *= 1.2
        sl_multiplier *= 0.8
    
    take_profit_pct = atr * tp_multiplier / 100  # Convert to percentage
    stop_loss_pct = atr * sl_multiplier / 100    # Convert to percentage
    
    return (take_profit_pct, stop_loss_pct)

def execute_trade(client: MEXCContractClient, symbol: str, funding_rate: float, config: Dict) -> Dict:
    """
    Execute a short trade for a symbol before funding time.
    
    :param client: Initialized MEXCContractClient
    :type client: MEXCContractClient
    :param symbol: Trading symbol
    :type symbol: str
    :param funding_rate: Current funding rate
    :type funding_rate: float
    :param config: Trading configuration
    :type config: Dict
    :return: Trade details
    :rtype: Dict
    """
    logger = get_logger()
    logger.info(f"Executing short trade for {symbol} with funding rate {funding_rate}")
    
    # Get 15-minute candles for ATR calculation
    now = datetime.now(timezone.utc)
    end_time = int(now.timestamp())
    start_time = end_time - (15 * 15 * 60)  # 15 candles of 15 minutes
    
    try:
        # Get 15-minute candles
        candles_15m = client.get_futures_ohlcv(symbol, 'Min15', start_time, end_time)
        
        # Calculate ATR
        atr = calculate_atr(candles_15m, period=config.get('atr_period', 14))
        logger.info(f"Calculated ATR for {symbol}: {atr}")
        
        # Calculate TP and SL levels
        tp_pct, sl_pct = calculate_tp_sl(funding_rate, atr, config)
        
        # Get current price
        latest_candle = candles_15m[-1] if candles_15m else None
        if not latest_candle:
            logger.error(f"No candle data available for {symbol}")
            return {}
        
        entry_price = float(latest_candle[4])  # Use close price as entry
        
        # Calculate TP and SL prices
        tp_price = entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 + sl_pct)
        
        # Log trade details
        logger.info(f"Trade details for {symbol}:")
        logger.info(f"  Entry Price: {entry_price}")
        logger.info(f"  Take Profit: {tp_price} ({tp_pct:.4f}%)")
        logger.info(f"  Stop Loss: {sl_price} ({sl_pct:.4f}%)")
        
        # In a real implementation, this would call the exchange API to place the order
        # For now, we'll just return the trade details
        trade = {
            'symbol': symbol,
            'side': 'SHORT',
            'entry_time': now.isoformat(),
            'entry_price': entry_price,
            'tp_price': tp_price,
            'sl_price': sl_price,
            'funding_rate': funding_rate,
            'atr': atr,
            'status': 'OPEN'
        }
        
        return trade
        
    except Exception as e:
        logger.error(f"Error executing trade for {symbol}: {e}")
        return {}

def close_trade(client: MEXCContractClient, trade: Dict) -> Dict:
    """
    Close an open trade.
    
    :param client: Initialized MEXCContractClient
    :type client: MEXCContractClient
    :param trade: Trade details
    :type trade: Dict
    :return: Updated trade details
    :rtype: Dict
    """
    logger = get_logger()
    logger.info(f"Closing trade for {trade['symbol']}")
    
    # Get current price
    now = datetime.now(timezone.utc)
    end_time = int(now.timestamp())
    start_time = end_time - 60  # 1 minute
    
    try:
        candles_1m = client.get_futures_ohlcv(trade['symbol'], 'Min1', start_time, end_time)
        if not candles_1m:
            logger.error(f"No candle data available for {trade['symbol']}")
            return trade
        
        exit_price = float(candles_1m[-1][4])  # Use close price as exit
        
        # Calculate profit/loss
        entry_price = trade['entry_price']
        pnl_pct = (entry_price - exit_price) / entry_price * 100  # For short position
        
        # Update trade details
        trade['exit_time'] = now.isoformat()
        trade['exit_price'] = exit_price
        trade['pnl_pct'] = pnl_pct
        trade['status'] = 'CLOSED'
        
        logger.info(f"Closed trade for {trade['symbol']}:")
        logger.info(f"  Exit Price: {exit_price}")
        logger.info(f"  P&L: {pnl_pct:.4f}%")
        
        return trade
        
    except Exception as e:
        logger.error(f"Error closing trade for {trade['symbol']}: {e}")
        return trade

def check_tp_sl(client: MEXCContractClient, trade: Dict) -> Dict:
    """
    Check if take profit or stop loss has been hit.
    
    :param client: Initialized MEXCContractClient
    :type client: MEXCContractClient
    :param trade: Trade details
    :type trade: Dict
    :return: Updated trade details
    :rtype: Dict
    """
    logger = get_logger()
    
    # Get current price
    now = datetime.now(timezone.utc)
    end_time = int(now.timestamp())
    start_time = end_time - 60  # 1 minute
    
    try:
        candles_1m = client.get_futures_ohlcv(trade['symbol'], 'Min1', start_time, end_time)
        if not candles_1m:
            logger.error(f"No candle data available for {trade['symbol']}")
            return trade
        
        current_price = float(candles_1m[-1][4])  # Use close price
        
        # Check if TP or SL hit
        if current_price <= trade['tp_price']:
            logger.info(f"Take profit hit for {trade['symbol']} at {current_price}")
            trade['exit_price'] = trade['tp_price']
            trade['exit_time'] = now.isoformat()
            trade['status'] = 'TP_HIT'
            trade['pnl_pct'] = (trade['entry_price'] - trade['tp_price']) / trade['entry_price'] * 100
            return trade
            
        if current_price >= trade['sl_price']:
            logger.info(f"Stop loss hit for {trade['symbol']} at {current_price}")
            trade['exit_price'] = trade['sl_price']
            trade['exit_time'] = now.isoformat()
            trade['status'] = 'SL_HIT'
            trade['pnl_pct'] = (trade['entry_price'] - trade['sl_price']) / trade['entry_price'] * 100
            return trade
            
        return trade
        
    except Exception as e:
        logger.error(f"Error checking TP/SL for {trade['symbol']}: {e}")
        return trade

def execute_funding_trades(client: MEXCContractClient, config: Dict) -> None:
    """
    Execute trades based on funding rates if within 30 seconds before a funding event.
    
    This function implements a trading strategy:
    1. At 30 seconds before funding: Enter short positions on top N symbols with highest funding rates
    2. Set TP/SL based on funding rate and 15-minute ATR
    3. Close positions 3 minutes after funding if TP/SL hasn't been hit
    
    :param client: Initialized MEXCContractClient.
    :type client: MEXCContractClient
    :param config: Configuration dictionary containing trading settings.
    :type config: dict
    :return: None
    """
    logger = get_logger()
    now = datetime.now(timezone.utc)
    logger.debug(f"Checking funding trades at {now.isoformat()}")
    
    try:
        # Get active trades from cache or storage
        active_trades = []  # In a real implementation, this would load from storage
        
        # Check and update existing trades
        for trade in active_trades:
            if trade['status'] == 'OPEN':
                # Check if TP/SL hit
                trade = check_tp_sl(client, trade)
                
                # Check if 3 minutes after funding has passed
                entry_time = datetime.fromisoformat(trade['entry_time'])
                funding_time = entry_time + timedelta(seconds=30)  # Entry is 30s before funding
                if now > funding_time + timedelta(minutes=3) and trade['status'] == 'OPEN':
                    logger.info(f"Closing trade for {trade['symbol']} after 3 minutes")
                    trade = close_trade(client, trade)
        
        # Look for new trading opportunities
        funding_times = get_next_funding_times(now)
        
        for funding_time in funding_times:
            time_to_funding = (funding_time - now).total_seconds()
            
            # If we're 30 seconds before funding, enter positions
            if 25 <= time_to_funding <= 35:  # 5-second buffer around 30 seconds
                logger.info(f"30-second window before funding at {funding_time.isoformat()}, entering positions")
                
                # Get top symbols with highest funding rates
                top_symbols = fetch_top_symbols(client, top_n=config.get('top_n', 3))
                
                # Get funding rates for these symbols
                all_rates = client.get_all_funding_rates_async(top_symbols)
                funding_rates = {rate['symbol']: float(rate['fundingRate']) for rate in all_rates if 'symbol' in rate}
                
                # Enter positions for each symbol
                for symbol in top_symbols:
                    if symbol in funding_rates:
                        trade = execute_trade(client, symbol, funding_rates[symbol], config)
                        if trade:
                            # In a real implementation, save trade to storage
                            logger.info(f"Successfully entered trade for {symbol}")
                    else:
                        logger.warning(f"No funding rate found for {symbol}")
                
                # Cache the symbols for reference
                cache_top_symbols(top_symbols, funding_time, cache_dir=CACHE_DIR)
                
    except Exception as e:
        logger.error(f"Error in execute_funding_trades: {e}")
        raise

def get_next_funding_times(reference_time: datetime = None) -> list[datetime]:
    """
    Computes the funding payout times in UTC for today and nearby boundary times.

    Funding typically happens at 00:00, 08:00, and 16:00 UTC daily. This function
    also includes 16:00 of the previous day and 00:00 of the next day to handle
    boundary cases.

    :param reference_time: Optional datetime to base computation on. Defaults to now.
    :type reference_time: datetime
    :return: List of datetime objects representing payout times.
    :rtype: list[datetime]
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    today = reference_time.date()
    funding_hours = [0, 4, 8, 16, 20]

    times = [datetime(today.year, today.month, today.day, h, 0, 0, tzinfo=timezone.utc)
             for h in funding_hours]

    prev_day = today - timedelta(days=1)
    next_day = today + timedelta(days=1)
    times.append(datetime(prev_day.year, prev_day.month, prev_day.day, 16, 0, 0, tzinfo=timezone.utc))
    times.append(datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0, tzinfo=timezone.utc))
    return sorted(times)

def is_within_window(target_time: datetime, window_seconds: int = 30) -> bool:
    """
    Checks if the current UTC time is within ±window_seconds of a target time.

    :param target_time: The target datetime to compare to now.
    :type target_time: datetime
    :param window_seconds: Number of seconds for the symmetric time window.
    :type window_seconds: int
    :return: True if within window, False otherwise.
    :rtype: bool
    """
    now = datetime.now(timezone.utc)
    delta = abs((now - target_time).total_seconds())
    return delta <= window_seconds

def save_trades_to_csv(trades: List[Dict], filename: str = "funding_trades.csv") -> None:
    """
    Saves the executed trades to a CSV file.

    :param trades: List of trade dictionaries.
    :type trades: List[Dict]
    :param filename: Name of the CSV file.
    :type filename: str
    :return: None
    """
    logger = get_logger()
    file_path = Path(filename)
    
    logger.debug(f"Saving trades to {file_path}")
    
    try:
        with file_path.open('w', newline='') as csvfile:
            fieldnames = ['symbol', 'side', 'entry_time', 'entry_price', 'exit_time', 
                         'exit_price', 'tp_price', 'sl_price', 'funding_rate', 
                         'atr', 'pnl_pct', 'status']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for trade in trades:
                writer.writerow(trade)
        
        logger.info(f"Successfully saved {len(trades)} trades to {file_path}")
    except Exception as e:
        logger.error(f"Error saving trades to CSV: {e}")
        raise