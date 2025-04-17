"""
Twitch OAuth Token Management Module

This module provides a robust token management service for handling Twitch OAuth authentication.
It implements automatic token refresh, persistent storage, and callback notifications
to ensure continuous authentication for API requests.

Key features:
- Secure token storage in a local file
- Automatic token refresh before expiration
- Token validation against Twitch API
- Callback system for token refresh events
- Thread-safe operations with asyncio locks

Usage:
    # Initialize token manager with a storage path
    token_manager = TokenManager("/path/to/tokens.json")
    
    # Start the token management service
    await token_manager.start()
    
    # Register a callback for token refresh events
    token_manager.register_refresh_callback(my_refresh_handler)
    
    # Get a valid access token for API requests
    token, refreshed = await token_manager.get_access_token()
    
    # Later, stop the service
    await token_manager.stop()
"""

import os
import json
import time
import asyncio
import aiohttp
from typing import Dict, Any, Optional, Tuple, Callable, List, Awaitable

class TokenManager:
    """
    Service for managing Twitch authentication tokens with automatic refresh.
    
    This class handles OAuth token lifecycle management including storage,
    validation, and scheduled refreshing before expiration. It provides
    thread-safe access to tokens and notifies registered callbacks when
    tokens are refreshed.
    
    Attributes:
        token_file (str): Path to the file for storing authentication tokens
        refresh_endpoint (str): URL for the token refresh service
        tokens (Dict[str, Any]): Currently loaded tokens
        refresh_task (asyncio.Task): Task for scheduled token refresh
        on_token_refresh_callbacks (List): Callbacks to notify on token refresh
        refresh_lock (asyncio.Lock): Lock for thread-safe token refresh
        refresh_buffer (int): Seconds before expiry to trigger refresh
    """
    
    def __init__(self, token_file_path: str, refresh_endpoint: str = None):
        """
        Initialize the token manager.
        
        Args:
            token_file_path: Path to the file for storing auth tokens
            refresh_endpoint: URL for the token refresh service. If None, a default URL is used.
        """
        self.token_file = token_file_path
        self.refresh_endpoint = refresh_endpoint or "https://authentication.acheapdomain.click/auth/refresh"
        self.tokens = None
        self.refresh_task = None
        self.on_token_refresh_callbacks: List[Callable[[str], Awaitable[None]]] = []
        self.refresh_lock = asyncio.Lock()
        self.refresh_buffer = 1800  # Refresh 30 minutes before expiry
        
    async def start(self):
        """
        Start the token manager and refresh scheduler.
        
        Loads tokens from storage and schedules the first refresh task
        if valid tokens are found. This method should be called before
        using any other methods.
        """
        # Load initial tokens
        await self.load_tokens()
        
        # Start refresh task if we have valid tokens
        if self.tokens and self.tokens.get("refresh_token"):
            self.schedule_refresh_task()
            
        print("[TokenManager] Started successfully")
    
    async def stop(self):
        """
        Stop the token manager and cancel any pending refresh tasks.
        
        Gracefully shuts down the token manager by canceling any
        scheduled refresh tasks. This method should be called before
        application shutdown.
        """
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            try:
                await self.refresh_task
            except asyncio.CancelledError:
                pass
        print("[TokenManager] Stopped")
    
    async def load_tokens(self) -> Dict[str, Any]:
        """
        Load tokens from the token file.
        
        Reads and parses the token JSON file from disk. If the file doesn't
        exist or is empty, initializes an empty tokens dictionary.
        
        Returns:
            Dict containing loaded tokens or empty dict if no tokens are found
        """
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, "r") as f:
                    content = f.read().strip()
                    if content:
                        self.tokens = json.loads(content)
                        print("[TokenManager] Loaded tokens from file")
                        return self.tokens
            print("[TokenManager] No token file found or empty file")
            self.tokens = {}
            return {}
        except Exception as e:
            print(f"[TokenManager] Error loading tokens: {e}")
            self.tokens = {}
            return {}
    
    async def save_tokens(self, tokens: Dict[str, Any]) -> bool:
        """
        Save tokens to the token file.
        
        Writes the token dictionary to disk in JSON format with pretty
        formatting for readability. Creates parent directories if needed.
        
        Args:
            tokens: Dictionary containing tokens to save
            
        Returns:
            bool: True if tokens were successfully saved, False otherwise
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            
            # Save tokens with pretty formatting
            with open(self.token_file, "w") as f:
                json.dump(tokens, f, indent=2)
            
            self.tokens = tokens
            return True
        except Exception as e:
            print(f"[TokenManager] Error saving tokens: {e}")
            return False
    
    async def get_access_token(self, force_refresh=False) -> Tuple[Optional[str], bool]:
        """
        Get the current access token, refreshing if needed.
        
        Provides a valid access token for API requests. If the token is
        expired or will expire soon, automatically refreshes it first.
        
        Args:
            force_refresh: If True, force a token refresh regardless of expiration
            
        Returns:
            Tuple containing:
                - The access token (str) or None if no valid token is available
                - Boolean indicating whether the token was refreshed
        """
        # If we don't have tokens, try to load them
        if not self.tokens:
            await self.load_tokens()
            
        # If still no tokens, return None
        if not self.tokens or not self.tokens.get("access_token"):
            return None, False
            
        # Check if token is expired or will expire soon, or if force_refresh is requested
        expires_at = self.tokens.get("expires_at", 0)
        if force_refresh or expires_at < (time.time() + self.refresh_buffer) * 1000:
            # Token expired or will expire soon, try to refresh
            print(f"[TokenManager] Token expired or refresh forced, refreshing...")
            refreshed = await self.refresh_token()
            if refreshed:
                return self.tokens.get("access_token"), True
                
        # Return current token
        return self.tokens.get("access_token"), False
    
    async def refresh_token(self) -> bool:
        """
        Refresh the access token using the refresh token.
        
        Makes an HTTP request to the refresh endpoint to obtain a new access token
        using the stored refresh token. Updates local storage and notifies
        registered callbacks on successful refresh.
        
        Returns:
            bool: True if the token was successfully refreshed, False otherwise
        
        Note:
            This method is thread-safe and uses a lock to prevent concurrent refreshes.
        """
        async with self.refresh_lock:  # Ensure only one refresh occurs at a time
            # Check if we have a refresh token
            if not self.tokens or not self.tokens.get("refresh_token"):
                print("[TokenManager] No refresh token available")
                return False
                
            try:
                refresh_token = self.tokens.get("refresh_token")
                
                # Call the refresh endpoint
                async with aiohttp.ClientSession() as session:
                    url = f"{self.refresh_endpoint}?refresh_token={refresh_token}"
                    
                    async with session.get(url) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            print(f"[TokenManager] Refresh failed: {response.status} - {error_text}")
                            return False
                            
                        # Parse the response
                        new_tokens = await response.json()
                        
                        # Log token information (partial for security)
                        if new_tokens.get("access_token"):
                            token_prefix = new_tokens["access_token"][:10]
                            token_length = len(new_tokens["access_token"])
                        
                        if not new_tokens.get("access_token") or not new_tokens.get("refresh_token"):
                            print("[TokenManager] Invalid refresh response, missing tokens")
                            return False
                            
                        # Update tokens with new data
                        updated_tokens = {
                            "access_token": new_tokens.get("access_token"),
                            "refresh_token": new_tokens.get("refresh_token"),
                            "expires_in": new_tokens.get("expires_in", 14400),  # Default to 4 hours
                            "expires_at": time.time() * 1000 + new_tokens.get("expires_in", 14400) * 1000
                        }
                        
                        # Save the updated tokens
                        saved = await self.save_tokens(updated_tokens)
                        
                        if saved:
                            # Reschedule refresh task
                            self.schedule_refresh_task()
                            
                            # Notify callbacks about refresh
                            for callback in self.on_token_refresh_callbacks:
                                try:
                                    await callback(updated_tokens["access_token"])
                                except Exception as e:
                                    print(f"[TokenManager] Error in refresh callback: {e}")
                            
                            return True
                        else:
                            print("[TokenManager] Failed to save refreshed tokens")
                            return False
            except Exception as e:
                print(f"[TokenManager] Error refreshing token: {e}")
                import traceback
                traceback.print_exc()
                return False
            
    async def validate_token(self, token: str) -> bool:
        """
        Validate a token with the Twitch API.
        
        Makes a test request to the Twitch API to check if the token is valid.
        This is useful when receiving a token from a potentially untrusted source
        or to verify a token before important operations.
        
        Args:
            token: The access token to validate
            
        Returns:
            bool: True if the token is valid, False otherwise
        """
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://api.twitch.tv/helix/users"
                headers = {
                    "Client-ID": "d88elif9gig3jo3921wrlusmc5rz21",
                    "Authorization": f"Bearer {token}"
                }
                async with session.get(url, headers=headers) as response:
                    is_valid = response.status == 200
                    if not is_valid:
                        print(f"[TokenManager] Token validation failed with status: {response.status}")
                    return is_valid
        except Exception as e:
            print(f"[TokenManager] Token validation error: {e}")
            return False

    def schedule_refresh_task(self):
        """
        Schedule a task to refresh the token before it expires.
        
        Calculates the time until token expiration and schedules a refresh
        task to run before the token expires. The refresh buffer determines
        how many seconds before expiration the refresh will occur.
        
        Note:
            If a refresh task is already scheduled, it will be canceled and replaced.
        """
        # Cancel existing task if it exists
        if self.refresh_task and not self.refresh_task.done():
            self.refresh_task.cancel()
            
        # Calculate when to refresh
        if not self.tokens or not self.tokens.get("expires_at"):
            print("[TokenManager] No expiry time, cannot schedule refresh")
            return
            
        expires_at = self.tokens.get("expires_at", 0) / 1000  # Convert from milliseconds
        now = time.time()
        
        time_until_refresh = max(0, expires_at - now - self.refresh_buffer)
        
        # Schedule the refresh task
        self.refresh_task = asyncio.create_task(self._delayed_refresh(time_until_refresh))
    
    async def _delayed_refresh(self, delay_seconds: float):
        """
        Wait for the specified time and then refresh the token.
        
        Internal method used by schedule_refresh_task to perform the actual
        delayed refresh operation.
        
        Args:
            delay_seconds: Number of seconds to wait before refreshing
        """
        try:
            await asyncio.sleep(delay_seconds)
            await self.refresh_token()
        except asyncio.CancelledError:
            pass  # Silent cancellation
        except Exception as e:
            print(f"[TokenManager] Refresh error: {e}")
    
    def register_refresh_callback(self, callback: Callable[[str], Awaitable[None]]):
        """
        Register a callback to be called when tokens are refreshed.
        
        Callbacks receive the new access token as a parameter and are called
        after a successful token refresh. This can be used to update token
        references in other services.
        
        Args:
            callback: Async function that takes the new token as a parameter
        """
        if callback not in self.on_token_refresh_callbacks:
            self.on_token_refresh_callbacks.append(callback)
            
    def unregister_refresh_callback(self, callback: Callable[[str], Awaitable[None]]):
        """
        Unregister a refresh callback.
        
        Removes a previously registered callback so it will no longer be
        called on token refresh events.
        
        Args:
            callback: The callback function to remove
        """
        if callback in self.on_token_refresh_callbacks:
            self.on_token_refresh_callbacks.remove(callback)