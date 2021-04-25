# elspot2mqtt

This script will fetch elspot prices and, for each upcoming hour (starting with the current one) publish the following information to MQTT:

- `ahead`
  - `timestamp`
  - `market_price` -- raw elspot price
  - `spot_price` -- energy price include markup and VAT
  - `total_price` -- `spot_price` + grid fees and energy tax
  - `avgNNN` -- floating average of `total_price` for the last NNN hours
  - `relpt` -- relative price percentage compared to `avgNNN`
  - `level` -- price level as text
  - `minima` -- local minima (bool)
- `behind`
  - `timestamp`
  - `market_price` -- raw elspot price
  - `spot_price` -- energy price include markup and VAT
  - `total_price` -- `spot_price` + grid fees and energy tax

## Configuration

- cache database
- area
- average window size (default 120)
- MQTT configuration
- costs
  - markup (cost added to market price)
  - grid fee
  - energy tax
  - VAT percentage
- price levels with gte/gte and text
