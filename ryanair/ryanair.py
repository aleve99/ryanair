import logging
import asyncio
import aiohttp

from copy import deepcopy
from typing import Optional, Tuple, List, Iterable, Dict
from datetime import date, timedelta, datetime, time

from .session_manager import SessionManager
from .payload import AvailabilityPayload, get_availabilty_payload, get_farfnd_one_way_payload
from .types import Airport, OneWayFare, RoundTripFare, Schedule
from .utils.timer import Timer

logger = logging.getLogger("ryanair")

class Ryanair:
    BASE_API_URL = "https://www.ryanair.com/api/"
    SERVICES_API_URL = "https://services-api.ryanair.com/"
    FLIGHT_PAGE_URL = "https://www.ryanair.com/en/us/trip/flights/select"
    FLEX_DAYS = 6

    def __init__(
            self,
            timeout: int = 10,
            max_retries: int = 5,
            USD: Optional[bool] = False
        ) -> None:
        
        if USD:
            self._currency_str = "en-us/"
            self._market = "en-us"
        else:
            self._currency_str = ""
            self._market = "it-it"

        self._max_retries = max_retries
        self.sm = SessionManager(timeout=timeout)

        # Initialize active_airports - will be populated asynchronously later
        self.active_airports: Optional[Tuple[Airport, ...]] = None

    async def get(self, url: str, params: Optional[Dict] = None, **kwargs) -> aiohttp.ClientResponse:
        """Performs an asynchronous GET request with proxy rotation and retries.

        Returns the raw `aiohttp.ClientResponse` object on success. The caller
        is responsible for managing the response context (e.g., using `async with`).

        Raises:
            Various `aiohttp.ClientError` or `asyncio.TimeoutError` on repeated failures.
            `RuntimeError` if all retries fail.
        """
        session = await self.sm.get_session()
        last_exception = None
        response: Optional[aiohttp.ClientResponse] = None # Define response variable outside try

        for attempt in range(self._max_retries):
            proxy_url = self.sm.get_next_proxy_url()
            timeout = aiohttp.ClientTimeout(total=self.sm.timeout)
            
            try:
                logger.debug(f"Attempt {attempt + 1}/{self._max_retries}: GET {url} via proxy {proxy_url}")
                # Remove internal async with, await the get directly
                response = await session.get(url=url, params=params, proxy=proxy_url, timeout=timeout, **kwargs)
                
                response.raise_for_status() # Raises ClientResponseError for 4xx/5xx
                
                logger.debug(f"GET {url} successful (Status: {response.status})")
                # Return successful response object directly (caller handles context)
                return response 
            
            except asyncio.TimeoutError as e:
                logger.warning(f"Attempt {attempt + 1} failed: Timeout for {url} via proxy {proxy_url}")
                last_exception = e
                # No response object created
                response = None 
            except aiohttp.ClientResponseError as e:
                logger.warning(f"Attempt {attempt + 1} failed: HTTP {e.status} for {url} via proxy {proxy_url}. Message: {e.message}")
                last_exception = e
                # We have a response object, but it's an error.
                # Ensure connection is released before next attempt or raising.
                if response is not None:
                    await response.release()
                response = None # Indicate response is handled/invalid
            except aiohttp.ClientError as e:
                # Includes connection errors, proxy errors, etc.
                logger.warning(f"Attempt {attempt + 1} failed: {type(e).__name__} for {url} via proxy {proxy_url}. Details: {e}")
                last_exception = e
                # No response object likely created, or if it was, it's unusable.
                if response is not None:
                    # Defensive release, though often not needed here
                    await response.release()
                response = None 

            # Wait a bit before retrying (optional, simple backoff)
            if attempt < self._max_retries - 1:
                 await asyncio.sleep(0.5 * (attempt + 1)) 

        # If loop finishes without returning, all retries failed
        error_message = f"Failed to fetch {url} after {self._max_retries} attempts."
        logger.error(error_message)
        if last_exception:
            raise last_exception # Re-raise the last known exception
        else:
            # Should not happen if MAX_RETRIES > 0, but as a fallback
            raise RuntimeError(error_message)

    # get_airport remains synchronous as it uses self.active_airports
    def get_airport(self, iata_code: str) -> Optional[Airport]:
        # Use the getter which includes the initialization check
        airports = self.get_active_airports() 
        for airport in airports:
            if airport.IATA_code == iata_code:
                return airport
        
        return None

    async def get_available_dates(self, origin: str, destination: str) -> Tuple[str, ...]:
        """Gets available dates (as ISO format strings) for a given route asynchronously."""
        trip = f"{origin}-{destination}"
        logger.info(f"Getting available dates for {trip}")
        url = self._available_dates_url(origin, destination)
        async with await self.get(url) as res: # Use async with for response context
            data = await res.json()
            return tuple(data)
    
    async def update_active_airports(self):
        """Fetches the latest active airports asynchronously and updates the instance attribute."""
        logger.info(f"Updating Ryanair active airports...")
        url = self._active_airports_url()
        try:
            async with await self.get(url) as res:
                data = await res.json()
                self.active_airports = tuple(
                    Airport(
                        airport['code'],
                        airport['coordinates']['latitude'],
                        airport['coordinates']['longitude'],
                        airport['name']
                    ) for airport in data
                )
                logger.info(f"Successfully updated active airports. Found {len(self.active_airports)}.")
        except Exception as e:
            # Log error but perhaps allow proceeding without airports? Or re-raise?
            logger.error(f"Failed to update active airports: {e}", exc_info=True)
            # Optionally set to empty tuple or re-raise depending on desired behavior
            self.active_airports = tuple() # Set empty on failure for now

    def get_active_airports(self) -> Tuple[Airport, ...]:
        """Returns the cached tuple of active airports.

        Raises:
            RuntimeError: If the client has not been initialized (e.g., used outside an `async with` block).
        """
        if self.active_airports is None:
            raise RuntimeError("Ryanair client not initialized. Use within an 'async with' block.")
        return self.active_airports

    async def get_schedules(
            self,
            origin: str,
            destination: str,
            year: int = None,
            month: int = None,
            response: aiohttp.ClientResponse = None
        ) -> List[Schedule]:
        """Gets flight schedules for a given route and month asynchronously.

        Can optionally reuse an existing `aiohttp.ClientResponse` if provided,
        otherwise fetches data based on year and month.

        Args:
            origin: Origin airport IATA code.
            destination: Destination airport IATA code.
            year: Year for schedules (required if response is None).
            month: Month for schedules (required if response is None).
            response: Optional `aiohttp.ClientResponse` from a previous request
                      to the schedules endpoint. If provided, `year` and `month`
                      are ignored, and the data is parsed from this response.
                      The caller must manage the response context.

        Returns:
            A list of `Schedule` objects.

        Raises:
            ValueError: If `response` is not provided and `year` or `month` is missing.
        """
        schedules: List[Schedule] = []
        data = None
        
        if response is None:
            if year is None or month is None:
                raise ValueError("Year and month must be provided if response is not provided")
            url = self._schedules_url(origin, destination, year, month)
            # Must manage the response context if not passed in
            async with await self.get(url) as res:
                # Need to get year/month from URL if not passed
                url_split = str(res.url).split('/') # Use res.url (yarl.URL)
                year, month = int(url_split[-3]), int(url_split[-1])
                data = await res.json()
        else:
            # Assuming the response context is managed externally if passed
            url_split = str(response.url).split('/') 
            year, month = int(url_split[-3]), int(url_split[-1])
            data = await response.json()

        for day in data['days']:
            day_date = date(year, month, day['day'])
            for flight in day['flights']:
                dep_time = time.fromisoformat(flight['departureTime'])
                arr_time = time.fromisoformat(flight['arrivalTime'])
                dep_datetime = datetime.combine(day_date, dep_time)

                # Check if arrival time wraps around midnight
                # Original logic comparing time objects might be tricky with timezones
                # Simpler check based on ISO format parsing directly might be needed
                # Assuming simple case for now:
                if flight['arrivalTime'] < flight['departureTime']:
                     arr_datetime = datetime.combine(day_date + timedelta(days=1), arr_time)
                else:
                     arr_datetime = datetime.combine(day_date, arr_time)
                
                schedule = Schedule(
                    origin=origin,
                    destination=destination,
                    arrival_time=arr_datetime,
                    departure_time=dep_datetime,
                    flight_number=flight['carrierCode'] + flight['number']
                )
                schedules.append(schedule)

        return schedules

    def get_round_trip_link(
            self,
            from_date: date,
            to_date: date,
            origin: str,
            destination: str
        ) -> str:
        """Builds the URL for selecting a round trip flight on the Ryanair website.

        Note: Relies on airport data fetched during `initialize()`.

        Raises:
            ValueError: If origin or destination IATA code is invalid.
            RuntimeError: If the client has not been initialized via `await initialize()`.
        """
        # This check now potentially raises RuntimeError if not initialized
        if not self.get_airport(origin):
            raise ValueError(f"IATA code {origin} not valid or client not initialized")
        
        if not self.get_airport(destination):
            raise ValueError(f"IATA code {destination} not valid or client not initialized")
        
        return self.FLIGHT_PAGE_URL + f"?" + \
            "&".join([
                "adults=1",
                "teens=0",
                "children=0",
                "infants=0",
                f"dateOut={from_date}",
                f"dateIn={to_date}",
                "isConnectedFlight=false",
                "discount=0",
                "promoCode=",
                "isReturn=true",
                f"originIata={origin}",
                f"destinationIata={destination}"
            ])
    
    def get_one_way_link(
            self,
            from_date: date,
            origin: str,
            destination: str
        ) -> str:
        """Builds the URL for selecting a one-way flight on the Ryanair website.

        Note: Relies on airport data fetched during `initialize()`.

        Raises:
            ValueError: If origin or destination IATA code is invalid.
            RuntimeError: If the client has not been initialized via `await initialize()`.
        """
        if not self.get_airport(origin):
            raise ValueError(f"IATA code {origin} not valid or client not initialized")
        
        if not self.get_airport(destination):
            raise ValueError(f"IATA code {destination} not valid or client not initialized")
        
        return self.FLIGHT_PAGE_URL + "?" + \
            "&".join([
                "adults=1",
                "teens=0",
                "children=0",
                "infants=0",
                f"dateOut={from_date}",
                "isConnectedFlight=false",
                "discount=0",
                "promoCode=",
                "isReturn=false",
                f"originIata={origin}",
                f"destinationIata={destination}"
            ])

    @staticmethod
    def _prepare_params_for_aiohttp(params_dict: Dict) -> Dict[str, str]:
        """Converts parameter values to strings suitable for aiohttp query params."""
        params_str = {}
        for k, v in params_dict.items():
            if v is None: continue # Skip None values
            if isinstance(v, date):
                params_str[k] = v.isoformat()
            elif isinstance(v, bool):
                params_str[k] = str(v).lower() # Convert bool to "true"/"false"
            elif isinstance(v, list):
                # Convert list items to string and join with comma
                params_str[k] = ",".join(map(str, v))
            elif isinstance(v, time):
                params_str[k] = v.strftime('%H:%M') # Format time as HH:MM
            else:
                # Assume other types can be directly converted to string
                params_str[k] = str(v)
        return params_str

    async def get_availability(self, payload: AvailabilityPayload) -> dict:
        """Fetches availability data asynchronously based on the provided payload.

        Returns the raw JSON response as a dictionary.
        """
        url = self._availabilty_url()
        params_dict = payload.to_dict()
        
        # Convert params using the helper function
        params_str = self._prepare_params_for_aiohttp(params_dict)
        
        logger.debug(f"Fetching availability with params: {params_str}")
        async with await self.get(url, params=params_str) as res:
            return await res.json()
    
    async def get_destination_codes(self, origin: str) -> Tuple[str, ...]:
        """Gets available destination IATA codes for a given origin asynchronously."""
        logger.info(f"Getting destinations for {origin}")
        url = self._destinations_url(origin)
        async with await self.get(url) as res:
             data = await res.json()
             # Check if data is a list and contains dicts with 'arrivalAirport'
             if isinstance(data, list) and all(isinstance(item, dict) and 'arrivalAirport' in item for item in data):
                return tuple(
                    dest['arrivalAirport']['code'] for dest in data if 'code' in dest['arrivalAirport']
                )
             else:
                 logger.warning(f"Unexpected format for destination codes response for {origin}: {data}")
                 return tuple() # Return empty tuple on unexpected format

    async def search_round_trip_fares(
            self,
            origin: str,
            min_days: int,
            max_days: int,
            from_date: date,
            to_date: date = None,
            destinations: Iterable[str] = []
        ) -> List[RoundTripFare]:
        """Searches for round trip fares asynchronously using the availability endpoint.

        Must be called within an `async with` block for initialization.
        If `destinations` is empty, it will fetch them using `get_destination_codes`.
        """

        if not destinations:
            destinations = await self.get_destination_codes(origin)

        timer = Timer(start=True)

        # Prepare parameters for all required requests
        code_requests_params = await self._prepare_availability_request_params(
            origin=origin,
            from_date=from_date,
            to_date=to_date,
            destinations=destinations
        )
        
        # Execute requests concurrently and compute fares
        fares = await self._execute_and_compute_availability(
            origin=origin,
            code_requests_params=code_requests_params,
            min_days=min_days,
            max_days=max_days
        )

        timer.stop()
        logger.info(f"Scraped {origin} round-trip fares in {timer.seconds_elapsed}s")
        return fares
    
    async def search_one_way_fares(
            self,
            origin: str,
            from_date: date,
            to_date: date = None,
            destinations: Iterable[str] = []
        ) -> List[OneWayFare]:
        """Searches for one way fares asynchronously using the availability endpoint (v1).

        Must be called within an `async with` block for initialization.
        If `destinations` is empty, it will fetch them using `get_destination_codes`.
        """
        if not destinations:
            destinations = await self.get_destination_codes(origin)
        
        timer = Timer(start=True)

        # Prepare parameters for all required requests
        code_requests_params = await self._prepare_availability_request_params(
            origin=origin,
            from_date=from_date,
            to_date=to_date,
            destinations=destinations,
            round_trip=False
        )
        
        all_request_params = []
        dest_map = {}
        param_index = 0
        for dest, params_list in code_requests_params.items():
            all_request_params.extend(params_list)
            for i in range(len(params_list)):
                dest_map[param_index + i] = dest
            param_index += len(params_list)

        # Execute all requests concurrently
        results = await self._execute_requests_concurrently(all_request_params)

        fares = []
        for i, result in enumerate(results):
            dest = dest_map.get(i)
            if dest is None: continue # Should not happen

            if isinstance(result, Exception):
                logger.warning(f"Request failed for {origin}-{dest} (index {i}): {result}")
                continue
            
            # Process successful response
            try:
                # Manage context for each response
                async with result as response:
                    json_res = await response.json()
                    currency = json_res['currency']

                    for trip_date in json_res['trips'][0]['dates']:
                        for flight in filter(
                            lambda fl: fl['faresLeft'] != 0, trip_date['flights']
                        ):
                            fares.append(
                                OneWayFare(
                                    datetime.fromisoformat(flight['time'][0]),
                                    datetime.fromisoformat(flight['time'][1]),
                                    origin, # Use original origin
                                    dest,   # Use destination mapped from index
                                    flight['regularFare']['fares'][0]['amount'],
                                    flight['faresLeft'],
                                    currency
                                )
                            )
            except Exception as e:
                 logger.error(f"Failed to process response for {origin}-{dest} (index {i}): {e}", exc_info=True)

        timer.stop()
        logger.info(f"Scraped {origin} one-way fares (v1) in {timer.seconds_elapsed}s")
        return fares

    async def search_one_way_fares_v2(
            self,
            origin: str,
            from_date: date,
            to_date: date,
            destinations: Iterable[str] = []
        ) -> List[OneWayFare]:
        """Searches for one way fares asynchronously using the farfnd endpoint (v2).

        Must be called within an `async with` block for initialization.
        If `destinations` is empty, it will fetch them using `get_destination_codes`.
        If `to_date` is None, it defaults to 30 days after `from_date`.
        Note: This endpoint does not provide 'faresLeft'.
        Note: Pagination is currently not handled.
        """
        if not destinations:
            destinations = await self.get_destination_codes(origin)
        
        timer = Timer(start=True)

        # Prepare parameters for all required requests
        request_params = await self._prepare_availability_request_params_v2(
            origin=origin,
            from_date=from_date,
            to_date=to_date,
            destinations=destinations,
            round_trip=False
        )

        # Execute requests concurrently
        results = await self._execute_requests_concurrently(request_params)
        timer.stop()
        logger.info(f"Scraped {origin} one-way fares (v2) requests in {timer.seconds_elapsed}s")

        fares = []
        processing_timer = Timer(start=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Farfnd request failed: {result}")
                continue
            
            try:
                async with result as response:
                    json_res = await response.json()
                    if json_res.get('nextPage') is not None:
                        logger.warning(f"Farfnd response indicates pagination (nextPage is not None), but handling is not implemented. URL: {response.url}")
                        # Potentially raise error or implement pagination logic

                    for flight in json_res.get('fares', []):
                        info = flight.get('outbound')
                        if not info: continue # Skip if no outbound info
                        
                        # Basic validation of expected keys
                        try:
                            fares.append(
                                OneWayFare(
                                    datetime.fromisoformat(info['departureDate']),
                                    datetime.fromisoformat(info['arrivalDate']),
                                    origin, # Use original origin
                                    info['arrivalAirport']['iataCode'],
                                    info['price']['value'],
                                    -1, # faresLeft not available in this endpoint
                                    info['price']['currencyCode']
                                )
                            )
                        except (KeyError, TypeError, ValueError) as parse_err:
                             logger.warning(f"Failed to parse fare entry: {parse_err}. Data: {info}")
                             
            except Exception as e:
                 logger.error(f"Failed to process farfnd response: {e}", exc_info=True)
        
        processing_timer.stop()
        logger.debug(f"Processed {origin} one-way fares (v2) responses in {processing_timer.seconds_elapsed}s. Found {len(fares)} fares.")
        return fares

    async def _prepare_availability_request_params(
            self,
            origin: str,
            from_date: date,
            to_date: 'date | None',
            destinations: Iterable[str],
            round_trip: bool = True
        ) -> Dict[str, List[Dict]]: # Return dict of params, not requests
        """(Async) Prepares parameters for availability API calls (v1).

        If `to_date` is None, it asynchronously fetches the last available date.
        Returns a dictionary mapping destination codes to lists of request parameter dicts.
        Each param dict contains 'url' and 'params' keys suitable for `self.get`.
        """
        requests_params = dict()
        dest_list = list(destinations) # Consume iterable

        # Determine _to_date if not provided (requires async call)
        resolved_to_date = {}
        if to_date is None:
             tasks = [self.get_available_dates(origin, code) for code in dest_list]
             results = await asyncio.gather(*tasks, return_exceptions=True)
             for i, result in enumerate(results):
                 code = dest_list[i]
                 if isinstance(result, Exception) or not result:
                     logger.warning(f"Could not get available dates for {origin}-{code}: {result}. Skipping this destination for auto date range.")
                     resolved_to_date[code] = from_date # Default to from_date if fetch fails
                 else:
                     resolved_to_date[code] = date.fromisoformat(result[-1])
        else:
             for code in dest_list:
                 resolved_to_date[code] = to_date

        # Generate parameter sets
        for code in dest_list:
            param_list = []
            _to_date = resolved_to_date.get(code, from_date)
            if _to_date < from_date: _to_date = from_date # Ensure to_date >= from_date

            _current_date = from_date
            while _current_date <= _to_date:
                days_remaining = (_to_date - _current_date).days
                flex_days = min(self.FLEX_DAYS, days_remaining)
                
                payload = get_availabilty_payload(
                    origin=origin,
                    destination=code,
                    date_out=_current_date,
                    date_in=_current_date, # date_in is needed even for one-way for this payload
                    flex_days=flex_days,
                    round_trip=round_trip
                )
                params_dict = payload.to_dict()
                # Convert params using the helper function
                params_str = self._prepare_params_for_aiohttp(params_dict)

                # Append dict with URL and processed params
                param_list.append({"url": self._availabilty_url(), "params": params_str})

                _current_date += timedelta(days=flex_days + 1)
            
            requests_params[code] = param_list
        
        return requests_params

    async def _prepare_availability_request_params_v2(
            self,
            origin: str,
            from_date: date,
            to_date: date,
            destinations: Iterable[str],
            round_trip: bool = True
        ) -> List[Dict]: # Returns a flat list of params
        """(Async) Prepares parameters for farfnd API calls.

        Fetches schedules asynchronously first to determine relevant time ranges.
        Returns a flat list of request parameter dicts. Each dict contains 'url'
        and 'params' keys suitable for `self.get`.
        """
        if round_trip:
            logger.warning("_prepare_availability_request_params_v2 called with round_trip=True, but endpoint is for one-way fares.")
            raise ValueError("round_trip must be False for one-way fares")

        request_params = []
        dest_list = list(destinations) # Consume iterable

        # Fetch schedules concurrently for all destinations in the date range
        schedules_by_code = await self._fetch_and_compute_schedules(
            origin=origin,
            destinations=destinations,
            from_date=from_date,
            to_date=to_date
        )

        # Process schedules day by day to find time ranges
        for days_offset in range(0, (to_date - from_date).days + 1):
            current_date = from_date + timedelta(days=days_offset)

            day_schedules: List[Schedule] = []
            # Gather schedules for the current day from all destinations
            for code in dest_list:
                for schedule in schedules_by_code.get(code, []):
                    if schedule.departure_time.date() == current_date:
                        day_schedules.append(schedule)

            if not day_schedules:
                continue

            day_schedules.sort(key=lambda s: s.departure_time)
            
            time_ranges = []

            time_from = day_schedules[0].departure_time.time()
            time_to = time_from

            # Initialize counts for destinations on this specific day
            # Filter dest_list based on actual schedules found for the day
            active_dest_list = list(set(s.destination for s in day_schedules))
            counts = {code: 0 for code in active_dest_list}
            
            i = 0
            while i < len(day_schedules):
                schedule = day_schedules[i]
                
                # Skip if destination is not active for this day (shouldn't happen with active_dest_list)
                if schedule.destination not in counts:
                    i += 1
                    continue

                if counts[schedule.destination] == 1:
                    # We've already seen one flight to this destination in the current time slice.
                    # End the current time slice just before this flight's departure.
                    time_to = (datetime.combine(
                        date=current_date, # Use current_date
                        time=schedule.departure_time.time()
                    ) - timedelta(minutes=1)).time()

                    time_ranges.append((time_from, time_to))
                    
                    # Start the new time slice from this flight's departure time.
                    time_from = schedule.departure_time.time()
                    time_to = time_from # Reset time_to
                    
                    # Find all flights departing at the exact same time as the current one
                    same_time_schedules = [
                        s for s in day_schedules[i:] # Optimization: only look forward
                        if s.departure_time.time() == schedule.departure_time.time()
                    ]
                    
                    # Reset counts for the new time slice, only including destinations with flights at this new start time
                    new_active_dests = list(set(s.destination for s in same_time_schedules))
                    counts = {code: 0 for code in new_active_dests} # Reset with only relevant destinations

                    # Populate counts based on flights starting exactly at time_from
                    for s in same_time_schedules:
                         if s.destination in counts:
                            counts[s.destination] += 1

                    # Advance index 'i' past all flights departing at this same time
                    # Find the index of the last flight in same_time_schedules within the original day_schedules list
                    if same_time_schedules:
                        last_same_time_schedule_original_index = -1
                        # Find the original index (this is inefficient, but mimics original logic attempt)
                        for idx in range(i, len(day_schedules)):
                            if day_schedules[idx] == same_time_schedules[-1]:
                                last_same_time_schedule_original_index = idx
                                break
                        if last_same_time_schedule_original_index != -1:
                            i = last_same_time_schedule_original_index # Move i past this group
                        else:
                            # Fallback if schedule not found (shouldn't happen)
                            i += len(same_time_schedules) -1 
                    else:
                        # Fallback if same_time_schedules is empty (shouldn't happen if i < len(day_schedules))
                        # i will be incremented at the end
                        pass
                         
                else:
                    # This is the first flight encountered for this destination in the current time slice.
                    counts[schedule.destination] += 1
                    # Extend the current time slice up to this flight's departure time.
                    time_to = schedule.departure_time.time()
                
                i += 1 # Move to the next schedule

            # Append the last time range after the loop finishes
            if time_ranges or day_schedules: # Ensure we add if there were any schedules
                # Check if the last time_to needs adjustment based on the very last schedule
                if day_schedules:
                    last_schedule_time = day_schedules[-1].departure_time.time()
                    if time_to < last_schedule_time:
                        time_to = last_schedule_time # Ensure the last range covers the last flight
                time_ranges.append((time_from, time_to))
            
            # Create request parameters for each calculated time range
            for time_from, time_to in time_ranges:
                # Identify destinations active within this specific time range
                # This is complex to track precisely with the above logic.
                # A simplification: include all destinations active on the day.
                # The API might handle filtering internally.
                # Alternatively, could try to track active destinations per range, but adds complexity.
                # Using active_dest_list (all dests with flights on this day) for simplicity.
                if not active_dest_list: continue # Skip if no destinations had flights today

                payload = get_farfnd_one_way_payload(
                    origin=origin,
                    destinations=active_dest_list, # Use destinations active on this day
                    date_from=current_date,
                    date_to=current_date,
                    time_from=time_from,
                    time_to=time_to,
                    market=self._market
                )
                params_dict = payload.to_dict()
                # Convert params using the helper function
                params_str = self._prepare_params_for_aiohttp(params_dict)

                request_params.append({"url": self._one_way_fares_url(), "params": params_str})

        return request_params

    async def _prepare_schedules_request_params(
            self,
            origin: str,
            destinations: Iterable[str],
            from_date: date,
            to_date: date
        ) -> Dict[str, List[Dict]]: # Return dict of params
        """(Async) Prepares parameters for schedules API calls.

        Returns a dictionary mapping destination codes to lists of request parameter dicts.
        Each param dict contains 'url' and 'params' (which is None for schedules).
        """
        requests_params = dict()

        for destination in destinations:
            param_list = []
            for year in range(from_date.year, to_date.year + 1):
                if year == from_date.year and from_date.year != to_date.year:
                    month_range = range(from_date.month, 13)
                elif year == to_date.year and from_date.year != to_date.year:
                    month_range = range(1, to_date.month + 1)
                elif year == from_date.year and from_date.year == to_date.year:
                    month_range = range(from_date.month, to_date.month + 1)
                else:
                    month_range = range(1, 13)

                for month in month_range:
                    url = self._schedules_url(
                        origin=origin,
                        destination=destination,
                        year=year,
                        month=month
                    )
                    # Append dict with URL (no params needed for schedules URL)
                    param_list.append({"url": url, "params": None})

            requests_params[destination] = param_list

        return requests_params

    async def _execute_requests_concurrently(
        self,
        request_params: List[Dict]
    ) -> List[aiohttp.ClientResponse | Exception]: # Return list of responses or exceptions
        """Executes a list of prepared requests concurrently using asyncio.gather.

        Args:
            request_params: A list of dictionaries, where each dict contains
                            'url' and 'params' keys for `self.get`.

        Returns:
            A list containing either `aiohttp.ClientResponse` objects for successful
            requests or `Exception` objects for failed requests. The order corresponds
            to the input `request_params`. Caller must handle response context/closing.
        """
        if not request_params:
            return []

        tasks = [
            self.get(url=p["url"], params=p.get("params")) 
            for p in request_params
        ]
        
        logger.debug(f"Executing {len(tasks)} requests concurrently...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        logger.debug(f"Finished executing {len(tasks)} requests.")
        
        success_count = sum(1 for r in results if isinstance(r, aiohttp.ClientResponse))
        error_count = len(results) - success_count
        logger.debug(f"Concurrent execution results: {success_count} successes, {error_count} errors.")

        return results

    async def _execute_and_compute_availability(
            self,
            origin: str,
            code_requests_params: Dict[str, List[Dict]],
            min_days: int,
            max_days: int
        ) -> List[RoundTripFare]:
        """(Async) Executes availability requests concurrently and computes round trip fares.

        Args:
            origin: Origin IATA code.
            code_requests_params: Params dict generated by `_prepare_availability_request_params`.
            min_days: Minimum trip duration.
            max_days: Maximum trip duration.

        Returns:
            A list of `RoundTripFare` objects.
        """
        fares, timer = list(), Timer()

        for code, param_list in code_requests_params.items():
            if not param_list:
                logger.debug(f"No request parameters prepared for {origin}-{code}, skipping.")
                continue
                
            timer.start()
            logger.debug(f"Executing {len(param_list)} availability requests for {origin}-{code}...")
            # Execute requests for this destination
            results = await self._execute_requests_concurrently(param_list)
            
            successful_data = []
            for i, result in enumerate(results):
                if isinstance(result, aiohttp.ClientResponse):
                    try:
                        # Ensure context is managed while reading JSON
                        async with result as response:
                           json_data = await response.json()
                           # Basic check for expected structure before appending
                           if isinstance(json_data, dict) and 'trips' in json_data:
                              successful_data.append(json_data)
                           else:
                              logger.warning(f"Availability response for {origin}-{code} (URL: {response.url}) has unexpected structure: {str(json_data)[:200]}...")
                    except aiohttp.ContentTypeError:
                        # Log error if response is not JSON
                        logger.error(f"Availability response for {origin}-{code} (URL: {result.url}) is not valid JSON.", exc_info=False)
                    except Exception as e:
                        logger.error(f"Error processing JSON for {origin}-{code} (URL: {result.url}): {repr(e)}", exc_info=False)
                elif isinstance(result, Exception):
                    failed_url = param_list[i]["url"]
                    logger.warning(f"Availability request failed for {origin}-{code} (URL: {failed_url}): {result}")

            if successful_data:
                # Pass the extracted list of dicts, not response objects
                computed_fares = self._compute_round_trip_fares(
                    response_data_list=successful_data,
                    origin=origin,
                    destination=code,
                    min_days=min_days,
                    max_days=max_days
                )
                fares.extend(computed_fares)
            else:
                logger.warning(f"No successful availability data collected for {origin}-{code}")
                    
            timer.stop()
            logger.info(f"{origin}-{code} availability scraped in {timer.seconds_elapsed}s")

        return fares

    async def _fetch_and_compute_schedules(
            self,
            origin: str,
            destinations: Iterable[str],
            from_date: date,
            to_date: date
        ) -> Dict[str, List[Schedule]]:
        """(Async) Fetches schedules concurrently for multiple destinations and computes Schedule objects.

        Returns:
             A dictionary mapping destination IATA codes to lists of `Schedule` objects
             found within the specified date range.
        """
        schedules_by_code: Dict[str, List[Schedule]] = {dest: [] for dest in destinations}
        timer = Timer()

        # Prepare schedule request parameters
        code_requests_params = await self._prepare_schedules_request_params(
            origin=origin,
            destinations=destinations,
            from_date=from_date,
            to_date=to_date
        )

        # Flatten params and map back to destination
        all_request_params = []
        dest_map = {}
        param_index = 0
        for dest, params_list in code_requests_params.items():
            all_request_params.extend(params_list)
            for i in range(len(params_list)):
                dest_map[param_index + i] = dest
            param_index += len(params_list)
            
        timer.start()
        # Execute all schedule requests concurrently
        results = await self._execute_requests_concurrently(all_request_params)
        timer.stop()
        logger.info(f"Fetched schedules data for {origin} in {timer.seconds_elapsed}s")

        processing_timer = Timer(start=True)
        # Process results
        for i, result in enumerate(results):
            destination = dest_map.get(i)
            if destination is None: continue

            if isinstance(result, Exception):
                 logger.warning(f"Schedule request failed for {origin}-{destination} (index {i}): {result}")
                 continue
            
            # Process successful response
            try:
                # get_schedules is already async and handles context/json parsing
                scheds = await self.get_schedules(
                    origin=origin,
                    destination=destination,
                    response=result # Pass the response object
                )
                # Filter schedules by the exact date range (get_schedules might parse broader month range)
                for sched in scheds:
                    if from_date <= sched.departure_time.date() <= to_date:
                        schedules_by_code[destination].append(sched)
            except Exception as e:
                logger.error(f"Failed to process schedule response for {origin}-{destination} (index {i}): {e}", exc_info=True)
            finally:
                # Ensure response is released if get_schedules didn't handle it (e.g., if it raises before async with)
                if isinstance(result, aiohttp.ClientResponse) and not result.closed:
                    await result.release()

        processing_timer.stop()
        logger.debug(f"Processed schedule responses in {processing_timer.seconds_elapsed}s")
        return schedules_by_code

    def _compute_round_trip_fares(
            self,
            response_data_list: List[dict],
            origin: str,
            destination: str,
            min_days: int,
            max_days: int
        ) -> List[RoundTripFare]:
        """Computes round trip fares from a list of successful availability JSON data dictionaries.

        Args:
            response_data_list: A list of dictionaries, where each dict is the parsed JSON
                                from a successful availability API response.
            origin: Origin IATA code.
            destination: Destination IATA code.
            min_days: Minimum trip duration.
            max_days: Maximum trip duration.

        Returns:
            A list of `RoundTripFare` objects.
        """
        
        # Aggregate data from all responses for this origin-destination pair
        aggregated_trips = None
        currency = None

        logger.debug(f"Computing round trip fares for {origin}-{destination}. Processing {len(response_data_list)} data items.")
        # Iterate through the already extracted JSON data (dictionaries)
        for i, json_res in enumerate(response_data_list):
            try:
                # Basic check for expected structure before processing
                if not isinstance(json_res, dict) or 'trips' not in json_res or not isinstance(json_res['trips'], list):
                    logger.warning(f"Data item {i+1}/{len(response_data_list)} for {origin}-{destination} has unexpected structure: {str(json_res)[:200]}...")
                    continue
                    
                if aggregated_trips is None:
                    # Initialize directly from the first valid response's trips list
                    aggregated_trips = json_res['trips']
                    currency = json_res.get('currency')
                    logger.debug(f"Initialized aggregated_trips from data item {i+1}. Num trips: {len(aggregated_trips)}. Currency: {currency}")
                else:
                    # Extend dates (logic remains the same)
                    if len(aggregated_trips) >= 2 and len(json_res['trips']) >= 2:
                        if 'dates' in aggregated_trips[0] and 'dates' in json_res['trips'][0]:
                            aggregated_trips[0]['dates'].extend(json_res['trips'][0]['dates'])
                        if 'dates' in aggregated_trips[1] and 'dates' in json_res['trips'][1]:
                            aggregated_trips[1]['dates'].extend(json_res['trips'][1]['dates'])
                        logger.debug(f"Extended aggregated_trips with data from item {i+1}")
                    else:
                        logger.warning(f"Skipping extension from data item {i+1} due to unexpected trip structure. Aggregated: {len(aggregated_trips)}, Current: {len(json_res['trips'])}")
                         
            except Exception as e:
                # Log errors during aggregation
                logger.error(f"Error processing data item {i+1}/{len(response_data_list)} for {origin}-{destination}: {repr(e)}", exc_info=False)
                continue # Skip this data item
        
        if aggregated_trips and len(aggregated_trips) >= 2:
            out_dates_count = len(aggregated_trips[0].get('dates', []))
            ret_dates_count = len(aggregated_trips[1].get('dates', []))
            logger.debug(f"Aggregated data for {origin}-{destination}: Outbound dates: {out_dates_count}, Return dates: {ret_dates_count}, Currency: {currency}")
            
            if out_dates_count == 0 or ret_dates_count == 0:
                logger.debug(f"Aggregated trips structure sample for {origin}-{destination}: {str(aggregated_trips)[:500]}...")
        else:
            logger.warning(f"Insufficient aggregated trip data structure for {origin}-{destination}. Structure: {aggregated_trips}")
            return [] # Return early if structure is wrong

        if not aggregated_trips or len(aggregated_trips) < 2:
            logger.warning(f"Insufficient trip data after processing responses for {origin}-{destination}")
            return []

        fares = []
        outbound_dates = aggregated_trips[0].get('dates', []) # Use .get for safety
        return_dates = aggregated_trips[1].get('dates', []) # Use .get for safety

        # Pre-process return dates for faster lookup (optional but can help)
        return_dates_map = {date.fromisoformat(d['dateOut'][:10]): d['flights'] for d in return_dates if 'dateOut' in d and 'flights' in d}

        for trip_date_out in outbound_dates:
            try:
                date_out_str = trip_date_out.get('dateOut')
                if not date_out_str: continue # Skip if no dateOut
                date_out = date.fromisoformat(date_out_str[:10])
                
                outbound_flights = trip_date_out.get('flights', [])
                if not outbound_flights: continue # Skip if no flights for this date
                
                for outbound_flight in outbound_flights:
                    if outbound_flight.get('faresLeft', 0) != 0 and outbound_flight.get('regularFare'):
                        # Calculate date range for return flight based on min/max days
                        min_return_date = date_out + timedelta(days=min_days)
                        max_return_date = date_out + timedelta(days=max_days)

                        # Iterate through potential return dates efficiently
                        current_return_date = min_return_date
                        while current_return_date <= max_return_date:
                            if current_return_date in return_dates_map:
                                for return_flight in return_dates_map[current_return_date]:
                                    if return_flight.get('faresLeft', 0) != 0 and return_flight.get('regularFare'):
                                        try:
                                            # Add checks for list lengths before indexing
                                            out_time = outbound_flight.get('time')
                                            ret_time = return_flight.get('time')
                                            out_fare_info = outbound_flight['regularFare'].get('fares')
                                            ret_fare_info = return_flight['regularFare'].get('fares')
                                            
                                            if not (out_time and len(out_time) >= 2 and 
                                                    ret_time and len(ret_time) >= 2 and 
                                                    out_fare_info and len(out_fare_info) >= 1 and 
                                                    ret_fare_info and len(ret_fare_info) >= 1):
                                                logger.debug(f"Skipping fare pair due to missing time/fare data. Out: {outbound_flight}, Ret: {return_flight}")
                                                continue
                                                 
                                            fares.append(RoundTripFare(
                                                datetime.fromisoformat(out_time[0]),
                                                datetime.fromisoformat(out_time[1]),
                                                datetime.fromisoformat(ret_time[0]),
                                                datetime.fromisoformat(ret_time[1]),
                                                origin, # Use passed origin
                                                destination, # Use passed destination
                                                out_fare_info[0]['amount'],
                                                outbound_flight['faresLeft'],
                                                ret_fare_info[0]['amount'],
                                                return_flight['faresLeft'],
                                                currency
                                            ))
                                        except (KeyError, IndexError, ValueError, TypeError) as parse_err:
                                            logger.warning(f"Failed parsing fare pair for {origin}-{destination}: {parse_err}. Out: {outbound_flight}, Ret: {return_flight}")
                            current_return_date += timedelta(days=1)
            except Exception as outer_loop_err:
                 logger.error(f"Error in outer fare computation loop for {origin}-{destination} on {trip_date_out.get('dateOut')}: {outer_loop_err}", exc_info=True)
        
        return fares
    
    @staticmethod
    def get_flight_key(flight: OneWayFare) -> str:
        return f"{flight.origin}({flight.dep_time}):{flight.destination}({flight.arr_time})"

    @classmethod
    def _airport_info_url(cls, iata_code: str) -> str:
        return cls.BASE_API_URL + f'views/locate/5/airports/en/{iata_code}'

    @classmethod
    def _available_dates_url(cls, origin: str, destination: str) -> str:
        return cls.BASE_API_URL + \
            f"farfnd/v4/oneWayFares/{origin}/{destination}/availabilities"
    
    @classmethod
    def _active_airports_url(cls) -> str:
        return cls.BASE_API_URL + "views/locate/5/airports/en/active"
    
    @classmethod
    def _destinations_url(cls, origin: str) -> str:
        return cls.BASE_API_URL + \
            f"views/locate/searchWidget/routes/en/airport/{origin}"
    
    @classmethod
    def _one_way_fares_url(cls) -> str:
        return cls.SERVICES_API_URL + "farfnd/v4/oneWayFares"

    @classmethod
    def _round_trip_fares_url(cls) -> str:
        return cls.SERVICES_API_URL + "farfnd/v4/roundTripFares"
    
    @classmethod
    def _schedules_url(cls, origin: str, destination: str, year: int, month: int) -> str:
        return cls.SERVICES_API_URL + \
            f"timtbl/3/schedules/{origin}/{destination}/years/{year}/months/{month}"
    
    def _availabilty_url(self) -> str:
        return self.BASE_API_URL + \
            f"booking/v4/{self._currency_str}availability"

    def __deepcopy__(self, memo):
        cls = self.__class__
        id_self = id(self)
        _copy = memo.get(id_self)
        if _copy is None:
            _copy = cls.__new__(cls)
            memo[id_self] = _copy
            for k, v in self.__dict__.items():
                if k == 'sm':
                    setattr(_copy, k, self.sm)  # Ensure the same session manager is used
                else:
                    setattr(_copy, k, deepcopy(v, memo))
        return _copy
    
    async def __aenter__(self):
        """Initializes the client (e.g., fetches airports) on entering the async context."""
        await self.update_active_airports()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Closes the underlying session on exiting the async context."""
        await self.sm.close_session()