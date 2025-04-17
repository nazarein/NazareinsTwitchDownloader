/**
 * API Service Module
 * 
 * Provides a unified interface for communicating with the backend server.
 * This module handles:
 * - REST API requests with error handling and request queuing
 * - WebSocket event subscriptions
 * - Concurrent request management
 * 
 * The module implements a request queue to prevent overwhelming the server
 * and to manage request concurrency effectively.
 * 
 * @module utils/api
 */

// Base URL for API endpoints derived from current hostname
const API_BASE_URL = `http://${window.location.hostname}:8420`;

// WebSocket connection and event subscription management
let websocket = null;
const statusSubscribers = new Set();           // Status update subscribers
const initialStateSubscribers = new Set();     // Initial state subscribers
const downloadStatusSubscribers = new Set();   // Download status subscribers
const liveStatusSubscribers = new Set();       // Live status subscribers
const thumbnailUpdateSubscribers = new Set();  // Thumbnail update subscribers

/**
 * Establish a WebSocket connection if one doesn't exist
 * 
 * @returns {void}
 */
const connectWebSocket = () => {
  if (websocket) return;
  
  // Create new WebSocket connection
  websocket = new WebSocket(`ws://${window.location.hostname}:8420/ws`);
  
  // Handle incoming messages
  websocket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('WebSocket message received:', data.type);
    
    // Route messages to appropriate subscribers based on type
    if (data.type === 'status_update') {
      statusSubscribers.forEach(callback => callback(data.streamer, data.status));
    }
    else if (data.type === 'download_status') {
      console.log('Download status update:', data);
      downloadStatusSubscribers.forEach(callback => 
        callback(data.streamer, data.status));
    }
    else if (data.type === 'live_status') {
      console.log('Live status update:', data);
      liveStatusSubscribers.forEach(callback => 
        callback(data.streamer, data.isLive));
    }
    else if (data.type === 'thumbnail_update') {
      console.log('Thumbnail update:', data);
      thumbnailUpdateSubscribers.forEach(callback => 
        callback(data.streamer, data.thumbnail, data.title));
    }
    else if (data.type === 'initial_state') {
      console.log('Received initial state:', data.data);
      initialStateSubscribers.forEach(callback => callback(data.data));
    }
  };

  // Handle connection establishment
  websocket.onopen = () => {
    console.log('WebSocket connection established');
    // Request initial state when connection opens
    requestInitialState();
  };

  // Handle connection closure with automatic reconnection
  websocket.onclose = () => {
    console.log('WebSocket connection closed');
    websocket = null;
    // Try to reconnect after 5 seconds
    setTimeout(connectWebSocket, 5000);
  };

  // Handle connection errors
  websocket.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
};

/**
 * Request initial application state from the server
 * 
 * @returns {void}
 */
const requestInitialState = () => {
  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send(JSON.stringify({
      type: 'request_initial_state'
    }));
  }
};

/**
 * Subscribe to general streamer status updates
 * 
 * @param {Function} callback - Function called with (streamer, status) on updates
 * @returns {Function} Unsubscribe function
 */
export const subscribeToStatusUpdates = (callback) => {
  statusSubscribers.add(callback);
  if (!websocket) connectWebSocket();
  return () => statusSubscribers.delete(callback);
};

/**
 * Subscribe to application initial state updates
 * 
 * @param {Function} callback - Function called with initial state data
 * @returns {Function} Unsubscribe function
 */
export const subscribeToInitialState = (callback) => {
  initialStateSubscribers.add(callback);
  if (!websocket) connectWebSocket();
  else if (websocket.readyState === WebSocket.OPEN) {
    requestInitialState(); // Request state immediately if connected
  }
  return () => initialStateSubscribers.delete(callback);
};

/**
 * Subscribe to download status updates
 * 
 * @param {Function} callback - Function called with (streamer, status) on updates
 * @returns {Function} Unsubscribe function
 */
export const subscribeToDownloadStatus = (callback) => {
  downloadStatusSubscribers.add(callback);
  if (!websocket) connectWebSocket();
  return () => downloadStatusSubscribers.delete(callback);
};

/**
 * Subscribe to streamer live status updates
 * 
 * @param {Function} callback - Function called with (streamer, isLive) on updates
 * @returns {Function} Unsubscribe function
 */
export const subscribeToLiveStatus = (callback) => {
  liveStatusSubscribers.add(callback);
  if (!websocket) connectWebSocket();
  return () => liveStatusSubscribers.delete(callback);
};

/**
 * Subscribe to streamer thumbnail updates
 * 
 * @param {Function} callback - Function called with (streamer, thumbnail, title) on updates
 * @returns {Function} Unsubscribe function
 */
export const subscribeToThumbnailUpdates = (callback) => {
  thumbnailUpdateSubscribers.add(callback);
  if (!websocket) connectWebSocket();
  return () => thumbnailUpdateSubscribers.delete(callback);
};

/**
 * Request Queue class for managing concurrent API requests
 * 
 * This class:
 * - Prevents duplicate requests for the same resource
 * - Limits concurrent API requests to prevent overwhelming the server
 * - Provides proper error handling and request tracking
 */
class RequestQueue {
  /**
   * Create a new request queue with concurrency control
   * 
   * @param {number} concurrency - Maximum number of concurrent requests
   */
  constructor(concurrency = 3) {
    this.queue = new Map();           // Queued requests
    this.inProgress = new Map();      // In-progress requests
    this.concurrency = concurrency;   // Maximum concurrent requests
  }

  /**
   * Enqueue a request to be executed when concurrency allows
   * 
   * @param {string} key - Unique identifier for this request type
   * @param {Function} requestFn - Async function that performs the actual request
   * @returns {Promise<any>} Result of the request
   */
  async enqueue(key, requestFn) {
    // If request is already in progress, return existing promise
    if (this.inProgress.has(key)) {
      return this.inProgress.get(key);
    }

    // Create the promise before using it
    let promiseResolve, promiseReject;
    const promise = new Promise((resolve, reject) => {
      promiseResolve = resolve;
      promiseReject = reject;
    });

    // Store the promise immediately
    this.inProgress.set(key, promise);

    // Execute the request
    try {
      // Wait if we're at concurrency limit
      while (this.inProgress.size > this.concurrency) {
        await Promise.race([...this.inProgress.values()]);
      }

      // Perform the actual request
      const result = await requestFn();
      promiseResolve(result);
      return result;
    } catch (error) {
      promiseReject(error);
      throw error;
    } finally {
      // Remove from in-progress tracking regardless of outcome
      this.inProgress.delete(key);
    }
  }
}

// Create a request queue instance with default concurrency
const requestQueue = new RequestQueue();

/**
 * Utility function to handle API errors consistently
 * 
 * @param {Response} response - Fetch API response object
 * @returns {Promise<any>} Parsed JSON response if successful
 * @throws {Error} With descriptive message if request failed
 */
const handleApiError = async (response) => {
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`API Error: ${errorText}`);
  }
  return response.json();
};

/**
 * Fetch the list of monitored streamers
 * 
 * @returns {Promise<Array<string>>} Array of streamer usernames
 */
export const fetchStreamers = async () => {
  return requestQueue.enqueue('streamers-list', async () => {
    try {
      console.log('Fetching streamers from:', `${API_BASE_URL}/api/streamers`);
      const response = await fetch(`${API_BASE_URL}/api/streamers`);
      console.log('Response status:', response.status);
      const data = await handleApiError(response);
      console.log('Response data:', data);
      
      // Validate response format
      if (!Array.isArray(data)) {
        console.error('Invalid response format:', data);
        throw new Error('Invalid response format: expected array');
      }
      return data;
    } catch (error) {
      console.error('Detailed error fetching streamers:', {
        message: error.message,
        stack: error.stack
      });
      throw error; // Let the hook handle the error
    }
  });
};

/**
 * Get status information for a specific streamer
 * 
 * @param {string} streamer - Twitch username of the streamer
 * @param {AbortSignal} signal - Optional abort signal for cancellation
 * @returns {Promise<Object>} Streamer status details
 */
export const getStreamerStatus = async (streamer, signal) => {
  return requestQueue.enqueue(`status-${streamer}`, async () => {
    const response = await fetch(
      `${API_BASE_URL}/api/streamers/${streamer}/status`,
      { signal }
    );
    return handleApiError(response);
  });
};

/**
 * Update settings for a specific streamer
 * 
 * @param {string} streamer - Twitch username of the streamer
 * @param {Object} settings - New settings to apply
 * @returns {Promise<Object>} API response
 */
export const updateStreamerSettings = async (streamer, settings) => {
  return requestQueue.enqueue(
    `settings-${streamer}`,
    async () => {
      const response = await fetch(
        `${API_BASE_URL}/api/streamers/${streamer}/settings`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(settings),
        }
      );
      return handleApiError(response);
    }
  );
};

/**
 * Update the list of monitored streamers
 * 
 * @param {Array<string>} streamers - Array of Twitch usernames to monitor
 * @returns {Promise<Object>} API response
 */
export const updateStreamers = async (streamers) => {
  return requestQueue.enqueue('update-streamers', async () => {
    const response = await fetch(`${API_BASE_URL}/api/streamers`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(streamers),
    });
    return handleApiError(response);
  });
};

/**
 * Subscribe to WebSocket events via the window event system
 * 
 * @param {Function} callback - Function to call when events are received
 * @returns {Function} Unsubscribe function
 */
export const subscribeToWebSocketEvents = (callback) => {
  const handleMessage = (event) => {
    if (event.detail && event.detail.data) {
      callback(event.detail.data);
    }
  };
  
  window.addEventListener('websocket_message', handleMessage);
  
  // Return unsubscribe function
  return () => {
    window.removeEventListener('websocket_message', handleMessage);
  };
};

/**
 * Get all streamer settings (Twitch-only version)
 * 
 * @returns {Promise<Object>} Settings object with streamer data
 */
export const getAllSettings = async () => {
  console.warn('getAllSettings called in Twitch-only version');
  const streamers = await fetchStreamers().catch(() => []);
  const result = { twitch: {} };
  
  // Initialize empty settings for each streamer
  for (const streamer of streamers) {
    result.twitch[streamer] = {};
  }
  
  return result;
};

/**
 * Update settings for multiple streamers in bulk (Twitch-only version)
 * 
 * @param {Object} settings - Object containing settings for multiple streamers
 * @returns {Promise<Object>} API response
 */
export const updateBulkSettings = async (settings) => {
  console.warn('updateBulkSettings called in Twitch-only version');
  
  // Process each streamer's settings individually
  if (settings.twitch) {
    for (const [streamer, streamerSettings] of Object.entries(settings.twitch)) {
      await updateStreamerSettings(streamer, streamerSettings);
    }
  }
  
  return { status: 'ok' };
};