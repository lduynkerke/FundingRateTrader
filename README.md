# FundingRateTrader

A cryptocurrency trading bot that automatically executes short positions before funding rate events on perpetual futures contracts.

## Overview

FundingRateTrader is designed to capitalize on funding rate arbitrage opportunities in cryptocurrency perpetual futures markets. The bot:

1. Identifies upcoming funding rate events
2. Selects the top N coins with the highest funding rates
3. Enters short positions 30 seconds before funding events
4. Sets take profit and stop loss levels based on the funding rate and 15-minute ATR
5. Automatically closes positions 3 minutes after funding if TP/SL hasn't been hit

## Features

- **Automated Trading**: Executes trades at precise times before funding events
- **Dynamic TP/SL**: Calculates take profit and stop loss levels based on market volatility (ATR)
- **Risk Management**: Configurable position sizing and maximum concurrent positions
- **Detailed Logging**: Comprehensive logging of all trading activities
- **Configurable Parameters**: Easily adjust trading parameters through config.yaml

## Requirements

- Python 3.8+
- MEXC API key and secret
- Required Python packages (see requirements.txt)

## Installation

1. Clone the repository:
```
git clone https://github.com/yourusername/FundingRateTrader.git
cd FundingRateTrader
```

2. Install dependencies:
```
pip install -r requirements.txt
```

3. Configure your API keys in config.yaml:
```yaml
mexc:
  api_key: "your_api_key_here"
  secret_key: "your_secret_key_here"
```

## Configuration

The bot's behavior can be customized through the `config.yaml` file:

```yaml
trading:
  # Number of top symbols to trade
  top_n: 3
  
  # Position sizing
  position_size_usd: 100  # Fixed USD amount per position
  max_positions: 3        # Maximum number of concurrent positions
  
  # ATR settings
  atr_period: 14          # Period for ATR calculation
  atr_timeframe: "Min15"  # Timeframe for ATR calculation
  
  # Take profit and stop loss settings
  tp_atr_multiplier: 1.5  # TP = entry_price - (atr * tp_multiplier)
  sl_atr_multiplier: 2.0  # SL = entry_price + (atr * sl_multiplier)
  
  # Funding rate thresholds
  min_funding_rate: 0.0001  # Minimum funding rate to consider trading (0.01%)
  
  # Time windows
  pre_funding_seconds: 30    # Enter position X seconds before funding
  post_funding_minutes: 3    # Close position X minutes after funding if TP/SL not hit
```

## Usage

Run the bot:

```
python main.py
```

The bot will:
1. Initialize the MEXC API client
2. Start monitoring for upcoming funding events
3. Execute trades according to the configured strategy
4. Log all activities to the logs directory

## Trading Strategy

The bot implements a funding rate arbitrage strategy:

1. **Funding Rate Selection**: Identifies the top N coins with the highest funding rates
2. **Entry Timing**: Enters short positions 30 seconds before funding events
3. **Position Sizing**: Uses fixed USD amount per position (configurable)
4. **Risk Management**:
   - Sets take profit based on funding rate and ATR
   - Sets stop loss based on ATR
   - Closes positions 3 minutes after funding if neither TP nor SL has been hit

## Testing

Run the tests:

```
pytest
```

## Disclaimer

This software is for educational purposes only. Use at your own risk. Cryptocurrency trading involves significant risk and can result in the loss of your invested capital. The authors are not responsible for any financial losses incurred while using this software.

## License

MIT License