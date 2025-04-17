# main.py with more descriptive comments
import os
import sys
import asyncio
import platform

# Add backend directory to Python path to enable imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

from backend.src.config.constants import WEB_PORT
from backend.src.web.app import WebApp
from backend.src.web.handlers import WebHandlers
from backend.src.web.websocket import WebSocketManager
from backend.src.services.background_service import StreamMonitorService

async def main():
    """Application entry point that initializes and starts all required services."""
    print("Starting Twitch stream monitor")
        
    # Initialize WebSocket manager for real-time communication with clients
    websocket_manager = WebSocketManager()
    
    # Create the background service that monitors streams and manages downloads
    monitor_service = StreamMonitorService(websocket_manager)
    
    # Set up web application with WebSocket support
    web_app = WebApp(websocket_manager=websocket_manager)
    
    # Initialize web route handlers with WebSocket capability for real-time updates
    handlers = WebHandlers(websocket_manager=websocket_manager)
    # Provide handlers with access to monitor service for status endpoints
    handlers.monitor_service = monitor_service
    
    # Configure application routes
    web_app.setup_routes(handlers)
    
    # Initialize system tray icon on Windows platforms
    system_tray_service = None
    if platform.system() == "Windows":
        try:
            from backend.src.services.system_tray import SystemTrayService
            system_tray_service = SystemTrayService(web_port=WEB_PORT)
            system_tray_service.start()
        except Exception as e:
            print(f"Failed to initialize system tray: {e}")
    
    # Start the web server
    print(f"Starting web server at http://localhost:{WEB_PORT}")
    await web_app.start("0.0.0.0", WEB_PORT)
    
    # Start the background monitoring service
    print("Starting background stream monitor service")
    await monitor_service.start()
    
    # Keep the application running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)