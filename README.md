# ryanair
Python Package to manage and retrieve information about ryanair flights and fares

## Installation

You can install the package directly from GitHub:

```bash
pip install git+https://github.com/aleve99/ryanair.git
```

Or after downloading the source:

```bash
pip install .
```

If you just want to install the dependencies without installing the package (for development):

```bash
pip install -r requirements.txt
```

## Usage

```python
from ryanair import Ryanair

# Initialize the client
client = Ryanair(timeout=10, pool_size=10)

# Get active airports
airports = client.get_active_airports()

# Search for one-way fares
from datetime import date
one_way_fares = client.search_one_way_fares(
    origin="DUB",  # Dublin
    from_date=date(2023, 6, 1),
    to_date=date(2023, 6, 30)
)

# Search for round-trip fares
round_trip_fares = client.search_round_trip_fares(
    origin="DUB",  # Dublin
    min_nights=3,
    max_nights=7,
    from_date=date(2023, 6, 1),
    to_date=date(2023, 6, 30)
)
```

## Using Proxies

The package supports using proxies for making requests, which can be useful for avoiding rate limits or IP blocks. You can add proxies to the session manager as follows:

```python
from ryanair import Ryanair

# Initialize the client
client = Ryanair(timeout=10, pool_size=10)

# Access the session manager
session_manager = client.sm  # The session manager is accessed via the 'sm' attribute

# Add proxies to the pool
proxies = [
    {
        "http": "http://proxy1.example.com:8080",
        "https": "https://proxy1.example.com:8080"
    },
    {
        "http": "http://proxy2.example.com:8080",
        "https": "https://proxy2.example.com:8080"
    }
]
session_manager.extend_proxies_pool(proxies)

# The session manager will cycle through the proxies automatically
# You can also manually switch to the next proxy
session_manager.set_next_proxy()
```

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
