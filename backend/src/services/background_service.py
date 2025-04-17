"""Background service for monitoring Twitch streams."""

import asyncio
import time
import os
from typing import Dict, Any

from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
from backend.src.services.gql_client import GQLClient
from backend.src.services.eventsub_service import EventSubService  # Import the new EventSub service
from backend.src.services.download_service import DownloadService
from backend.src.services.token_manager import TokenManager
from backend.src.services.backup_manager import backup_streamers_config

class StreamMonitorService:
    """
    Background service that monitors Twitch streams, manages token authentication,
    handles EventSub WebSocket connections, and coordinates stream downloads.
    """

    def __init__(self, websocket_manager):
        """
        Initialize the stream monitoring service.
        
        Args:
            websocket_manager: Manager for WebSocket connections to broadcast updates to clients
        """
        self.websocket_manager = websocket_manager
        self.update_interval = 300  # Poll interval in seconds (5 minutes)
        self.running = False
        self.last_update_time = {}  # Tracks when each streamer was last updated
        
        # Initialize token manager for OAuth authentication
        from backend.src.config.settings import CONFIG_DIR
        token_file = os.path.join(CONFIG_DIR, "token.json")
        self.token_manager = TokenManager(token_file)
        
        # Initialize Twitch EventSub service for real-time stream status notifications
        self.eventsub_service = EventSubService(websocket_manager)
        
        # Share token manager with EventSub for authentication
        self.eventsub_service.token_manager = self.token_manager

        # Initialize download service for recording streams
        self.download_service = DownloadService(websocket_manager, self.token_manager)
        
        # Track last backup time for configuration files
        self.last_backup_time = 0
        
    async def start(self):
        """
        Start all monitoring services and initialize token handling, EventSub
        connections, and download management.
        """
        self.running = True
        
        # Start token authentication management
        await self.token_manager.start()
        
        # Register callback for token refresh events
        self.token_manager.register_refresh_callback(self._on_token_refresh)
        
        # Check if we have a valid auth token
        token, refreshed = await self.token_manager.get_access_token()
        
        # Only start EventSub if we have valid authentication
        if token:
            self.eventsub_service.token = token
            self.eventsub_service.token_error = None
            print(f"[Monitor] Set token in EventSub service: {token[:10]}...")
            
            # Start EventSub service for real-time stream notifications
            await self.eventsub_service.start()
        else:
            print("[Monitor] No valid token available - EventSub will start after authentication")
        
        # Start the stream download service
        await self.download_service.start()
        
        # Start the background polling for streamer status updates
        asyncio.create_task(self._monitoring_loop())
        
        # Start scheduled backup of configuration
        asyncio.create_task(self._backup_scheduler())
        
    async def _backup_scheduler(self):
        """
        Periodically backs up streamer configuration to prevent data loss.
        Creates timestamped backups and manages rotation of old backup files.
        """
        # Wait before first backup to avoid disk activity during startup
        await asyncio.sleep(3600)
        
        while self.running:
            try:
                from backend.src.config.settings import CONFIG_DIR
                current_time = time.time()
                
                # Only backup if 24 hours have passed since last backup
                if current_time - self.last_backup_time >= 86400:  # 24 hours
                    print("[Monitor] Performing scheduled backup of streamers configuration")
                    backup_result = backup_streamers_config(CONFIG_DIR, max_backups=5)
                    if backup_result:
                        self.last_backup_time = current_time
                        print("[Monitor] Backup completed successfully")
                
            except Exception as e:
                print(f"[Monitor] Error during scheduled backup: {e}")
                import traceback
                traceback.print_exc()
            
            # Check every hour
            await asyncio.sleep(3600)  # 1 hour
        
    async def stop(self):
        """
        Gracefully shut down all monitoring services and clean up resources.
        """
        self.running = False
        
        # Stop token management service
        await self.token_manager.stop()
        
        # Stop EventSub WebSocket service
        await self.eventsub_service.stop()
        
        print("[Monitor] Stream monitoring service stopped")
        
    async def _monitoring_loop(self):
        """
        Main monitoring loop that checks stream status periodically.
        This provides a fallback mechanism in addition to real-time
        EventSub notifications.
        """
        while self.running:
            try:
                await self._update_all_streamers()
            except Exception as e:
                print(f"[Monitor] Error in monitoring loop: {e}")
            
            # Wait until next check interval
            await asyncio.sleep(self.update_interval)
            
    async def _update_all_streamers(self):
        """
        Query Twitch for all monitored streamers and update their status.
        
        Fetches current information for each streamer, detects status changes,
        updates thumbnails, and broadcasts updates to clients via WebSockets.
        When a streamer goes offline, their title is saved for later restoration.
        """
        streamers = get_monitored_streamers()
        gql_client = GQLClient()
        
        for streamer, settings in streamers.items():
            try:
                # Only update if we have a Twitch ID
                if settings.get("twitch_id"):
                    # Get channel info from Twitch
                    channel_info = await gql_client.get_channel_info(settings["twitch_id"])
                    
                    if channel_info:
                        # Check if stream status has changed
                        is_live = bool(channel_info.get("stream"))
                        was_live = settings.get("isLive", False)
                        
                        # Always update status in the streamers dict
                        streamers[streamer]["isLive"] = is_live
                        
                        # If status changed, broadcast update
                        if is_live != was_live:
                            # If streamer went offline, adjust the title
                            if not is_live and was_live:
                                # Save the current title (for when they go online again)
                                if settings.get("title") and settings.get("title") != "Offline":
                                    streamers[streamer]["lastTitle"] = settings.get("title")
                                
                                # Set title to "Offline"
                                streamers[streamer]["title"] = "Offline"
                                
                                print(f"[Monitor] {streamer} went offline. Setting title to 'Offline'")
                            
                            # If streamer went online, restore their last title if available
                            elif is_live and not was_live:
                                if "lastTitle" in streamers[streamer]:
                                    streamers[streamer]["title"] = streamers[streamer]["lastTitle"]
                                    print(f"[Monitor] {streamer} went online. Restored title from saved title")
                            
                            await self.websocket_manager.broadcast_live_status(
                                streamer, is_live
                            )
                            
                            # Log the change
                            if is_live:
                                print(f"[Monitor] {streamer} is now LIVE")
                            else:
                                print(f"[Monitor] {streamer} is now OFFLINE")
                        
                        # If live, update thumbnail and title
                        if is_live:
                            # Get new values
                            new_thumbnail = channel_info.get("thumbnail")
                            new_title = channel_info.get("title")
                            
                            # Add a timestamp to force cache busting
                            if new_thumbnail:

                                cache_buster = int(time.time())
                                if '?' in new_thumbnail:
                                    new_thumbnail = f"{new_thumbnail}&_t={cache_buster}"
                                else:
                                    new_thumbnail = f"{new_thumbnail}?_t={cache_buster}"
                            
                            # Update the dictionary
                            if new_thumbnail:
                                streamers[streamer]["thumbnail"] = new_thumbnail
                            
                            if new_title:
                                streamers[streamer]["title"] = new_title
                            
                            # Always broadcast update for live streamers on each cycle
                            if new_thumbnail:
                                await self.websocket_manager.broadcast_thumbnail_update(
                                    streamer, 
                                    new_thumbnail,
                                    new_title
                                )
                                
                        
                        # Save changes to persistent storage
                        self.last_update_time[streamer] = time.time()
            except Exception as e:
                print(f"[Monitor] Error updating {streamer}: {e}")
        
        # Save streamer data with updates
        update_monitored_streamers(streamers)

        
    async def _on_token_refresh(self, new_token):
        """
        Handle OAuth token refresh events.
        
        Args:
            new_token (str): The newly refreshed authentication token
            
        Note:
            Validates the token before restarting the EventSub service.
            Includes short delays to ensure proper shutdown/startup sequence.
        """
                
                
        if hasattr(self.token_manager, 'validate_token'):
            is_valid = await self.token_manager.validate_token(new_token)
            if not is_valid:
                print("[Monitor] Token validation failed, not restarting EventSub")
                return  # Don't proceed with invalid token
        
        # Add a short delay
        await asyncio.sleep(2)
        
        # Stop the EventSub service
        await self.eventsub_service.stop()
        
        # Update the token
        self.eventsub_service.token = new_token
        self.eventsub_service.token_error = None
        
        # Add another short delay
        await asyncio.sleep(2)
        
        # Start the service again
        await self.eventsub_service.start()
        

    async def restart_eventsub(self):
        """
        Restart the EventSub WebSocket service with a fresh authentication token.
        
        Used when authentication changes or when connections need to be re-established.
        Obtains a fresh token, stops the existing service, and starts a new instance.
        """
        print("[Monitor] Restarting EventSub service")
        try:
            # Stop the existing service
            await self.eventsub_service.stop()
            
            # Get fresh token
            token, refreshed = await self.token_manager.get_access_token()
            
            if token:
                print(f"[Monitor] Got token for restart: starts with '{token[:10]}...' (length: {len(token)})")
                
                # Update the token in the service
                self.eventsub_service.token = token
                self.eventsub_service.token_error = None
                
                # Restart the service with the new token
                await self.eventsub_service.start()
                print("[Monitor] EventSub service restarted with new token")
                
            else:
                print("[Monitor] No valid token available after refresh attempt")
                
        except Exception as e:
            print(f"[Monitor] Error restarting EventSub service: {e}")
            import traceback
            traceback.print_exc()
        
    def get_status_summary(self) -> Dict[str, Any]:
        """
        Generate a summary of the monitoring service's current status.
        
        Returns:
            Dict[str, Any]: Dictionary containing service status information including:
                - running: Whether the service is active
                - update_interval: Polling frequency in seconds
                - monitored_streamers: Count of tracked streamers
                - live_streamers: List of currently live streamers
                - last_update: Timestamps of most recent updates
                - eventsub: Status of the EventSub WebSocket service
        """
        streamers = get_monitored_streamers()
        live_streamers = [s for s, data in streamers.items() if data.get("isLive")]
        
        # Get EventSub status
        eventsub_status = self.eventsub_service.get_status()
        
        return {
            "running": self.running,
            "update_interval": self.update_interval,
            "monitored_streamers": len(streamers),
            "live_streamers": live_streamers,
            "last_update": self.last_update_time,
            "eventsub": eventsub_status
        }