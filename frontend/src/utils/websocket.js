/**
 * WebSocket Service Module
 *
 * Provides a singleton WebSocket client that handles real-time communication 
 * with the backend server. This service implements:
 * - Connection management with automatic reconnection
 * - Message type registration and event dispatching
 * - Exponential backoff retry strategy
 * - Custom event subscription system
 * 
 * The singleton pattern ensures only one WebSocket connection is maintained
 * throughout the application, preventing resource waste and potential race conditions.
 *
 * @module utils/websocket
 */

import React from 'react';

// Configuration constants
const WS_URL = `ws://${window.location.hostname}:8420/ws`;
const RECONNECT_INTERVAL_BASE = 1000;  // Base delay in ms before reconnecting
const RECONNECT_INTERVAL_MAX = 30000;  // Maximum reconnection delay (30 seconds)
const MAX_RECONNECT_ATTEMPTS = 20;     // Maximum number of reconnection attempts

// Global connection state tracking
let globalWebSocketInstance = null;     // Singleton instance reference
let connectionInProgress = false;       // Flag to prevent simultaneous connection attempts
let initialStateRequested = false;      // Flag to track if initial state was requested

/**
 * WebSocketService class manages the WebSocket connection and message handling
 */
class WebSocketService {
  /**
   * Creates a new WebSocketService instance or returns the existing singleton
   */
  constructor() {
    // Implement singleton pattern - return existing instance if available
    if (globalWebSocketInstance) {
      console.log('[WebSocket] Returning existing singleton instance');
      return globalWebSocketInstance;
    }
    
    // Initialize instance properties
    this.socket = null;                    // WebSocket connection
    this.reconnectAttempts = 0;            // Current number of reconnection attempts
    this.reconnectTimeout = null;          // Timer for scheduled reconnections
    this.messageHandlers = new Map();      // Map of message types to handler functions
    this.connectionStatusListeners = new Set(); // Listeners for connection status changes
    
    // Register default message handlers
    this.registerMessageType('live_status', this._handleLiveStatus.bind(this));
    this.registerMessageType('download_status', this._handleDownloadStatus.bind(this));
    this.registerMessageType('thumbnail_update', this._handleThumbnailUpdate.bind(this));
    this.registerMessageType('initial_state', this._handleInitialState.bind(this));
    this.registerMessageType('status_update', this._handleStatusUpdate.bind(this));
    
    // Store singleton instance for future references
    globalWebSocketInstance = this;
    console.log('[WebSocket] Created new WebSocket service instance');
  }

  /**
   * Establish a WebSocket connection to the server
   * @returns {void}
   */
  connect() {
    // Prevent multiple simultaneous connection attempts
    if (connectionInProgress) {
      console.log('[WebSocket] Connection already in progress, skipping');
      return;
    }
    
    // Skip if already connected
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      console.log('[WebSocket] Already connected, skipping');
      return;
    }
    
    connectionInProgress = true;
    console.log('[WebSocket] Connecting to WebSocket server...');
    
    try {
      // Create a new WebSocket connection
      this.socket = new WebSocket(WS_URL);
      
      // Set up event handlers
      this.socket.onopen = this._handleOpen.bind(this);
      this.socket.onclose = this._handleClose.bind(this);
      this.socket.onmessage = this._handleMessage.bind(this);
      this.socket.onerror = this._handleError.bind(this);
    } catch (error) {
      console.error('[WebSocket] Error creating connection:', error);
      this._scheduleReconnect();
      connectionInProgress = false;
    }
  }

  /**
   * Close the WebSocket connection and clean up resources
   * @returns {void}
   */
  disconnect() {
    console.log('[WebSocket] Disconnecting WebSocket');
    
    // Clear any pending reconnect timers
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    
    // Clean up and close the socket if it exists
    if (this.socket) {
      // Remove event handlers to prevent memory leaks
      this.socket.onopen = null;
      this.socket.onclose = null;
      this.socket.onmessage = null;
      this.socket.onerror = null;
      
      // Close the connection if it's open or connecting
      if (this.socket.readyState === WebSocket.OPEN || 
          this.socket.readyState === WebSocket.CONNECTING) {
        this.socket.close();
      }
      
      this.socket = null;
    }
    
    // Notify listeners about disconnection
    this._notifyConnectionStatusChange(false);
    connectionInProgress = false;
  }

  /**
   * Send a message through the WebSocket connection
   * 
   * @param {string} type - The message type identifier
   * @param {Object} data - Additional data to include in the message
   * @returns {boolean} Whether the message was successfully sent
   */
  sendMessage(type, data = {}) {
    // Verify connection is available
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      console.warn('[WebSocket] Cannot send message, socket not connected');
      return false;
    }
    
    try {
      // Construct and send the message
      const message = JSON.stringify({
        type,
        ...data
      });
      this.socket.send(message);
      return true;
    } catch (error) {
      console.error('[WebSocket] Error sending message:', error);
      return false;
    }
  }

  /**
   * Request initial state from the server
   * This should be called once after connection is established
   * 
   * @returns {boolean} Whether the request was sent successfully
   */
  requestInitialState() {
    // Skip if already requested to prevent duplicate state
    if (initialStateRequested) {
      console.log('[WebSocket] Initial state already requested, skipping');
      return false;
    }
    
    // Verify connection is available
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      console.warn('[WebSocket] Cannot request initial state, socket not connected');
      return false;
    }
    
    try {
      console.log('[WebSocket] Requesting initial state...');
      this.sendMessage('request_initial_state');
      
      // Set flag to prevent duplicate requests
      initialStateRequested = true;
      
      return true;
    } catch (error) {
      console.error('[WebSocket] Error requesting initial state:', error);
      return false;
    }
  }

  /**
   * Register a handler for a specific message type
   * 
   * @param {string} type - The message type to handle
   * @param {Function} handler - Callback function when message is received
   * @returns {Function} Unsubscribe function to remove the handler
   */
  registerMessageType(type, handler) {
    // Create handler set if it doesn't exist
    if (!this.messageHandlers.has(type)) {
      this.messageHandlers.set(type, new Set());
    }
    
    // Add the handler to the set
    this.messageHandlers.get(type).add(handler);
    
    // Return unsubscribe function
    return () => this.unregisterMessageType(type, handler);
  }

  /**
   * Unregister a handler for a specific message type
   * 
   * @param {string} type - The message type to unregister
   * @param {Function} handler - The handler function to remove
   */
  unregisterMessageType(type, handler) {
    if (this.messageHandlers.has(type)) {
      this.messageHandlers.get(type).delete(handler);
    }
  }

  /**
   * Register a listener for connection status changes
   * 
   * @param {Function} listener - Callback function with isConnected parameter
   * @returns {Function} Unsubscribe function to remove the listener
   */
  onConnectionStatusChange(listener) {
    // Add the listener
    this.connectionStatusListeners.add(listener);
    
    // Immediately notify with current status
    if (this.socket) {
      listener(this.socket.readyState === WebSocket.OPEN);
    } else {
      listener(false);
    }
    
    // Return unsubscribe function
    return () => this.connectionStatusListeners.delete(listener);
  }

  /**
   * Register a handler for live status updates
   * 
   * @param {Function} handler - Callback for live status events
   * @returns {Function} Unsubscribe function
   */
  onLiveStatusUpdate(handler) {
    return this.registerMessageType('live_status', handler);
  }

  /**
   * Register a handler for download status updates
   * 
   * @param {Function} handler - Callback for download status events
   * @returns {Function} Unsubscribe function
   */
  onDownloadStatusUpdate(handler) {
    return this.registerMessageType('download_status', handler);
  }

  /**
   * Register a handler for thumbnail updates
   * 
   * @param {Function} handler - Callback for thumbnail update events
   * @returns {Function} Unsubscribe function
   */
  onThumbnailUpdate(handler) {
    return this.registerMessageType('thumbnail_update', handler);
  }

  /**
   * Register a handler for initial state data
   * 
   * @param {Function} handler - Callback for initial state events
   * @returns {Function} Unsubscribe function
   */
  onInitialState(handler) {
    return this.registerMessageType('initial_state', handler);
  }

  /**
   * Register a handler for streamer status updates
   * 
   * @param {Function} handler - Callback for status update events
   * @returns {Function} Unsubscribe function
   */
  onStatusUpdate(handler) {
    return this.registerMessageType('status_update', handler);
  }

  /**
   * Handle WebSocket open event
   * @private
   */
  _handleOpen(event) {
    console.log('[WebSocket] Connected successfully');
    
    // Reset reconnection attempts on successful connection
    this.reconnectAttempts = 0;
    
    // Notify listeners about connection
    this._notifyConnectionStatusChange(true);
    connectionInProgress = false;
    
    // Request initial application state
    this.requestInitialState();
  }

  /**
   * Handle WebSocket close event
   * @private
   */
  _handleClose(event) {
    console.warn(`[WebSocket] Disconnected (code: ${event.code}, reason: ${event.reason || 'No reason provided'})`);
    
    // Notify listeners about disconnection
    this._notifyConnectionStatusChange(false);
    connectionInProgress = false;
    
    // Reset state request flag to ensure we request again on reconnection
    initialStateRequested = false;
    
    // Schedule reconnection attempt
    this._scheduleReconnect();
  }

  /**
   * Handle WebSocket error event
   * @private
   */
  _handleError(event) {
    console.error('[WebSocket] Error:', event);
    connectionInProgress = false;
  }

  /**
   * Process incoming WebSocket messages
   * @private
   */
  _handleMessage(event) {
    try {
      // Parse the message data
      const data = JSON.parse(event.data);
      const messageType = data.type;
      
      // Validate message has a type
      if (!messageType) {
        console.warn('[WebSocket] Received message without type:', data);
        return;
      }

      // Special logging for initial state messages
      if (messageType === 'initial_state') {
        console.log(`[WebSocket] Received initial state with ${Object.keys(data.data?.twitch || {}).length} streamers`);
      }

      // Process message with registered handlers
      if (this.messageHandlers.has(messageType)) {
        this.messageHandlers.get(messageType).forEach(handler => {
          try {
            handler(data);
          } catch (error) {
            console.error(`[WebSocket] Error in handler for "${messageType}":`, error);
          }
        });
      }
      
      // Dispatch as custom event for backward compatibility
      window.dispatchEvent(new CustomEvent('websocket_message', {
        detail: { data }
      }));
    } catch (error) {
      console.error('[WebSocket] Error parsing message:', error);
    }
  }

  /**
   * Handle live status update messages
   * @private
   */
  _handleLiveStatus(data) {
    console.log(`[WebSocket] ${data.streamer} is ${data.isLive ? 'LIVE' : 'OFFLINE'}`);
    
    // Dispatch global event for components to listen
    window.dispatchEvent(new CustomEvent('live_status_update', {
      detail: {
        streamer: data.streamer,
        isLive: data.isLive
      }
    }));
  }

  /**
   * Handle download status update messages
   * @private
   */
  _handleDownloadStatus(data) {
    console.log(`[WebSocket] Download status for ${data.streamer}: ${data.status}`);
    
    // Dispatch global event for components to listen
    window.dispatchEvent(new CustomEvent('download_status_update', {
      detail: {
        streamer: data.streamer,
        status: data.status
      }
    }));
  }

  /**
   * Handle thumbnail update messages
   * @private
   */
  _handleThumbnailUpdate(data) {
    console.log(`[WebSocket] Thumbnail update for ${data.streamer}`);
    
    // Dispatch global event for components to listen
    window.dispatchEvent(new CustomEvent('thumbnail_update', {
      detail: {
        streamer: data.streamer,
        thumbnail: data.thumbnail,
        title: data.title
      }
    }));
  }

  /**
   * Handle initial state messages
   * @private
   */
  _handleInitialState(data) {
    // Nothing additional needed here - handlers are called by _handleMessage
  }

  /**
   * Handle status update messages
   * @private
   */
  _handleStatusUpdate(data) {
    console.log(`[WebSocket] Status update for ${data.streamer} (${data.platform})`);
  }

  /**
   * Schedule WebSocket reconnection with exponential backoff
   * @private
   */
  _scheduleReconnect() {
    // Clear any existing reconnection timer
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }
    
    // Give up after maximum attempts
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error(`[WebSocket] Failed to reconnect after ${this.reconnectAttempts} attempts. Giving up.`);
      return;
    }
    
    // Calculate delay with exponential backoff and jitter
    // Jitter helps prevent all clients from reconnecting simultaneously
    const delay = Math.min(
      RECONNECT_INTERVAL_BASE * Math.pow(1.5, this.reconnectAttempts) * (0.9 + Math.random() * 0.2),
      RECONNECT_INTERVAL_MAX
    );
    
    this.reconnectAttempts++;
    console.log(`[WebSocket] Scheduling reconnect attempt ${this.reconnectAttempts} in ${Math.round(delay / 1000)}s`);
    
    // Schedule reconnection attempt
    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, delay);
  }

  /**
   * Notify all registered listeners about connection status changes
   * @private
   * 
   * @param {boolean} isConnected - Whether the WebSocket is now connected
   */
  _notifyConnectionStatusChange(isConnected) {
    this.connectionStatusListeners.forEach(listener => {
      try {
        listener(isConnected);
      } catch (error) {
        console.error('[WebSocket] Error in connection status listener:', error);
      }
    });
  }
}

// Create and export singleton instance
const webSocketService = new WebSocketService();

/**
 * Connect to the WebSocket server
 * Convenience function to access the singleton
 * 
 * @returns {void}
 */
export const connectWebSocket = () => {
  console.log('[WebSocket] Connect called through convenience function');
  return webSocketService.connect();
};

/**
 * Disconnect from the WebSocket server
 * Convenience function to access the singleton
 * 
 * @returns {void}
 */
export const disconnectWebSocket = () => webSocketService.disconnect();

/**
 * Send a message through the WebSocket
 * Convenience function to access the singleton
 * 
 * @param {string} type - The message type
 * @param {Object} data - The message data
 * @returns {boolean} Whether the message was sent successfully
 */
export const sendWebSocketMessage = (type, data) => webSocketService.sendMessage(type, data);

/**
 * React hook to manage WebSocket connection
 * Ensures the WebSocket is connected and handles cleanup
 * 
 * @param {Function} onStatusChange - Optional callback for connection status changes
 * @returns {WebSocketService} The WebSocket service instance
 */
export const useWebSocketConnection = (onStatusChange) => {
  React.useEffect(() => {
    console.log('[WebSocket] useWebSocketConnection hook called');
    
    // Ensure connection is established
    connectWebSocket();
    
    // Register status change listener if provided
    const unsubscribe = onStatusChange ? 
      webSocketService.onConnectionStatusChange(onStatusChange) : 
      () => {};
      
    // Cleanup on component unmount
    return () => {
      unsubscribe();
    };
  }, [onStatusChange]);
  
  return webSocketService;
};

export default webSocketService;