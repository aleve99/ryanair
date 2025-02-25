"""
Simple test script to verify the ryanair package works correctly.
Run this after installing the package with `pip install -e .`
"""

from ryanair import Ryanair

def main():
    print("Initializing Ryanair client...")
    client = Ryanair(timeout=10, pool_size=10)
    
    print("Getting active airports...")
    airports = client.get_active_airports()
    print(f"Found {len(airports)} active airports")
    
    if airports:
        print("First 5 airports:")
        for airport in airports[:5]:
            print(f"  - {airport.location} ({airport.IATA_code})")

if __name__ == "__main__":
    main()