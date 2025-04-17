/**
 * EventSubDebug Component
 * 
 * This component displays real-time status information about the Twitch EventSub
 * WebSocket connections. It provides monitoring and debugging capabilities for:
 * - Connection status and health
 * - Authentication state
 * - Active streamers and channels
 * - WebSocket connection details
 * - Token errors and validation issues
 * 
 * The component features an expandable interface with detailed information
 * and manual reconnection capabilities for troubleshooting connection issues.
 * It also auto-detects authentication changes and triggers reconnection when needed.
 * 
 * @module components/EventSubDebug
 */

import React, { useState, useEffect } from 'react';
import { AlertCircle, CheckCircle, RefreshCw, ChevronDown, ChevronUp, LogIn, Clock } from 'lucide-react';

/**
 * EventSubDebug component for monitoring Twitch EventSub connections
 * 
 * @returns {JSX.Element} EventSubDebug component
 */
const EventSubDebug = () => {
  // State for tracking EventSub status data
  const [status, setStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [expanded, setExpanded] = useState(false);

  /**
   * Fetch EventSub status data from the API
   * 
   * @async
   * @returns {Promise<void>}
   */
  const fetchStatus = async () => {
    try {
      setIsLoading(true);
      setError(null);
      
      // Fetch status from API endpoint
      const response = await fetch('/api/eventsub/debug');
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }
      
      // Parse and store the data
      const data = await response.json();
      setStatus(data);
    } catch (err) {
      console.error('Error fetching EventSub status:', err);
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Trigger a login request event for authentication
   */
  const handleLogin = () => {
    window.dispatchEvent(new Event('login:request'));
  };

  /**
   * Initialize status polling on component mount
   */
  useEffect(() => {
    // Initial status fetch
    fetchStatus();
    
    // Set up polling interval (every 15 seconds)
    const intervalId = setInterval(fetchStatus, 15000);
    
    // Cleanup on unmount
    return () => clearInterval(intervalId);
  }, []);

  /**
   * Handle token refresh after successful login
   * Auto-reconnects when authentication is refreshed
   */
  useEffect(() => {
    const handleLoginSuccess = () => {
      console.log("[EventSub] Login detected, checking if reconnect is needed");
      
      // If token was previously invalid, trigger reconnect
      if (status && status.token_valid === false) {
        console.log("[EventSub] Token was invalid, auto-reconnecting...");
        // Wait a moment for token to be saved
        setTimeout(handleReconnect, 1500);
      }
    };
    
    // Listen for login success events
    window.addEventListener('twitchLogin', handleLoginSuccess);
    
    // Cleanup listener on unmount or status change
    return () => {
      window.removeEventListener('twitchLogin', handleLoginSuccess);
    };
  }, [status]);

  /**
   * Manually trigger a reconnection to the EventSub service
   * 
   * @async
   * @returns {Promise<void>}
   */
  const handleReconnect = async () => {
    try {
      setIsReconnecting(true);
      
      // Call API to trigger reconnection
      const response = await fetch('/api/eventsub/reconnect', {
        method: 'POST'
      });
      
      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}`);
      }
      
      // Wait 3 seconds and then fetch the updated status
      setTimeout(fetchStatus, 3000);
    } catch (err) {
      console.error('Error reconnecting EventSub:', err);
      setError(`Failed to reconnect: ${err.message}`);
    } finally {
      setIsReconnecting(false);
    }
  };

  // Loading state - show spinner
  if (isLoading && !status) {
    return (
      <div className="bg-zinc-800 p-4 rounded-lg mb-4">
        <div className="flex items-center gap-2 text-gray-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span>Loading EventSub status...</span>
        </div>
      </div>
    );
  }

  // Error state - show error with retry button
  if (error && !status) {
    return (
      <div className="bg-zinc-800 p-4 rounded-lg mb-4">
        <div className="flex items-center gap-2 text-red-400">
          <AlertCircle className="w-5 h-5" />
          <span>Error loading EventSub status: {error}</span>
          <button 
            onClick={fetchStatus}
            className="ml-auto text-purple-400 hover:text-purple-300"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>
      </div>
    );
  }

  // No status data available
  if (!status) {
    return null;
  }

  // No authentication token available - show login prompt
  if (status.status === 'no_token') {
    return (
      <div className="bg-zinc-800 p-4 rounded-lg mb-4">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-white font-semibold">EventSub Status</h2>
        </div>
        
        <div className="flex flex-col items-center p-4 text-center">
          <AlertCircle className="w-8 h-8 text-yellow-400 mb-2" />
          <p className="text-white mb-4">Authentication required for EventSub monitoring</p>
          <p className="text-gray-400 text-sm">Log in with your Twitch account using the button at the top of the page to enable automatic stream detection</p>
        </div>
      </div>
    );
  }
  
  // Regular status display with connection information
  return (
    <div className="bg-zinc-800 p-4 rounded-lg mb-4">
      {/* Header with expansion toggle */}
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-white font-semibold flex items-center">
          EventSub Status
          {/* Show token expired badge if authentication is invalid */}
          {status.token_valid === false && (
            <span className="ml-2 px-2 py-0.5 bg-red-500 text-white text-xs rounded-full">
              Token Expired
            </span>
          )}
        </h2>
        {/* Expansion toggle button */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-gray-400 hover:text-white"
        >
          {expanded ? <ChevronUp className="w-5 h-5" /> : <ChevronDown className="w-5 h-5" />}
        </button>
      </div>
      
      {/* Connection status summary and actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {/* Status indicators with appropriate icons and colors */}
          {status.token_valid === false ? (
            <>
              <Clock className="w-5 h-5 text-red-400" />
              <span className="text-red-400">Authentication Expired</span>
            </>
          ) : status.status === 'active' ? (
            <>
              <CheckCircle className="w-5 h-5 text-green-400" />
              <span className="text-green-400">Connected</span>
            </>
          ) : (
            <>
              <AlertCircle className="w-5 h-5 text-yellow-400" />
              <span className="text-yellow-400">Disconnected</span>
            </>
          )}
        </div>
        
        {/* Reconnect button */}
        <button
          onClick={handleReconnect}
          disabled={isReconnecting || status.token_valid === false}
          className={`
            px-3 py-1 rounded bg-purple-500 hover:bg-purple-600 text-white
            flex items-center gap-1
            ${(isReconnecting || status.token_valid === false) ? 'opacity-70 cursor-not-allowed' : ''}
          `}
        >
          <RefreshCw className={`w-4 h-4 ${isReconnecting ? 'animate-spin' : ''}`} />
          {isReconnecting ? 'Reconnecting...' : 'Reconnect'}
        </button>
      </div>
      
      {/* Token expiration warning */}
      {status.token_valid === false && (
        <div className="bg-red-900 bg-opacity-20 rounded-md p-2 mt-2 text-red-400 flex items-center gap-2">
          <AlertCircle className="w-4 h-4" />
          <span>Authentication expired - Please use the Login button at the top of the page</span>
        </div>
      )}
      
      {/* Expanded details section */}
      {expanded && (
        <div className="mt-4 text-sm">
          {/* Status summary grid */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-gray-400 mb-1">Active Connections:</p>
              <p className="text-white">{status.active_connections}</p>
            </div>
            <div>
              <p className="text-gray-400 mb-1">Live Channels:</p>
              <p className="text-white">{status.live_channels}</p>
            </div>
            <div>
              <p className="text-gray-400 mb-1">Streamers Monitored:</p>
              <p className="text-white">{status.streamers_monitored}</p>
            </div>
            <div>
              <p className="text-gray-400 mb-1">Client ID:</p>
              <p className="text-white truncate">{status.client_id || 'Not available'}</p>
            </div>
          </div>
          
          {/* Live streamers list */}
          {status.live_streamers && status.live_streamers.length > 0 && (
            <div className="mt-4">
              <p className="text-gray-400 mb-1">Live Streamers:</p>
              <div className="flex flex-wrap gap-2">
                {status.live_streamers.map(streamer => (
                  <span key={streamer} className="px-2 py-1 bg-green-900 text-green-300 rounded-full text-xs">
                    {streamer}
                  </span>
                ))}
              </div>
            </div>
          )}
          
          {/* WebSocket connections list */}
          {status.connections && status.connections.length > 0 && (
            <div className="mt-4">
              <p className="text-gray-400 mb-1">WebSocket Connections:</p>
              <div className="flex flex-col gap-2">
                {status.connections.map(conn => (
                  <div key={conn.id} className="flex items-center gap-2">
                    {/* Connection status indicator */}
                    <div className={`w-2 h-2 rounded-full ${
                      conn.status === 'connected' ? 'bg-green-500' : 
                      conn.status === 'connecting' ? 'bg-yellow-500' :
                      'bg-red-500'
                    }`} />
                    <span>Connection {conn.id}: {conn.status}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          
          {/* Token error details */}
          {status.token_error && (
            <div className="mt-4 p-2 bg-red-900 bg-opacity-50 text-red-300 rounded">
              <p className="font-semibold">Token Error:</p>
              <p>{status.token_error}</p>
            </div>
          )}
          
          {/* Refresh button */}
          <div className="mt-4 flex justify-end">
            <button
              onClick={fetchStatus}
              className="text-purple-400 hover:text-purple-300 flex items-center gap-1"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default EventSubDebug;