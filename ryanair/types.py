from dataclasses import dataclass, asdict
from typing import Optional, Tuple
from datetime import datetime, timedelta


@dataclass(frozen=True, eq=True)
class Airport:
    IATA_code: str
    lat: Optional[float]
    lng: Optional[float]
    location: Optional[str]

@dataclass(eq=True, frozen=True)
class OneWayFare:
    dep_time: datetime
    arr_time: datetime
    origin: str
    destination: str
    fare: float
    left: int
    currency: str
    flight_number: str = ""         # e.g., "FR1453"
    operating_carrier: str = ""     # e.g., "FR" - who operates the flight
    marketing_carrier: str = ""     # e.g., "FR" - who sells the ticket

    def to_dict(self):
        return asdict(self)

@dataclass(eq=True, frozen=True)
class RoundTripFare:
    outbound: OneWayFare
    inbound: OneWayFare
    
    @property
    def total_fare(self) -> float:
        return self.outbound.fare + self.inbound.fare
    
    @property
    def currency(self) -> str:
        return self.outbound.currency

@dataclass(eq=True, frozen=True)
class Schedule:
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    flight_number: str

@dataclass(eq=True, frozen=True)
class Stay:
    location: str
    duration: timedelta

@dataclass(eq=True, frozen=True)
class Trip:
    flights: Tuple[OneWayFare, ...]
    total_cost: float
    total_duration: timedelta
    stays: Tuple[Stay, ...]