"""
Funding rate data collection and logging pipeline.

This module implements the core functionality for monitoring cryptocurrency funding rates
and collecting market data around funding events. It handles:

1. Identifying upcoming funding rate payout times
2. Finding the highest funding rate symbols before each payout
3. Collecting OHLCV data at different timeframes around funding events
4. Saving the collected data to CSV files for later analysis

The module is designed to be called periodically and will automatically determine
when to collect data based on proximity to funding times.
"""

import csv
import os
from pathlib import Path
from typing import List, Dict
from datetime import datetime, timedelta, timezone
from api.contract_client import MEXCContractClient
from utils.funding_rate_cache import cache_top_symbols, load_cached_symbols, cleanup_old_caches
from utils.config_loader import load_config
from utils.logger import get_logger

CACHE_DIR = Path("cache/funding_rates")

def fetch_top_symbols(client: MEXCContractClient, top_n: int = 3) -> list[str]:
    """
    Fetches the top 3 symbols with highest absolute funding rates.

    :param client: Initialized MEXCContractClient.
    :type client: MEXCContractClient
    :param top_n: Number of top symbols to return.
    :type top_n: int
    :return: List of top 3 symbols.
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

def log_funding_snapshot(client: MEXCContractClient, config: Dict) -> None:
    """
    Logs funding rate snapshot and OHLCV data if within 15 or 10 minutes before a funding event.

    This function implements a two-phase data collection strategy:
    1. At 15 minutes before funding: Identifies and caches the top symbols with highest funding rates
    2. At 15 minutes after funding: Retrieves the cached symbols and collects OHLCV data for them
    
    The function should be called periodically (e.g., every 5 minutes) and will automatically
    determine when to perform each action based on proximity to funding times.
    
    This approach allows the system to identify high-funding-rate symbols early, then focus
    data collection efforts on just those symbols as the funding time approaches.

    :param client: Initialized MEXCContractClient.
    :type client: MEXCContractClient
    :param config: Configuration dictionary containing funding settings.
    :type config: dict
    :return: None
    """
    logger = get_logger()
    now = datetime.now(timezone.utc)
    logger.debug(f"Checking funding snapshot at {now.isoformat()}")
    
    try:
        funding_times = get_next_funding_times(now)
        next_funding = min(funding_times, key=lambda ft: abs((ft - now).total_seconds()))
        logger.debug(f"Next funding time: {next_funding.isoformat()}")

        for funding_time in funding_times:
            delta = (now - funding_time).total_seconds() / 60
            logger.debug(f"Checking funding time {funding_time.isoformat()}, delta: {delta:.2f} minutes")

            if -15 <= delta < 0:
                logger.info(f"15-minute window before funding at {funding_time.isoformat()}, caching top symbols")
                top_symbols = fetch_top_symbols(client, top_n=config.get('top_n', 5))
                cache_top_symbols(top_symbols, funding_time, cache_dir=CACHE_DIR)
                logger.info(f"Top 5 symbols cached at {now.isoformat()} for {funding_time.isoformat()}: {', '.join(top_symbols)}")

            if 15 <= delta <= 30:
                logger.info(f"15-minute window after funding at {funding_time.isoformat()}, collecting data")
                top3_symbols = load_cached_symbols(funding_time, cache_dir=CACHE_DIR)
                logger.info(f"Loaded cached symbols for {funding_time.isoformat()}: {', '.join(top3_symbols)}")
                for symbol in top3_symbols:
                    collect_and_save_data(client, symbol, funding_time, config)
                logger.info(f"Data collection completed for {funding_time.isoformat()} at {now.isoformat()}")
    except Exception as e:
        logger.error(f"Error in log_funding_snapshot: {e}")
        raise

def collect_and_save_data(client: MEXCContractClient, symbol: str, funding_time: datetime, config: Dict) -> None:
    """
    Collects OHLCV candles and saves them to CSV for a given symbol and funding time.
    
    This function retrieves price data at multiple timeframes around a funding event:
    - Daily candles: For longer-term context (configurable days back from funding time)
    - Hourly candles: For medium-term context (configurable hours back from funding time)
    - 10m candles: For short-term context before funding (configurable hours before funding)
    - 1m candles: For detailed price action around funding (configurable minutes before and after)
    
    All timeframes are configurable through the config.yaml file under the funding.time_windows section.
    The collected data is saved to a CSV file with a timestamp in the filename.
    
    :param client: Initialized MEXCContractClient.
    :type client: MEXCContractClient
    :param symbol: Contract symbol (e.g., 'BTC_USDT').
    :type symbol: str
    :param funding_time: The datetime of the funding rate payout.
    :type funding_time: datetime
    :param config: Configuration dictionary containing funding settings, especially time_windows.
    :type config: dict
    :return: None
    """
    logger = get_logger()
    logger.info(f"Collecting data for {symbol} at funding time {funding_time.isoformat()}")
    
    try:
        time_windows = config.get('time_windows', {})
        
        days_back = time_windows.get('daily_days_back', 3)
        hourly_back = time_windows.get('hourly_hours_back', 4)
        ten_min_hours_before = time_windows.get('ten_min_hours_before', 1)
        one_min_minutes_before = time_windows.get('one_min_minutes_before', 10)
        one_min_minutes_after = time_windows.get('one_min_minutes_after', 10)
        
        funding_ts = int(funding_time.timestamp())
        
        daily_end = funding_ts
        daily_start = daily_end - days_back * 24 * 3600
        
        hourly_end = funding_ts
        hourly_start = funding_ts - hourly_back * 3600
        
        ten_min_end = funding_ts
        ten_min_start = ten_min_end - ten_min_hours_before * 3600
        
        one_min_end = funding_ts + one_min_minutes_after * 60
        one_min_start = funding_ts - one_min_minutes_before * 60

        logger.debug(f"Fetching daily candles for {symbol}: {daily_start} to {daily_end}")
        candles_daily = client.get_futures_ohlcv(symbol, 'Day1', daily_start, daily_end)
        logger.debug(f"Fetched {len(candles_daily)} daily candles")
        
        logger.debug(f"Fetching hourly candles for {symbol}: {hourly_start} to {hourly_end}")
        candles_1h = client.get_futures_ohlcv(symbol, 'Hour1', hourly_start, hourly_end)
        logger.debug(f"Fetched {len(candles_1h)} hourly candles")
        
        logger.debug(f"Fetching 10m candles for {symbol}: {ten_min_start} to {ten_min_end}")
        candles_10m = client.get_futures_ohlcv(symbol, 'Min10', ten_min_start, ten_min_end)
        logger.debug(f"Fetched {len(candles_10m)} 10m candles")
        
        logger.debug(f"Fetching 1m candles for {symbol}: {one_min_start} to {one_min_end}")
        candles_1m = client.get_futures_ohlcv(symbol, 'Min1', one_min_start, one_min_end)
        logger.debug(f"Fetched {len(candles_1m)} 1m candles")

        data = {'daily': candles_daily, '1h': candles_1h, '10m': candles_10m, '1m': candles_1m}
        save_data_to_csv(symbol, funding_time, data)
        logger.info(f"Successfully collected and saved data for {symbol}")
    except Exception as e:
        logger.error(f"Error collecting data for {symbol}: {e}")
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


def is_within_window(target_time: datetime, window_minutes: int = 10) -> bool:
    """
    Checks if the current UTC time is within ±window_minutes of a target time.

    :param target_time: The target datetime to compare to now.
    :type target_time: datetime
    :param window_minutes: Number of minutes for the symmetric time window.
    :type window_minutes: int
    :return: True if within window, False otherwise.
    :rtype: bool
    """
    now = datetime.now(timezone.utc)
    delta = abs((now - target_time).total_seconds()) / 60
    return delta <= window_minutes

def save_data_to_csv(symbol: str, funding_time: datetime, candle_data: Dict[str, List[list]]) -> None:
    """
    Saves the collected candle data to a CSV file.

    :param symbol: Contract symbol.
    :type symbol: str
    :param funding_time: The datetime of the funding rate payout.
    :type funding_time: datetime
    :param candle_data: Dictionary with '1m', '10m', and '1h' candle lists.
    :type candle_data: dict
    :return: None
    """
    logger = get_logger()
    timestamp_str = funding_time.strftime('%Y-%m-%d_%H-%M')
    file_path = Path(f"funding_data_{symbol}_{timestamp_str}.csv")
    
    logger.debug(f"Saving data to {file_path}")
    
    try:
        total_candles = sum(len(candles) for candles in candle_data.values())
        logger.info(f"Writing {total_candles} candles to CSV for {symbol}")
        
        with file_path.open('w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Symbol', 'FundingTime', 'Interval', 'Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume'])

            for interval, candles in candle_data.items():
                for candle in candles:
                    timestamp = int(candle[0]) // 1000 if isinstance(candle[0], str) else candle[0] // 1000
                    writer.writerow([
                        symbol,
                        funding_time.isoformat(),
                        interval,
                        datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                        *candle[1:]
                    ])
        
        logger.info(f"Successfully saved data to {file_path}")
    except Exception as e:
        logger.error(f"Error saving data to CSV for {symbol}: {e}")
        raise
