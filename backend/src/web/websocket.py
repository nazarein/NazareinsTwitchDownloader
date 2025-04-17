"""
WebSocket Communication Module

This module implements real-time bidirectional communication between the server
and frontend clients using WebSockets. It handles two types of WebSocket connections:
- Application WebSockets: For streamer status updates, live notifications, and download status
- Console WebSockets: For streaming application logs to the web interface console

Key features:
- Connection lifecycle management (connect, disconnect, heartbeat)
- Message routing and broadcast to connected clients
- Console output interception for real-time logging
- Debounced state synchronization
- Client tracking and dead connection cleanup

The module uses a message-type based communication protocol with JSON payloads,
allowing for structured updates and requests between server and clients.

Usage:
    # Initialize the WebSocket manager
    websocket_manager = WebSocketManager()
    
    # Add WebSocket routes to the web application
    app.router.add_get("/ws", websocket_manager.handle_websocket)
    app.router.add_get("/console", websocket_manager.handle_console_websocket)
    
    # Broadcast updates to connected clients
    await websocket_manager.broadcast_live_status("streamer123", True)
"""

import asyncio
import enum
import json
import logging
import sys
import time
import traceback
from io import StringIO
from typing import Dict, Optional, Set, Any, List, Callable
from aiohttp import web, WSMsgType

# Set up logging
logger = logging.getLogger("websocket")

class LogLevel(enum.Enum):
    """
    Log level enum for standardized log messages.
    
    Used to categorize log messages by severity for appropriate
    display in the console UI.
    
    Attributes:
        DEBUG: Low-level details useful for debugging
        INFO: Normal operational information
        WARNING: Non-critical issues that may need attention
        ERROR: Serious issues affecting functionality
        SUCCESS: Positive operational outcomes
    """
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"

class MessageType(enum.Enum):
    """
    WebSocket message types for standardized communication.
    
    Defines a protocol of message types used between server and clients
    to categorize different kinds of updates and requests.
    
    Attributes:
        INITIAL_STATE: Full application state for newly connected clients
        STATUS_UPDATE: General settings or configuration changes
        LIVE_STATUS: Updates on whether a streamer is currently live
        DOWNLOAD_STATUS: Updates on download progress or state
        THUMBNAIL_UPDATE: New stream thumbnail image URLs
        STORAGE_SYNC: Client-side storage synchronization messages
        LOG: Application log messages for the console
    """
    INITIAL_STATE = "initial_state"
    STATUS_UPDATE = "status_update"
    LIVE_STATUS = "live_status"
    DOWNLOAD_STATUS = "download_status"
    THUMBNAIL_UPDATE = "thumbnail_update"
    STORAGE_SYNC = "storage_sync"
    LOG = "log"

class ClientManager:
    """
    Manages a set of WebSocket clients with common functionality.
    
    Provides a unified interface for tracking connected clients,
    broadcasting messages, and handling connection lifecycles.
    
    Attributes:
        name: Descriptive name for this client group (used in logging)
        clients: Set of active WebSocket connections
    """
    
    def __init__(self, name: str):
        """
        Initialize a client manager with a descriptive name.
        
        Args:
            name: Identifier for this client group (e.g., "AppWS" or "ConsoleWS")
        """
        self.name = name
        self.clients: Set[web.WebSocketResponse] = set()
    
    def add_client(self, client: web.WebSocketResponse) -> None:
        """
        Add a client to the managed set.
        
        Registers a new WebSocket connection and logs the total
        number of active connections.
        
        Args:
            client: WebSocket response object for the new connection
        """
        self.clients.add(client)
        logger.info(f"[{self.name}] Client connected. Total: {len(self.clients)}")
    
    def remove_client(self, client: web.WebSocketResponse) -> None:
        """
        Remove a client from the managed set.
        
        Deregisters a WebSocket connection when it closes or errors
        and logs the remaining number of active connections.
        
        Args:
            client: WebSocket response object to remove
        """
        if client in self.clients:
            self.clients.remove(client)
            logger.info(f"[{self.name}] Client disconnected. Remaining: {len(self.clients)}")
    
    async def broadcast(self, message: Dict[str, Any]) -> None:
        """
        Broadcast a message to all connected clients.
        
        Sends the same message to all active WebSocket connections
        and removes any clients that error during sending.
        
        Args:
            message: JSON-serializable dictionary to send to all clients
            
        Note:
            If no clients are connected, the method returns immediately.
            Dead clients (those that error during send) are automatically removed.
        """
        if not self.clients:
            return
            
        msg_type = message.get('type', 'unknown')
        logger.debug(f"[{self.name}] Broadcasting {msg_type} to {len(self.clients)} clients")
        
        dead_clients = set()
        
        for client in self.clients:
            try:
                await client.send_json(message)
            except Exception as e:
                logger.error(f"[{self.name}] Error sending to client: {e}")
                dead_clients.add(client)
        
        # Remove dead clients
        for client in dead_clients:
            self.remove_client(client)

class WebSocketManager:
    """
    Manages WebSocket connections with frontend clients for real-time updates.
    
    This class is the central hub for WebSocket communication, handling:
    - Connection establishment and lifecycle management
    - Message processing and routing
    - Broadcast operations to all connected clients
    - Console output interception for logging
    
    It maintains two separate sets of WebSocket connections:
    1. Application clients: Receive streamer status updates and notifications
    2. Console clients: Receive application log messages
    
    Attributes:
        app_clients: Manager for application WebSocket connections
        console_clients: Manager for console WebSocket connections
        log_buffer: Circular buffer of recent log messages for new console clients
        max_buffer_size: Maximum number of log messages to retain
        last_state_sent: Tracks when initial state was last sent to each client
        initial_state_debounce_time: Minimum seconds between initial state sends
    """

    def __init__(self):
        """
        Initialize the WebSocket manager with client tracking and message handlers.
        
        Sets up separate client managers for application and console connections,
        configures the log buffer, and intercepts stdout for console logging.
        """
        # Regular WebSocket clients receiving application events
        self.app_clients = ClientManager("AppWS")
        
        # Console WebSocket clients receiving log messages
        self.console_clients = ClientManager("ConsoleWS")
        
        # Buffer for log messages to send to new console clients
        self.log_buffer = []
        self.max_buffer_size = 1000  # Maximum log messages to retain
        
        # Track last state sent time per client
        self.last_state_sent = {}
        self.initial_state_debounce_time = 3  # seconds
        
        # Intercept stdout for console logging
        self._setup_log_interception()
        
        # Log initialization
        logger.info("WebSocketManager initialized")
    
    async def handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Handle WebSocket connections and messages from application clients.
        
        This method is registered as an HTTP route handler and:
        1. Establishes the WebSocket connection
        2. Sends an initial empty state message
        3. Processes incoming messages from the client
        4. Handles disconnection and cleanup
        
        Args:
            request: The HTTP request upgrading to a WebSocket connection
            
        Returns:
            WebSocketResponse: The WebSocket response object
            
        Note:
            The connection remains open until the client disconnects or an error occurs.
            The method processes messages in an asynchronous loop.
        """
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        
        self.app_clients.add_client(ws)
        client_ip = request.remote
        client_id = id(ws)  # Use object id as unique client identifier
        
        # Send initial welcome message without full state data
        try:
            await ws.send_json({
                "type": MessageType.INITIAL_STATE.value,
                "data": {
                    "twitch": {}
                }
            })
            
            # Process incoming messages
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        message_type = data.get("type")
                        
                        if message_type == "request_initial_state":
                            logger.debug(f"[AppWS] Initial state requested by client {client_ip}")
                            
                            # Check if we've sent state to this client recently
                            current_time = time.time()
                            if client_id in self.last_state_sent:
                                time_since_last = current_time - self.last_state_sent[client_id]
                                if time_since_last < self.initial_state_debounce_time:
                                    logger.debug(f"[AppWS] Skipping duplicate initial state request (sent {time_since_last:.1f}s ago)")
                                    continue
                            
                            # Send full state and update last sent time
                            await self.send_initial_state(ws)
                            self.last_state_sent[client_id] = current_time
                            
                        elif message_type == "storage_sync":
                            logger.debug(f"[AppWS] Storage sync received from client {client_ip}")
                            # Handle storage sync logic here if needed
                        else:
                            logger.debug(f"[AppWS] Received message type: {message_type}")
                            
                    except json.JSONDecodeError:
                        logger.warning(f"[AppWS] Invalid JSON received from {client_ip}: {msg.data[:100]}...")
                    except Exception as e:
                        logger.error(f"[AppWS] Error handling message from {client_ip}: {str(e)}")
                        logger.debug(f"[AppWS] Exception details: {traceback.format_exc()}")
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"[AppWS] WebSocket connection closed with error: {ws.exception()}")
        except Exception as e:
            logger.error(f"[AppWS] Unhandled error in WebSocket handler: {str(e)}")
            logger.debug(f"[AppWS] Exception details: {traceback.format_exc()}")
        finally:
            self.app_clients.remove_client(ws)
            # Clean up client tracking
            if client_id in self.last_state_sent:
                del self.last_state_sent[client_id]
            
        return ws

    async def handle_console_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """
        Handle WebSocket connections for the console UI.
        
        This method is registered as an HTTP route handler for console connections and:
        1. Establishes the WebSocket connection
        2. Sends all buffered log messages to the new client
        3. Processes any incoming commands from the console UI
        4. Handles disconnection and cleanup
        
        Args:
            request: The HTTP request upgrading to a WebSocket connection
            
        Returns:
            WebSocketResponse: The WebSocket response object
            
        Note:
            Console WebSockets are primarily for receiving log messages,
            but can also send commands to the server if needed.
        """
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        
        self.console_clients.add_client(ws)
        client_ip = request.remote
        
        # Send buffered log messages
        try:
            # Send buffered logs to new client
            for log in self.log_buffer:
                await ws.send_json(log)
            
            # Process incoming messages (e.g., for console commands)
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        # Handle console commands here if needed
                        command = data.get("command")
                        if command:
                            logger.debug(f"[ConsoleWS] Received command: {command}")
                    except json.JSONDecodeError:
                        logger.warning(f"[ConsoleWS] Invalid JSON received from {client_ip}")
                    except Exception as e:
                        logger.error(f"[ConsoleWS] Error handling message: {str(e)}")
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"[ConsoleWS] WebSocket connection closed with error: {ws.exception()}")
        except Exception as e:
            logger.error(f"[ConsoleWS] Unhandled error in console WebSocket handler: {str(e)}")
        finally:
            self.console_clients.remove_client(ws)
            
        return ws

    def _setup_log_interception(self):
        """
        Set up interception of stdout to broadcast logs to console clients.
        
        Replaces the standard sys.stdout with a custom implementation that:
        1. Passes through all output to the original stdout
        2. Processes log messages line by line
        3. Adds them to the log buffer
        4. Broadcasts them to connected console clients
        
        This enables real-time streaming of application logs to the web console UI.
        
        Note:
            Includes fallback handling for environments where stdout is unavailable.
            Uses heuristic detection of log levels based on message content.
        """
        # Check if stdout is valid
        if sys.stdout is None or not hasattr(sys.stdout, 'write'):
            # Create a fallback
            class SafeOutput:
                def write(self, text):
                    pass
                def flush(self):
                    pass
            sys.stdout = SafeOutput()
            
        # Store original stdout
        self.original_stdout = sys.stdout
        
        # Create a custom stdout to intercept messages
        class ConsoleLogInterceptor(StringIO):
            def __init__(self, ws_manager, original_stdout):
                super().__init__()
                self.ws_manager = ws_manager
                self.original_stdout = original_stdout
                self.buffer = ""
            
            def write(self, text):
                # Write to original stdout
                self.original_stdout.write(text)
                
                # Buffer the text and process complete lines
                self.buffer += text
                if '\n' in self.buffer:
                    lines = self.buffer.split('\n')
                    for line in lines[:-1]:  # Process all complete lines
                        if line.strip():  # Only process non-empty lines
                            self._process_log_line(line)
                    self.buffer = lines[-1]  # Keep any partial line
            
            def _process_log_line(self, text):
                # Determine log level based on content
                level = LogLevel.INFO.value
                
                lower_text = text.lower()
                if "error" in lower_text or "[error]" in lower_text:
                    level = LogLevel.ERROR.value
                elif "warning" in lower_text or "[warning]" in lower_text or "[warn]" in lower_text:
                    level = LogLevel.WARNING.value
                elif "debug" in lower_text or "[debug]" in lower_text:
                    level = LogLevel.DEBUG.value
                elif "success" in lower_text or "[success]" in lower_text:
                    level = LogLevel.SUCCESS.value
                
                # Create log message
                log_msg = {
                    "type": MessageType.LOG.value,
                    "message": text.rstrip(),
                    "level": level,
                    "timestamp": time.time()
                }
                
                # Store in buffer
                self.ws_manager.add_log(log_msg)
                
                # Broadcast to console clients - safely handle non-async contexts
                if self.ws_manager.console_clients.clients:
                    try:
                        # Try to get running loop and create task
                        loop = asyncio.get_running_loop()
                        asyncio.create_task(self.ws_manager.console_clients.broadcast(log_msg))
                    except RuntimeError:
                        # No running loop, just store the log message but don't try to broadcast
                        # Could use threading.Thread here if needed
                        pass
            
            def flush(self):
                self.original_stdout.flush()
                # Process any remaining content in buffer
                if self.buffer.strip():
                    self._process_log_line(self.buffer)
                    self.buffer = ""
        
        # Replace stdout with our interceptor
        sys.stdout = ConsoleLogInterceptor(self, self.original_stdout)
        logger.info("Console log interception set up")
    
    def add_log(self, log_msg: Dict[str, Any]) -> None:
        """
        Add a log message to the buffer, maintaining maximum size.
        
        Implements a circular buffer for log messages, discarding
        oldest messages when the buffer exceeds maximum size.
        
        Args:
            log_msg: Log message dictionary with type, message, level, and timestamp
        """
        self.log_buffer.append(log_msg)
        # Remove oldest logs if buffer exceeds max size
        while len(self.log_buffer) > self.max_buffer_size:
            self.log_buffer.pop(0)


    async def send_initial_state(self, client: web.WebSocketResponse):
        """
        Send initial application state to a client.
        
        Retrieves the current streamer configuration and sends it to
        a newly connected client. This gives the client all information
        needed to render the initial UI state.
        
        Args:
            client: WebSocket client to send the initial state to
            
        Note:
            If an error occurs during sending, it is logged but not propagated.
            This prevents connection errors from affecting the application.
        """
        from backend.src.config.settings import get_monitored_streamers
        
        # Get current streamers and their settings
        twitch_streamers = get_monitored_streamers()
        
        # Count streamers with profile images (for summary log)
        streamers_with_images = sum(1 for s in twitch_streamers.values() if s.get("profileImageURL"))
        total_streamers = len(twitch_streamers)
        
        try:
            await client.send_json({
                "type": "initial_state",
                "data": {
                    "twitch": twitch_streamers
                }
            })
        except Exception as e:
            print(f"[WebSocket] Error sending initial state: {e}")
            
    async def broadcast_status_update(self, platform: str, streamer: str, settings: Dict[str, Any]):
        """
        Broadcast settings update to all connected clients.
        
        Sends a notification about updated streamer settings to all
        connected application clients. This is used when streamer
        configuration changes.
        
        Args:
            platform: Platform identifier (e.g., "twitch")
            streamer: Streamer username
            settings: Dictionary of updated settings
        """
        print(f"[WebSocket] Broadcasting settings update for {platform}/{streamer}")
    
        await self.app_clients.broadcast({
            "type": "status_update",
            "platform": platform,
            "streamer": streamer,
            "settings": settings
        })
    
    async def broadcast_live_status(self, streamer: str, is_live: bool) -> None:
        """
        Broadcast a live status update for a specific streamer.
        
        Notifies all connected clients about a streamer going live or offline.
        This is typically triggered by EventSub notifications or polling.
        
        Args:
            streamer: Streamer username
            is_live: Whether the streamer is currently live
        """
        await self.app_clients.broadcast({
            "type": MessageType.LIVE_STATUS.value,
            "streamer": streamer,
            "isLive": is_live
        })
    
    async def broadcast_download_status(self, streamer: str, status: str) -> None:
        """
        Broadcast a download status update for a specific streamer.
        
        Notifies all connected clients about changes in download status
        for a streamer, such as starting, stopping, completion, or errors.
        
        Args:
            streamer: Streamer username
            status: Download status (e.g., "downloading", "completed", "error")
        """
        await self.app_clients.broadcast({
            "type": MessageType.DOWNLOAD_STATUS.value,
            "streamer": streamer,
            "status": status
        })
    
    async def broadcast_thumbnail_update(self, streamer: str, thumbnail: str, title: Optional[str] = None) -> None:
        """
        Broadcast a thumbnail update for a specific streamer.
        
        Notifies all connected clients about a new stream thumbnail or title.
        This is used to update the UI with the latest stream visuals.
        
        Args:
            streamer: Streamer username
            thumbnail: URL of the stream thumbnail image
            title: Optional stream title to update
        """
        message = {
            "type": MessageType.THUMBNAIL_UPDATE.value,
            "streamer": streamer,
            "thumbnail": thumbnail
        }
        if title:
            message["title"] = title
            
        await self.app_clients.broadcast(message)