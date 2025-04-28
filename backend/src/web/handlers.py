"""
Web Application Route Handlers Module

This module implements the HTTP request handlers for the Twitch Downloader application's
REST API. It provides endpoint implementations for managing streamers, downloads,
storage settings, authentication, and real-time status updates.

The handlers are organized into logical groups:
- Streamer management: Adding, removing, and updating streamer information
- Storage configuration: Setting file paths for downloads
- Authentication: Managing Twitch OAuth tokens and cookies
- EventSub: Managing Twitch WebSocket subscriptions for stream status
- Download control: Starting, stopping, and configuring stream downloads
- Frontend serving: Handling SPA routes and static files

Each handler implements proper error handling and follows a consistent
response format using JSON for all API responses.

Usage:
    # Initialize handlers with a WebSocket manager
    handlers = WebHandlers(websocket_manager=websocket_manager)
    
    # Attach handlers to web app routes
    app.router.add_get("/api/streamers", handlers.get_streamers)
    app.router.add_post("/api/streamers", handlers.update_streamers)
    # ... and so on for all routes
"""

import os
import json
import platform
import time
import asyncio
import sys
import traceback
from typing import Dict, List, Any, Optional, Set

from aiohttp import web
from backend.src.config.settings import (
    get_monitored_streamers,
    update_monitored_streamers,
    get_storage_path,
    update_storage_path,
    get_streamer_storage_path,
    update_streamer_storage_path,
)

class WebHandlers:
    """
    Implements HTTP request handlers for the web application API.
    
    This class contains handler methods for all API endpoints exposed by the
    web application. It processes incoming HTTP requests, interfaces with
    the application's core services (monitoring, download, etc.), and returns
    appropriate JSON responses.
    
    The handlers manage various aspects of the application:
    - Streamer information and status
    - Download control and configuration
    - Storage paths and file system operations
    - Authentication token and cookie management
    - EventSub service status and control
    
    Attributes:
        websocket_manager: Manager for WebSocket connections to broadcast updates
        monitor_service: Reference to the background monitoring service
        frontend_path: Path to the frontend files for serving the SPA
    """

    def __init__(self, websocket_manager=None):
        """
        Initialize the web request handlers.
        
        Creates a new instance of the WebHandlers class with optional
        WebSocket manager for real-time client updates.
        
        Args:
            websocket_manager: Manager for WebSocket connections to broadcast updates.
                              The monitor_service is typically set later by the application.
        """
        self.websocket_manager = websocket_manager
        # monitor_service is typically set by the application after initialization

    async def get_streamers(self, request: web.Request) -> web.Response:
        """
        Handle GET requests for the list of monitored streamers.
        
        Retrieves the current list of monitored streamers from the configuration
        and returns their usernames as a JSON array.
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response containing the list of monitored streamers
            
        Error Response:
            500: If an error occurs while retrieving streamers
        """
        try:
            streamers = get_monitored_streamers()
            return web.json_response(list(streamers.keys()))
        except Exception as e:
            print(f"Error getting streamers: {e}")
            return web.json_response({"error": str(e)}, status=500)
        
    async def update_streamers(self, request: web.Request) -> web.Response:
        """
        Update the list of monitored streamers.
        
        Processes a list of streamer usernames, adds new streamers with their
        Twitch IDs and profile information, and removes streamers that are no
        longer in the list. For new streamers, it fetches additional information
        from Twitch and creates EventSub subscriptions.
        
        Args:
            request: The HTTP request containing a JSON array of streamer usernames
            
        Returns:
            JSON response with status and initial information for new streamers
            
        Error Responses:
            400: If the request data is not in the expected format
            500: If an error occurs during processing
            
        Note:
            This is a complex handler that performs multiple operations:
            1. Normalizes streamer names to lowercase
            2. Identifies new and removed streamers
            3. Fetches Twitch IDs and profile information for new streamers
            4. Updates the streamer configuration
            5. Sets up EventSub subscriptions for new streamers
            6. Notifies clients about new streamers via WebSockets
        """
        try:
            data = await request.json()
            if not isinstance(data, list):
                return web.json_response(
                    {"error": "Invalid data format. Expected array."}, status=400
                )

            # Get current streamers
            current_streamers = get_monitored_streamers()
            updated_streamers = {}

            # Normalize streamer names (lowercase) to prevent duplicates with different capitalization
            unique_streamers = set(streamer.lower() for streamer in data)
            
            # Identify new streamers that need ID lookup
            new_streamers = [s for s in unique_streamers if s not in current_streamers]
            
            # Identify streamers that were removed
            removed_streamers = [s for s in current_streamers.keys() if s not in unique_streamers]

            # Remove EventSub subscriptions and stop downloads for removed streamers
            if removed_streamers and hasattr(self, 'monitor_service') and self.monitor_service:
                for streamer in removed_streamers:
                    # Stop any active downloads
                    try:
                        asyncio.create_task(
                            self.monitor_service.download_service.stop_download(streamer)
                        )
                        print(f"[Streamers] Stopping download for removed streamer: {streamer}")
                    except Exception as e:
                        print(f"[Streamers] Error stopping download for {streamer}: {e}")
                        
                    # Then remove EventSub subscription
                    user_id = current_streamers[streamer].get("twitch_id")
                    if user_id:
                        try:
                            # Remove subscription for this streamer
                            asyncio.create_task(
                                self.monitor_service.eventsub_service.remove_streamer_subscription(user_id)
                            )
                        except Exception as e:
                            print(f"[Streamers] Error removing EventSub subscription for {streamer}: {e}")

            # Lookup Twitch IDs for new streamers
            twitch_ids = {}
            channel_info = {}
            if new_streamers:
                try:
                    print(f"[Streamers] Fetching details for {len(new_streamers)} NEW streamers")
                    from backend.src.services.gql_client import GQLClient
                    gql_client = GQLClient()
                    
                    # Fetch Twitch IDs
                    twitch_ids = await gql_client.lookup_channel_ids(new_streamers)
                    print(f"[Streamers] Fetched {len(twitch_ids)} Twitch IDs for new streamers")
                    
                    # Now fetch channel info including profile images for each new streamer
                    for streamer, channel_id in twitch_ids.items():
                        info = await gql_client.get_channel_info(channel_id)
                        if info:
                            channel_info[streamer] = info
                    
                except Exception as e:
                    print(f"[Streamers] Error fetching Twitch data: {e}")
                    # Continue even if API lookups fail
            
            # Add each streamer to the updated list
            for streamer in unique_streamers:
                # Keep existing settings if streamer was already monitored
                if streamer in current_streamers:
                    updated_streamers[streamer] = current_streamers[streamer]
                else:
                    # Get channel info for this streamer
                    info = channel_info.get(streamer, {})
                    
                    # Initialize new streamer with default settings plus any fetched data
                    updated_streamers[streamer] = {
                        "downloads_enabled": False,
                        "twitch_id": twitch_ids.get(streamer, ""),
                        "save_directory": get_storage_path(),
                        "isLive": bool(info.get("stream")),
                        "title": info.get("title") or f"{streamer}'s Stream",
                        "thumbnail": info.get("thumbnail", ""),
                        "profileImageURL": info.get("profileImageURL", ""),
                        "offlineImageURL": info.get("offlineImageURL", "")
                    }
                    
                    # Log whether we got profile image
                    if info.get("profileImageURL"):
                        print(f"Added new streamer: {streamer} profile image")
                    else:
                        print(f"Added new streamer: {streamer} without profile image")

            # Save the updated streamers list
            update_monitored_streamers(updated_streamers)
            
            # Create EventSub subscriptions for new streamers
            if hasattr(self, 'monitor_service') and self.monitor_service and new_streamers:
                for streamer in new_streamers:
                    if streamer in updated_streamers and updated_streamers[streamer].get("twitch_id"):
                        try:
                            user_id = updated_streamers[streamer]["twitch_id"]
                            is_live = updated_streamers[streamer].get("isLive", False)
                            
                            # Add subscription for this streamer
                            asyncio.create_task(
                                self.monitor_service.eventsub_service.add_streamer_subscription(
                                    user_id, streamer, is_live
                                )
                            )
                            print(f"[Streamers] Adding EventSub subscription for {streamer}")
                        except Exception as e:
                            print(f"[Streamers] Error adding EventSub subscription for {streamer}: {e}")

            # Build response with initial status for new streamers
            initial_status = {
                streamer: updated_streamers[streamer]
                for streamer in updated_streamers 
                if streamer not in current_streamers
            }
            
            # Notify WebSocket clients about new streamers' status
            if hasattr(self, 'websocket_manager') and new_streamers:
                for streamer in new_streamers:
                    if streamer in updated_streamers:
                        try:
                            await self.websocket_manager.broadcast_status_update(
                                "twitch", streamer, updated_streamers[streamer]
                            )
                            
                            # Also broadcast live status specifically
                            await self.websocket_manager.broadcast_live_status(
                                streamer, updated_streamers[streamer].get("isLive", False)
                            )
                            
                            # If thumbnail is available, broadcast it too
                            if updated_streamers[streamer].get("thumbnail"):
                                await self.websocket_manager.broadcast_thumbnail_update(
                                    streamer, 
                                    updated_streamers[streamer]["thumbnail"],
                                    updated_streamers[streamer].get("title")
                                )
                        except Exception as e:
                            print(f"[Streamers] Error broadcasting updates for {streamer}: {e}")
            
            return web.json_response({
                "status": "ok", 
                "initial_status": initial_status
            })
        except Exception as e:
            print(f"Error updating streamers: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def get_streamer_status(self, request: web.Request) -> web.Response:
        """
        Get the status of a specific streamer using cached data.
        
        Retrieves the current status of a streamer from the configuration,
        including live status, download settings, title, thumbnail URLs,
        and storage path. Uses only cached data to avoid API calls.
        
        Args:
            request: The HTTP request with the streamer name in the URL path
            
        Returns:
            JSON response with the streamer's status information
            
        Error Responses:
            404: If the requested streamer is not found
            500: If an error occurs while retrieving the status
            
        Note:
            This handler does not perform any Twitch API calls and uses
            only the locally cached information for quick responses.
        """
    async def get_streamer_status(self, request: web.Request) -> web.Response:
        try:
            streamer = request.match_info["streamer"].lower()
            streamers = get_monitored_streamers()
            
            if streamer not in streamers:
                return web.json_response({"error": "Streamer not found"}, status=404)
            
            settings = streamers[streamer]
            is_live = settings.get("isLive", False)
            
            # Create response using cached data - no GQL queries
            status = {
                "isLive": is_live,
                "downloads_enabled": settings.get("downloads_enabled", False),
                "title": settings.get("title") if is_live else "Offline",
                "thumbnail": settings.get("thumbnail") if is_live else settings.get("offlineImageURL", ""),
                "storage_path": settings.get("save_directory", get_storage_path()),
                "profileImageURL": settings.get("profileImageURL", ""),
                "offlineImageURL": settings.get("offlineImageURL", ""),
                "stream_resolution": settings.get("stream_resolution", "best"),
            }
            
            # Explicitly include download status if available
            if "downloadStatus" in settings:
                status["downloadStatus"] = settings["downloadStatus"]
            # Also check active downloads if available
            elif hasattr(self, 'monitor_service') and self.monitor_service:
                if streamer in self.monitor_service.download_service.active_downloads:
                    status["downloadStatus"] = "downloading"
            
            return web.json_response(status)
        except Exception as e:
            print(f"Error getting streamer status: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def get_eventsub_debug(self, request: web.Request) -> web.Response:
        """
        Get debug information about the EventSub service.
        
        Retrieves the current status of the Twitch EventSub service,
        including WebSocket connections, active subscriptions, and
        authentication status.
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response with the EventSub service status
            
        Error Responses:
            500: If the monitor service is not available or another error occurs
        """
        try:
            if not hasattr(self, 'monitor_service'):
                return web.json_response({
                    "error": "Monitor service not available"
                }, status=500)
                
            # Get status from the EventSub service
            eventsub_status = self.monitor_service.eventsub_service.get_status()
            
            return web.json_response(eventsub_status)
        except Exception as e:
            print(f"Error getting EventSub debug info: {e}")
            return web.json_response({"error": str(e)}, status=500)
            
    async def eventsub_reconnect(self, request: web.Request) -> web.Response:
        """
        Force reconnection of EventSub connections.
        
        Stops and restarts the EventSub service to establish new WebSocket
        connections with Twitch. This is useful when connections are stale
        or after authentication changes.
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response confirming the reconnection was initiated
            
        Error Responses:
            500: If the monitor service is not available or another error occurs
        """
        try:
            if not hasattr(self, 'monitor_service'):
                return web.json_response({
                    "error": "Monitor service not available"
                }, status=500)
                
            # Stop and start the EventSub service
            await self.monitor_service.eventsub_service.stop()
            await self.monitor_service.eventsub_service.start()
            
            return web.json_response({
                "status": "ok",
                "message": "EventSub reconnect initiated"
            })
        except Exception as e:
            print(f"Error reconnecting EventSub: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_token(self, request: web.Request) -> web.Response:
        """
        Handle authentication token operations.
        
        Provides endpoints for retrieving, storing, and deleting Twitch
        OAuth tokens. Supports multiple HTTP methods:
        - GET: Retrieve current token information
        - POST: Store a new token
        - DELETE: Remove the current token
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response with token data or operation status
            
        Error Responses:
            400: If the token data is invalid or incomplete
            405: If an unsupported HTTP method is used
            500: If an error occurs during token operations
            
        Note:
            When a new token is stored, the EventSub service is automatically
            restarted to use the new authentication.
        """
        try:
            from backend.src.config.settings import CONFIG_DIR
            token_file = os.path.join(CONFIG_DIR, "token.json")
            
            if request.method == "GET":
                # Return token if exists
                if os.path.exists(token_file):
                    try:
                        with open(token_file, "r") as f:
                            content = f.read().strip()
                            if content:  # Check if file is not empty
                                token_data = json.loads(content)
                                return web.json_response(token_data)
                            else:
                                print(f"[Token] Token file exists but is empty")
                                return web.json_response({})
                    except json.JSONDecodeError as e:
                        print(f"[Token] Error decoding JSON from token file: {e}")
                        # If token file is corrupted, return empty response
                        return web.json_response({})
                
                print(f"[Token] Token file doesn't exist, returning empty")
                return web.json_response({})
                
            elif request.method == "POST":
                try:
                    # Save new token
                    data = await request.json()
                    
                    # Ensure all required fields are present
                    required_fields = ['access_token', 'refresh_token', 'expires_in']
                    missing_fields = [f for f in required_fields if f not in data]
                    
                    if missing_fields:
                        return web.json_response({
                            "error": f"Missing required fields: {', '.join(missing_fields)}"
                        }, status=400)
                    
                    # Make sure we have expires_at value
                    if 'expires_at' not in data:
                        # Calculate it if not provided
                        data['expires_at'] = int(time.time() * 1000) + (data['expires_in'] * 1000)
                    
                    # Ensure directory exists
                    os.makedirs(os.path.dirname(token_file), exist_ok=True)
                    
                    # Pretty print with indent for readability
                    with open(token_file, "w") as f:
                        json.dump(data, f, indent=2)
                    
                    print(f"[Token] Successfully saved token")
                    
                    # Restart EventSub service to use the new token
                    if hasattr(self, 'monitor_service') and self.monitor_service:
                        try:
                            # Queue the restart to avoid blocking the response
                            asyncio.create_task(self.monitor_service.restart_eventsub())
                            print(f"[Token] Triggered EventSub service restart")
                        except Exception as e:
                            print(f"[Token] Error restarting EventSub service: {e}")
                            
                    return web.json_response({"status": "ok"})
                except json.JSONDecodeError as e:
                    print(f"[Token] Error parsing request JSON: {e}")
                    return web.json_response({"error": "Invalid JSON format"}, status=400)
                
            elif request.method == "DELETE":
                # Delete token
                if os.path.exists(token_file):
                    os.remove(token_file)
                    print(f"[Token] Token file deleted")
                return web.json_response({"status": "ok"})
                
            else:
                print(f"[Token] Method not allowed: {request.method}")
                return web.json_response({"error": "Method not allowed"}, status=405)
                
        except Exception as e:
            print(f"Error handling token: {e}")
            traceback.print_exc()  # Print the full traceback for debugging
            return web.json_response({"error": str(e)}, status=500)
            
    async def handle_twitch_cookie(self, request: web.Request) -> web.Response:
        """
        Handle saving Twitch authentication cookie.
        
        Stores the Twitch authentication cookie provided in the request body
        to a file, which can be used for ad-free stream downloads.
        
        Args:
            request: The HTTP request with the auth_token in the JSON body
            
        Returns:
            JSON response confirming the cookie was saved
            
        Error Responses:
            400: If the auth_token is missing or empty
            500: If an error occurs while saving the cookie
        """
        try:
            data = await request.json()
            
            if "auth_token" not in data or not data["auth_token"]:
                return web.json_response({"error": "Auth token is required"}, status=400)
                
            auth_token = data["auth_token"]
            
            # Import CONFIG_DIR from settings
            from backend.src.config.settings import CONFIG_DIR
            
            # Save the cookie to a file
            cookie_file = os.path.join(CONFIG_DIR, "twitch_auth_cookie.txt")
            with open(cookie_file, "w") as f:
                f.write(auth_token)
            
            print(f"[Cookie] Successfully saved Twitch auth cookie to {cookie_file}")
            
            return web.json_response({
                "status": "ok",
                "message": "Auth cookie saved successfully",
                "path": cookie_file
            })
        except Exception as e:
            print(f"[Cookie] Error saving Twitch auth cookie: {e}")
            traceback.print_exc()
            return web.json_response({"error": str(e)}, status=500)
    
    async def handle_streamer_storage(self, request: web.Request) -> web.Response:
        """
        Handle updating storage path for a specific streamer.
        
        Sets a custom download directory for a specific streamer's recordings.
        Creates the directory if it doesn't exist and verifies write access.
        
        Args:
            request: The HTTP request with the streamer name in the URL path
                    and the new path in the JSON body
            
        Returns:
            JSON response confirming the storage path was updated
            
        Error Responses:
            400: If the path is missing, empty, or not writable
            500: If an error occurs during the update
        """
        try:
            streamer = request.match_info["streamer"].lower()  # Normalize to lowercase
            data = await request.json()
            
            if "path" not in data:
                return web.json_response({"error": "Path is required"}, status=400)
                
            path = data["path"]
            
            # Check if the path is accessible
            try:
                os.makedirs(path, exist_ok=True)
                test_file = os.path.join(path, ".test")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                return web.json_response({"error": f"Path is not writable: {str(e)}"}, status=400)
            
            # Update in streamers.json with the new field name
            streamers = get_monitored_streamers()
            
            if streamer not in streamers:
                streamers[streamer] = {
                    "downloads_enabled": False,
                    "twitch_id": "",
                    "save_directory": path
                }
            else:
                streamers[streamer]["save_directory"] = path
            
            update_monitored_streamers(streamers)
            
            return web.json_response({"status": "ok", "path": path})
        except Exception as e:
            print(f"Error handling streamer storage: {e}")
            return web.json_response({"error": str(e)}, status=500)
            
    async def update_streamer_settings(self, request: web.Request) -> web.Response:
        """
        Update settings for a specific streamer.
        
        Applies changes to a streamer's configuration settings based on the
        request body. Handles persistent settings (like download options and
        storage paths) and notifies other services about relevant changes.
        
        Args:
            request: The HTTP request with the streamer name in the URL path
                    and the new settings in the JSON body
            
        Returns:
            JSON response confirming the settings were updated
            
        Error Responses:
            404: If the streamer is not found
            500: If an error occurs during the update
            
        Note:
            When download settings are changed, the download service is
            immediately notified to start or stop downloads as appropriate.
        """
        try:
            streamer = request.match_info["streamer"].lower()  # Normalize to lowercase
            streamers = get_monitored_streamers()
            
            # Check if streamer exists
            if streamer not in streamers:
                return web.json_response({"error": "Streamer not found"}, status=404)
            
            # Get new settings from request
            new_settings = await request.json()
            settings_to_save = {}
            
            # Only save persistent settings
            if "downloads_enabled" in new_settings:
                settings_to_save["downloads_enabled"] = new_settings["downloads_enabled"]
                
                # Notify download service about the change
                if hasattr(self, 'monitor_service') and self.monitor_service:
                    # This will immediately start/stop downloads as needed
                    await self.monitor_service.download_service.enable_downloads(
                        streamer, new_settings["downloads_enabled"]
                    )
            
            if "twitch_id" in new_settings:
                settings_to_save["twitch_id"] = new_settings["twitch_id"]
                
            if "save_directory" in new_settings:
                settings_to_save["save_directory"] = new_settings["save_directory"]
                
            if "stream_resolution" in new_settings:
                settings_to_save["stream_resolution"] = new_settings["stream_resolution"]
                print(f"[Settings] Updating resolution for {streamer} to {new_settings['stream_resolution']}")
            
            # Update settings
            streamers[streamer].update(settings_to_save)
            
            # Save updated settings
            update_monitored_streamers(streamers)
            
            # For the response and notifications, include both persistent and display settings
            response_settings = streamers[streamer].copy()
            
            # Add display fields for frontend
            response_settings["isLive"] = streamers[streamer].get("isLive", False)  # Use actual value
            response_settings["title"] = streamers[streamer].get("title", f"{streamer}'s Stream")
            response_settings["thumbnail"] = streamers[streamer].get("thumbnail", "")

            # Make sure to preserve profile image URLs
            if "profileImageURL" not in response_settings and "profileImageURL" in streamers[streamer]:
                response_settings["profileImageURL"] = streamers[streamer]["profileImageURL"]
            if "offlineImageURL" not in response_settings and "offlineImageURL" in streamers[streamer]:
                response_settings["offlineImageURL"] = streamers[streamer]["offlineImageURL"]
            
            # Notify clients about the update
            if hasattr(self, 'websocket_manager'):
                # If we have access to the WebSocketManager, notify clients
                await self.websocket_manager.broadcast_status_update(
                    "twitch", streamer, response_settings
                )
            
            return web.json_response({"status": "ok"})
        except Exception as e:
            print(f"Error updating streamer settings: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def get_storage_info(self, request: web.Request) -> web.Response:
        """
        Get information about storage configuration.
        
        Retrieves the global storage path and system-specific path information
        like the path separator and whether the system is Windows.
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response with storage configuration information
            
        Error Responses:
            500: If an error occurs while retrieving storage information
        """
        try:
            path = get_storage_path()
            
            return web.json_response({
                "path": path,
                "separator": "\\" if platform.system() == "Windows" else "/",
                "isWindows": platform.system() == "Windows"
            })
        except Exception as e:
            print(f"Error getting storage info: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def update_storage_path(self, request: web.Request) -> web.Response:
        """
        Update the global storage path.
        
        Sets the global default directory for stream recordings.
        Creates the directory if it doesn't exist and verifies write access.
        
        Args:
            request: The HTTP request with the new path in the JSON body
            
        Returns:
            JSON response confirming the storage path was updated
            
        Error Responses:
            400: If the path is missing, empty, or not writable
            500: If an error occurs during the update
        """
        try:
            data = await request.json()
            
            if "path" not in data:
                return web.json_response({"error": "Path is required"}, status=400)
                
            path = data["path"]
            
            # Check if the path is accessible
            try:
                os.makedirs(path, exist_ok=True)
                test_file = os.path.join(path, ".test")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
            except Exception as e:
                return web.json_response({"error": f"Path is not writable: {str(e)}"}, status=400)
            
            # Update storage path
            if update_storage_path(path):
                return web.json_response({"status": "ok", "path": path})
            else:
                return web.json_response({"error": "Failed to update storage path"}, status=500)
        except Exception as e:
            print(f"Error updating storage path: {e}")
            return web.json_response({"error": str(e)}, status=500)
    
    async def get_available_paths(self, request: web.Request) -> web.Response:
        """
        Get available directories for the path selector.
        
        Lists available directories at a given path for the storage path
        selection UI. Handles special cases for Windows drive letters and
        handles path normalization.
        
        Args:
            request: The HTTP request with the path to list (in query or body)
            
        Returns:
            JSON response with a list of available directories
            
        Error Responses:
            403: If the path exists but permission is denied
            404: If the path does not exist
            500: If an error occurs during the operation
            
        Note:
            On Windows, requesting the root path ("/") returns a list of available
            drive letters. On other platforms, it returns directories in the home folder.
        """
        try:
            # Get path from query or body
            if request.method == "GET":
                path = request.query.get("path", "")
            else:
                data = await request.json()
                path = data.get("path", "")
            
            # If no path is provided, use the root or home directory
            if not path:
                if platform.system() == "Windows":
                    # Return drive letters on Windows
                    drives = []
                    import string
                    import ctypes
                    
                    # Get logical drives bitmask
                    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                    for letter in string.ascii_uppercase:
                        if bitmask & 1:
                            drives.append(f"{letter}:\\")
                        bitmask >>= 1
                    
                    return web.json_response({"dirs": drives})
                else:
                    # Use home directory on Unix
                    path = os.path.expanduser("~")
            
            # Special handling for root on Windows
            if path == "/" and platform.system() == "Windows":
                drives = []
                import string
                import ctypes
                
                # Get logical drives bitmask
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for letter in string.ascii_uppercase:
                    if bitmask & 1:
                        drives.append(f"{letter}:\\")
                    bitmask >>= 1
                
                return web.json_response({"dirs": drives})
            
            # Expand ~ to home directory
            path = os.path.expanduser(path)
            
            # Check if path exists
            if not os.path.exists(path):
                return web.json_response({"error": "Path does not exist"}, status=404)
            
            # Get directories
            dirs = []
            try:
                with os.scandir(path) as entries:
                    for entry in entries:
                        if entry.is_dir() and not entry.name.startswith('.'):
                            dirs.append(entry.name)
            except PermissionError:
                return web.json_response({"error": "Permission denied"}, status=403)
            
            return web.json_response({"dirs": sorted(dirs)})
        except Exception as e:
            print(f"Error getting available paths: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def start_download(self, request: web.Request) -> web.Response:
        """
        Start download for a streamer.
        
        Initiates a stream recording for the specified streamer if they are currently live.
        The recording is saved to the configured storage path with a filename based
        on the date and stream title.
        
        Args:
            request: The HTTP request with the streamer name in the URL path
            
        Returns:
            JSON response confirming the download was started
            
        Error Responses:
            404: If the streamer is not found
            400: If the streamer is not currently live
            500: If an error occurs during the download start process
            
        Note:
            This endpoint requires the monitor_service to be set and accessible.
            The actual download process runs asynchronously in the background.
        """
        streamer = request.match_info["streamer"].lower()
        try:
            streamers = get_monitored_streamers()
            if streamer not in streamers:
                return web.json_response({"error": "Streamer not found"}, status=404)
                
            # Check if streamer is live
            if not streamers[streamer].get("isLive", False):
                return web.json_response({"error": "Streamer is not live"}, status=400)
                
            # Start the download
            await self.monitor_service.download_service.start_download(
                streamer, streamers[streamer]
            )
            
            return web.json_response({"status": "ok"})
        except Exception as e:
            print(f"Error starting download: {e}")
            return web.json_response({"error": str(e)}, status=500)
            
    async def stop_download(self, request: web.Request) -> web.Response:
        """
        Stop download for a streamer.
        
        Stops any active recording for the specified streamer. The partial
        recording file will be preserved with whatever content was already
        captured.
        
        Args:
            request: The HTTP request with the streamer name in the URL path
            
        Returns:
            JSON response confirming the download was stopped
            
        Error Responses:
            500: If an error occurs during the download stop process
            
        Note:
            This endpoint requires the monitor_service to be set and accessible.
            It will attempt to stop the download even if the streamer is not found
            in the current configuration, which allows stopping downloads for
            streamers that have been removed.
        """
        streamer = request.match_info["streamer"].lower()
        try:
            await self.monitor_service.download_service.stop_download(streamer)
            return web.json_response({"status": "ok"})
        except Exception as e:
            print(f"Error stopping download: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def toggle_downloads(self, request: web.Request) -> web.Response:
        """
        Enable or disable downloads for a streamer.
        
        Sets the automatic download flag for a streamer, which determines
        whether streams are automatically recorded when they go live. This
        affects both the configuration and the active download service state.
        
        Args:
            request: The HTTP request with the streamer name in the URL path
                    and the enabled flag in the JSON body
            
        Returns:
            JSON response confirming the download setting was updated
            
        Error Responses:
            404: If the streamer is not found
            500: If an error occurs during the update
            
        Note:
            The download service is notified about the change before the configuration
            is updated to ensure immediate effect on any active downloads.
        """
        streamer = request.match_info["streamer"].lower()
        try:
            data = await request.json()
            enabled = data.get("enabled", False)
            
            # Notify the download service FIRST
            if hasattr(self, 'monitor_service') and self.monitor_service:
                await self.monitor_service.download_service.enable_downloads(streamer, enabled)
            
            # Then update settings
            streamers = get_monitored_streamers()
            if streamer not in streamers:
                return web.json_response({"error": "Streamer not found"}, status=404)
                
            # Update the setting
            streamers[streamer]["downloads_enabled"] = enabled
            update_monitored_streamers(streamers)
            
            return web.json_response({"status": "ok", "enabled": enabled})
        except Exception as e:
            print(f"Error toggling downloads: {e}")
            return web.json_response({"error": str(e)}, status=500)
        
    async def check_cookie_file(self, request: web.Request) -> web.Response:
        """
        Check if the Twitch auth cookie file exists.
        
        Verifies whether the Twitch authentication cookie file exists and
        contains valid content. This is used by the frontend to determine
        if the user has provided authentication for ad-free recordings.
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response indicating whether the cookie file exists and is valid
            
        Error Responses:
            500: If an error occurs during the check
        """
        try:
            from backend.src.config.settings import CONFIG_DIR
            import os
            
            # The path to the cookie file
            cookie_file = os.path.join(CONFIG_DIR, "twitch_auth_cookie.txt")
            
            # Check if the file exists and has content
            exists = os.path.exists(cookie_file)
            has_content = False
            
            if exists:
                try:
                    with open(cookie_file, "r") as f:
                        content = f.read().strip()
                        has_content = bool(content)
                except Exception:
                    pass
            
            return web.json_response({
                "exists": exists and has_content
            })
        except Exception as e:
            print(f"[Cookie] Error checking cookie file: {e}")
            return web.json_response({
                "exists": False,
                "error": str(e)
            }, status=500)

    async def handle_dummy_endpoint(self, request: web.Request) -> web.Response:
        """
        Handle endpoints that aren't needed but are being called by the frontend.
        
        Provides a placeholder response for endpoints that exist for compatibility
        with the frontend but don't require actual implementation. This helps
        prevent errors in the frontend when it expects certain endpoints to exist.
        
        Args:
            request: The HTTP request object
            
        Returns:
            JSON response with a generic "ok" status
            
        Error Responses:
            500: If an unexpected error occurs
        """
        try:
            return web.json_response({
                "status": "ok",
                "message": "This endpoint is a placeholder"
            })
        except Exception as e:
            print(f"Error in dummy endpoint: {e}")
            return web.json_response({"error": str(e)}, status=500)
            
    def set_frontend_path(self, frontend_path):
        """
        Set the frontend path for serving index.html.
        
        Configures the path where the frontend files (HTML, CSS, JS) are located.
        This is used by the serve_index method to locate the SPA index.html file.
        
        Args:
            frontend_path: Path to the directory containing the frontend files
        """
        self.frontend_path = frontend_path
        
    async def serve_index(self, request: web.Request) -> web.Response:
        """
        Serve the index.html file for SPA routing.
        
        Handles requests for the Single Page Application's index.html file,
        which is needed for client-side routing. Modifies the file content
        to ensure relative paths work correctly.
        
        Args:
            request: The HTTP request object
            
        Returns:
            HTTP response with the index.html content
            
        Error Responses:
            500: If an error occurs while reading or serving the file
            
        Note:
            This method modifies the index.html content to fix path references,
            changing absolute paths (/static/...) to relative paths (./static/...),
            which is necessary for proper asset loading.
        """
        try:
            if getattr(sys, 'frozen', False):
                # Running as executable
                if hasattr(sys, '_MEIPASS'):
                    base_dir = sys._MEIPASS
                else:
                    base_dir = os.path.dirname(sys.executable)
                
                frontend_dir = os.path.join(base_dir, 'frontend', 'build')
            else:
                # Running as Python script
                frontend_dir = os.path.join(os.getcwd(), 'frontend', 'build')
                
            index_path = os.path.join(frontend_dir, 'index.html')
            
            # Read and modify the index.html file to fix the paths
            with open(index_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Force the links to be relative by adding ./ prefix
            content = content.replace('href="/', 'href="./').replace('src="/', 'src="./')
            
            # Return the modified content
            return web.Response(
                text=content,
                content_type='text/html'
            )
        except Exception as e:
            print(f"Error serving index.html: {e}")
            traceback.print_exc()
            raise