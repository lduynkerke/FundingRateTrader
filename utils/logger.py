"""
Logging utility module for the Funding Rate Strategy application.

This module provides functions to set up and retrieve a configured logger instance
that can be used throughout the application for consistent logging.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from utils.config_loader import load_config

# Global logger instance
logger = None

def setup_logger(log_config: dict = None):
    """
    Sets up the application logger based on configuration.
    
    This function configures a logger with both file and console handlers based on settings
    from the config.yaml file. It creates a global logger instance that can be imported
    and used throughout the application.
    
    The logger is configured with:
    - A file handler that writes to a daily log file (YYYYMMDD.log)
    - A console handler for terminal output
    - Different log levels for file and console output
    - A formatter that includes timestamp, logger name, level, and message
    
    Args:
        log_config: Dictionary containing logger configuration settings.
                   Expected to be the 'logging' section from the main config.
                   If None, default values will be used.
    
    Returns:
        logging.Logger: Configured logger instance
    """
    global logger
    
    if logger is not None:
        return logger
    
    # If no config is provided, use default values
    if log_config is None:
        log_config = {}
    
    log_dir = log_config.get('log_dir', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    
    logger = logging.getLogger('funding_rate_strategy')
    
    log_level = getattr(logging, log_config.get('log_level', 'INFO'))
    console_log_level = getattr(logging, log_config.get('console_log_level', 'WARNING'))
    file_log_level = getattr(logging, log_config.get('file_log_level', 'INFO'))
    
    logger.setLevel(log_level)
    
    if logger.handlers:
        logger.handlers.clear()
    
    timestamp = datetime.now().strftime('%Y%m%d')
    log_filename = f"{timestamp}.log"
    log_path = Path(log_dir) / log_filename
    
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(file_log_level)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_log_level)
    
    log_format = log_config.get('log_format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info("Logger initialized")
    return logger

def get_logger(log_config: dict = None):
    """
    Returns the global logger instance, initializing it if necessary.
    
    This function provides a convenient way to access the logger throughout the application.
    It ensures that the logger is initialized only once and reused across all modules.
    
    Args:
        log_config: Dictionary containing logger configuration settings.
                   Expected to be the 'logging' section from the main config.
                   If None, default values will be used.
    
    Returns:
        logging.Logger: The configured logger instance
    """
    global logger
    if logger is None:
        logger = setup_logger(log_config)
    return logger