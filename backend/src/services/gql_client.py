"""
Twitch GraphQL API Client Module

This module provides a robust client for interacting with Twitch's GraphQL API,
handling authentication, rate limiting, caching, and error management.

The GQLClient class offers methods to:
- Look up channel IDs from usernames
- Check stream status for multiple streamers
- Get detailed channel information with efficient caching
- Manage SSL contexts and connection handling

Usage:
    client = GQLClient()
    
    # Look up channel IDs
    ids = await client.lookup_channel_ids(["streamer1", "streamer2"])
    
    # Check if streams are live
    statuses = await client.check_streams_status(["streamer1", "streamer2"])
    
    # Get detailed channel info
    channel_info = await client.get_channel_info("channel_id")
"""

from typing import Dict, Any, List, Optional
import asyncio
import aiohttp
import time
import ssl
import certifi
from backend.src.config.constants import TWITCH_GQL_URL, CLIENT_ID


class GQLClient:
    """
    Client for making GraphQL requests to Twitch's API.
    
    This client handles authentication, rate limiting, request timeouts,
    response caching, and SSL configuration for secure API communication.
    
    Attributes:
        headers (Dict[str, str]): HTTP headers for GraphQL requests
        _rate_limit_semaphore (asyncio.Semaphore): Semaphore for API rate limiting
        _request_timeout (aiohttp.ClientTimeout): Timeout configuration for requests
        _cache (Dict): Cache storage for API responses
        _cache_ttl (Dict): Time-to-live values for different cache types
        _ssl_context (ssl.SSLContext): SSL context for secure connections
    """

    def __init__(self):
        """
        Initialize the GraphQL client with default configuration.
        
        Sets up headers, rate limiting, timeouts, caching configuration,
        and SSL context for secure API communication.
        """
        self.headers = {
            "Client-ID": CLIENT_ID,
            "Content-Type": "application/json",
        }
        # Rate limit to 10 concurrent requests
        self._rate_limit_semaphore = asyncio.Semaphore(10)
        # Set 10-second timeout for requests
        self._request_timeout = aiohttp.ClientTimeout(total=10)
        # Initialize cache storage
        self._cache = {}
        # Configure TTL values for different cache types
        self._cache_ttl = {
            "channel_info": 86400,  # 24 hours for profile images, offline screens
            "stream_status": 60     # 1 minute for stream status
        }
        
        # Create a secure SSL context using certifi's CA bundle
        self._ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def lookup_channel_ids(self, usernames: List[str]) -> Dict[str, str]:
        """
        Look up Twitch channel IDs for a list of usernames.
        
        Args:
            usernames: List of Twitch usernames to look up
            
        Returns:
            Dict mapping lowercase usernames to their corresponding channel IDs.
            Only successfully looked up usernames will be included in the result.
            
        Note:
            This method handles rate limiting automatically and processes
            usernames sequentially to comply with API restrictions.
        """
        if not usernames:
            return {}

        username_to_id = {}
        query = {
            "operationName": "GetUserID",
            "variables": {"login": None},
            "query": """
                query GetUserID($login: String!) {
                    user(login: $login) {
                        id
                        login
                        displayName
                    }
                }
            """,
        }

        for username in usernames:
            try:
                if not username or not username.strip():
                    continue
                    
                async with self._rate_limit_semaphore:
                    query["variables"]["login"] = username
                    # Use SSL context for secure connection
                    async with aiohttp.ClientSession(
                        timeout=self._request_timeout,
                        connector=aiohttp.TCPConnector(ssl=self._ssl_context)
                    ) as session:
                        async with session.post(
                            TWITCH_GQL_URL,
                            headers=self.headers,
                            json=query,
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                if not data or not isinstance(data, dict):
                                    print(f"[GQL] Invalid response for username {username}")
                                    continue
                                    
                                # Use safe nested gets to avoid KeyError
                                user_data = data.get("data", {}).get("user", {})
                                if user_data and user_data.get("id"):
                                    user_id = user_data.get("id")
                                    username_to_id[username.lower()] = user_id
                                    print(
                                        f"[GQL] Found channel ID for {username}: {user_id}"
                                    )

                # Add small delay between requests to avoid rate limiting
                await asyncio.sleep(0.1)
            except asyncio.TimeoutError:
                print(f"[GQL] Timeout looking up channel ID for {username}")
                continue
            except Exception as e:
                print(f"[GQL] Error looking up channel ID for {username}: {e}")
                import traceback
                traceback.print_exc()
                continue

        return username_to_id
        
    async def check_streams_status(self, usernames: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Check stream status for multiple Twitch usernames simultaneously.
        
        Args:
            usernames: List of Twitch usernames to check
            
        Returns:
            Dict mapping lowercase usernames to their stream status information.
            Each status contains fields like:
            - isLive (bool): Whether stream is currently live
            - title (str): Stream title if live, None otherwise
            - thumbnail (str): Stream thumbnail URL if live, None otherwise
            - profileImageURL (str): User's profile image URL
            - offlineImageURL (str): User's offline banner image URL
            
        Note:
            Processes usernames in batches of 5 to avoid rate limiting and 
            timeout issues. Failed lookups will return default offline status.
        """
        if not usernames:
            return {}
            
        results = {}
        
        # Process in smaller batches to avoid rate limits and timeout issues
        batch_size = 5
        for i in range(0, len(usernames), batch_size):
            batch = usernames[i:i+batch_size]
            batch_results = await asyncio.gather(
                *[self.check_stream_status(username) for username in batch],
                return_exceptions=True
            )
            
            for j, username in enumerate(batch):
                # Skip results that raised exceptions
                if isinstance(batch_results[j], Exception):
                    print(f"[GQL] Error checking stream status for {username}: {batch_results[j]}")
                    results[username.lower()] = {"isLive": False, "title": None, "thumbnail": None}
                else:
                    results[username.lower()] = batch_results[j]
                    
            # Add a small delay between batches
            if i + batch_size < len(usernames):
                await asyncio.sleep(0.5)
                
        return results
        
    async def check_stream_status(self, username: str) -> Dict[str, Any]:
        """
        Check if a specific Twitch streamer is live and get stream information.
        
        Args:
            username: Twitch username to check
            
        Returns:
            Dict containing stream status information:
            - isLive (bool): Whether stream is currently live
            - profileImageURL (str): User's profile image URL
            - displayName (str): User's display name
            - offlineImageURL (str): User's offline banner image URL
            - title (str): Stream title if live, None otherwise
            - thumbnail (str): Stream thumbnail URL if live, None otherwise
            - viewersCount (int): Current viewer count if live, None otherwise
            - game (str): Game being played if live, None otherwise
            
        Note:
            Returns a default offline status dict if any errors occur during the lookup.
        """
        if not username or not username.strip():
            return {"isLive": False, "title": None, "thumbnail": None}
            
        query = {
            "operationName": "GetStreamStatus",
            "variables": {"login": username.lower()},
            "query": """
                query GetStreamStatus($login: String!) {
                    user(login: $login) {
                        login
                        displayName
                        profileImageURL(width: 150)  # Request higher quality profile image
                        offlineImageURL
                        stream {
                            id
                            title
                            viewersCount
                            previewImageURL(width: 440, height: 248)
                            game {
                                name
                            }
                        }
                    }
                }
            """
        }
        
        try:
            async with self._rate_limit_semaphore:
                # Use SSL context for secure connection
                async with aiohttp.ClientSession(
                    timeout=self._request_timeout,
                    connector=aiohttp.TCPConnector(ssl=self._ssl_context)
                ) as session:
                    async with session.post(
                        TWITCH_GQL_URL,
                        headers=self.headers,
                        json=query
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            # Handle invalid responses
                            if not data or not isinstance(data, dict):
                                print(f"[GQL] Invalid response format for {username}")
                                return {"isLive": False, "title": None, "thumbnail": None}
                                
                            # Extract user data
                            user_data = data.get("data", {}).get("user", {})
                            if not user_data:
                                print(f"[GQL] No user data for {username}")
                                return {"isLive": False, "title": None, "thumbnail": None}
                                
                            # Check if stream exists
                            stream = user_data.get("stream", None)
                            
                            # Create result with basic user info
                            result = {
                                "isLive": bool(stream),
                                "profileImageURL": user_data.get("profileImageURL"),
                                "displayName": user_data.get("displayName"),
                                "offlineImageURL": user_data.get("offlineImageURL"),
                                "title": None,
                                "thumbnail": None
                            }
                            
                            # Add stream info if live
                            if stream and isinstance(stream, dict):
                                result.update({
                                    "title": stream.get("title"),
                                    "thumbnail": stream.get("previewImageURL"),
                                    "viewersCount": stream.get("viewersCount"),
                                    "game": (stream.get("game") or {}).get("name")
                                })
                                
                            return result
                        else:
                            print(f"[GQL] Error response {response.status} for {username}")
                            return {"isLive": False, "title": None, "thumbnail": None}
        except asyncio.TimeoutError:
            print(f"[GQL] Timeout checking stream status for {username}")
            return {"isLive": False, "title": None, "thumbnail": None}
        except Exception as e:
            print(f"[GQL] Error checking stream status for {username}: {e}")
            import traceback
            traceback.print_exc()
            return {"isLive": False, "title": None, "thumbnail": None}
        
    async def get_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """
        Get detailed channel information with efficient caching.
        
        Implements a two-level caching strategy:
        1. Profile images and offline images are cached for 24 hours
        2. Stream status is cached for only 1 minute
        
        Args:
            channel_id: Twitch channel ID to look up
            
        Returns:
            Dict containing channel information including:
            - login (str): Username
            - displayName (str): Display name
            - profileImageURL (str): Profile image URL
            - offlineImageURL (str): Offline banner image URL
            - title (str): Stream title if live
            - thumbnail (str): Stream thumbnail URL if live
            - viewersCount (int): Current viewer count if live
            - game (str): Game being played if live
            - stream (dict): Raw stream data if live
            
        Note:
            Returns an empty dict if channel_id is invalid or any errors occur.
            Uses cached data when available to reduce API calls.
        """
        if not channel_id:
            print(f"[GQL] Warning: Called get_channel_info with empty channel_id")
            return {}
            
        cache_key = f"channel_info:{channel_id}"
        
        # Check if we have cached data that's still valid
        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            age = time.time() - cached_data["timestamp"]
            
            # Different TTL for different parts of the data
            if age < self._cache_ttl["channel_info"]:
                # For profile images and offline images, use cached data
                result = cached_data["data"].copy()
                
                # For stream status, check if we need fresh data
                if age >= self._cache_ttl["stream_status"]:
                    # Only fetch stream status (not profile images)
                    fresh_stream = await self._fetch_stream_status(channel_id)
                    if fresh_stream:
                        result.update(fresh_stream)
                        # Update cache with new stream status
                        cached_data["data"].update(fresh_stream)
                        self._cache[cache_key] = {
                            "data": cached_data["data"],
                            "timestamp": time.time()
                        }
                
                return result
        
        # If not cached or expired, fetch full data
        result = await self._fetch_channel_info(channel_id)
        
        # Cache the result
        if result:
            self._cache[cache_key] = {
                "data": result,
                "timestamp": time.time()
            }
        
        return result

    async def _fetch_channel_info(self, channel_id: str) -> Dict[str, Any]:
        """
        Fetch complete channel information from Twitch GraphQL API.
        
        Internal method that queries the API for all channel data including:
        - Basic user information (login, display name)
        - Profile and offline images
        - Stream status and details if currently live
        
        Args:
            channel_id: Twitch channel ID to look up
            
        Returns:
            Dict containing complete channel information or empty dict on error
            
        Note:
            This method is used internally by get_channel_info when cache is invalid.
        """
        query = {
            "operationName": "GetChannelInfo",
            "query": """
                query GetChannelInfo($id: ID!) {
                    user(id: $id) {
                        id
                        login
                        displayName
                        profileImageURL(width: 150)
                        offlineImageURL
                        stream {
                            id
                            title
                            viewersCount
                            previewImageURL(width: 440, height: 248)
                            game {
                                name
                            }
                        }
                    }
                }
            """,
            "variables": {"id": channel_id},
        }

        try:
            async with self._rate_limit_semaphore:
                # Use SSL context for secure connection
                async with aiohttp.ClientSession(
                    timeout=self._request_timeout,
                    connector=aiohttp.TCPConnector(ssl=self._ssl_context)
                ) as session:
                    async with session.post(
                        TWITCH_GQL_URL,
                        headers=self.headers,
                        json=query,
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            # Error handling for missing fields
                            if not data or not isinstance(data, dict):
                                print(f"[GQL] Invalid response format for channel ID {channel_id}")
                                return {}
                                
                            user_data = data.get("data", {}).get("user")
                            if not user_data:
                                print(f"[GQL] No user data for channel ID {channel_id}")
                                return {}
                                
                            stream = user_data.get("stream")

                            # Base response
                            result = {
                                "login": user_data.get("login"),
                                "displayName": user_data.get("displayName"),
                                "profileImageURL": user_data.get("profileImageURL"),
                                "offlineImageURL": user_data.get("offlineImageURL"),
                                "title": None,
                                "thumbnail": None,
                                "viewersCount": None,
                                "game": None,
                                "stream": stream,
                            }

                            # Add stream data if live
                            if stream and isinstance(stream, dict):
                                result.update({
                                    "title": stream.get("title"),
                                    "thumbnail": stream.get("previewImageURL"),
                                    "viewersCount": stream.get("viewersCount"),
                                    "game": (stream.get("game") or {}).get("name"),
                                })

                            return result
                        print(
                            f"[GQL] Error response {response.status} for channel ID {channel_id}"
                        )
                        return {}
        except asyncio.TimeoutError:
            print(f"[GQL] Timeout getting channel info for {channel_id}")
            return {}
        except Exception as e:
            print(f"[GQL] Error getting channel info for {channel_id}: {e}")
            import traceback
            traceback.print_exc()
            return {}

    async def _fetch_stream_status(self, channel_id: str) -> Dict[str, Any]:
        """
        Fetch only stream status information for optimization.
        
        This lightweight query only fetches current stream information without
        retrieving profile images or other static data. Used for efficient
        cache updates of dynamic stream data.
        
        Args:
            channel_id: Twitch channel ID to look up
            
        Returns:
            Dict containing only stream status information or empty dict on error
            
        Note:
            Used internally by get_channel_info for partial cache updates.
        """
        query = {
            "operationName": "GetStreamStatusOnly",
            "query": """
                query GetStreamStatusOnly($id: ID!) {
                    user(id: $id) {
                        stream {
                            id
                            title
                            viewersCount
                            previewImageURL(width: 440, height: 248)
                            game {
                                name
                            }
                        }
                    }
                }
            """,
            "variables": {"id": channel_id},
        }

        try:
            async with self._rate_limit_semaphore:
                # Use SSL context for secure connection
                async with aiohttp.ClientSession(
                    timeout=self._request_timeout,
                    connector=aiohttp.TCPConnector(ssl=self._ssl_context)
                ) as session:
                    async with session.post(
                        TWITCH_GQL_URL,
                        headers=self.headers,
                        json=query,
                    ) as response:
                        if response.status == 200:
                            data = await response.json()
                            
                            # Handle invalid responses
                            if not data or not isinstance(data, dict):
                                return {}
                                
                            user_data = data.get("data", {}).get("user", {})
                            if not user_data:
                                return {}
                                
                            stream = user_data.get("stream")
                            
                            # Create result with just stream status
                            result = {
                                "isLive": bool(stream),
                                "title": None,
                                "thumbnail": None,
                                "viewersCount": None,
                                "game": None,
                            }
                            
                            # Add stream data if live
                            if stream and isinstance(stream, dict):
                                result.update({
                                    "title": stream.get("title"),
                                    "thumbnail": stream.get("previewImageURL"),
                                    "viewersCount": stream.get("viewersCount"),
                                    "game": (stream.get("game") or {}).get("name"),
                                })
                                
                            return result
                        return {}
        except Exception:
            # Just return empty dict for any error
            return {}