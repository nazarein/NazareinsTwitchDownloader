/**
 * Streamer Management Hook
 * 
 * This custom React hook manages the state and operations for all monitored Twitch
 * streamers. It provides functionality for:
 * - Loading and maintaining streamer data
 * - Handling real-time updates from WebSockets
 * - Managing streamer settings with optimistic updates
 * - Adding and removing streamers
 * - Batched API requests to prevent server overload
 * - Debounced settings updates to minimize API calls
 * 
 * This is a Twitch-only implementation that focuses on efficient state management
 * and responsive UI updates via WebSocket notifications.
 * 
 * @module hooks/useAllStreamers
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { 
  subscribeToWebSocketEvents,
  fetchStreamers,
  updateStreamers,
  getStreamerStatus,
  updateStreamerSettings,
  subscribeToThumbnailUpdates  
} from '../utils/api';

/**
 * Hook to manage all streamer data and operations
 * 
 * @returns {Object} An object containing:
 *   - allStreamers: Current state of all streamers with their settings and status
 *   - loading: Boolean indicating if data is currently loading
 *   - error: Error message if something went wrong, null otherwise
 *   - updateSettings: Function to update a streamer's settings
 *   - addStreamer: Function to add a new streamer to monitor
 *   - deleteStreamer: Function to remove a streamer from monitoring
 *   - refreshThumbnails: Function to manually refresh all streamer data
 */
export const useAllStreamers = () => {
  // Main state for all streamer data organized by platform (Twitch-only in this version)
  const [allStreamers, setAllStreamers] = useState({
    twitch: {}
  });
  
  // Simple list of streamer usernames for easier manipulation
  const [streamersList, setStreamersList] = useState({
    twitch: []
  });
  
  // UI state tracking
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Ref to track pending settings updates for debouncing
  const pendingUpdates = useRef({
    twitch: {}
  });
  
  // Ref for the debounce timeout
  const updateTimeoutRef = useRef(null);
  
  /**
   * Load all streamer data from the backend
   * 
   * This function:
   * 1. Fetches the list of monitored streamers
   * 2. Batches status requests to avoid overwhelming the server
   * 3. Merges all data into a unified state object
   * 
   * @returns {Promise<void>}
   */
  const loadAllStreamerData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      // Fetch list of streamer usernames
      const twitchStreamers = await fetchStreamers().catch(() => []);
      
      // Update the simple list of streamers
      setStreamersList({
        twitch: twitchStreamers
      });
      
      // Initialize state structure with empty objects for each streamer
      const initialState = {
        twitch: {}
      };
      
      // Create placeholder entries for each streamer
      twitchStreamers.forEach(streamer => {
        initialState.twitch[streamer] = {};
      });
      
      /**
       * Fetch detailed status for each streamer in batches
       * to avoid overwhelming the server with simultaneous requests
       * 
       * @returns {Promise<Object>} Object with streamer statuses by platform
       */
      const fetchStatusDirectly = async () => {
        const twitchStatuses = {};
        
        // Process streamers in small batches
        const batchSize = 5;
        
        // Process Twitch streamers in batches
        for (let i = 0; i < twitchStreamers.length; i += batchSize) {
          const batch = twitchStreamers.slice(i, i + batchSize);
          // Request status for all streamers in batch simultaneously
          const results = await Promise.all(
            batch.map(streamer => getStreamerStatus(streamer).catch(() => ({})))
          );
          // Store results by streamer name
          batch.forEach((streamer, idx) => {
            twitchStatuses[streamer] = results[idx];
          });
          // Add delay between batches to prevent server overload
          if (i + batchSize < twitchStreamers.length) {
            await new Promise(r => setTimeout(r, 500));
          }
        }
        
        return { twitch: twitchStatuses };
      };
      
      // Get current status for all streamers
      const allStatuses = await fetchStatusDirectly();
      
      // Create a new state object from initial structure
      const mergedState = {
        twitch: { ...initialState.twitch }
      };
      
      // Merge in status information for each streamer
      Object.entries(allStatuses.twitch).forEach(([streamer, status]) => {
        mergedState.twitch[streamer] = { ...status };
      });
      
      // Update state with complete data
      setAllStreamers(mergedState);
      
    } catch (err) {
      console.error('Error loading streamers:', err);
      setError('Failed to load streamer data');
    } finally {
      setLoading(false);
    }
  };
  
  /**
   * Handle thumbnail update events from WebSocket
   * 
   * Updates the thumbnail URL and title in state when new thumbnails
   * become available. Also adds cache-busting to prevent browser caching.
   * 
   * @param {string} streamer - Streamer username
   * @param {string} thumbnail - URL of the new thumbnail
   * @param {string} title - Optional new stream title
   */
  const handleThumbnailUpdate = useCallback((streamer, thumbnail, title) => {
    console.log(`[useAllStreamers] Received thumbnail update for ${streamer}: ${thumbnail}`);
    
    // Add timestamp to force browser to reload the image
    const cacheBustingTimestamp = Date.now();
    const thumbnailWithTimestamp = thumbnail.includes('?') 
      ? `${thumbnail}&_t=${cacheBustingTimestamp}` 
      : `${thumbnail}?_t=${cacheBustingTimestamp}`;
    
    setAllStreamers(prev => {
      // Skip update if streamer doesn't exist in state
      if (!prev.twitch[streamer]) return prev;
      
      // Create a deep clone to ensure React detects the change
      const newState = JSON.parse(JSON.stringify(prev));
      
      // Update thumbnail and title if provided
      newState.twitch[streamer].thumbnail = thumbnailWithTimestamp;
      if (title) {
        newState.twitch[streamer].title = title;
      }
      
      console.log(`[useAllStreamers] Updated state for ${streamer} with new thumbnail`);
      return newState;
    });
  }, []);
  
  // Set up WebSocket subscriptions and event listeners on mount
  useEffect(() => {
    // Initial data load
    loadAllStreamerData();
    
    // Subscribe to thumbnail update events
    const unsubscribeThumbnail = subscribeToThumbnailUpdates(handleThumbnailUpdate);
    
    /**
     * WebSocket event handler for other event types
     * 
     * @param {Object} data - WebSocket event data
     */
    const handleWebSocketEvent = (data) => {
      // Handle live status updates
      if (data.type === 'live_status') {
        const { streamer, isLive } = data;
        
        setAllStreamers(prev => {
          // Create a deep clone for the state update
          const newState = JSON.parse(JSON.stringify(prev));
          
          // Update the live status if streamer exists
          if (newState.twitch[streamer]) {
            newState.twitch[streamer].isLive = isLive;
          }
          
          return newState;
        });
      }
      
      // Handle download status updates
      if (data.type === 'download_status') {
        const { streamer, status } = data;
        
        setAllStreamers(prev => {
          // Create a deep clone for the state update
          const newState = JSON.parse(JSON.stringify(prev));
          
          // Update download status if streamer exists
          if (newState.twitch[streamer]) {
            newState.twitch[streamer].downloadStatus = status;
          }
          
          return newState;
        });
      }
    };
    
    // Subscribe to general WebSocket events
    const unsubscribeWebSocket = subscribeToWebSocketEvents(handleWebSocketEvent);
    
    /**
     * Handle download status events from DOM events
     * (Alternative notification channel for backward compatibility)
     * 
     * @param {CustomEvent} event - Download status event
     */
    const handleDownloadStatus = (event) => {
      const { streamer, status } = event.detail;
      if (!streamer) return;
      
      setAllStreamers(prev => {
        // Create a deep clone for the state update
        const newState = JSON.parse(JSON.stringify(prev));
        
        // Update download status if streamer exists
        if (newState.twitch[streamer]) {
          newState.twitch[streamer].downloadStatus = status;
        }
        
        return newState;
      });
    };
    
    // Listen for download status DOM events
    window.addEventListener('download_status_update', handleDownloadStatus);
    
    // Cleanup function to run on unmount
    return () => {
      // Unsubscribe from all event sources
      unsubscribeThumbnail();
      unsubscribeWebSocket();
      window.removeEventListener('download_status_update', handleDownloadStatus);
      
      // Clear any pending update timeouts
      if (updateTimeoutRef.current) {
        clearTimeout(updateTimeoutRef.current);
      }
    };
  }, [handleThumbnailUpdate]);
  
  /**
   * Update settings for a specific streamer
   * 
   * Implements optimistic updates (update UI immediately) with
   * debounced API calls to minimize server requests and improve UX.
   * 
   * @param {string} platform - Platform identifier (only 'twitch' supported)
   * @param {string} streamer - Streamer username
   * @param {Object} settings - New settings to apply
   */
  const updateSettings = useCallback((platform, streamer, settings) => {
    // Only handle Twitch platform in this version
    if (platform !== 'twitch') return;
    
    // Update local state immediately for responsive UI
    setAllStreamers(prev => {
      // Create a deep clone for the state update
      const newState = JSON.parse(JSON.stringify(prev));
      
      // Create streamer object if it doesn't exist
      if (!newState.twitch[streamer]) {
        newState.twitch[streamer] = {};
      }
      
      // Merge the new settings with existing ones
      newState.twitch[streamer] = {
        ...newState.twitch[streamer],
        ...settings
      };
      
      return newState;
    });
    
    // Queue the update to be sent to server
    pendingUpdates.current.twitch[streamer] = {
      ...(pendingUpdates.current.twitch[streamer] || {}),
      ...settings
    };
    
    // Clear existing timeout if present
    if (updateTimeoutRef.current) {
      clearTimeout(updateTimeoutRef.current);
    }
    
    // Create new timeout to send updates after debounce delay
    updateTimeoutRef.current = setTimeout(() => {
      /**
       * Send batched settings updates to the server
       */
      const updateSettingOnServer = async () => {
        try {
          const updates = pendingUpdates.current.twitch;
          
          // Process each streamer's updates
          for (const [streamer, settings] of Object.entries(updates)) {
            // Skip empty updates
            if (Object.keys(settings).length === 0) continue;
            await updateStreamerSettings(streamer, settings);
          }
          
          // Clear pending updates after successful update
          pendingUpdates.current = {
            twitch: {}
          };
        } catch (err) {
          console.error('Error updating settings:', err);
          setError('Failed to update settings');
        }
      };
      
      updateSettingOnServer();
    }, 300);  // 300ms debounce delay
  }, []);
  
  /**
   * Add a new streamer to monitor
   * 
   * Implements optimistic UI updates with error rollback if the
   * API call fails. Ensures the streamer exists before adding.
   * 
   * @param {string} platform - Platform identifier (only 'twitch' supported)
   * @param {string} streamerName - Streamer username to add
   * @returns {Promise<Object>} Result with success flag and optional error
   */
  const addStreamer = useCallback(async (platform, streamerName) => {
    // Only handle Twitch platform in this version
    if (platform !== 'twitch') return;
    
    try {
      // Update local state immediately for responsive UI
      setStreamersList(prev => ({
        twitch: [...prev.twitch, streamerName]
      }));
      
      // Add to all streamers with a temporary loading state
      setAllStreamers(prev => {
        const newState = JSON.parse(JSON.stringify(prev));
        newState.twitch[streamerName] = { isLoading: true };
        return newState;
      });
      
      // Send request to backend to add streamer
      const response = await updateStreamers([...streamersList.twitch, streamerName]);
      
      // Validate the response to ensure streamer was found
      if (response && response.initial_status) {
        const streamerStatus = response.initial_status[streamerName];
        
        // Check if a valid Twitch ID was found
        if (!streamerStatus || !streamerStatus.twitch_id) {
          throw new Error('Streamer not found. Please check the username and try again.');
        }
      }
      
      // Reload all data to get complete details for the new streamer
      await loadAllStreamerData();
      return { success: true };
    } catch (err) {
      console.error('Error adding streamer:', err);
      setError(err.message || 'Failed to add streamer');
      
      // Rollback local state updates on error
      setStreamersList(prev => ({
        twitch: prev.twitch.filter(s => s !== streamerName)
      }));
      
      // Remove from all streamers state
      setAllStreamers(prev => {
        const newState = JSON.parse(JSON.stringify(prev));
        if (newState.twitch[streamerName]) {
          delete newState.twitch[streamerName];
        }
        return newState;
      });
      
      return { 
        success: false, 
        error: err.message || 'Failed to add streamer' 
      };
    }
  }, [streamersList]);

  /**
   * Delete a streamer from monitoring
   * 
   * Optimistically removes the streamer from local state before
   * sending the API request for responsive UI updates.
   * 
   * @param {string} platform - Platform identifier (only 'twitch' supported)
   * @param {string} streamerName - Streamer username to remove
   */
  const deleteStreamer = useCallback(async (platform, streamerName) => {
    // Only handle Twitch platform in this version
    if (platform !== 'twitch') return;
    
    try {
      // Update local state immediately for responsive UI
      setStreamersList(prev => ({
        twitch: prev.twitch.filter(s => s !== streamerName)
      }));
      
      // Remove from all streamers state
      setAllStreamers(prev => {
        const newState = JSON.parse(JSON.stringify(prev));
        
        if (newState.twitch[streamerName]) {
          delete newState.twitch[streamerName];
        }
        
        return newState;
      });
      
      // Send updated list to server
      await updateStreamers(streamersList.twitch.filter(s => s !== streamerName));
    } catch (err) {
      console.error('Error deleting streamer:', err);
      setError('Failed to delete streamer');
      
      // Reload all data to recover from error
      loadAllStreamerData();
    }
  }, [streamersList]);
  
  /**
   * Manually refresh all streamer data
   * 
   * Useful for forcing an immediate update when automatic
   * updates might be delayed or not triggered.
   * 
   * @returns {Promise<void>}
   */
  const refreshThumbnails = useCallback(async () => {
    await loadAllStreamerData();
  }, []);
  
  // Return the hook interface
  return {
    allStreamers,    // Current state of all streamers
    loading,         // Whether streamers are currently loading
    error,           // Error message if something went wrong
    updateSettings,  // Function to update a streamer's settings
    addStreamer,     // Function to add a new streamer
    deleteStreamer,  // Function to remove a streamer
    refreshThumbnails // Function to manually refresh all streamer data
  };
};