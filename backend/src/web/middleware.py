"""
Web Application Middleware Module

This module provides middleware components for the aiohttp web application,
implementing Cross-Origin Resource Sharing (CORS) support and request error handling.

Middleware functions in this module:
- CORS middleware: Enables cross-origin requests by adding appropriate headers
  to responses and handling OPTIONS preflight requests

Benefits:
- Allows the frontend application to make API requests from different origins
- Implements proper preflight request handling for complex HTTP requests
- Provides centralized error handling for all request processing

Usage:
    # Add middleware to an aiohttp application
    app = web.Application()
    app.middlewares.append(cors_middleware)
"""

from aiohttp import web
from typing import Callable, Awaitable

@web.middleware
async def cors_middleware(request: web.Request, 
                         handler: Callable[[web.Request], Awaitable[web.Response]]) -> web.Response:
    """
    CORS middleware to handle cross-origin requests.
    
    This middleware implements Cross-Origin Resource Sharing (CORS) support
    for the web application, allowing frontend code served from a different
    origin to make API requests. It handles both preflight OPTIONS requests
    and adds appropriate CORS headers to all responses.
    
    Args:
        request: The incoming HTTP request
        handler: The next request handler in the middleware chain
        
    Returns:
        web.Response: Either a preflight response for OPTIONS requests,
                     or the response from the handler with CORS headers added
                    
    Note:
        This middleware uses a permissive CORS policy with "*" for
        Access-Control-Allow-Origin, which allows requests from any origin.
        In production, you might want to restrict this to specific domains.
    """
    # Handle CORS preflight (OPTIONS) requests
    if request.method == "OPTIONS":
        # Return a response with CORS headers but no content
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "3600",  # Cache preflight response for 1 hour
        }
        return web.Response(headers=headers)
    
    try:
        # Process the request through the handler chain
        response = await handler(request)
        
        # Add CORS headers to the response
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        
        return response
    except Exception as e:
        # Handle and log errors
        # Only log actual errors, not normal request processing
        print(f"Error handling request {request.path}: {e}")
        
        # Return a 500 Internal Server Error response
        return web.Response(
            status=500, 
            text=str(e),
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type"
            }
        )