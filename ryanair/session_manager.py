import aiohttp
import asyncio
import logging
from itertools import cycle
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class SessionManager:
    BASE_SITE_FOR_SESSION_URL = "https://www.ryanair.com"
    SESSION_HEADERS = {
        "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/132.0.0.0 Safari/537.36",
        "Accept": "application/json",
        'client': 'desktop',
        'client-version': '3.132.0'
    }
    HEADER_SIZE_LIMIT = 16 * 1024 # 16KB, adjust if needed

    def __init__(self, timeout: int):
        self._session: Optional[aiohttp.ClientSession] = None
        self._timeout = timeout # Keep timeout, aiohttp uses it differently
        self._create_proxies_pool()
        self._lock = asyncio.Lock() # Lock for session creation

    async def get_session(self) -> aiohttp.ClientSession:
        """Gets the current aiohttp session, creating one if necessary."""
        async with self._lock:
            if self._session is None or self._session.closed:
                logger.debug("Creating new aiohttp ClientSession with increased header limits.")

                self._session = aiohttp.ClientSession(
                    headers=self.SESSION_HEADERS,
                    max_line_size=self.HEADER_SIZE_LIMIT,
                    max_field_size=self.HEADER_SIZE_LIMIT
                )
                try:
                    # Make an initial request to potentially set cookies
                    # Use a reasonable timeout for this initial request
                    timeout = aiohttp.ClientTimeout(total=self.timeout)
                    logger.debug(f"Making initial request to {self.BASE_SITE_FOR_SESSION_URL}")
                    async with self._session.get(self.BASE_SITE_FOR_SESSION_URL, timeout=timeout) as response:
                        response.raise_for_status()
                        logger.debug(f"Initial session request to {self.BASE_SITE_FOR_SESSION_URL} status: {response.status}")
                        # Consume body to avoid unread connection warnings
                        await response.text()
                except aiohttp.ClientResponseError as e:
                    # Log HTTP errors specifically
                    logger.warning(f"Initial session request failed with HTTP status {e.status}: {e.message}. URL: {e.request_info.url}. Proceeding without initial cookies.")
                except asyncio.TimeoutError:
                    logger.warning(f"Initial session request timed out after {self.timeout}s. Proceeding without initial cookies.")
                except aiohttp.ClientError as e:
                    # Catch other client errors (connection issues, etc.)
                    logger.warning(f"Initial session request failed: {type(e).__name__} - {e}. Proceeding without initial cookies.")
                    
            return self._session

    @property
    def timeout(self) -> int:
        return self._timeout

    def _create_proxies_pool(self) -> None:
        # Initialize with None to indicate no proxy by default
        self._proxies_pool: List[Optional[str]] = [None]
        self._proxies_loop = cycle(self._proxies_pool)

    def extend_proxies_pool(self, proxies: List[Dict[str, str]]):
        """Adds proxy URLs to the pool. Expects a list of dicts like [{'http': url, 'https': url}]."""
        if not proxies:
            return

        # Remove the default None if we are adding actual proxies
        if self._proxies_pool == [None]:
            self._proxies_pool.pop()

        # Extract the URL - assuming http and https are the same proxy URL
        proxy_urls = [p.get("http") or p.get("https") for p in proxies if p.get("http") or p.get("https")]
        
        # Add unique proxy URLs
        added_count = 0
        for url in proxy_urls:
            if url and url not in self._proxies_pool:
                self._proxies_pool.append(url)
                added_count +=1

        if added_count > 0:
            logger.info(f"Added {added_count} unique proxies to the pool.")
            # Recreate the cycle iterator with the updated pool
            self._proxies_loop = cycle(self._proxies_pool)
        elif not self._proxies_pool:
            # If after adding, pool is still empty, add None back
            logger.warning("Proxy list provided, but no valid URLs extracted. Using no proxy.")
            self._proxies_pool = [None]
            self._proxies_loop = cycle(self._proxies_pool)

    def get_next_proxy_url(self) -> Optional[str]:
        """Returns the next proxy URL from the pool (can be None)."""
        next_proxy = next(self._proxies_loop)
        logger.debug(f"Using proxy: {next_proxy}")
        return next_proxy

    async def close_session(self):
        """Closes the aiohttp session if it exists."""
        async with self._lock:
            if self._session and not self._session.closed:
                await self._session.close()
                self._session = None
                logger.info("aiohttp ClientSession closed.")

    # __del__ is unreliable, better to explicitly close the session
    # async def __aenter__(self):
    #     await self.get_session()
    #     return self

    # async def __aexit__(self, exc_type, exc_val, exc_tb):
    #     await self.close_session()