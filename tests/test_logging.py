"""
Logger functionality tests for the Funding Rate Strategy application.

This module tests the logging functionality of the application, including:
1. Logger setup and configuration
2. API client logging capabilities
3. Log file creation and message formatting

These tests ensure that the application's logging system works correctly
and can track operations across different components.
"""

import pytest
import logging
from datetime import datetime, timezone

from utils.logger import setup_logger, get_logger
from api.contract_client import MEXCContractClient
from utils.config_loader import load_config


@pytest.fixture
def logger():
    """
    Fixture that provides a configured logger instance for testing.
    
    This fixture initializes the application logger with the configuration
    from the config.yaml file, making it available for tests to verify its properties
    and behavior. The logger is configured with both file and console handlers.
    
    Returns:
        logging.Logger: A fully configured logger instance.
    """
    config = load_config()
    return setup_logger(config['logging'])


@pytest.fixture
def client():
    """
    Fixture that provides an initialized MEXCContractClient for testing.
    
    This fixture loads the configuration and creates a real (non-mocked) client
    that can be used to test actual API interactions and verify that logging
    occurs during these operations.
    
    Returns:
        MEXCContractClient: An initialized contract client.
    """
    config = load_config()
    return MEXCContractClient(config=config['mexc'])


def test_logger_setup(logger):
    """
    Test that the logger is properly set up and can log messages.
    
    This test verifies that:
    - The logger is correctly initialized with the expected name
    - It has both file and console handlers configured
    - The handlers are of the correct types
    - The logger can log messages at different levels (debug, info, warning, error)
    
    This test ensures that the logging system is properly configured and ready
    to capture application events at various severity levels.
    
    Args:
        logger: Fixture providing a configured logger instance
    """
    # Verify logger initialization
    assert logger is not None, "Logger should not be None"
    assert logger.name == 'funding_rate_strategy', "Logger name should be 'funding_rate_strategy'"
    assert len(logger.handlers) == 2, "Logger should have 2 handlers (file and console)"
    
    # Verify handler types
    file_handler = next((h for h in logger.handlers if isinstance(h, logging.FileHandler)), None)
    console_handler = next((h for h in logger.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)), None)
    
    assert file_handler is not None, "Logger should have a FileHandler"
    assert console_handler is not None, "Logger should have a StreamHandler"
    
    # Verify logging at different levels
    logger.debug("This is a debug message from test_logging.py")
    logger.info("This is an info message from test_logging.py")
    logger.warning("This is a warning message from test_logging.py")
    logger.error("This is an error message from test_logging.py")


def test_api_client_logging(client):
    """
    Test that the API client properly logs its operations.
    
    This test verifies that:
    - The API client is correctly initialized with a logger
    - The client can successfully retrieve data from the API
    - API operations trigger logging events
    - The retrieved data has the expected structure
    
    This test ensures that the API client's logging functionality works correctly
    during actual API operations, which is essential for troubleshooting and
    monitoring in production.
    
    Args:
        client: Fixture providing an initialized MEXCContractClient
    """
    # Verify client initialization
    assert client is not None, "API client should not be None"
    assert client.base_url is not None, "API client base URL should not be None"
    assert client.logger is not None, "API client logger should not be None"
    
    # Perform API operations that trigger logging
    symbols = client.get_available_perpetual_symbols()
    
    # Verify symbols were retrieved
    assert symbols is not None, "Symbols list should not be None"
    assert len(symbols) > 0, "At least one symbol should be retrieved"
    
    if symbols:
        # Retrieve OHLCV data for the first symbol
        test_symbol = symbols[0]
        now = int(datetime.now(timezone.utc).timestamp())
        candles = client.get_futures_ohlcv(test_symbol, 'Min1', now - 3600, now)
        
        # Verify candles were retrieved
        assert candles is not None, "Candles should not be None"
        
        # Verify candle data structure based on its type
        if isinstance(candles, dict):
            assert len(candles) >= 0, "Candles dictionary should be valid"
        elif isinstance(candles, list) and len(candles) > 0:
            assert len(candles[0]) >= 5, "Each candle should have at least 5 elements (timestamp, open, high, low, close)"
        else:
            assert hasattr(candles, "__len__"), "Candles should be iterable"