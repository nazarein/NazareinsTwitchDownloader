/**
 * App.js - Main Application Component
 * 
 * This is the root component for the Twitch Downloader application.
 * It manages the overall application state, handles WebSocket connections,
 * and renders all subcomponents including streamer management, authentication,
 * and the console interface.
 * 
 * The application allows users to:
 * - Add/remove Twitch streamers to monitor
 * - View live status of streamers
 * - Configure download settings for each streamer
 * - Authenticate with Twitch for EventSub notifications
 * - Monitor application logs through a console interface
 * 
 * @module App
 */

import React, { useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { useAllStreamers } from './hooks/useAllStreamers';
import StreamerBar from './components/StreamerBar';
import ErrorBoundary from './components/ErrorBoundary';
import AuthManager from './components/AuthManager';
import Console from './components/Console';
import LoginBanners from './components/LoginBanners';
import { setupStorageSync } from './utils/syncStorage';
import webSocketService, { connectWebSocket, useWebSocketConnection } from './utils/websocket';

// Handle OAuth redirect for authentication flow
if (window.opener && window.location.hash) {
  const params = new URLSearchParams(window.location.hash.substring(1));
  window.opener.postMessage({
    access_token: params.get('access_token'),
    expires_in: params.get('expires_in')
  }, window.location.origin);
  window.close();
}

// Initialize WebSocket and storage sync on application load
connectWebSocket();
setupStorageSync(webSocketService);

/**
 * Header component displaying the application title and connection status
 * 
 * @param {Object} props - Component props
 * @param {boolean} props.isConnected - Whether the WebSocket is connected
 * @returns {JSX.Element} Header with title and connection indicator
 */
const Header = React.memo(({ isConnected }) => (
  <div className="flex justify-between items-center mb-4">
    <div className="flex items-center">
      <h1 className="text-white text-2xl font-bold">Nazareins Twitch Downloader</h1>
      <div 
        className={`ml-2 w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} 
        title={isConnected ? "Connected to server" : "Disconnected from server"}
      />
    </div>
    <AuthManager />
  </div>
));

/**
 * Input component for adding new streamers to monitor
 * 
 * @param {Object} props - Component props
 * @param {Function} props.onAdd - Callback function when a streamer is added
 * @returns {JSX.Element} Form for adding new streamers
 */
const AddStreamerBar = React.memo(({ onAdd }) => {
  // State for the streamer name input field
  const [streamerName, setStreamerName] = useState('');
  // Loading state during API calls
  const [isLoading, setIsLoading] = useState(false);
  // Error state for validation/API errors
  const [error, setError] = useState(null);

  /**
   * Handle form submission to add a new streamer
   * 
   * @param {Event} e - Form submit event
   */
  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmedName = streamerName.trim();
    if (!trimmedName) return;
    
    setIsLoading(true);
    setError(null);
    
    try {
      const result = await onAdd(trimmedName);
      if (result && result.success) {
        // Clear input field on success
        setStreamerName('');
      }
    } catch (err) {
      setError(err.message || 'Failed to add streamer. Please check the username and try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="mb-4">
      <form onSubmit={handleSubmit} className="flex justify-between items-center">
        <div className="flex-1">
          <input
            type="text"
            value={streamerName}
            onChange={(e) => {
              setStreamerName(e.target.value);
              // Clear error when user types
              if (error) setError(null);
            }}
            placeholder="Enter Twitch username"
            className={`w-full bg-zinc-800 text-white px-4 py-2 rounded-lg focus:outline-none focus:ring-2 ${error ? 'focus:ring-red-500 border border-red-500' : 'focus:ring-purple-500'}`}
            disabled={isLoading}
          />
        </div>
        <button
          type="submit"
          className={`ml-2 ${isLoading ? 'bg-purple-400' : 'bg-purple-500 hover:bg-purple-600'} text-white px-4 py-2 rounded-lg flex items-center gap-2 transition-colors`}
          disabled={isLoading || !streamerName.trim()}
        >
          {isLoading ? (
            <RefreshCw className="w-5 h-5 animate-spin" />
          ) : (
            <Plus className="w-5 h-5" />
          )}
          {isLoading ? 'Adding...' : 'Add Streamer'}
        </button>
      </form>
      {error && (
        <div className="mt-2 text-red-400 text-sm">
          {error}
        </div>
      )}
    </div>
  );
});

/**
 * Main application component
 * 
 * Manages global application state, renders all main UI components,
 * and coordinates interactions between components.
 * 
 * @returns {JSX.Element} The complete application UI
 */
const App = () => {
  // Track WebSocket connection state
  const [isConnected, setIsConnected] = useState(false);
  
  // Use custom hook to monitor WebSocket connection
  useWebSocketConnection(setIsConnected);
  
  // Retrieve and manage streamer data using custom hook
  const { 
    allStreamers,  // All streamer data with status
    loading,       // Loading state for initial data fetch
    error,         // Error state for streamer data operations
    updateSettings, // Function to update streamer settings
    addStreamer,    // Function to add a new streamer
    deleteStreamer  // Function to remove a streamer
  } = useAllStreamers();
  
  // Extract Twitch streamers from the data structure
  const streamers = allStreamers.twitch || {};
  
  /**
   * Handler to add a new streamer
   * 
   * @param {string} streamerName - Twitch username to add
   * @returns {Promise} Result of the add operation
   */
  const handleAddStreamer = (streamerName) => {
    return addStreamer('twitch', streamerName);
  };
  
  /**
   * Handler to remove a streamer
   * 
   * @param {string} streamerName - Twitch username to remove
   */
  const handleDeleteStreamer = (streamerName) => {
    deleteStreamer('twitch', streamerName);
  };
  
  /**
   * Handler to update streamer configuration
   * 
   * @param {string} streamerName - Twitch username to update
   * @param {Object} settings - New settings to apply
   */
  const handleUpdateSettings = (streamerName, settings) => {
    updateSettings('twitch', streamerName, settings);
  };
  
  return (
    <div className="min-h-screen bg-zinc-900 p-6 relative">
      {/* Console component for viewing application logs */}
      <Console initiallyExpanded={false} />
    
      <div className="console-collapsed">
        <div className="flex justify-center">
          <div className="w-full max-w-4xl">
            <div className="max-w-3xl mx-auto">
              {/* Header with app title and auth manager */}
              <Header isConnected={isConnected} />
              
              {/* Authentication requirement banners */}
              <LoginBanners />
              
              {/* Error boundary catches errors in child components */}
              <ErrorBoundary>
                {/* Input for adding new streamers */}
                <AddStreamerBar onAdd={handleAddStreamer} />
                
                {/* Global error display */}
                {error && (
                  <div className="bg-red-500 text-white p-4 rounded-lg mb-4">
                    {error}
                  </div>
                )}
                
                {/* Loading state */}
                {loading ? (
                  <div className="text-white text-center p-4">Loading streamers...</div>
                ) : Object.keys(streamers).length === 0 ? (
                  // Empty state when no streamers are added
                  <div className="text-gray-400 text-center p-4">
                    No streamers added yet. Add a streamer to get started!
                  </div>
                ) : (
                  // Render StreamerBar components for each streamer
                  Object.keys(streamers).map((streamerName) => {
                    const settings = streamers[streamerName] || {};
                    return (
                      <div key={streamerName} className="relative">
                        <StreamerBar
                          streamer={streamerName}
                          isOnline={settings.isLive || false}
                          thumbnail={settings.thumbnail}
                          offlineImageURL={settings.offlineImageURL}
                          profileImageURL={settings.profileImageURL}
                          title={settings.title || "Twitch Stream"}
                          downloads_enabled={settings.downloads_enabled || false}
                          downloadStatus={settings.downloadStatus}
                          stream_resolution={settings.stream_resolution || "best"} 
                          onDelete={() => handleDeleteStreamer(streamerName)}
                          onUpdateSettings={(settings) => handleUpdateSettings(streamerName, settings)}
                        />
                      </div>
                    );
                  })
                )}
              </ErrorBoundary>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;