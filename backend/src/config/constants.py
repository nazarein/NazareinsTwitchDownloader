"""
Application constants module.

This module contains constant values used throughout the application including
server configuration, API endpoints, and client identifiers for Twitch services.
"""

# Web server configuration
WEB_HOST = "0.0.0.0"  # Listen on all available network interfaces
WEB_PORT = 8420  # Web application server port

# Twitch API endpoints
TWITCH_GQL_URL = "https://gql.twitch.tv/gql"  # Twitch GraphQL API endpoint

# Twitch API configuration
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"  # Twitch GQL endpoint client ID
EVENTSUB_CLIENT_ID = "d88elif9gig3jo3921wrlusmc5rz21"  # OAuth application client ID