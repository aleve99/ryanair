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
import asyncio
from datetime import date
from ryanair import Ryanair

async def main():
    # The client is now an async context manager
    # Initialization (fetching airports) happens on entering the block
    # Cleanup (closing session) happens on exiting the block
    async with Ryanair(timeout=30) as client:
        print("Client context entered, initializing...")

        # Get active airports (check requires initialization from context manager)
        try:
            airports = client.get_active_airports()
            print(f"Found {len(airports)} active airports.")
        except RuntimeError as e:
            print(f"Error getting airports: {e}")
            return # Error during initialization in __aenter__

        # Search for one-way fares (async)
        print("Searching for one-way fares...")
        one_way_fares = await client.search_one_way_fares(
            origin="DUB",  # Dublin
            from_date=date(2024, 8, 1), # Updated example dates
            to_date=date(2024, 8, 15)
        )
        print(f"Found {len(one_way_fares)} one-way fares.")

        # Search for round-trip fares (async)
        print("Searching for round-trip fares...")
        round_trip_fares = await client.search_round_trip_fares(
            origin="DUB",  # Dublin
            min_days=3,
            max_days=7,
            from_date=date(2024, 8, 1),
            to_date=date(2024, 8, 15)
        )
        print(f"Found {len(round_trip_fares)} round-trip fares.")

    # Session is automatically closed here when exiting the 'async with' block
    print("Client context exited, session closed.")

if __name__ == "__main__":
    asyncio.run(main())
```

## Using Proxies

The package supports using proxies for making requests. Proxies are managed by the internal `SessionManager` and are automatically rotated.

```python
import asyncio
from datetime import date
from ryanair import Ryanair

async def main_with_proxies():
    # Proxies should be added *after* creating the client instance,
    # but *before* entering the async context where initialization occurs.
    client = Ryanair(timeout=30)

    # Define your proxy URLs
    proxy_urls = [
        "http://user1:pass1@proxy1.example.com:8080",
        "http://user2:pass2@proxy2.example.com:8080"
    ]
    # Convert to the list-of-dicts format expected by extend_proxies_pool
    proxies_list_of_dicts = [{"http": url, "https": url} for url in proxy_urls]

    # Add proxies to the session manager's pool *before* entering the context
    client.sm.extend_proxies_pool(proxies_list_of_dicts)
    print(f"Added {len(proxies_list_of_dicts)} proxies to the pool.")

    # Enter the async context, which triggers initialization
    async with client:
        print("Client context entered with proxies.")

        # Perform searches - proxies will be rotated automatically
        print("Searching for one-way fares using proxies...")
        try:
            one_way_fares = await client.search_one_way_fares(
                origin="STN",  # Stansted
                from_date=date(2024, 9, 1),
                to_date=date(2024, 9, 5),
                destinations=["BCN"] # Example: Limit destinations
            )
            print(f"Found {len(one_way_fares)} one-way fares.")
        except RuntimeError as e:
            # Handle potential initialization errors if __aenter__ failed
            print(f"Error during search: {e}")

    # Session is automatically closed here
    print("Client session closed.")

if __name__ == "__main__":
    asyncio.run(main_with_proxies())
```

## License

This project is licensed under the GNU General Public License v3.0 - see the LICENSE file for details.
