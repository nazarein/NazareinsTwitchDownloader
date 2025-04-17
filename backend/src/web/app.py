"""
Web Application Server Module

This module implements the web server component of the Twitch Downloader application,
providing both API endpoints and serving the frontend Single Page Application (SPA).

The server handles:
- RESTful API endpoints for streamer management and configuration
- Authentication and token management
- WebSocket connections for real-time updates
- Static file serving for the React frontend
- CORS support for cross-origin requests

The application uses aiohttp for both HTTP and WebSocket support, allowing
for efficient asynchronous handling of client requests and real-time updates.

Usage:
    # Initialize the web application
    websocket_manager = WebSocketManager()
    web_app = WebApp(websocket_manager=websocket_manager)
    
    # Configure routes with handlers
    handlers = WebHandlers(websocket_manager=websocket_manager)
    web_app.setup_routes(handlers)
    
    # Start the server
    await web_app.start("0.0.0.0", 8420)
"""

import os
import sys
from aiohttp import web
from backend.src.web.handlers import WebHandlers
from backend.src.web.websocket import WebSocketManager
from backend.src.web.middleware import cors_middleware

class WebApp:
    """
    Web application server that provides API endpoints and serves the frontend.
    
    This class creates and configures the aiohttp web application, sets up middleware,
    registers routes for API endpoints and static files, and manages WebSocket
    connections for real-time client updates.
    
    Attributes:
        app (web.Application): The aiohttp web application instance
        websocket_manager (WebSocketManager): Manager for WebSocket connections
    """

    def __init__(self, websocket_manager: WebSocketManager = None):
        """
        Initialize the web application.
        
        Creates a new aiohttp web application instance and configures it with
        CORS middleware for cross-origin requests.
        
        Args:
            websocket_manager: Manager for WebSocket connections for real-time updates.
                              If None, a new instance will be created.
        """
        self.app = web.Application()
        self.websocket_manager = websocket_manager or WebSocketManager()

        # Add CORS middleware for cross-origin requests
        self.app.middlewares.append(cors_middleware)

    def setup_routes(self, handlers: WebHandlers):
        """
        Configure application routes for API endpoints and WebSocket connections.
        
        This method registers all API endpoints, WebSocket handlers, and static file
        routes with the aiohttp application router. The organization follows a RESTful
        pattern with appropriate HTTP methods for each operation.
        
        Args:
            handlers: Object containing route handler methods for various endpoints
        
        Route Groups:
            - Streamer management (/api/streamers/*)
            - Storage configuration (/api/storage/*)
            - Authentication (/api/auth/*)
            - EventSub monitoring (/api/eventsub/*)
            - Download control (/api/streamers/*/download/*)
            - WebSocket endpoints (/ws, /console)
            - Static file serving (/, /static/*, etc.)
        """

        # API routes for Twitch
        self.app.router.add_get("/api/streamers", handlers.get_streamers)
        self.app.router.add_post("/api/streamers", handlers.update_streamers)
        self.app.router.add_get(
            "/api/streamers/{streamer}/status", handlers.get_streamer_status
        )
        self.app.router.add_post(
            "/api/streamers/{streamer}/settings", handlers.update_streamer_settings
        )
        self.app.router.add_post(
            "/api/streamers/{streamer}/storage", handlers.handle_streamer_storage
        )
        self.app.router.add_get("/api/storage", handlers.get_storage_info)
        self.app.router.add_post("/api/storage", handlers.update_storage_path)
        self.app.router.add_post("/api/available-paths", handlers.get_available_paths)
        
        # Authentication routes 
        self.app.router.add_route("*", "/api/auth/token", handlers.handle_token)
        self.app.router.add_post("/api/auth/twitch-cookie", handlers.handle_twitch_cookie)
        self.app.router.add_post("/api/auth/extract-cookie", handlers.handle_dummy_endpoint)

        # WebSocket routes for real-time updates
        self.app.router.add_get("/ws", self.websocket_manager.handle_websocket)
        self.app.router.add_get("/console", self.websocket_manager.handle_console_websocket)
        
        # Static file handler for SPA root
        self.app.router.add_get("/", handlers.serve_index)
        
        # Catch-all route for SPA - handles client-side routing
        self.app.router.add_get("/{tail:.*}", handlers.serve_index)

        # API routes for EventSub
        self.app.router.add_get("/api/eventsub/debug", handlers.get_eventsub_debug)
        self.app.router.add_post("/api/eventsub/reconnect", handlers.eventsub_reconnect)

        # Download control routes
        self.app.router.add_post(
            "/api/streamers/{streamer}/download/start", handlers.start_download
        )
        self.app.router.add_post(
            "/api/streamers/{streamer}/download/stop", handlers.stop_download
        )
        self.app.router.add_post(
            "/api/streamers/{streamer}/downloads", handlers.toggle_downloads
        )
        self.app.router.add_get("/api/auth/check-cookie-file", handlers.check_cookie_file)
        
    async def start(self, host: str, port: int):
        """
        Start the web application server.
        
        This method:
        1. Determines the correct path to frontend files based on execution context
        2. Sets up static file serving with a multi-stage approach to handle edge cases
        3. Creates and starts the HTTP server on the specified host and port
        
        The static file serving setup follows a specific order to ensure proper
        handling of all frontend assets, both in development and production modes,
        as well as when running as a frozen executable.
        
        Args:
            host: The hostname or IP address to bind the server to (e.g., "0.0.0.0")
            port: The port number to listen on
            
        Note:
            If the frontend files cannot be found, the method will log an error
            and return without starting the server.
        """
        import sys
        import os
        
        # Determine frontend directory based on execution context
        if getattr(sys, 'frozen', False):
            # Running as executable (PyInstaller)
            if hasattr(sys, '_MEIPASS'):
                base_dir = sys._MEIPASS  # PyInstaller temp directory
            else:
                base_dir = os.path.dirname(sys.executable)
            
            frontend_dir = os.path.join(base_dir, 'frontend', 'build')
        else:
            # Running as Python script in development
            frontend_dir = os.path.join(os.getcwd(), 'frontend', 'build')
        
        # Verify frontend files exist to prevent startup errors
        index_path = os.path.join(frontend_dir, 'index.html')
        if not os.path.exists(index_path):
            print(f"[WebApp] ERROR: index.html NOT found at: {index_path}")
            return
            
        # Setup static file serving - ORDER MATTERS for proper routing
        # The sequence below handles various special cases for static files
        
        # 1. First serve /static files (CSS, JS, media)
        static_dir = os.path.join(frontend_dir, 'static')
        if os.path.exists(static_dir):
            self.app.router.add_static('/static', static_dir)
            
        # 2. Add explicit route for asset-manifest.json (needed for React)
        manifest_path = os.path.join(frontend_dir, 'asset-manifest.json')
        if os.path.exists(manifest_path):
            async def serve_manifest(request):
                return web.FileResponse(manifest_path, headers={"Content-Type": "application/json"})
            self.app.router.add_get('/asset-manifest.json', serve_manifest)
            
        # 3. Serve favicon.ico explicitly (browsers request this automatically)
        favicon_path = os.path.join(frontend_dir, 'favicon.ico')
        if os.path.exists(favicon_path):
            async def serve_favicon(request):
                return web.FileResponse(favicon_path, headers={"Content-Type": "image/x-icon"})
            self.app.router.add_get('/favicon.ico', serve_favicon)
                
        # 4. Add specific handler for the root path (/)
        async def serve_root_index(request):
            return web.FileResponse(index_path, headers={"Content-Type": "text/html"})
        self.app.router.add_get('/', serve_root_index)
        
        # 5. Add general static file serving for other files in the root
        try:
            # This may fail if there are route conflicts
            self.app.router.add_static('/', frontend_dir)
        except ValueError as e:
            # Fallback: manually add routes for each file in the directory
            print(f"[WebApp] Contents of {frontend_dir}:")
            for item in os.listdir(frontend_dir):
                print(f"  - {item}")
                
            # Create individual routes for each file
            for item in os.listdir(frontend_dir):
                item_path = os.path.join(frontend_dir, item)
                if os.path.isfile(item_path):
                    print(f"[WebApp] Adding individual file route for: {item}")
                    
                    # Create a proper closure to capture the current value of item_path
                    def make_handler(path):
                        async def handler(request):
                            print(f"[WebApp] Serving file: {path}")
                            return web.FileResponse(path)
                        return handler
                        
                    self.app.router.add_get(f'/{item}', make_handler(item_path))
        
        # 6. Set up index.html fallback for SPA routes - this must be LAST
        # This enables client-side routing to work properly
        self.app.router.add_get('/{path:.*}', serve_root_index)
                
        # Start the web server
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        
        print(f"[WebApp] Server started on http://{host}:{port}")