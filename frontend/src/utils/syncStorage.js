/**
 * Storage Synchronization Module
 * 
 * This module enables synchronization of browser localStorage with the backend
 * via WebSocket. It serves as a persistence layer across browser sessions by:
 * 
 * 1. Overriding localStorage methods to detect changes
 * 2. Debouncing sync operations to minimize network traffic
 * 3. Tracking pending changes when WebSocket is disconnected
 * 4. Auto-syncing when connection is re-established
 * 
 * This implementation ensures user preferences and settings persist
 * across different devices and browser sessions.
 * 
 * @module utils/syncStorage
 */

// State tracking variables
let syncPending = false;     // Whether a sync operation is pending
let syncTimeout = null;      // Timeout ID for debounced sync
let webSocketInstance = null; // Reference to WebSocket service

// Configuration
const SYNC_DEBOUNCE_TIME = 1000; // Debounce time in milliseconds

/**
 * Synchronize all localStorage items to the backend via WebSocket
 * 
 * Collects all items from localStorage and sends them to the server
 * through the WebSocket connection. If the WebSocket is not connected,
 * marks the sync as pending for when connection is re-established.
 * 
 * @returns {boolean} Whether the sync attempt was successful
 */
const syncStorageWithBackend = () => {
  // Check if WebSocket is available and connected
  if (!webSocketInstance || !webSocketInstance.socket || 
      webSocketInstance.socket.readyState !== WebSocket.OPEN) {
    // WebSocket not ready, mark sync as pending for later
    syncPending = true;
    return false;
  }

  try {
    // Collect all localStorage items
    const storage = {};
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      storage[key] = localStorage.getItem(key);
    }

    // Send storage data through WebSocket
    webSocketInstance.sendMessage('storage_sync', { data: storage });
    
    // Reset pending flag after successful sync
    syncPending = false;
    return true;
  } catch (error) {
    console.error('[Storage] Error synchronizing storage:', error);
    // Mark as pending to retry later
    syncPending = true;
    return false;
  }
};

/**
 * Set up storage synchronization with the WebSocket service
 * 
 * Initializes the sync system by:
 * 1. Storing a reference to the WebSocket service
 * 2. Setting up connection status listeners
 * 3. Overriding localStorage methods to detect changes
 * 4. Triggering an initial sync
 * 
 * @param {Object} webSocketService - The WebSocket service instance
 */
export const setupStorageSync = (webSocketService) => {
  // Store reference to WebSocket service
  webSocketInstance = webSocketService;
  
  // Set up listener for WebSocket connection changes
  webSocketService.onConnectionStatusChange((isConnected) => {
    if (isConnected && syncPending) {
      // When connection is established and sync is pending, perform sync
      syncStorageWithBackend();
    }
  });

  // Override localStorage methods to track changes
  
  // Original method reference
  const originalSetItem = localStorage.setItem;
  // Override setItem to trigger sync after changes
  localStorage.setItem = function(key, value) {
    // Call original method
    originalSetItem.apply(this, arguments);
    // Schedule sync after change
    scheduleSync();
  };

  // Original method reference
  const originalRemoveItem = localStorage.removeItem;
  // Override removeItem to trigger sync after changes
  localStorage.removeItem = function(key) {
    // Call original method
    originalRemoveItem.apply(this, arguments);
    // Schedule sync after change
    scheduleSync();
  };

  // Original method reference
  const originalClear = localStorage.clear;
  // Override clear to trigger sync after changes
  localStorage.clear = function() {
    // Call original method
    originalClear.apply(this);
    // Schedule sync after change
    scheduleSync();
  };

  // Trigger initial sync
  scheduleSync();
};

/**
 * Schedule a debounced sync operation
 * 
 * Prevents excessive sync operations when multiple localStorage
 * changes occur in rapid succession by debouncing the sync.
 */
const scheduleSync = () => {
  // Clear existing timeout if one exists
  if (syncTimeout) {
    clearTimeout(syncTimeout);
  }
  
  // Set new timeout for delayed sync
  syncTimeout = setTimeout(() => {
    syncStorageWithBackend();
    syncTimeout = null;
  }, SYNC_DEBOUNCE_TIME);
};

/**
 * Manually trigger a storage sync
 * 
 * Forces an immediate synchronization of localStorage to the backend,
 * canceling any pending debounced sync operations.
 * 
 * @returns {boolean} Whether the sync attempt was successful
 */
export const forceSyncStorage = () => {
  // Clear any pending sync timeout
  if (syncTimeout) {
    clearTimeout(syncTimeout);
    syncTimeout = null;
  }
  // Perform immediate sync
  return syncStorageWithBackend();
};