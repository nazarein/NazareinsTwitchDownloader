"""Authentication server that runs on AWS with enhanced security."""

import aiohttp
import time
import os
import ssl
import sys
import json
from collections import defaultdict
from aiohttp import web
from datetime import datetime, timedelta

# Get CLIENT_SECRET from environment variable
CLIENT_ID = "d88elif9gig3jo3921wrlusmc5rz21"
CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET")

# Exit if CLIENT_SECRET is not set
if not CLIENT_SECRET:
    print("ERROR: TWITCH_CLIENT_SECRET environment variable must be set!", file=sys.stderr)
    print("Please set this environment variable before starting the server.", file=sys.stderr)
    sys.exit(1)

ALLOWED_ORIGINS = [
    "http://localhost:8420",
    "https://authentication.acheapdomain.click",
]

# Security settings
RATE_LIMIT_REQUESTS = 15          # Max requests per window
RATE_LIMIT_WINDOW = 3600          # Window size in seconds (1 hour)
FAILED_ATTEMPTS_LIMIT = 3       # Number of failed attempts before temporary block
TEMPORARY_BLOCK_DURATION = 3600   # Block duration in seconds after failed attempts (1 hour)
SUSPICIOUS_BLOCK_DURATION = 86400 # Block duration for suspicious activity (24 hours)
TWITCH_DOMAINS = ["id.twitch.tv", "twitch.tv"]

@web.middleware
async def cors_middleware(request, handler):
    try:
        resp = await handler(request)
        origin = request.headers.get("Origin")
        
        # Allow any origin with port 8420 or the auth domain
        if origin and (":8420" in origin or origin == "https://authentication.acheapdomain.click"):
            resp.headers["Access-Control-Allow-Origin"] = origin
        
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp
    except Exception as e:
        return web.Response(text=f"Internal server error: {str(e)}", status=500)

class SecurityManager:
    def __init__(self):
        self.requests = defaultdict(list)
        self.failed_attempts = defaultdict(int)
        self.blocked_until = defaultdict(float)
        self.suspicious_ips = set()
        
        # Try to load previously blocked IPs from disk
        try:
            if os.path.exists("blocked_ips.json"):
                with open("blocked_ips.json", "r") as f:
                    data = json.load(f)
                    self.blocked_until = defaultdict(float, data.get("blocked_until", {}))
                    self.suspicious_ips = set(data.get("suspicious_ips", []))
                    print(f"Loaded {len(self.blocked_until)} blocked IPs and {len(self.suspicious_ips)} suspicious IPs")
        except Exception as e:
            print(f"Error loading blocked IPs: {e}")

    def save_state(self):
        """Save blocked and suspicious IPs to disk"""
        try:
            # Convert defaultdict to regular dict for serialization
            blocked_dict = dict(self.blocked_until)
            # Filter out expired blocks
            now = time.time()
            blocked_dict = {ip: until for ip, until in blocked_dict.items() if until > now}
            
            data = {
                "blocked_until": blocked_dict,
                "suspicious_ips": list(self.suspicious_ips)
            }
            
            with open("blocked_ips.json", "w") as f:
                json.dump(data, f)
        except Exception as e:
            print(f"Error saving security state: {e}")

    def check_request(self, ip, path):
        """Check if request should be allowed"""
        now = time.time()
        
        # Check if IP is currently blocked
        if self.blocked_until[ip] > now:
            # Calculate time remaining in the block
            remaining = int(self.blocked_until[ip] - now)
            minutes, seconds = divmod(remaining, 60)
            hours, minutes = divmod(minutes, 60)
            
            time_message = ""
            if hours > 0:
                time_message += f"{hours} hour{'s' if hours != 1 else ''} "
            if minutes > 0 or hours > 0:
                time_message += f"{minutes} minute{'s' if minutes != 1 else ''} "
            time_message += f"{seconds} second{'s' if seconds != 1 else ''}"
            
            return False, f"Too many failed attempts. Please try again in {time_message}."
        
        # Rate limiting
        self.requests[ip] = [
            req_time for req_time in self.requests[ip]
            if now - req_time < RATE_LIMIT_WINDOW
        ]
        
        # Check if over rate limit
        if len(self.requests[ip]) >= RATE_LIMIT_REQUESTS:
            # Set a block for 1 hour
            self.blocked_until[ip] = now + TEMPORARY_BLOCK_DURATION
            self.save_state()
            return False, "Rate limit exceeded. Please try again later."
        
        self.requests[ip].append(now)
        return True, None

    def record_success(self, ip):
        """Record successful authentication"""
        self.failed_attempts[ip] = 0  # Reset failed attempts on success

    def record_failure(self, ip):
        """Record failed authentication attempt"""
        self.failed_attempts[ip] += 1
        
        # Check if reached failure threshold
        if self.failed_attempts[ip] >= FAILED_ATTEMPTS_LIMIT:
            print(f"IP {ip} blocked for {TEMPORARY_BLOCK_DURATION}s due to {self.failed_attempts[ip]} failed attempts")
            now = time.time()
            self.blocked_until[ip] = now + TEMPORARY_BLOCK_DURATION
            
            # If multiple blocks, consider suspicious and block for longer
            if ip in self.suspicious_ips:
                print(f"IP {ip} marked as suspicious, extending block to 24 hours")
                self.blocked_until[ip] = now + SUSPICIOUS_BLOCK_DURATION
            
            # After blocking twice, mark as suspicious for future
            if self.failed_attempts[ip] >= FAILED_ATTEMPTS_LIMIT * 2:
                print(f"IP {ip} added to suspicious list")
                self.suspicious_ips.add(ip)
            
            self.save_state()
            self.failed_attempts[ip] = 0  # Reset counter after blocking

# Create the security manager
security_manager = SecurityManager()

async def handle_oauth_callback(request):
    """Handle OAuth callback for authorization code flow."""
    client_ip = request.remote
    
    # Security check
    allowed, message = security_manager.check_request(client_ip, request.path)
    if not allowed:
        return web.Response(text=message, status=429)

    code = request.query.get("code")
    if not code:
        security_manager.record_failure(client_ip)
        return web.Response(text="No authorization code received", status=400)

    try:
        async with aiohttp.ClientSession() as session:
            token_response = await session.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": "https://authentication.acheapdomain.click/auth/callback",
                },
            )

            if token_response.status != 200:
                security_manager.record_failure(client_ip)
                return web.Response(
                    text="Failed to exchange code for token", status=400
                )

            tokens = await token_response.json()

            validate_response = await session.get(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {tokens['access_token']}"},
            )

            if validate_response.status != 200:
                security_manager.record_failure(client_ip)
                return web.Response(text="Invalid token received", status=400)

            gql_response = await session.get(
                "https://gql.twitch.tv/gql",
                headers={
                    "Authorization": f"OAuth {tokens['access_token']}",
                    "Client-ID": CLIENT_ID, 
                },
            )

            print(f"GQL response status: {gql_response.status}")
            print(f"GQL response cookies: {[c for c in gql_response.cookies]}")

            auth_cookie = None
            for cookie_name, cookie in gql_response.cookies.items():
                if cookie_name == "auth-token":
                    auth_cookie = cookie.value
                    tokens["auth_cookie"] = auth_cookie
                    break

            if auth_cookie:
                tokens["auth_cookie"] = auth_cookie
                
            security_manager.record_success(client_ip)

    except Exception as e:
        print(f"Error in OAuth callback: {str(e)}")
        return web.Response(text="Internal server error", status=500)

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Authentication Complete</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 2em; text-align: center; }}
        </style>
    </head>
    <body>
        <h3>Authentication Successful!</h3>
        <p>You may close this window and return to the application.</p>
        <script>
            // Prepare tokens object
            const tokens = {{
                access_token: "{tokens['access_token']}",
                refresh_token: "{tokens['refresh_token']}",
                expires_in: {tokens['expires_in']},
                auth_cookie: "{tokens.get('auth_cookie', '')}"
            }};
            
            // Use wildcard origin to bypass cross-origin issues
            try {{
                console.log("Sending token data to opener window");
                window.opener.postMessage(tokens, "*");
                setTimeout(() => window.close(), 2000);
            }} catch (e) {{
                console.error("Error communicating with opener:", e);
                document.body.innerHTML += '<div style="color:red">Error sending data to application. Please close this window and try again.</div>';
            }}
        </script>
    </body>
    </html>
    """

    return web.Response(text=html, content_type="text/html")

# Token refresh endpoint with security
async def handle_token_refresh(request):
    """Refresh access token using refresh token."""
    client_ip = request.remote
    
    # Security check
    allowed, message = security_manager.check_request(client_ip, request.path)
    if not allowed:
        return web.Response(text=message, status=429)
        
    refresh_token = request.query.get("refresh_token")
    if not refresh_token:
        security_manager.record_failure(client_ip)
        return web.Response(text="No refresh token provided", status=400)

    try:
        async with aiohttp.ClientSession() as session:
            refresh_response = await session.post(
                "https://id.twitch.tv/oauth2/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )

            if refresh_response.status != 200:
                security_manager.record_failure(client_ip)
                return web.Response(text="Failed to refresh token", status=400)

            new_tokens = await refresh_response.json()

            # Validate new access token
            validate_response = await session.get(
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {new_tokens['access_token']}"},
            )

            if validate_response.status != 200:
                security_manager.record_failure(client_ip)
                return web.Response(text="Invalid token received", status=400)

            # Record successful token refresh
            security_manager.record_success(client_ip)
            return web.json_response(new_tokens)

    except Exception as e:
        print(f"Error in token refresh: {str(e)}")
        return web.Response(text="Internal server error", status=500)

# Status endpoint for monitoring
async def handle_status(request):
    """Status endpoint with basic security information."""
    now = time.time()
    blocked_count = sum(1 for time_val in security_manager.blocked_until.values() if time_val > now)
    
    status = {
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "security": {
            "blocked_ips_count": blocked_count,
            "suspicious_ips_count": len(security_manager.suspicious_ips),
            "rate_limit_window": f"{RATE_LIMIT_WINDOW} seconds",
            "failed_attempts_limit": FAILED_ATTEMPTS_LIMIT
        }
    }
    return web.json_response(status)

async def init_app():
    app = web.Application(middlewares=[cors_middleware])
    
    app.router.add_get("/", lambda r: web.Response(text="Twitch Auth Server Running"))
    app.router.add_get("/auth/callback", handle_oauth_callback)
    app.router.add_get("/auth/refresh", handle_token_refresh)
    app.router.add_get("/status", handle_status)

    return app

if __name__ == "__main__":
    app = init_app()

    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(
        "/etc/letsencrypt/live/authentication.acheapdomain.click/fullchain.pem",
        "/etc/letsencrypt/live/authentication.acheapdomain.click/privkey.pem",
    )

    web.run_app(app, host="0.0.0.0", port=443, ssl_context=ssl_context)