"""
Main entry point for the Funding Rate Trader application.

This module initializes the application components and sets up a scheduler to
periodically check for funding events and execute trades. It handles:

1. Setting up the logging system
2. Initializing the MEXC API client
3. Scheduling periodic funding rate checks
4. Running the main application loop with error handling

The application runs continuously, checking for upcoming funding events and
executing trades at strategic times before each funding rate payout.
"""

import time
import schedule
from datetime import datetime, timezone
from api.contract_client import MEXCContractClient
from pipeline.funding_rate_trader import execute_funding_trades, get_next_funding_times
from utils.config_loader import load_config
from utils.logger import setup_logger, get_logger

def main() -> None:
    """
    Initializes the MEXC API client and periodically schedules the funding trader.

    The trader is triggered every minute and internally decides whether to execute trades
    based on proximity to funding times. This ensures resilience in case of minor time drift or delays.
    """
    try:
        config = load_config()
        
        # Initialize the logger
        logger = setup_logger(config['logging'])
        logger.info("Configuration loaded successfully")
        logger.info("Starting Funding Rate Trader application")
        
        client = MEXCContractClient(config=config['mexc'])
        logger.info("MEXC client initialized")

        logger.info(f"Scheduler initialized at: {datetime.now(timezone.utc).isoformat()}")
        logger.info("Upcoming funding times (UTC):")
        for t in get_next_funding_times()[:5]:
            logger.info(f"  {t.isoformat()}")

        # Run every minute to ensure we don't miss the 30-second window before funding
        schedule.every(1).minutes.do(run_trader_safely, client, config['trading'])
        logger.info("Scheduler set to run every minute")

        logger.info("Entering main loop")
        while True:
            schedule.run_pending()
            time.sleep(10)  # Check more frequently than in the logger
    except Exception as e:
        logger.critical(f"Fatal error in main application: {e}", exc_info=True)
        raise

def run_trader_safely(client: MEXCContractClient, config: dict) -> None:
    """
    Wraps the funding trader in try-except for resilience.

    :param client: Initialized MEXCContractClient.
    :type client: MEXCContractClient
    :param config: Configuration dictionary containing trading settings.
    :type config: dict
    """
    logger = get_logger()  # Use the already initialized logger
    try:
        logger.debug("Starting funding trader execution")
        execute_funding_trades(client, config=config)
        logger.info(f"Trader executed successfully at {datetime.now(timezone.utc).isoformat()}")
    except Exception as e:
        logger.error(f"Error during trader execution: {e}", exc_info=True)


if __name__ == "__main__":
    main()