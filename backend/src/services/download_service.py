# src/services/download_service.py
import asyncio
import os
import subprocess
import platform
import logging
import json
import time
from typing import Dict, Set

class DownloadService:
    """
    Service for downloading and recording Twitch streams when they go live.
    Manages download processes, file naming, and stream quality selection.
    """

    def __init__(self, websocket_manager, token_manager=None):
        """
        Initialize the download service.
        
        Args:
            websocket_manager: Manager for WebSocket connections to broadcast updates to clients
            token_manager: Manager for authentication tokens used for ad-free downloads
        """
        self.websocket_manager = websocket_manager
        self.token_manager = token_manager
        self.active_downloads = {}  # Maps streamers to their download processes
        self.configured_streamers = set()  # Streamers with downloads enabled
        self.running = False
        self.cancellation_flags = {}  # Maps streamers to their cancellation flags
        self.download_lock = asyncio.Lock() 
        self.download_cooldowns = {}  # Track cooldown periods after natural completion
        self.cooldown_duration = 30  # 30-second cooldown
        
    async def start(self):
        """
        Start the download service and load initial configuration.
        Begins monitoring enabled streamers for download opportunities.
        """
        self.running = True
        # Load streamers with downloads enabled
        await self._load_configured_streamers()
        #Immediately check for live streams to handle application restart case
        await self._initial_state_reconciliation()
        # Start monitoring for streams to download
        asyncio.create_task(self._download_monitor_loop())
        
    async def _load_configured_streamers(self):
        """
        Load the list of streamers that have downloads enabled.
        
        Retrieves streamer settings from configuration storage and populates
        the configured_streamers set with streamers marked for downloading.
        """
        # Load streamers with downloads_enabled=True from settings
        from backend.src.config.settings import get_monitored_streamers
        streamers = get_monitored_streamers()
        self.configured_streamers = {
            streamer for streamer, settings in streamers.items() 
            if settings.get("downloads_enabled", False)
        }
        
    async def _download_monitor_loop(self):
        """
        Main monitoring loop that periodically checks for download opportunities.
        
        Runs continuously while the service is active, checking every 10 seconds
        for streamers that should have downloads started or stopped based on
        their current live status and configuration.
        """
        # Main loop to check if downloads should be started/stopped
        while self.running:
            try:
                await self._check_downloads()
            except Exception as e:
                print(f"[DownloadService] Error in monitor loop: {e}")
            await asyncio.sleep(10)  # Check every 10 seconds

    async def _check_downloads(self):
        """
        Check all configured streamers to determine if downloads should be started or stopped.
        
        For streamers with downloads enabled:
        - Starts downloads for streamers who are live but not currently being recorded
        
        For streamers with downloads disabled:
        - Stops any active downloads if the streamer was previously enabled
        """
        # Get current status of all streamers
        from backend.src.config.settings import get_monitored_streamers
        streamers = get_monitored_streamers()
        
        # First check for zombie downloads (downloads running but stream is offline)
        active_streamers = list(self.active_downloads.keys())
        for streamer in active_streamers:
            # Get current status from settings
            streamer_settings = streamers.get(streamer, {})
            is_currently_live = streamer_settings.get("isLive", False)
            
            if not is_currently_live and streamer in self.active_downloads:
                await self.stop_download(streamer)
                
                # Send completion notification since stream likely ended
                await self.websocket_manager.broadcast_download_status(
                    streamer, "completed"
                )
        
        # code for starting/stopping downloads
        for streamer, settings in streamers.items():
            if streamer in self.configured_streamers:
                # If streamer is live and not already downloading, start download
                if settings.get("isLive", False) and streamer not in self.active_downloads:
                    await self.start_download(streamer, settings)
            else:
                # If downloads are disabled but we have an active download, stop it
                if streamer in self.active_downloads:
                    await self.stop_download(streamer)
        
    
    async def start_download(self, streamer, settings):
        """
        Start downloading a streamer's live stream.
        
        Creates an appropriately named file based on date and stream title,
        configures the Streamlink session with authentication if available,
        and launches a download thread to capture the stream.
        
        Args:
            streamer (str): Twitch username of the streamer
            settings (dict): Streamer's configuration settings containing resolution, 
                            storage path, and other metadata
        """

        # Lock and duplicate check at the very beginning
        async with self.download_lock:
            # Check if there's already a download in progress for this streamer
            if streamer in self.active_downloads:
                print(f"[DownloadService] Download already in progress for {streamer}, skipping")
                return
                
            # Check for cooldown period
            current_time = time.time()
            if streamer in self.download_cooldowns and current_time < self.download_cooldowns[streamer]:
                remaining = int(self.download_cooldowns[streamer] - current_time)
                print(f"[DownloadService] Download for {streamer} in cooldown period ({remaining}s remaining), skipping")
                return

            #Verify stream is still live
            try:
                from backend.src.services.gql_client import GQLClient
                gql_client = GQLClient()
                
                # Get the streamer's Twitch ID
                twitch_id = settings.get("twitch_id", "")
                if not twitch_id:
                    # If no Twitch ID, look it up (you already have this logic below)
                    from backend.src.config.settings import get_monitored_streamers
                    streamers = get_monitored_streamers()
                    if streamer in streamers:
                        twitch_id = streamers[streamer].get("twitch_id", "")
                
                if twitch_id:
                    # Fetch current channel info directly to verify it's still live
                    channel_info = await gql_client.get_channel_info(twitch_id)
                    if not channel_info or not channel_info.get("stream"):
                        print(f"[DownloadService] Stream is no longer live for {streamer}, aborting download")
                        
                        # Update streamer's live status in the configuration
                        from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
                        streamers = get_monitored_streamers()
                        if streamer in streamers:
                            streamers[streamer]["isLive"] = False
                            update_monitored_streamers(streamers)
                        
                        # Notify WebSocket clients
                        await self.websocket_manager.broadcast_download_status(
                            streamer, "stopped"
                        )
                        await self.websocket_manager.broadcast_live_status(
                            streamer, False
                        )
                        
                        return
            except Exception as e:
                print(f"[DownloadService] Error checking live status for {streamer}: {e}")

            # Get the selected resolution (defaulting to "best" if not set)
            selected_resolution = settings.get("stream_resolution", "best")

            # Get path for saving
            save_path = settings.get("save_directory", "")
            if not save_path:
                from backend.src.config.settings import get_storage_path
                save_path = get_storage_path()
                
            # Create a folder for the streamer inside the base path
            save_path = os.path.join(save_path, streamer)
            
            # Ensure directory exists
            os.makedirs(save_path, exist_ok=True)
            
            # Get auth token
            auth_token = await self._get_auth_token()
            if not auth_token:
                print("[DownloadService] No auth cookie file found, will use alternative download method")
            
            # Create filename with date and stream title
            import re
            
            date_str = time.strftime("%Y-%m-%d")
            
            # Get the actual stream title from settings
            stream_title = settings.get("title", "")
            
            # If no valid title exists, fetch it directly via GQL
            if not stream_title or stream_title == "Offline" or stream_title == f"{streamer}'s Stream":
                try:
                    # Create GQL client to fetch the current title
                    from backend.src.services.gql_client import GQLClient
                    gql_client = GQLClient()
                    
                    # Get the streamer's Twitch ID
                    twitch_id = settings.get("twitch_id", "")
                    if not twitch_id:
                        # If no Twitch ID, look it up
                        from backend.src.config.settings import get_monitored_streamers
                        streamers = get_monitored_streamers()
                        if streamer in streamers:
                            twitch_id = streamers[streamer].get("twitch_id", "")
                    
                    if twitch_id:
                        # Fetch current channel info
                        channel_info = await gql_client.get_channel_info(twitch_id)
                        if channel_info and channel_info.get("stream") and channel_info.get("title"):
                            stream_title = channel_info.get("title")
                            
                            # Update the stored title in settings
                            from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
                            streamers = get_monitored_streamers()
                            if streamer in streamers:
                                streamers[streamer]["title"] = stream_title
                                update_monitored_streamers(streamers)
                    
                    # If we still don't have a title, we have no choice but to abort
                    if not stream_title or stream_title == "Offline" or stream_title == f"{streamer}'s Stream":
                        await self.websocket_manager.broadcast_download_status(
                            streamer, "error"
                        )
                        print(f"[DownloadService] Error: Could not fetch a valid title for {streamer}. Download aborted.")
                        return
                        
                except Exception as e:
                    print(f"[DownloadService] Error fetching stream title for {streamer}: {e}")
                    await self.websocket_manager.broadcast_download_status(
                        streamer, "error"
                    )
                    return
            
            # Sanitize the stream title to make it safe for filesystem
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', stream_title)
            
            # Truncate title if it's too long (max 100 chars)
            if len(safe_title) > 100:
                safe_title = safe_title[:97] + "..."
                
            # Base filename without extension
            base_filename = f"[{date_str}] {safe_title}"
            
            # Check if file already exists and add number if needed
            counter = 0
            filepath = os.path.join(save_path, f"{base_filename}.mp4")
            
            while os.path.exists(filepath):
                counter += 1
                filepath = os.path.join(save_path, f"{base_filename} ({counter}).mp4")
            
            # Create a stream downloader function that runs in a separate thread
            def download_stream():
                try:
                    import streamlink
                    from streamlink.session import Streamlink
                    import threading
                    
                    # Create a new Streamlink session
                    session = Streamlink()
                    
                    # Configure session
                    session.set_option("stream-timeout", 60)
                    session.set_option("ringbuffer-size", 32 * 1024 * 1024)  # 32M
                    
                    # Configure auth
                    if auth_token:
                        session.set_option("http-cookies", {"auth-token": auth_token})
                        session.set_option("http-headers", {
                            "Authorization": f"OAuth {auth_token}"
                        })
                    else:
                        session.set_option("twitch-disable-ads", True)
                    
                    # Get streams
                    streams = session.streams(f"https://twitch.tv/{streamer}")
                    
                    if not streams:
                        print(f"[DownloadService] No streams found for {streamer}")
                        return False
                    
                    # Get stream with selected resolution if available, otherwise best quality
                    if selected_resolution in streams:
                        stream = streams[selected_resolution]
                    else:
                        # If selected resolution is not available, fallback to best
                        stream = streams["best"]
                        print(f"[DownloadService] Selected resolution {selected_resolution} not available, using best")
                    
                    # Open stream
                    fd = stream.open()
                    
                    # Write to file
                    with open(filepath, "wb") as f:
                        while True:
                            try:
                                data = fd.read(1024 * 1024)  # Read 1MB at a time
                                if not data:
                                    break
                                f.write(data)
                            except Exception as e:
                                print(f"[DownloadService] Error during stream read: {e}")
                                break
                    
                    # When stream ends naturally
                    if not cancellation_flag.is_set():
                        print(f"[DownloadService] Download completed for {streamer}")
                        # Clean up when thread completes successfully
                        asyncio.run_coroutine_threadsafe(
                            self._handle_download_completion(streamer, 0),  # 0 = success
                            asyncio.get_event_loop()
                        )
                        return True
                        
                except Exception as e:
                    print(f"[DownloadService] Error in download thread: {e}")
                    import traceback
                    traceback.print_exc()
                    # Clean up after exceptions
                    asyncio.run_coroutine_threadsafe(
                        self._handle_download_completion(streamer, 1),  # 1 = error
                        asyncio.get_event_loop()
                    )
                    return False
            
            # Create and start the download thread
            import threading

            self.cancellation_flags[streamer] = threading.Event()

            loop = asyncio.get_running_loop()

            download_thread = threading.Thread(
                target=self._download_stream_thread,
                args=(streamer, filepath, auth_token, selected_resolution, self.cancellation_flags[streamer], loop)
            )
            download_thread.daemon = True
            download_thread.start()
            
            # Store both the thread and additional information we'll need for cleanup
            self.active_downloads[streamer] = {
                "thread": download_thread,
                "filepath": filepath,
                "cancellation_flag": self.cancellation_flags[streamer]
            }

            # Update status in persistent storage - ADD THIS CODE HERE
            from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
            streamers = get_monitored_streamers()
            if streamer in streamers:
                streamers[streamer]["downloadStatus"] = "downloading"
                update_monitored_streamers(streamers)

            # Notify about download start - THIS LINE ALREADY EXISTS
            await self.websocket_manager.broadcast_download_status(
                streamer, "downloading"
            )

            print(f"[DownloadService] Started download thread for {streamer}")
    
    async def stop_download(self, streamer):
        """
        Stop an active download for a specific streamer.
        
        Removes the download from tracking and broadcasts status update
        to clients. Since we can't directly terminate threads, the daemon
        thread will continue until the application exits.
        
        Args:
            streamer (str): Twitch username of the streamer to stop downloading
        """
        if streamer in self.active_downloads:
            print(f"[DownloadService] Stopping download for {streamer}")
            
            download_info = self.active_downloads[streamer]
            
            # Signal the thread to stop
            if streamer in self.cancellation_flags:
                self.cancellation_flags[streamer].set()
            
            # Give a short time for the thread to clean up resources
            await asyncio.sleep(0.5)
            
            # Remove from tracking
            del self.active_downloads[streamer]
            
            # Remove cancellation flag
            if streamer in self.cancellation_flags:
                del self.cancellation_flags[streamer]
            
            # Update status in persistent storage
            from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
            streamers = get_monitored_streamers()
            if streamer in streamers:
                streamers[streamer]["downloadStatus"] = "stopped"
                update_monitored_streamers(streamers)
                
            # Notify WebSocket clients
            await self.websocket_manager.broadcast_download_status(
                streamer, "stopped"
            )
            
            print(f"[DownloadService] Download stopped for {streamer}")

    def _download_stream_thread(self, streamer, filepath, auth_token, selected_resolution, cancellation_flag, loop):
        try:
            import streamlink
            from streamlink.session import Streamlink
            
            # Create a new Streamlink session
            session = Streamlink()
            
            # Configure session (same configuration as before)
            session.set_option("stream-timeout", 60)
            session.set_option("ringbuffer-size", 32 * 1024 * 1024)  # 32M
            
            # Configure auth
            if auth_token:
                session.set_option("http-cookies", {"auth-token": auth_token})
                session.set_option("http-headers", {
                    "Authorization": f"OAuth {auth_token}"
                })
            else:
                session.set_option("twitch-disable-ads", True)
            
            # Get streams
            streams = session.streams(f"https://twitch.tv/{streamer}")
            
            if not streams:
                print(f"[DownloadService] No streams found for {streamer}")
                return False
            
            # Get stream with selected resolution if available, otherwise best quality
            if selected_resolution in streams:
                stream = streams[selected_resolution]
            else:
                # If selected resolution is not available, fallback to best
                stream = streams["best"]
                print(f"[DownloadService] Selected resolution {selected_resolution} not available, using best")
            
            # Open stream
            fd = stream.open()
            
            # Track this for cleanup
            self._current_fd = fd
            
            # Write to file
            with open(filepath, "wb") as f:
                while not cancellation_flag.is_set():
                    try:
                        data = fd.read(1024 * 1024)  # Read 1MB at a time
                        if not data:
                            break
                        f.write(data)
                    except Exception as e:
                        print(f"[DownloadService] Error during stream read: {e}")
                        break
                
                # Properly flush the file
                f.flush()
            
            # Ensure stream is properly closed
            if fd:
                try:
                    fd.close()
                except:
                    pass
                self._current_fd = None
            
            if cancellation_flag.is_set():
                print(f"[DownloadService] Download cancelled for {streamer}")
                return False
                    
            print(f"[DownloadService] Download completed for {streamer}")
            # Use the passed loop instead of trying to get it in the thread
            asyncio.run_coroutine_threadsafe(
                self._handle_download_completion(streamer, 0),  # 0 = success
                loop
            )
            return True
                
        except Exception as e:
            print(f"[DownloadService] Error in download thread: {e}")
            import traceback
            traceback.print_exc()
            # Also use the passed loop here if needed
            try:
                asyncio.run_coroutine_threadsafe(
                    self._handle_download_completion(streamer, 1),  # 1 = error
                    loop
                )
            except Exception as loop_error:
                print(f"[DownloadService] Error in completion notification: {loop_error}")
            return False
        
    async def _handle_download_completion(self, streamer, return_code):
        """
        Handle download completion for a streamer.
        """
        # Clean up and notify about download completion
        if streamer in self.active_downloads:
            del self.active_downloads[streamer]
        
        # Set a cooldown to prevent immediate restart
        self.download_cooldowns[streamer] = time.time() + self.cooldown_duration
        
        # Get streamers data to update status
        from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
        streamers = get_monitored_streamers()
        
        status = "completed" if return_code == 0 else "error"
        
        # Update the status in persistent storage
        if streamer in streamers:
            print(f"[DownloadService] Updating downloadStatus for {streamer} to {status}")
            streamers[streamer]["downloadStatus"] = status
            update_monitored_streamers(streamers)
        
        # Broadcast status update to clients
        print(f"[DownloadService] Broadcasting download status for {streamer}: {status}")
        await self.websocket_manager.broadcast_download_status(
            streamer, status
        )
        
    async def enable_downloads(self, streamer, enabled):
        """
        Enable or disable downloads for a specific streamer.
        
        Updates tracking for configured streamers and immediately stops
        any active downloads if downloads are being disabled.
        
        Args:
            streamer (str): Twitch username of the streamer
            enabled (bool): Whether downloads should be enabled or disabled
        """
        print(f"[DownloadService] Setting downloads for {streamer} to {enabled}")
        
        if enabled:
            # Add to configured streamers
            self.configured_streamers.add(streamer)
        else:
            # Remove from configured streamers
            if streamer in self.configured_streamers:
                self.configured_streamers.remove(streamer)
                
            # IMPORTANT: Stop any active download immediately when disabled
            if streamer in self.active_downloads:
                await self.stop_download(streamer)
                
    async def _initial_state_reconciliation(self):
        """
        Check the current state of all streams on application startup by
        directly querying the Twitch API for fresh stream status.
        
        This ensures that if the application was restarted while streams were live,
        downloads will be started immediately rather than waiting for the next status update.
        """
        
        # Get all configured streamers with downloads enabled
        from backend.src.config.settings import get_monitored_streamers, update_monitored_streamers
        streamers = get_monitored_streamers()
        
        # Create GQL client to query Twitch directly
        from backend.src.services.gql_client import GQLClient
        gql_client = GQLClient()
        
        # Track which streamers were found to be live
        updated_streamers = {}
        live_streamers_found = []
        
        # Query each configured streamer's status
        for streamer_name, settings in streamers.items():
            # Skip streamers that don't have downloads enabled
            if streamer_name not in self.configured_streamers:
                continue
                
            # Get the Twitch ID - required for querying
            twitch_id = settings.get("twitch_id", "")
            if not twitch_id:
                print(f"[DownloadService] Cannot reconcile {streamer_name} - missing Twitch ID")
                continue
                
            try:
                # Direct query to Twitch API for fresh status
                channel_info = await gql_client.get_channel_info(twitch_id)
                
                if channel_info:
                    # Determine if the streamer is live from fresh data
                    is_live = bool(channel_info.get("stream"))
                    
                    # Update the cached state
                    streamers[streamer_name]["isLive"] = is_live
                    
                    # Update metadata if available
                    if channel_info.get("title"):
                        streamers[streamer_name]["title"] = channel_info.get("title")
                    if channel_info.get("thumbnail"):
                        streamers[streamer_name]["thumbnail"] = channel_info.get("thumbnail")
                    
                    # Start download if streamer is live and not already downloading
                    if is_live and streamer_name not in self.active_downloads:
                        live_streamers_found.append(streamer_name)
                        
                        # Use a separate task to start the download to avoid blocking the reconciliation process
                        asyncio.create_task(self.start_download(streamer_name, streamers[streamer_name]))
            except Exception as e:
                print(f"[DownloadService] Error reconciling {streamer_name}: {e}")
        
        # Save the updated streamer data
        update_monitored_streamers(streamers)
        
    
    async def _get_auth_token(self):
        """
        Retrieve the Twitch authentication token for ad-free downloads.
        
        Reads the authentication cookie from the configuration directory
        if it exists, which allows Streamlink to authenticate with Twitch.
        
        Returns:
            str or None: The authentication token if found, otherwise None
        """
        # Check for the auth cookie - this is all we need for Streamlink
        from backend.src.config.settings import CONFIG_DIR
        cookie_path = os.path.join(CONFIG_DIR, "twitch_auth_cookie.txt")
        
        if os.path.exists(cookie_path):
            try:
                with open(cookie_path, "r") as f:
                    cookie_value = f.read().strip()
                    return cookie_value
            except Exception as e:
                print(f"[DownloadService] Error reading cookie file: {e}")
        else:
            print("[DownloadService] No auth cookie file found, will use alternative download method")
            # Return None to indicate we should use alternative command
            return None