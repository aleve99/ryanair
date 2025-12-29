"""
Simple test script to verify the async ryanair package works correctly.
Run this after installing the package with `pip install -e .`
"""

import asyncio
import logging
from datetime import date
from ryanair import Ryanair

# Configure logging
ryanair_logger = logging.getLogger("ryanair")
ryanair_logger.setLevel(logging.DEBUG)
logger = logging.getLogger("ryanair.test")


# Common Search Parameters
ORIGIN = "STN"
DEST = "MLA"
DATE_FROM = date(2026, 3, 1)
DATE_TO = date(2026, 3, 15)

# Round Trip Specific Parameters
RT_MIN_DAYS = 2
RT_MAX_DAYS = 5

# Client Config
CLIENT_TIMEOUT = 20
CLIENT_MAX_RETRIES = 3
CLIENT_USE_USD = True
CLIENT_POOL_SIZE = 50

async def main():
    logger.info("Initializing Ryanair client using async context manager...")
    # Use constants for client config
    async with Ryanair(
        timeout=CLIENT_TIMEOUT, 
        max_retries=CLIENT_MAX_RETRIES, 
        USD=CLIENT_USE_USD,
        pool_size=CLIENT_POOL_SIZE
    ) as client:
        logger.info("Client initialized (session opened).")

        # Example: Search One-Way Fares (v1)
        # Use common constants
        logger.info(f"Searching for one-way fares (v1) from {ORIGIN} to {DEST} between {DATE_FROM} and {DATE_TO}...")
        one_way_fares_v1 = [] # Initialize in case of exception
        try:
            one_way_fares_v1 = await client.search_one_way_fares(
                origin=ORIGIN,
                from_date=DATE_FROM,
                to_date=DATE_TO,
                destinations=[DEST]
            )
            logger.info(f"Found {len(one_way_fares_v1)} one-way fares (v1).")
            if one_way_fares_v1:
                logger.info("First fare found:")
                logger.info(one_way_fares_v1[0])
        except Exception as e:
            logger.error(f"Error searching one-way fares (v1): {e}", exc_info=True)

        # Example: Search Round Trip Fares
        # Use common origin/dest/dates and RT specific days
        logger.info(f"Searching for round trip fares from {ORIGIN} to {DEST} between {DATE_FROM} and {DATE_TO} (stay {RT_MIN_DAYS}-{RT_MAX_DAYS} days)...")
        round_trip_fares = [] # Initialize in case of exception
        try:
            round_trip_fares = await client.search_round_trip_fares(
                origin=ORIGIN,
                min_days=RT_MIN_DAYS,
                max_days=RT_MAX_DAYS,
                from_date=DATE_FROM,
                to_date=DATE_TO,
                destinations=[DEST]
            )
            logger.info(f"Found {len(round_trip_fares)} round trip fares.")
            if round_trip_fares:
                logger.info("First fare found:")
                logger.info(round_trip_fares[0])
        except Exception as e:
            logger.error(f"Error searching round trip fares: {e}", exc_info=True)

        # Example: Search One-Way Fares (v2 - farfnd)
        # Use common constants
        logger.info(f"Searching for one-way fares (v2) from {ORIGIN} to {DEST} between {DATE_FROM} and {DATE_TO}...")
        one_way_fares_v2 = [] # Initialize in case of exception
        try:
            one_way_fares_v2 = await client.search_one_way_fares_v2(
                origin=ORIGIN,
                from_date=DATE_FROM,
                to_date=DATE_TO,
                destinations=[DEST]
            )
            logger.info(f"Found {len(one_way_fares_v2)} one-way fares (v2).")
            if one_way_fares_v2:
                logger.info("First fare found:")
                logger.info(one_way_fares_v2[0])
        except Exception as e:
            logger.error(f"Error searching one-way fares (v2): {e}", exc_info=True)

    # Compare v1 and v2 fares (Now potentially meaningful)
    logger.info("Comparing v1 and v2 one-way fares...")
    # Check if lists were initialized and potentially populated
    if 'one_way_fares_v1' in locals() and 'one_way_fares_v2' in locals():
        # Convert to sets for comparison (ignoring order and duplicates)
        set_v1 = {Ryanair.get_flight_key(f) for f in one_way_fares_v1} # Using a comparable key
        set_v2 = {Ryanair.get_flight_key(f) for f in one_way_fares_v2}
        
        if set_v1 == set_v2:
            logger.info("Sets of v1 and v2 fares (based on origin/dest/times) are identical.")
        else:
            logger.warning("Sets of v1 and v2 fares (based on origin/dest/times) differ.")
            diff_v1_not_v2 = set_v1 - set_v2
            diff_v2_not_v1 = set_v2 - set_v1
            if diff_v1_not_v2:
                logger.warning(f" {len(diff_v1_not_v2)} Flight keys in v1 but not v2: {diff_v1_not_v2}")
            if diff_v2_not_v1:
                logger.warning(f" {len(diff_v2_not_v1)} Flight keys in v2 but not v1: {diff_v2_not_v1}")
            # Note: Price/seats left differences are expected and not compared here.
    else:
         logger.warning("Could not compare v1 and v2 fares due to errors during fetching or list initialization.")
        
    logger.info("Client context exited (session closed).")

if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main())