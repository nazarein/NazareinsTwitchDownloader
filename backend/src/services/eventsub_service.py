"""EventSub WebSocket client for Twitch real-time events with improved connection and subscription handling."""

import asyncio
import json
import time
import os
import traceback
import random
import logging
from typing import Dict, Set, List, Any, Optional
import websockets
import aiohttp

from backend.src.config.constants import EVENTSUB_CLIENT_ID
from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers

# Set up a dedicated logger for EventSub with levels
logger = logging.getLogger("eventsub")
logger.setLevel(logging.INFO)  # Set default level - can be changed to DEBUG for more details

class EventSubService:
    """
    Service that manages Twitch EventSub WebSocket connections for real-time
    stream status notifications. Handles connection management, subscription
    creation, and event processing.
    """

    def __init__(self, websocket_manager=None):
        """
        Initialize the EventSub service.
        
        Args:
            websocket_manager: Manager for WebSocket connections to broadcast updates to clients
        """
        self.websocket_manager = websocket_manager
        self.running = False
        self.ws_connections = []  # Active WebSocket connections to Twitch
        self.active_subscriptions = {}  # Tracks stream ID to subscription mapping
        self.session_ids = []  # Active session identifiers
        self.token = None  # Twitch OAuth token
        self.token_error = None  # Stores auth error messages
        self.max_connections = 3  # Maximum parallel connections to Twitch
        self.connection_tasks = []  # AsyncIO tasks for active connections
        
        # Tracks ongoing unsubscribe operations to prevent duplicates
        self.pending_unsubscribes = set()
        
        # Maps session IDs to subscriptions for better reconnection handling
        self.subscriptions_by_session = {}  # session_id -> {user_id: event_type}
        
        # Connection state tracking for efficient reconnection
        self.last_connection_state = {}
        self.reconnect_urls = {}
        
        # Rate limiting for Twitch API
        self.subscription_rate_limiter = asyncio.Semaphore(5)
        self.retry_after = 0  # Timestamp when to retry after hitting rate limits

    async def start(self):
        """
        Start the EventSub service and establish WebSocket connections to Twitch.
        
        Initializes state, obtains authentication tokens, sets up periodic cleanup tasks,
        and establishes WebSocket connections to Twitch's EventSub service for real-time
        stream status notifications.
        
        Note:
            Requires a valid OAuth token to function properly. If no token is available,
            the service will not start until authentication is provided.
        """
        self.running = True
        self.initialization_time = time.time()
        
        # Reset state
        self.ws_connections = []
        self.active_subscriptions = {}
        self.session_ids = []
        self.connection_tasks = []
        self.pending_unsubscribes = set()
        self.last_connection_state = {}
        self.reconnect_urls = {}
        self.subscriptions_by_session = {}
        
        # Token now provided by StreamMonitorService - don't load from disk again
        if not self.token:
            # Try to get token directly from token_manager if available
            if hasattr(self, 'token_manager'):
                token, _ = await self.token_manager.get_access_token()
                if token:
                    print(f"[EventSub] Got token from token_manager: starts with '{token[:10]}...' (length: {len(token)})")
                    self.token = token
                    self.token_error = None
                else:
                    print("[EventSub] No access token available from token_manager")
                    return
            else:
                print("[EventSub] No access token provided and no token_manager available")
                return

        # Start the periodic cleanup scheduler - reduce frequency to every 12 hours
        asyncio.create_task(self._start_cleanup_scheduler())

        # Start the connection manager task
        if self.token:
            self.connection_manager_task = asyncio.create_task(self._manage_connections())
            print(f"[EventSub] Service started with token {self.token[:10]}... (length: {len(self.token)})")
        else:
            print("[EventSub] Cannot start service - no token available")

    async def stop(self):
        """Stop the EventSub service."""
        print("[EventSub] Stopping service...")
        self.running = False
        
        # First unsubscribe all active subscriptions before canceling tasks
        await self._unsubscribe_all()
        
        # Cancel connection management task
        if hasattr(self, 'connection_manager_task') and not self.connection_manager_task.done():
            self.connection_manager_task.cancel()
            
        # Cancel all connection tasks
        for task in self.connection_tasks:
            if not task.done():
                task.cancel()
                
        self.connection_tasks = []
        self.ws_connections = []
        self.active_subscriptions = {}
        self.session_ids = []
        self.pending_unsubscribes = set()
        self.subscriptions_by_session = {}
        print("[EventSub] Service stopped")

    async def _manage_connections(self):
        """Manage EventSub WebSocket connections based on monitored streamers."""
        first_run = True
        while self.running:
            try:
                # Get current streamers
                streamers = get_monitored_streamers()
                
                # Group streamers by online/offline status
                online_streamers = []
                offline_streamers = []
                
                for streamer, settings in streamers.items():
                    if settings.get("twitch_id"):
                        if settings.get("isLive", False):
                            online_streamers.append((settings["twitch_id"], streamer))
                        else:
                            offline_streamers.append((settings["twitch_id"], streamer))
                
                # Calculate how many connections we need
                total_streamers = len(online_streamers) + len(offline_streamers)
                
                # If this is the first run or we have no connections but should have some,
                # create new connections
                if first_run or (not self.ws_connections and total_streamers > 0):
                    await self._create_connections(online_streamers, offline_streamers)
                    first_run = False
                elif not self.ws_connections and len(self.session_ids) == 0:
                    # We lost all connections - try to re-establish them
                    print(f"[EventSub] No active connections detected, attempting to re-establish")
                    await self._create_connections(online_streamers, offline_streamers)
                else:
                    # Check for failed connections and restart if needed
                    await self._check_connections()
                    
            except Exception as e:
                print(f"[EventSub] Error in connection management: {e}")
                
            # Check connections every 60 seconds
            await asyncio.sleep(60)
            
    async def _create_connections(self, online_streamers, offline_streamers):
        """
        Create WebSocket connections to Twitch EventSub service for groups of streamers.
        
        Divides streamers into batches to stay within Twitch's connection limits,
        and creates WebSocket connections for each batch. Each connection can handle
        multiple subscription events.
        
        Args:
            online_streamers: List of tuples (user_id, streamer_name) for online streamers
            offline_streamers: List of tuples (user_id, streamer_name) for offline streamers
        """

        self.last_connection_attempt = time.time()
        # Combine all streamers but keep track of their status
        all_streamers = [(user_id, streamer, True) for user_id, streamer in online_streamers]
        all_streamers.extend([(user_id, streamer, False) for user_id, streamer in offline_streamers])
        
        if not all_streamers:
            print("[EventSub] No streamers to monitor")
            return
            
        # Split into batches - Twitch has a limit on subscriptions per connection
        # Each subscription has a cost of 1, and each connection has a max total cost of 10
        batch_size = 5  # Reduced from 10 to leave some room for error
        streamers_batches = []
        
        for i in range(0, len(all_streamers), batch_size):
            batch = all_streamers[i:i+batch_size]
            streamers_batches.append(batch)
            
        
        for i, batch in enumerate(streamers_batches[:self.max_connections]):
            streamer_names = [name for _, name, _ in batch]

            
            task = asyncio.create_task(self._handle_connection(batch, i))
            self.connection_tasks.append(task)
            self.ws_connections.append({
                "task": task,
                "streamers": batch,
                "connection_id": i,
                "status": "connecting"
            })
            
    async def _check_connections(self):
        """
        Monitor active WebSocket connections and restart any that have failed.
        
        Checks the status of all connection tasks, detects any that have completed
        or failed, and restarts them with the same set of streamers to maintain
        continuous monitoring.
        """
        for i, conn in enumerate(self.ws_connections):
            if conn["task"].done():
                try:
                    # Get the result to check for exceptions
                    conn["task"].result()
                    # If we get here, the task completed normally
                    print(f"[EventSub] Connection {conn['connection_id']} completed normally")
                except asyncio.CancelledError:
                    print(f"[EventSub] Connection {conn['connection_id']} was cancelled")
                except Exception as e:
                    print(f"[EventSub] Connection {conn['connection_id']} failed with error: {e}")
                
                # Either way, restart the connection
                streamers = conn["streamers"]
                print(f"[EventSub] Restarting connection {conn['connection_id']} with {len(streamers)} streamers")
                
                # Start a new connection task
                new_task = asyncio.create_task(self._handle_connection(streamers, conn["connection_id"]))
                self.connection_tasks.append(new_task)
                
                # Update the connection object
                self.ws_connections[i] = {
                    "task": new_task,
                    "streamers": streamers,
                    "connection_id": conn["connection_id"],
                    "status": "connecting"
                }
        
    async def _handle_connection(self, streamers, connection_id):
        """
        Manage a single WebSocket connection to Twitch's EventSub service.
        
        Establishes and maintains a WebSocket connection to Twitch, handling initial
        handshaking, subscription creation, message processing, and automatic reconnection
        with exponential backoff when connection errors occur.
        
        Args:
            streamers: List of tuples containing (user_id, streamer_name, is_online)
                    for streamers to be managed through this connection
            connection_id: Unique identifier for this connection
            
        Note:
            Each connection has a limit of subscriptions it can handle (typically 10).
            The method implements retry logic with exponential backoff when connection failures occur.
        """
        retry_count = 0
        max_retries = 15  # max retries
        initial_retry_delay = 2  # seconds
        retry_delay = initial_retry_delay
        connection_session_id = None  # Track the session ID for this connection
        
        streamer_names = [name for _, name, _ in streamers]
        
        # Update status for this connection
        for conn in self.ws_connections:
            if conn["connection_id"] == connection_id:
                conn["status"] = "connecting"
        
        while retry_count < max_retries and self.running:
            try:
                # Check if we have a reconnect URL for this connection
                reconnect_url = self.reconnect_urls.get(connection_id)
                ws_url = reconnect_url if reconnect_url else "wss://eventsub.wss.twitch.tv/ws"

                if reconnect_url:
                    print(f"[EventSub] Connection {connection_id}: Using reconnect URL")
                    # Clear the reconnect URL after using it - they're typically one-time use
                    del self.reconnect_urls[connection_id]
                
                # Connect to EventSub WebSocket
                async with websockets.connect(
                    ws_url, 
                    close_timeout=30,  # Increase from 5 to 30
                    ping_interval=25,  # Add regular pings
                    ping_timeout=10,   # How long to wait for pong
                    additional_headers={    # Add proper headers
                        'User-Agent': 'NazareinsTwitchDownloader/1.0',
                        'Origin': 'https://twitch.tv'
                    }
                ) as websocket:
                    print(f"[EventSub] Connection {connection_id}: Connected successfully")
                    
                    # Update status
                    for conn in self.ws_connections:
                        if conn["connection_id"] == connection_id:
                            conn["status"] = "connected"
                    
                    # Process welcome message
                    welcome_msg = await websocket.recv()
                    try:
                        welcome_data = json.loads(welcome_msg)
                        
                        if welcome_data["metadata"]["message_type"] == "session_welcome":
                            session_id = welcome_data["payload"]["session"]["id"]
                            connection_session_id = session_id  # Store the session ID for this connection
                            
                            # Store the session ID
                            if session_id not in self.session_ids:
                                self.session_ids.append(session_id)
                            
                            # Initialize session tracking
                            if session_id not in self.subscriptions_by_session:
                                self.subscriptions_by_session[session_id] = {}
                            
                            
                            # Reset retry parameters on successful connection
                            retry_count = 0
                            retry_delay = initial_retry_delay
                            
                            # Clear any old subscriptions for streamers in this batch
                            # This helps avoid duplication when reconnecting
                            for user_id, streamer_name, _ in streamers:
                                # If this streamer is already subscribed in another active session,
                                # unsubscribe them first to prevent duplicate subscriptions
                                await self._check_and_clean_streamer_subscriptions(user_id, streamer_name)
                            
                            # Add a short delay to allow unsubscribe operations to complete
                            await asyncio.sleep(1)
                            await self._check_existing_subscriptions_with_twitch(session_id)

                            # Add this new code to clean up existing subscriptions:
                            # Clean up any existing subscriptions found during the check
                            if self.active_subscriptions:
                                
                                # Create a copy of the IDs to avoid modifying while iterating
                                existing_user_ids = list(self.active_subscriptions.keys())
                                
                                # Delete each existing subscription
                                for user_id in existing_user_ids:
                                    streamer_info = self.active_subscriptions.get(user_id, {})
                                    streamer_name = streamer_info.get("streamer", "unknown")
                                    await self.remove_streamer_subscription(user_id, quiet=False)
                                
                                # Wait for all removals to complete
                                await asyncio.sleep(1)
                                
                            # Create subscriptions with rate limiting and retry logic
                            subscriptions_created = 0

                            
                            for user_id, streamer_name, is_online in streamers:
                                # If online, subscribe to offline events; if offline, subscribe to online events
                                event_type = "stream.offline" if is_online else "stream.online"
                                
                                # Check if we're above the rate limit threshold
                                current_time = time.time()
                                if current_time < self.retry_after:
                                    wait_time = self.retry_after - current_time
                                    print(f"[EventSub] Rate limited, waiting {wait_time:.1f} seconds before continuing")
                                    await asyncio.sleep(wait_time)
                                
                                # Use semaphore for rate limiting
                                async with self.subscription_rate_limiter:
                                    try:
                                        success = await self._create_subscription(session_id, user_id, streamer_name, event_type)
                                        
                                        if success:
                                            subscriptions_created += 1
                                            # Store in both tracking dictionaries
                                            self.active_subscriptions[user_id] = {
                                                "streamer": streamer_name,
                                                "event_type": event_type,
                                                "session_id": session_id
                                            }
                                            
                                            # Also track by session for reconnection management
                                            self.subscriptions_by_session[session_id][user_id] = {
                                                "streamer": streamer_name,
                                                "event_type": event_type
                                            }
                                        else:
                                            print(f"[EventSub] Failed to subscribe to {event_type} for {streamer_name}")
                                    except Exception as sub_err:
                                        print(f"[EventSub] Error creating subscription for {streamer_name}: {sub_err}")
                                
                                # Add a small delay between subscription requests to avoid rate limiting
                                await asyncio.sleep(0.2)
                            

                            
                            # Process incoming WebSocket messages
                            while self.running:
                                try:
                                    # Set a timeout on receive to detect disconnections
                                    message = await asyncio.wait_for(websocket.recv(), timeout=60)
                                    data = json.loads(message)
                                    message_type = data["metadata"]["message_type"]
                                    
                                    if message_type == "notification":
                                        await self._handle_notification(data)
                                    elif message_type == "session_keepalive":
                                        # Just log an occasional keepalive
                                        pass
                                    elif message_type == "session_reconnect":
                                        # Handle reconnect by storing the URL for later use
                                        reconnect_url = data["payload"]["session"]["reconnect_url"]
                                        print(f"[EventSub] Connection {connection_id}: Received reconnect message with URL")
                                        
                                        # Store reconnect URL for this connection
                                        self.reconnect_urls[connection_id] = reconnect_url
                                        
                                        # Update status
                                        for conn in self.ws_connections:
                                            if conn["connection_id"] == connection_id:
                                                conn["status"] = "reconnecting"
                                        
                                        # Close current connection for reconnection
                                        await websocket.close()
                                        
                                        break  # Exit the inner loop to reconnect
                                    elif message_type == "revocation":
                                        print(f"[EventSub] Connection {connection_id}: Subscription revoked: {data['payload']['subscription']['type']}")
                                        
                                        # Extract the user_id from the condition
                                        revoked_user_id = data['payload']['subscription']['condition'].get('broadcaster_user_id')
                                        
                                        # Remove from active subscriptions
                                        if revoked_user_id in self.active_subscriptions:
                                            # Also remove from session tracking
                                            sub_session_id = self.active_subscriptions[revoked_user_id].get("session_id")
                                            if sub_session_id and sub_session_id in self.subscriptions_by_session:
                                                if revoked_user_id in self.subscriptions_by_session[sub_session_id]:
                                                    del self.subscriptions_by_session[sub_session_id][revoked_user_id]
                                            
                                            del self.active_subscriptions[revoked_user_id]
                                except asyncio.TimeoutError:
                                    # Send a ping to check if the connection is still alive
                                    try:
                                        pong_waiter = await websocket.ping()
                                        await asyncio.wait_for(pong_waiter, timeout=10)
                                        print(f"[EventSub] Connection {connection_id}: Ping successful, connection alive")
                                        continue
                                    except:
                                        print(f"[EventSub] Connection {connection_id}: Ping failed, connection dead")
                                        raise websockets.exceptions.ConnectionClosed(
                                            1006, "Connection closed abnormally (ping timeout)"
                                        )
                                except websockets.exceptions.ConnectionClosed:
                                    print(f"[EventSub] Connection {connection_id}: WebSocket connection closed unexpectedly")
                                    
                                    # Update status
                                    for conn in self.ws_connections:
                                        if conn["connection_id"] == connection_id:
                                            conn["status"] = "disconnected"
                                    
                                    raise  # Re-raise to trigger reconnection
                        else:
                            print(f"[EventSub] Connection {connection_id}: Unexpected message type in welcome: {welcome_data['metadata']['message_type']}")
                            # Let the retry happen
                            raise websockets.exceptions.ConnectionClosed(
                                1003, f"Unexpected message type: {welcome_data['metadata']['message_type']}"
                            )
                    except json.JSONDecodeError:
                        print(f"[EventSub] Connection {connection_id}: Invalid welcome message (not JSON): {welcome_msg[:100]}...")
                        raise websockets.exceptions.ConnectionClosed(
                            1003, "Invalid welcome message format"
                        )
                    
                    # If we made it here, reset retry count on successful connection
                    retry_count = 0
                    
            except websockets.exceptions.ConnectionClosed as e:
                
                if e.code == 1006:  # Abnormal closure without a clean disconnect
                    # Add a longer delay to allow network to stabilize
                    stabilization_delay = 5  # seconds
                    await asyncio.sleep(stabilization_delay)
                
                    # Check if network is back by making a simple request
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get("https://api.twitch.tv/helix", timeout=5) as response:
                                pass  # We just need to check if the request succeeds
                    except Exception:
                        # Add even more delay if network check fails
                        await asyncio.sleep(10)
                
                # Update status
                for conn in self.ws_connections:
                    if conn["connection_id"] == connection_id:
                        conn["status"] = "disconnected"
                
                # Clean up this session from session_ids if it's tracked
                if connection_session_id in self.session_ids:
                    self.session_ids.remove(connection_session_id)
                    
                    # Clean up subscriptions associated with this session
                    if connection_session_id in self.subscriptions_by_session:
                        print(f"[EventSub] Connection {connection_id}: Cleaning up {len(self.subscriptions_by_session[connection_session_id])} subscriptions from closed session")
                        
                        # Create a list to avoid modifying during iteration
                        user_ids_to_remove = list(self.subscriptions_by_session[connection_session_id].keys())
                        
                        # Remove from active_subscriptions
                        for user_id in user_ids_to_remove:
                            if user_id in self.active_subscriptions and \
                            self.active_subscriptions[user_id].get("session_id") == connection_session_id:
                                del self.active_subscriptions[user_id]
                                            
                        # Clear session tracking
                        del self.subscriptions_by_session[connection_session_id]
                
                retry_count += 1
                print(f"[EventSub] Connection {connection_id}: Retrying in {retry_delay} seconds... ({retry_count}/{max_retries})")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 300)  # Exponential backoff capped at 5 minutes
            
            except Exception as e:
                print(f"[EventSub] Connection {connection_id}: Error in connection: {e}")
                
                # Update status
                for conn in self.ws_connections:
                    if conn["connection_id"] == connection_id:
                        conn["status"] = "error"
                
                # Clean up this session from session_ids if it's tracked
                if connection_session_id in self.session_ids:
                    self.session_ids.remove(connection_session_id)
                    
                    # Clean up subscriptions associated with this session
                    if connection_session_id in self.subscriptions_by_session:
                        # Remove from active_subscriptions
                        for user_id in list(self.subscriptions_by_session[connection_session_id].keys()):
                            if user_id in self.active_subscriptions and \
                               self.active_subscriptions[user_id].get("session_id") == connection_session_id:
                                del self.active_subscriptions[user_id]
                        
                        # Clear session tracking
                        del self.subscriptions_by_session[connection_session_id]
                
                retry_count += 1
                print(f"[EventSub] Connection {connection_id}: Retrying in {retry_delay} seconds... ({retry_count}/{max_retries})")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 300)  # Exponential backoff capped at 5 minutes
                
        if retry_count >= max_retries:
            print(f"[EventSub] Connection {connection_id}: Maximum retries reached. Connection failed.")
            
            # Update status
            for conn in self.ws_connections:
                if conn["connection_id"] == connection_id:
                    conn["status"] = "failed"
        
        # Return to allow the connection manager to detect failures
        return
    
    async def _check_and_clean_streamer_subscriptions(self, user_id, streamer_name):
        """
        Check if a streamer already has active subscriptions and clean them up if needed.
        
        Args:
            user_id: Twitch user ID of the streamer
            streamer_name: Twitch username of the streamer
        """
        if user_id in self.active_subscriptions:
            print(f"[EventSub] Streamer {streamer_name} already has an active subscription, cleaning up")
            await self.remove_streamer_subscription(user_id, quiet=True)
            # Add a small delay to allow the unsubscribe to complete
            await asyncio.sleep(0.5)

    async def _check_existing_subscriptions_with_twitch(self, session_id):
        """
        Query Twitch API to fetch and track existing subscriptions.
        
        Maps existing Twitch subscriptions to our internal tracking system to
        maintain consistency between our records and Twitch's actual state.
        
        Args:
            session_id: The EventSub session ID to associate with found subscriptions
        """
        token_to_use = None
        if hasattr(self, 'token_manager') and self.token_manager:
            token_to_use, _ = await self.token_manager.get_access_token()
        if not token_to_use:
            token_to_use = self.token
        if not token_to_use:
            return
        
        try:
            url = "https://api.twitch.tv/helix/eventsub/subscriptions"
            headers = {
                "Client-ID": EVENTSUB_CLIENT_ID,
                "Authorization": f"Bearer {token_to_use}",  # Use the fresh token
            }
                
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        subscriptions = data.get("data", [])
                        
                        # Map existing subscriptions to our internal tracking
                        for sub in subscriptions:
                            condition = sub.get("condition", {})
                            user_id = condition.get("broadcaster_user_id")
                            
                            if user_id and sub.get("transport", {}).get("method") == "websocket":
                                # Only track WebSocket subscriptions
                                event_type = sub.get("type")
                                
                                # Find the streamer name for this user_id
                                streamer_name = None
                                streamers = get_monitored_streamers()
                                for streamer, settings in streamers.items():
                                    if settings.get("twitch_id") == user_id:
                                        streamer_name = streamer
                                        break
                                
                                if streamer_name:
                                    
                                    # Add to our tracking
                                    self.active_subscriptions[user_id] = {
                                        "streamer": streamer_name,
                                        "event_type": event_type,
                                        "session_id": session_id
                                    }
                                    
                                    # Also track by session
                                    if session_id not in self.subscriptions_by_session:
                                        self.subscriptions_by_session[session_id] = {}
                                        
                                    self.subscriptions_by_session[session_id][user_id] = {
                                        "streamer": streamer_name,
                                        "event_type": event_type
                                    }
                        
                        
                    else:
                        print(f"[EventSub] Failed to check existing subscriptions: {response.status}")
                        
        except Exception as e:
            print(f"[EventSub] Error checking existing subscriptions: {e}")
    
    async def _create_subscription(self, session_id, user_id, streamer_name, event_type):
        """
        Create a new EventSub subscription via Twitch API.
        
        Makes an API request to Twitch to create a subscription for a specific event type
        for a streamer. Handles rate limiting, authentication, and retries on failure.
        
        Args:
            session_id: WebSocket session ID to associate with the subscription
            user_id: Twitch user ID of the streamer
            streamer_name: Twitch username of the streamer
            event_type: Type of event to subscribe to (e.g., "stream.online")
            
        Returns:
            bool: True if subscription was successfully created, False otherwise
        """
        url = "https://api.twitch.tv/helix/eventsub/subscriptions"
        
        # Fetch the latest token
        token_to_use = None
        if hasattr(self, 'token_manager') and self.token_manager:
            token_to_use, _ = await self.token_manager.get_access_token()
        if not token_to_use:
            token_to_use = self.token
        if not token_to_use:
            return False
            
        headers = {
            "Client-ID": EVENTSUB_CLIENT_ID,
            "Authorization": f"Bearer {token_to_use}",
        }
        
        payload = {
            "type": event_type,
            "version": "1",
            "condition": {
                "broadcaster_user_id": user_id
            },
            "transport": {
                "method": "websocket",
                "session_id": session_id
            }
        }
        
        max_attempts = 3
        current_attempt = 0
        base_delay = 1  # seconds
        
        while current_attempt < max_attempts:
            try:
                async with aiohttp.ClientSession() as session:
                    # Add a timeout to the request to avoid hanging
                    async with session.post(url, headers=headers, json=payload, timeout=30) as response:
                        if response.status == 202:
                            print(f"[EventSub] Successfully subscribed to {event_type} events for {streamer_name} ({user_id})")
                            return True
                        # Replace the current rate limit handling code with:
                        elif response.status == 429:  # Rate limited
                            # Get retry-after header if present
                            retry_after = response.headers.get('Retry-After')
                            try:
                                base_wait = 5  # Base delay in seconds
                                max_wait = 60  # Maximum delay in seconds
                                
                                if retry_after:
                                    wait_seconds = int(retry_after)
                                else:
                                    # Use exponential backoff based on the attempt number
                                    wait_seconds = min(base_wait * (2 ** current_attempt), max_wait)
                                
                                # Add some jitter to avoid all clients retrying at the same time
                                wait_seconds = wait_seconds * (0.9 + 0.2 * random.random())
                                    
                                self.retry_after = time.time() + wait_seconds
                                
                                print(f"[EventSub] Rate limited. Will retry after {wait_seconds:.1f} seconds")
                                await asyncio.sleep(wait_seconds)
                                current_attempt += 1
                                continue
                            except ValueError:
                                # Default if we can't parse the value
                                wait_seconds = base_wait * (2 ** current_attempt)
                                self.retry_after = time.time() + wait_seconds
                                await asyncio.sleep(wait_seconds)
                                current_attempt += 1
                                continue
                        else:
                            response_text = await response.text()
                            print(f"[EventSub] Failed to subscribe to {event_type} events for {streamer_name}: {response.status} - {response_text}")
                            
                            # Store token error for display in UI
                            if response.status == 401:
                                self.token_error = f"Token unauthorized: {response_text}"
                                print(f"[EventSub] Token appears to be invalid, will trigger refresh")
                                if hasattr(self, 'token_manager') and self.token_manager:
                                    # Force a token refresh
                                    print("[EventSub] Requesting token refresh...")
                                    fresh_token, refreshed = await self.token_manager.get_access_token(force_refresh=True)
                                    if refreshed and fresh_token:
                                        print(f"[EventSub] Successfully refreshed token, will retry on next cycle")
                                        # Update our token
                                        self.token = fresh_token
                                        self.token_error = None
                            
                            return False
            except asyncio.TimeoutError:
                print(f"[EventSub] Timeout creating subscription for {streamer_name}")
                current_attempt += 1
                await asyncio.sleep(base_delay * (2 ** current_attempt))  # Exponential backoff
            except Exception as e:
                print(f"[EventSub] Error creating subscription for {streamer_name}: {e}")
                return False
        
        print(f"[EventSub] Failed to create subscription after {max_attempts} attempts")
        return False
            
    async def _unsubscribe_all(self):
        """
        Unsubscribe from all active EventSub subscriptions on Twitch.
        
        Queries Twitch API for all current subscriptions and systematically
        deletes them, handling rate limiting and ensuring all subscriptions
        are properly cleaned up before service shutdown.
        """
        if not self.token:
            print("[EventSub] No token available for unsubscribing")
            return

        print("[EventSub] Performing complete subscription cleanup...")
        
        try:
            # Get all active subscriptions from Twitch
            url = "https://api.twitch.tv/helix/eventsub/subscriptions"
            headers = {
                "Client-ID": EVENTSUB_CLIENT_ID,
                "Authorization": f"Bearer {self.token}",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        subscriptions = data.get("data", [])
                        
                        if not subscriptions:
                            print("[EventSub] No active subscriptions found on Twitch")
                            return
                        
                        print(f"[EventSub] Found {len(subscriptions)} subscriptions to clean up")
                        
                        # Group subscriptions by user_id for better logging
                        subs_by_user = {}
                        for sub in subscriptions:
                            sub_id = sub.get("id")
                            user_id = sub.get("condition", {}).get("broadcaster_user_id")
                            
                            if user_id:
                                if user_id not in subs_by_user:
                                    subs_by_user[user_id] = []
                                subs_by_user[user_id].append(sub_id)
                        
                        # Delete subscriptions one by one but log as batches
                        deleted_count = 0
                        total_users = len(subs_by_user)
                        current_user = 0
                        
                        # Use semaphore to limit concurrent deletion requests
                        delete_semaphore = asyncio.Semaphore(5)
                        
                        async def delete_subscription(sub_id):
                            nonlocal deleted_count
                            delete_url = f"{url}?id={sub_id}"
                            try:
                                async with delete_semaphore:
                                    async with session.delete(delete_url, headers=headers) as delete_response:
                                        if delete_response.status == 204:  # Success
                                            deleted_count += 1
                                        elif delete_response.status == 429:  # Rate limited
                                            retry_after = delete_response.headers.get('Retry-After', '5')
                                            try:
                                                wait_seconds = int(retry_after)
                                            except ValueError:
                                                wait_seconds = 5
                                            
                                            print(f"[EventSub] Rate limited on deletion, waiting {wait_seconds} seconds")
                                            await asyncio.sleep(wait_seconds)
                                            
                                            # Retry once after waiting
                                            async with session.delete(delete_url, headers=headers) as retry_response:
                                                if retry_response.status == 204:
                                                    deleted_count += 1
                                        else:
                                            error_text = await delete_response.text()
                                            print(f"[EventSub] Failed to delete subscription {sub_id}: {delete_response.status} - {error_text}")
                            except Exception as e:
                                print(f"[EventSub] Error deleting subscription {sub_id}: {e}")
                        
                        # Create tasks for all deletions
                        delete_tasks = []
                        for user_id, sub_ids in subs_by_user.items():
                            current_user += 1
                            # Only log progress every 5 users or at the end
                            if current_user % 5 == 0 or current_user == total_users:
                                print(f"[EventSub] Cleanup progress: {current_user}/{total_users} users")
                                
                            # Create tasks for all subscriptions for this user
                            for sub_id in sub_ids:
                                delete_tasks.append(asyncio.create_task(delete_subscription(sub_id)))
                        
                        # Wait for all deletion tasks to complete
                        if delete_tasks:
                            await asyncio.gather(*delete_tasks, return_exceptions=True)
                        
                        print(f"[EventSub] Successfully cleaned up {deleted_count}/{sum(len(subs) for subs in subs_by_user.values())} subscriptions")
                        
                        # Wait a moment to ensure Twitch processes all deletions
                        await asyncio.sleep(1)
                    else:
                        error_text = await response.text()
                        print(f"[EventSub] Failed to get subscriptions: {response.status} - {error_text}")
        except Exception as e:
            print(f"[EventSub] Error during subscription cleanup: {e}")

    async def _start_cleanup_scheduler(self):
        """
        Start a scheduled task to periodically clean up duplicate subscriptions.
        
        Runs every 12 hours to identify and remove duplicate subscriptions that
        may have been created due to reconnection events or API errors.
        """
        while self.running:
            try:
                # Run cleanup every 12 hours
                await asyncio.sleep(12 * 60 * 60)
                
                # Only run cleanup if we have active subscriptions
                if self.active_subscriptions:
                    await self._check_and_clean_duplicates()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[EventSub] Error in cleanup scheduler: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying
                
    async def _check_and_clean_duplicates(self):
        """
        Identify and remove duplicate EventSub subscriptions.
        
        Queries Twitch API for all current subscriptions, identifies duplicates
        (multiple subscriptions for the same user_id and event type), and removes
        extra subscriptions to maintain a clean state.
        """
        if not self.token:
            return
            
        try:
            url = "https://api.twitch.tv/helix/eventsub/subscriptions"
            headers = {
                "Client-ID": EVENTSUB_CLIENT_ID,
                "Authorization": f"Bearer {self.token}",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        subscriptions = data.get("data", [])
                        
                        # Group subscriptions by user_id and type to find duplicates
                        grouped_subs = {}
                        for sub in subscriptions:
                            user_id = sub.get("condition", {}).get("broadcaster_user_id")
                            sub_type = sub.get("type")
                            if user_id and sub_type:
                                key = f"{user_id}:{sub_type}"
                                if key not in grouped_subs:
                                    grouped_subs[key] = []
                                grouped_subs[key].append(sub)
                        
                        # Find duplicates
                        duplicates = {key: subs for key, subs in grouped_subs.items() if len(subs) > 1}
                        
                        if duplicates:
                            # Log summary of duplicates found
                            duplicate_count = sum(len(subs) - 1 for subs in duplicates.values())
                            
                            # Use a semaphore to rate limit deletion requests
                            semaphore = asyncio.Semaphore(5)
                            deleted_count = 0
                            
                            # Function to delete a single subscription with rate limiting
                            async def delete_subscription(sub_id):
                                nonlocal deleted_count
                                try:
                                    async with semaphore:
                                        delete_url = f"{url}?id={sub_id}"
                                        async with session.delete(delete_url, headers=headers) as delete_response:
                                            if delete_response.status == 204:
                                                deleted_count += 1
                                                return True
                                            elif delete_response.status == 429:  # Rate limited
                                                retry_after = delete_response.headers.get('Retry-After', '5')
                                                try:
                                                    wait_seconds = int(retry_after)
                                                except ValueError:
                                                    wait_seconds = 5
                                                
                                                print(f"[EventSub] Rate limited, waiting {wait_seconds} seconds")
                                                await asyncio.sleep(wait_seconds)
                                                
                                                # Retry once
                                                async with session.delete(delete_url, headers=headers) as retry_response:
                                                    if retry_response.status == 204:
                                                        deleted_count += 1
                                                        return True
                                            
                                            error_text = await delete_response.text()
                                            print(f"[EventSub] Failed to delete duplicate: {delete_response.status} - {error_text}")
                                            return False
                                except Exception as e:
                                    print(f"[EventSub] Error deleting duplicate subscription: {e}")
                                    return False
                            
                            # Create tasks for all duplicate deletions
                            delete_tasks = []
                            for key, subs in duplicates.items():
                                user_id, sub_type = key.split(":")
                                
                                # Keep the first one, delete the rest
                                for sub in subs[1:]:
                                    sub_id = sub.get("id")
                                    if sub_id:
                                        delete_tasks.append(asyncio.create_task(delete_subscription(sub_id)))
                            
                            # Wait for all deletion tasks to complete
                            if delete_tasks:
                                await asyncio.gather(*delete_tasks, return_exceptions=True)
                            
                        else:
                            print("[EventSub] No duplicate subscriptions found")
        except Exception as e:
            print(f"[EventSub] Error checking for duplicate subscriptions: {e}")

    async def _handle_notification(self, data):
        """
        Process a notification event received from Twitch.
        
        Parses notification data, identifies the affected streamer, updates their status
        in the local database, and broadcasts updates to WebSocket clients. Also handles
        subscription switching between online/offline events based on stream status changes.
        
        Args:
            data: Event data received from Twitch containing notification details
        """
        try:
            event_type = data["metadata"]["subscription_type"]
            event_data = data["payload"]["event"]
            user_id = event_data["broadcaster_user_id"]
            
            # Lookup the streamer name from user_id
            streamers = get_monitored_streamers()
            streamer_name = None
            
            for streamer, settings in streamers.items():
                if settings.get("twitch_id") == user_id:
                    streamer_name = streamer
                    break
                    
            if not streamer_name:
                print(f"[EventSub] Received event for unknown user_id: {user_id}")
                return
                
            # Process the event based on type
            if event_type == "stream.online":
                # Extract the stream type from the event data
                stream_type = event_data.get("type", "")
                
                # Only proceed if this is an actual live stream, not a rerun or other type
                if stream_type != "live":
                    print(f"[EventSub] 🔴 {streamer_name} started a {stream_type} (not a live stream). Ignoring.")
                    return
                    
                print(f"[EventSub] 🔴 {streamer_name} JUST WENT LIVE!")
                
                # Update streamer status in our database
                if streamer_name in streamers:
                    old_state = streamers[streamer_name].get("isLive", False)
                    streamers[streamer_name]["isLive"] = True
                    update_monitored_streamers(streamers)
                    
                    # Notify WebSocket clients
                    if self.websocket_manager:
                        await self.websocket_manager.broadcast_live_status(streamer_name, True)
                        
                        # We don't have the title and thumbnail yet, but we'll update anyway
                        # The background service will fetch the full details soon
                        await self.websocket_manager.broadcast_status_update(
                            "twitch", 
                            streamer_name, 
                            {"isLive": True}
                        )
                        
                    # Change subscription type without excessive logging
                    if user_id in self.active_subscriptions and not old_state:
                        session_id = self.active_subscriptions[user_id].get("session_id")
                        if session_id:
                            # Remove old subscription quietly
                            await self.remove_streamer_subscription(user_id, quiet=True)
                            # Create new subscription type
                            await self._create_subscription(session_id, user_id, streamer_name, "stream.offline")
                            self.active_subscriptions[user_id] = {
                                "streamer": streamer_name,
                                "event_type": "stream.offline", 
                                "session_id": session_id
                            }
                            
                            # Update session tracking
                            if session_id in self.subscriptions_by_session:
                                self.subscriptions_by_session[session_id][user_id] = {
                                    "streamer": streamer_name,
                                    "event_type": "stream.offline"
                                }
                
            elif event_type == "stream.offline":
                print(f"[EventSub] ⚫ {streamer_name} is now OFFLINE")
                
                # Update streamer status in our database
                if streamer_name in streamers:
                    old_state = streamers[streamer_name].get("isLive", False)
                    streamers[streamer_name]["isLive"] = False
                    
                    # Save the current title temporarily (for when they go online again)
                    if streamers[streamer_name].get("title") and streamers[streamer_name].get("title") != "Offline":
                        streamers[streamer_name]["lastTitle"] = streamers[streamer_name].get("title")
                        
                    # Set title to "Offline"
                    streamers[streamer_name]["title"] = "Offline"
                    
                    update_monitored_streamers(streamers)
                    
                    # Notify WebSocket clients
                    if self.websocket_manager:
                        await self.websocket_manager.broadcast_live_status(streamer_name, False)
                        await self.websocket_manager.broadcast_status_update(
                            "twitch", 
                            streamer_name, 
                            {"isLive": False, "title": "Offline"}
                        )
                        
                    # Change subscription type without excessive logging
                    if user_id in self.active_subscriptions and old_state:
                        session_id = self.active_subscriptions[user_id].get("session_id")
                        if session_id:
                            # Remove old subscription quietly
                            await self.remove_streamer_subscription(user_id, quiet=True)
                            # Create new subscription
                            await self._create_subscription(session_id, user_id, streamer_name, "stream.online")
                            self.active_subscriptions[user_id] = {
                                "streamer": streamer_name,
                                "event_type": "stream.online",
                                "session_id": session_id
                            }
                            
                            # Update session tracking
                            if session_id in self.subscriptions_by_session:
                                self.subscriptions_by_session[session_id][user_id] = {
                                    "streamer": streamer_name,
                                    "event_type": "stream.online"
                                }
        except Exception as e:
            print(f"[EventSub] Error handling notification: {e}")

    async def _reconnect_websockets(self):
        """
        Attempt to reconnect all WebSocket connections after disconnection.
        
        Creates new connections with the same streamers as before, tracks old
        session IDs for cleanup, and ensures subscription continuity during
        the reconnection process.
        
        Returns:
            bool: True if reconnection was successful, False otherwise
        """
        print("[EventSub] Attempting to reconnect WebSocket connections")
        
        # Stop any existing connections
        for task in self.connection_tasks:
            if not task.done():
                task.cancel()
        
        # Clear existing state
        self.ws_connections = []
        
        # Keep track of session IDs and subscriptions for cleanup
        old_session_ids = self.session_ids.copy()
        old_subscriptions_by_session = self.subscriptions_by_session.copy()
        
        # Reset session state
        self.session_ids = []
        self.connection_tasks = []
        
        # Get current streamers
        streamers = get_monitored_streamers()
        
        # Group streamers by online/offline status
        online_streamers = []
        offline_streamers = []
        
        for streamer, settings in streamers.items():
            if settings.get("twitch_id"):
                if settings.get("isLive", False):
                    online_streamers.append((settings["twitch_id"], streamer))
                else:
                    offline_streamers.append((settings["twitch_id"], streamer))
        
        # Create new connections
        await self._create_connections(online_streamers, offline_streamers)
        
        # Wait for connections to establish
        await asyncio.sleep(3)
        
        # Check if connections were successful
        if self.session_ids:
            print(f"[EventSub] Reconnection successful, established {len(self.session_ids)} sessions")
            
            # Clean up old sessions in the background
            asyncio.create_task(self._cleanup_old_sessions(old_session_ids, old_subscriptions_by_session))
            
            return True
        else:
            print("[EventSub] Reconnection failed, no sessions established")
            return False
            
    async def _cleanup_old_sessions(self, old_session_ids, old_subscriptions_by_session):
        """
        Clean up subscriptions from previous WebSocket sessions after reconnection.
        
        Args:
            old_session_ids: List of session IDs from previous connections
            old_subscriptions_by_session: Mapping of session IDs to subscriptions
        """
        print(f"[EventSub] Cleaning up {len(old_session_ids)} old sessions")
        
        try:
            # Get all current subscriptions from Twitch
            if not self.token:
                return
                
            url = "https://api.twitch.tv/helix/eventsub/subscriptions"
            headers = {
                "Client-ID": EVENTSUB_CLIENT_ID,
                "Authorization": f"Bearer {self.token}",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        subscriptions = data.get("data", [])
                        
                        # Filter for subscriptions belonging to old sessions
                        old_sub_ids = []
                        for sub in subscriptions:
                            transport = sub.get("transport", {})
                            if transport.get("method") == "websocket":
                                session_id = transport.get("session_id")
                                if session_id in old_session_ids:
                                    old_sub_ids.append(sub.get("id"))
                        
                        if old_sub_ids:
                            print(f"[EventSub] Found {len(old_sub_ids)} subscriptions from old sessions to clean up")
                            
                            # Use a semaphore to limit concurrent deletion requests
                            semaphore = asyncio.Semaphore(5)
                            
                            # Create delete tasks
                            delete_tasks = []
                            for sub_id in old_sub_ids:
                                delete_url = f"{url}?id={sub_id}"
                                
                                async def delete_single_sub(sub_id, delete_url):
                                    try:
                                        async with semaphore:
                                            async with session.delete(delete_url, headers=headers) as delete_response:
                                                return delete_response.status == 204
                                    except Exception:
                                        return False
                                
                                delete_tasks.append(asyncio.create_task(
                                    delete_single_sub(sub_id, delete_url)
                                ))
                            
                            # Wait for all deletions to complete
                            results = await asyncio.gather(*delete_tasks, return_exceptions=True)
                            success_count = sum(1 for r in results if r is True)
                            
                            print(f"[EventSub] Successfully cleaned up {success_count}/{len(old_sub_ids)} old subscriptions")
                        else:
                            print(f"[EventSub] No subscriptions found for old sessions")
        except Exception as e:
            print(f"[EventSub] Error cleaning up old sessions: {e}")

    async def add_streamer_subscription(self, user_id, streamer_name, is_live):
        """
        Add a new streamer subscription to the EventSub service.
        
        Creates a new subscription for a streamer without requiring a full service restart.
        Handles session selection, load balancing across available connections, and
        rate limiting for Twitch API requests.
        
        Args:
            user_id: Twitch user ID of the streamer
            streamer_name: Twitch username of the streamer
            is_live: Current live status of the streamer (determines event type to subscribe to)
            
        Returns:
            bool: True if subscription was successfully created, False otherwise
        """
        print(f"[EventSub] Adding subscription for {streamer_name}")
        
        # Skip if missing token
        if not self.token:
            print(f"[EventSub] Missing token, can't add subscription")
            return False
        
        # Check for active sessions - if none, try to reconnect
        if not self.session_ids:
            print(f"[EventSub] No active sessions, attempting to reconnect before adding subscription")
            try:
                reconnect_success = await self._reconnect_websockets()
                if not reconnect_success:
                    print(f"[EventSub] Reconnection failed, can't add subscription")
                    return False
            except Exception as e:
                print(f"[EventSub] Error during reconnection: {e}")
                return False
                
        # Determine event type based on current status
        event_type = "stream.offline" if is_live else "stream.online"
        
        # First check if this streamer already has a subscription
        await self._check_and_clean_streamer_subscriptions(user_id, streamer_name)
        
        # Find a connection that has available capacity
        # Twitch has a max of 10 subscriptions per connection
        connection_selected = False
        session_id = None
        
        # Count subscriptions per session
        session_counts = {}
        for session_id in self.session_ids:
            if session_id in self.subscriptions_by_session:
                session_counts[session_id] = len(self.subscriptions_by_session[session_id])
            else:
                session_counts[session_id] = 0
        
        # Find a session with space available
        for session_id, count in session_counts.items():
            if count < 8:  # Reduced from 10 to provide buffer
                connection_selected = True
                break
        
        # If no connection with space, use the one with the least subscriptions
        if not connection_selected and self.session_ids:
            session_id = min(session_counts, key=session_counts.get)
            print(f"[EventSub] Warning: Adding to session {session_id} with {session_counts[session_id]} subscriptions")
            connection_selected = True
        elif not self.session_ids:
            print(f"[EventSub] No active sessions available")
            return False
        
        # If we have a session, try to create subscription
        if session_id:
            # Check for rate limits before attempting subscription
            current_time = time.time()
            if current_time < self.retry_after:
                wait_time = self.retry_after - current_time
                print(f"[EventSub] Rate limited, waiting {wait_time:.1f} seconds before adding subscription")
                await asyncio.sleep(wait_time)
            
            # Use the rate limiter
            async with self.subscription_rate_limiter:
                success = await self._create_subscription(session_id, user_id, streamer_name, event_type)
                
                if success:
                    print(f"[EventSub] Successfully added subscription to {event_type} for {streamer_name}")
                    self.active_subscriptions[user_id] = {
                        "streamer": streamer_name,
                        "event_type": event_type,
                        "session_id": session_id
                    }
                    
                    # Add to session tracking
                    if session_id not in self.subscriptions_by_session:
                        self.subscriptions_by_session[session_id] = {}
                        
                    self.subscriptions_by_session[session_id][user_id] = {
                        "streamer": streamer_name,
                        "event_type": event_type
                    }
                    
                    return True
                else:
                    print(f"[EventSub] Failed to add subscription for {streamer_name}")
        else:
            print(f"[EventSub] No active sessions available")
        
        return False
    
    async def remove_streamer_subscription(self, user_id, quiet=False):
        """
        Remove a streamer's EventSub subscription.
        
        Deletes the subscription from Twitch's servers and updates local tracking.
        Handles cases where the subscription might not exist or multiple
        subscriptions might need to be removed.
        
        Args:
            user_id: Twitch user ID of the streamer
            quiet: Whether to suppress detailed log messages
            
        Returns:
            bool: True if subscription was successfully removed, False otherwise
        """
        
        # Check if this user_id is already being unsubscribed
        if user_id in self.pending_unsubscribes:
            # Print statement removed
            return True
            
        # Add to pending set
        self.pending_unsubscribes.add(user_id)
        
        try:
            # Check if we have this subscription in our internal tracking
            if user_id not in self.active_subscriptions:
                self.pending_unsubscribes.remove(user_id)
                return False
            
            # Get subscription details
            subscription = self.active_subscriptions[user_id]
            streamer_name = subscription.get("streamer", "unknown")
            session_id = subscription.get("session_id")
            
            # Also remove from session tracking
            if session_id in self.subscriptions_by_session and user_id in self.subscriptions_by_session[session_id]:
                del self.subscriptions_by_session[session_id][user_id]
            
            # With WebSocket transport, we need to explicitly delete the subscription from Twitch API
            try:
                url = "https://api.twitch.tv/helix/eventsub/subscriptions"
                
                # Use the token from token_manager or the stored one
                token_to_use = None
                if hasattr(self, 'token_manager') and self.token_manager:
                    token_to_use, _ = await self.token_manager.get_access_token()
                
                if not token_to_use:
                    token_to_use = self.token
                    
                if not token_to_use:
                    if not quiet:
                        print(f"[EventSub] No token available for deleting subscription for {streamer_name}")
                    # Still remove from our tracking dictionary
                    if user_id in self.active_subscriptions:
                        del self.active_subscriptions[user_id]
                    self.pending_unsubscribes.remove(user_id)
                    return False
                    
                headers = {
                    "Client-ID": EVENTSUB_CLIENT_ID,
                    "Authorization": f"Bearer {token_to_use}",
                }
                
                # First, get all active subscriptions to find the one(s) for this user_id
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=30) as response:
                        if response.status == 200:
                            data = await response.json()
                            subscriptions = data.get("data", [])
                            
                            # Create a dictionary to track unique subscriptions by ID
                            unique_subs_by_id = {}
                            
                            # Find subscriptions for this user_id and deduplicate by ID
                            for sub in subscriptions:
                                condition = sub.get("condition", {})
                                if condition.get("broadcaster_user_id") == user_id:
                                    sub_id = sub.get("id")
                                    sub_type = sub.get("type")
                                    if sub_id:
                                        unique_subs_by_id[sub_id] = sub_type
                            
                            if not unique_subs_by_id:
                                if not quiet:
                                    print(f"[EventSub] No subscriptions found on Twitch for {streamer_name}")
                                # Still remove from our tracking dictionary
                                if user_id in self.active_subscriptions:
                                    del self.active_subscriptions[user_id]
                                self.pending_unsubscribes.remove(user_id)
                                return True
                            
                            # Delete each unique subscription found
                            success = True
                            deleted_count = 0
                            
                            # Use a semaphore to limit concurrent deletions
                            delete_semaphore = asyncio.Semaphore(3)
                            
                            async def delete_single_subscription(sub_id):
                                nonlocal deleted_count
                                try:
                                    async with delete_semaphore:
                                        delete_url = f"{url}?id={sub_id}"
                                        async with session.delete(delete_url, headers=headers, timeout=10) as delete_response:
                                            if delete_response.status == 204:  # Success for DELETE is 204 No Content
                                                deleted_count += 1
                                                return True
                                            else:
                                                if not quiet:
                                                    error_text = await delete_response.text()
                                                    print(f"[EventSub] Failed to delete subscription {sub_id}: {delete_response.status} - {error_text}")
                                                return False
                                except Exception as e:
                                    if not quiet:
                                        print(f"[EventSub] Exception while deleting subscription {sub_id}: {e}")
                                    return False
                            
                            # Create tasks for all deletions
                            delete_tasks = []
                            for sub_id in unique_subs_by_id:
                                delete_tasks.append(asyncio.create_task(delete_single_subscription(sub_id)))
                            
                            # Wait for all deletions to complete
                            if delete_tasks:
                                results = await asyncio.gather(*delete_tasks, return_exceptions=True)
                                success = all(isinstance(r, bool) and r for r in results)
                            
                            # Remove from our tracking regardless of API success
                            if user_id in self.active_subscriptions:
                                del self.active_subscriptions[user_id]
                            
                            self.pending_unsubscribes.remove(user_id)
                            return success
                        else:
                            if not quiet:
                                error_text = await response.text()
                                print(f"[EventSub] Failed to get subscriptions: {response.status} - {error_text}")
                            # Still remove from our tracking dictionary
                            if user_id in self.active_subscriptions:
                                del self.active_subscriptions[user_id]
                            self.pending_unsubscribes.remove(user_id)
                            return False
            except Exception as e:
                if not quiet:
                    print(f"[EventSub] Error removing subscription for {streamer_name}: {e}")
                # Still remove from our tracking dictionary to avoid issues
                if user_id in self.active_subscriptions:
                    del self.active_subscriptions[user_id]
                self.pending_unsubscribes.remove(user_id)
                return False
        except Exception as e:
            if not quiet:
                print(f"[EventSub] Unhandled error in remove_streamer_subscription: {e}")
            # Make sure to remove from pending set
            if user_id in self.pending_unsubscribes:
                self.pending_unsubscribes.remove(user_id)
            return False

    def get_status(self):
        """
        Generate a comprehensive status report of the EventSub service.
        
        Collects information about current connections, active subscriptions,
        monitored streamers, and authentication status to provide a complete
        overview of the service state.
        
        Returns:
            dict: Dictionary containing detailed status information
        """
        if not self.token:
            return {
                "status": "no_token",
                "token_valid": False,
                "token_error": self.token_error,
                "initialization_time": getattr(self, 'initialization_time', 0),
                "last_connection_attempt": getattr(self, 'last_connection_attempt', 0),
                "uptime": time.time() - getattr(self, 'initialization_time', time.time()),
                "connection_tasks": len(self.connection_tasks),
                "session_ids": len(self.session_ids)
            }
        
        active_connections = len([conn for conn in self.ws_connections if conn["status"] == "connected"])
        streamers_monitored = len(self.active_subscriptions)
        
        # Count live channels in monitored streamers
        live_channels = 0
        live_streamers = []
        
        streamers = get_monitored_streamers()
        for streamer, settings in streamers.items():
            if settings.get("isLive", False):
                live_channels += 1
                live_streamers.append(streamer)
        
        # Count subscriptions per session
        session_counts = {}
        for session_id in self.session_ids:
            if session_id in self.subscriptions_by_session:
                session_counts[session_id] = len(self.subscriptions_by_session[session_id])
            else:
                session_counts[session_id] = 0
        
        return {
            "status": "active" if active_connections > 0 else "inactive",
            "token_valid": bool(self.token),
            "token_error": self.token_error,
            "active_connections": active_connections,
            "connections": [{"id": conn["connection_id"], "status": conn["status"]} for conn in self.ws_connections],
            "streamers_monitored": streamers_monitored,
            "live_channels": live_channels,
            "live_streamers": live_streamers,
            "client_id": EVENTSUB_CLIENT_ID,
            "initialization_time": getattr(self, 'initialization_time', 0),
            "last_connection_attempt": getattr(self, 'last_connection_attempt', 0),
            "uptime": time.time() - getattr(self, 'initialization_time', time.time()),
            "connection_tasks": len(self.connection_tasks),
            "session_ids": len(self.session_ids),
            "session_subscription_counts": session_counts
        }