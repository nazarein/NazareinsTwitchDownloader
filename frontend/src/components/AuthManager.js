/**
 * Authentication Manager Component
 * 
 * Manages user authentication with Twitch via both OAuth and cookie-based methods.
 * This component:
 * - Handles Twitch OAuth login/logout flow
 * - Stores and manages authentication tokens
 * - Provides a toggle for the cookie helper interface
 * - Detects platform type (Windows/Linux) for optimal settings
 * - Broadcasts authentication events to other components
 * 
 * The component supports two authentication methods:
 * 1. OAuth for EventSub WebSocket connections and standard API access
 * 2. Cookie-based authentication for ad-free stream downloads
 * 
 * @module components/AuthManager
 */

import React, { useState, useEffect } from 'react';
import { LogIn, LogOut, Cookie } from 'lucide-react';
import CookieHelper from './CookieHelper';

/**
 * Authentication Manager component for handling Twitch login flows
 * 
 * @returns {JSX.Element} AuthManager component
 */
const AuthManager = () => {
    // Authentication state
    const [isLoggedIn, setIsLoggedIn] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState(null);
    
    // UI state
    const [showCookieHelper, setShowCookieHelper] = useState(false);
    const [isLinuxServer, setIsLinuxServer] = useState(false);

    /**
     * Detect if running on Linux server to adjust UI accordingly
     */
    useEffect(() => {
        fetch('/api/storage')
            .then(res => res.json())
            .then(data => {
                setIsLinuxServer(!data.isWindows);
            })
            .catch(err => {
                console.error('Failed to detect platform:', err);
            });
    }, []);

    /**
     * Check authentication token status and update login state
     * 
     * @async
     * @returns {Promise<void>}
     */
    const checkTokenStatus = async () => {
      try {
        // Fetch current token from backend
        const response = await fetch('/api/auth/token');
        if (!response.ok) {
          throw new Error(`Error fetching token: ${response.status}`);
        }
        
        const tokens = await response.json();
        
        // Validate token and update login state
        if (tokens && tokens.access_token && tokens.refresh_token) {
          const expiresAt = tokens.expires_at;
          
          // Log expiry time for debugging
          const timeUntilExpiry = expiresAt - Date.now();
          console.log(`[Auth] Token expires in ${Math.floor(timeUntilExpiry/1000/60)} minutes`);
          
          // Update login state
          setIsLoggedIn(true);
        } else {
          setIsLoggedIn(false);
        }
      } catch (error) {
        console.error('[Auth] Error checking token status:', error);
        setIsLoggedIn(false);
      }
    };
    
    /**
     * Check token status on component mount
     */
    useEffect(() => {
      checkTokenStatus();
    }, []);

    /**
     * Set up listener for authentication messages from the OAuth popup
     */
    useEffect(() => {
        /**
         * Handle authentication messages from popup window
         * 
         * @param {MessageEvent} event - Window message event
         */
        const handleAuthMessage = (event) => {
          // Security: Only accept messages from our auth server domain
          if (event.origin === 'https://authentication.acheapdomain.click') {
            console.log("Received message from auth server:", event.origin);
            
            // Extract token data from message
            const { access_token, refresh_token, expires_in, auth_cookie } = event.data;
            
            // Log received data types for debugging (without exposing actual tokens)
            console.log("[Auth] Message contains:", {
              has_access_token: !!access_token,
              has_refresh_token: !!refresh_token,
              expires_in: expires_in,
              has_auth_cookie: !!auth_cookie
            });
            
            // Process tokens if both required tokens are present
            if (access_token && refresh_token) {
              handleTokenReceived(access_token, refresh_token, expires_in, auth_cookie);
            } else {
              console.error("[Auth] Missing required tokens in message");
            }
          } else {
            console.log("Ignored message from:", event.origin);
          }
        };
      
        // Set up message event listener
        window.addEventListener('message', handleAuthMessage);
        
        // Clean up on unmount
        return () => {
          window.removeEventListener('message', handleAuthMessage);
        };
      }, []);

    /**
     * Process received auth tokens and save them to backend
     * 
     * @async
     * @param {string} accessToken - OAuth access token
     * @param {string} refreshToken - OAuth refresh token
     * @param {number} expiresIn - Token expiration time in seconds
     * @param {string} authCookie - Optional Twitch auth cookie
     */
    const handleTokenReceived = async (accessToken, refreshToken, expiresIn, authCookie) => {
        try {
          // Log token presence (without revealing actual tokens)
          console.log("[Auth] Received tokens:", 
                      accessToken ? "Token present" : "No token", 
                      refreshToken ? "Refresh token present" : "No refresh token");
          
          // Calculate absolute expiry timestamp
          const expiresAt = Date.now() + (expiresIn * 1000);
          
          // Save tokens to backend
          const tokenResponse = await fetch('/api/auth/token', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ 
              access_token: accessToken,
              refresh_token: refreshToken,
              expires_in: expiresIn,
              expires_at: expiresAt
            }),
          });
          
          if (!tokenResponse.ok) {
            throw new Error('Failed to save token to backend');
          }
          
          // Also save auth cookie if provided (for ad-free downloads)
          if (authCookie) {
            console.log("[Auth] Also storing auth_cookie from OAuth flow");
            await fetch('/api/auth/twitch-cookie', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ auth_token: authCookie }),
            });
          }
          
          // Update UI state and broadcast login event
          setIsLoggedIn(true);
          window.dispatchEvent(new CustomEvent('twitchLogin'));
        } catch (error) {
          console.error('Error saving token:', error);
          setError(error.message);
        } finally {
          setIsLoading(false);
        }
    };

    /**
     * Initiate Twitch OAuth login process
     * Opens a popup window to the Twitch authorization page
     */
    const handleLogin = () => {
        setIsLoading(true);
        setError(null);
    
        // Prepare OAuth parameters
        const params = new URLSearchParams({
            response_type: 'code',
            client_id: 'd88elif9gig3jo3921wrlusmc5rz21',
            redirect_uri: 'https://authentication.acheapdomain.click/auth/callback',
            scope: [] // Empty scope array - no scopes needed for basic websocket
        });
    
        // Open popup for OAuth flow
        window.open(
            `https://id.twitch.tv/oauth2/authorize?${params}`,
            'TwitchAuth',
            'width=400,height=600,left=960,top=200'
        );
    };

    /**
     * Handle logout by removing stored tokens
     * 
     * @async
     */
    const handleLogout = async () => {
        try {
            // Delete token from backend
            const response = await fetch('/api/auth/token', { 
                method: 'DELETE'
            });

            if (!response.ok) {
                throw new Error('Failed to clear token');
            }

            // Update UI state and broadcast logout event
            setIsLoggedIn(false);
            window.dispatchEvent(new CustomEvent('twitchLogout'));
        } catch (error) {
            console.error('Logout error:', error);
            setError('Failed to logout');
        }
    };

    return (
        <div className="flex flex-col gap-4">
            {/* Conditionally render cookie helper */}
            {showCookieHelper && <CookieHelper />}
            
            <div className="flex items-center gap-2">
                {/* OAuth login/logout button */}
                <button
                    onClick={isLoggedIn ? handleLogout : handleLogin}
                    disabled={isLoading}
                    className={`
                        ${isLoading ? 'bg-purple-400' : 'bg-purple-500 hover:bg-purple-600'}
                        text-white px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
                        ${isLoading ? 'cursor-not-allowed' : 'cursor-pointer'}
                    `}
                >
                    {isLoading ? (
                        <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white" />
                    ) : isLoggedIn ? (
                        <>
                            <LogOut className="w-5 h-5" />
                            Logout
                        </>
                    ) : (
                        <>
                            <LogIn className="w-5 h-5" />
                            Login with OAuth
                        </>
                    )}
                </button>
                
                {/* Cookie helper toggle button */}
                <button
                    onClick={() => setShowCookieHelper(!showCookieHelper)}
                    className={`${!isLinuxServer ? 'ml-2' : ''} bg-zinc-700 hover:bg-zinc-600 text-white px-4 py-2 rounded-lg flex items-center gap-2 transition-colors`}
                >
                    <Cookie className="w-5 h-5" />
                    {showCookieHelper ? 'Hide Cookie Helper' : 'Cookie login'}
                </button>
                
                {/* Error message display */}
                {error && (
                    <div className="text-red-500 text-sm">
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
};

export default AuthManager;