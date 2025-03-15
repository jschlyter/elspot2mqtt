# elspot2mqtt

This script will fetch elspot prices and, for each upcoming hour (starting with the current one) publish the following information to MQTT:

- `ahead`
  - `timestamp`
  - `market_price` -- raw elspot price
  - `spot_price` -- energy price include markup and VAT
  - `total_price` -- `spot_price` + grid fees and energy tax
  - `avg` -- floating average of `total_price` for the last NNN hours
  - `relpt` -- relative price percentage compared to `avgNNN`
  - `level` -- price level as text
  - `minima` -- local minima (bool)
- `behind`
  - `timestamp`
  - `market_price` -- raw elspot price
  - `spot_price` -- energy price include markup and VAT
  - `total_price` -- `spot_price` + grid fees and energy tax
- `chargewindow`
  - `start` -- start of window
  - `end` -- end of window
  - `max_price` -- maxiumum price during window
  - `min_price` -- mininum price during window
  - `avg_price` -- average price during window

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
- charge window parameters


## Usage

To run locally, use:

    uv run elspot2mqtt --help


## Container

To build a container, use:

    docker build -t elspot2mqtt .

With your config file (`elspot2mqtt.json`) located in the current working directory, run with:

    docker run --rm -v .:/elspot2mqtt -e TZ=Europe/Stockholm -w /elspot2mqtt elspot2mqtt


## Data Sources

- https://www.energidataservice.dk/tso-electricity/elspotprices
