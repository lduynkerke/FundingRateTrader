"""
Caching utilities for storing and retrieving top funding rate symbols.

This module provides functions to cache the top N MEXC contract symbols at funding
rate payout times, load cached symbols for later data collection, and clean up
outdated cache files. Cached files are timestamped and stored in a specified directory.

Functions:
    - cache_top_symbols
    - load_cached_symbols
    - cleanup_old_caches
"""
from pathlib import Path
from typing import List
from datetime import datetime, timezone, timedelta

def cache_top_symbols(symbols: list[str], funding_time: datetime, cache_dir: Path) -> Path:
    """
    Caches the top 3 symbols to a text file with a timestamp-based filename.

    The filename follows the pattern: top3symbols_<ISO_TIMESTAMP>.txt. Characters invalid in filenames
    (e.g., colons) are replaced with hyphens for cross-platform compatibility.

    :param symbols: List of top 3 symbols to cache.
    :type symbols: list[str]
    :param funding_time: The funding time this snapshot corresponds to.
    :type funding_time: datetime
    :param cache_dir: Directory where the cache file will be stored.
    :type cache_dir: Path
    :return: Path to the created cache file.
    :rtype: Path
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_timestamp = funding_time.isoformat().replace(":", "-")
    filename = f"top3symbols_{safe_timestamp}.txt"
    file_path = cache_dir / filename

    with open(file_path, 'w') as f:
        for symbol in symbols:
            f.write(f"{symbol}\n")

    return file_path


def load_cached_symbols(funding_time: datetime, cache_dir: Path) -> list[str]:
    """
    Loads cached top 3 symbols for a specific funding time from a text file.

    Expects the file to be named: top3symbols_<ISO_TIMESTAMP>.txt, with the timestamp formatted
    with hyphens instead of colons.

    :param funding_time: The funding time to load symbols for.
    :type funding_time: datetime
    :param cache_dir: Directory where the cache file is stored.
    :type cache_dir: Path
    :return: List of cached symbols, or empty list if file not found.
    :rtype: list[str]
    """
    safe_timestamp = funding_time.isoformat().replace(":", "-")
    filename = f"top3symbols_{safe_timestamp}.txt"
    file_path = cache_dir / filename

    if file_path.exists():
        with open(file_path, 'r') as f:
            return [line.strip() for line in f.readlines()]
    return []


def cleanup_old_caches(cache_dir: Path, max_age_hours: int = 24) -> None:
    """
    Removes cache files older than a specified maximum age from a given directory.

    Files are expected to be named as top3symbols_<ISO_TIMESTAMP>.txt. Timestamps in filenames
    are parsed to determine file age. Invalid filenames are ignored.

    :param cache_dir: Directory path where cache files are stored.
    :type cache_dir: Path
    :param max_age_hours: Maximum allowable file age in hours before deletion.
    :type max_age_hours: int
    :return: None
    :rtype: None
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    for file in cache_dir.glob("top3symbols_*.txt"):
        timestamp_str = file.stem.split("_")[-1]
        try:
            iso_str = timestamp_str.replace("-", ":", 2).replace("-", ":").replace("+", "+").replace("-", ":", 1)
            file_time = datetime.fromisoformat(iso_str)
            if file_time < cutoff:
                file.unlink()
        except Exception:
            continue  # Skip malformed filenames
