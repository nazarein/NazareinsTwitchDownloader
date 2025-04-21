/**
 * Console Component
 * 
 * An expandable, real-time application console that displays log messages
 * streamed from the backend via WebSocket. The console features:
 * - Collapsible sidebar interface
 * - Live log streaming with auto-scroll
 * - Color-coded log levels
 * - Text filtering capability
 * - Log download and clearing functionality
 * - Connection status indicator
 * 
 * This component helps developers and advanced users troubleshoot the
 * application by providing visibility into server-side processes.
 * 
 * @module components/Console
 */

import React, { useState, useEffect, useRef } from 'react';
import { ChevronRight, ChevronLeft, Trash2, Download } from 'lucide-react';

/**
 * Console component for displaying real-time application logs
 * 
 * @param {Object} props - Component props
 * @param {boolean} props.initiallyExpanded - Whether console should be expanded on mount
 * @returns {JSX.Element} Console component
 */
const Console = ({ initiallyExpanded = false }) => {
  // State for UI and data
  const [isExpanded, setIsExpanded] = useState(initiallyExpanded); // Controls visibility
  const [logMessages, setLogMessages] = useState([]); // Stores log entries
  const [isConnected, setIsConnected] = useState(false); // WebSocket connection status
  const [filter, setFilter] = useState(''); // Text filter for logs
  
  // References
  const messagesEndRef = useRef(null); // For auto-scrolling
  const webSocketRef = useRef(null); // WebSocket connection reference

  /**
   * Establish and manage WebSocket connection for log streaming
   * Only connects when console is expanded to save resources
   */
  useEffect(() => {
    let ws = null;
    
    /**
     * Create or reuse WebSocket connection to backend
     * @returns {WebSocket} The active WebSocket connection
     */
    const connectWebSocket = () => {
      // Reuse existing global WebSocket if available
      if (window.consoleWebSocket && window.consoleWebSocket.readyState === WebSocket.OPEN) {
        console.log('Using existing console WebSocket connection');
        ws = window.consoleWebSocket;
        setIsConnected(true);
        return ws;
      }
      
      // Create new connection if needed
      ws = new WebSocket(`ws://${window.location.hostname}:8420/console`);
      window.consoleWebSocket = ws; // Store globally for reuse
      
      // Handle connection establishment
      ws.onopen = () => {
        console.log('Console WebSocket connected');
        setIsConnected(true);
      };
      
      // Process incoming log messages
      ws.onmessage = (event) => {
        try {
          // Attempt to parse as JSON (structured log)
          const data = JSON.parse(event.data);
          if (data.type === 'log') {
            setLogMessages(prev => [...prev, {
              timestamp: data.timestamp * 1000,  // Convert server timestamp (seconds) to JS milliseconds
              message: data.message,
              level: data.level || 'info',
              id: Date.now() + Math.random() // Unique ID for React keys
            }]);
          }
        } catch (error) {
          // Fall back to treating as plain text message
          setLogMessages(prev => [...prev, {
            timestamp: Date.now(),  // Use current time for non-JSON messages
            message: event.data,
            level: 'info',
            id: Date.now() + Math.random()
          }]);
        }
      };
      
      // Handle connection closure with automatic reconnection
      ws.onclose = () => {
        console.log('Console WebSocket disconnected, reconnecting...');
        setIsConnected(false);
        window.consoleWebSocket = null;
        setTimeout(connectWebSocket, 3000); // Retry after 3 seconds
      };
      
      // Handle connection errors
      ws.onerror = (error) => {
        console.error('Console WebSocket error:', error);
        setIsConnected(false);
      };
      
      // Store reference to WebSocket
      webSocketRef.current = ws;
      return ws;
    };
    
    // Only establish connection when console is expanded
    if (isExpanded) {
      ws = connectWebSocket();
    }
    
    // Cleanup function that preserves global WebSocket
    return () => {
      // Don't close global WebSocket on component unmount
      // Just remove the reference to avoid memory leaks
      webSocketRef.current = null;
    };
  }, [isExpanded]);

  /**
   * Handle auto-scrolling and layout adjustments when console state changes
   */
  useEffect(() => {
    // Auto-scroll to bottom when new messages arrive (if expanded)
    if (messagesEndRef.current && isExpanded) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
    
    // Adjust main content layout based on console expansion state
    const mainContent = document.querySelector('.max-w-4xl');
    if (mainContent) {
      if (isExpanded) {
        mainContent.classList.add('console-expanded');
        mainContent.classList.remove('console-collapsed');
      } else {
        mainContent.classList.add('console-collapsed');
        mainContent.classList.remove('console-expanded');
      }
    }
  }, [logMessages, isExpanded]);

  /**
   * Toggle console expansion state
   */
  const toggleConsole = () => {
    setIsExpanded(!isExpanded);
  };

  /**
   * Clear all log messages
   */
  const clearLogs = () => {
    setLogMessages([]);
  };

  /**
   * Download log messages as a text file
   * Formats logs with timestamps and levels, then triggers browser download
   */
  const downloadLogs = () => {
    // Format logs for text file
    const logContent = logMessages.map(log => 
      `[${log.timestamp}] [${log.level.toUpperCase()}] ${log.message}`
    ).join('\n');
    
    // Create downloadable blob and URL
    const blob = new Blob([logContent], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    
    // Create temporary anchor element to trigger download
    const a = document.createElement('a');
    a.href = url;
    a.download = `console-logs-${new Date().toISOString().replace(/:/g, '-')}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    
    // Clean up URL object to prevent memory leaks
    URL.revokeObjectURL(url);
  };

  // Apply text filtering to logs
  const filteredLogs = filter 
    ? logMessages.filter(log => 
        log.message.toLowerCase().includes(filter.toLowerCase()) ||
        log.level.toLowerCase().includes(filter.toLowerCase())
      )
    : logMessages;

  /**
   * Get text color class based on log level
   * 
   * @param {string} level - Log level (error, warning, success, debug, info)
   * @returns {string} Tailwind CSS color class
   */
  const getLevelColor = (level) => {
    switch(level.toLowerCase()) {
      case 'error': return 'text-red-500';
      case 'warning': case 'warn': return 'text-yellow-500';
      case 'success': return 'text-green-500';
      case 'debug': return 'text-purple-500';
      default: return 'text-gray-300';
    }
  };

  return (
    <div 
      className={`fixed right-0 ${isExpanded ? 'w-1/3' : 'w-0'} 
                 h-screen bg-zinc-900 transition-all duration-300 z-50 
                 shadow-lg flex flex-col border-l border-zinc-700`}
      style={{ top: 0 }}
    >
      {/* Toggle button outside console panel */}
      <button 
        onClick={toggleConsole}
        className="absolute -left-10 top-1/2 transform -translate-y-1/2 
                   bg-zinc-800 hover:bg-zinc-700 text-white p-2 
                   rounded-l-lg shadow-lg"
        title={isExpanded ? "Collapse Console" : "Expand Console"}
      >
        {isExpanded ? <ChevronRight /> : <ChevronLeft />}
      </button>

      {/* Expanded console content - only rendered when expanded */}
      {isExpanded && (
        <>
          {/* Console header with controls */}
          <div className="flex items-center justify-between p-3 border-b border-zinc-700 bg-zinc-800">
            <div className="flex items-center">
              <h3 className="text-white font-semibold">Console</h3>
              {/* Connection status indicator */}
              <div className={`ml-2 w-2 h-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`} 
                   title={isConnected ? "Connected" : "Disconnected"}></div>
            </div>
            {/* Action buttons */}
            <div className="flex space-x-2">
              <button 
                onClick={downloadLogs} 
                className="text-white hover:text-blue-400 transition"
                title="Download Logs"
              >
                <Download size={18} />
              </button>
              <button 
                onClick={clearLogs} 
                className="text-white hover:text-red-400 transition"
                title="Clear Console"
              >
                <Trash2 size={18} />
              </button>
            </div>
          </div>

          {/* Filter input */}
          <div className="p-2 bg-zinc-800 border-b border-zinc-700">
            <input
              type="text"
              placeholder="Filter logs..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="w-full bg-zinc-900 text-white px-3 py-1 rounded focus:outline-none focus:ring-1 focus:ring-purple-500"
            />
          </div>

          {/* Log messages container with scrolling */}
          <div className="flex-1 overflow-y-auto p-2 text-sm font-mono">
            {filteredLogs.length === 0 ? (
              // Empty state message
              <div className="text-gray-500 text-center mt-4">
                {filter ? "No matching logs found" : "No logs yet"}
              </div>
            ) : (
              // Map log entries to components
              filteredLogs.map((log) => (
                <div key={log.id} className="py-1 border-b border-zinc-800">
                  {/* Timestamp */}
                  <span className="text-xs text-gray-500">[{new Date(log.timestamp).toLocaleTimeString()}]</span>
                  {/* Message with level-based color */}
                  <span className={`ml-2 ${getLevelColor(log.level)}`}>{log.message}</span>
                </div>
              ))
            )}
            {/* Invisible element for auto-scrolling */}
            <div ref={messagesEndRef} />
          </div>

          {/* Status bar with message count */}
          <div className="p-2 border-t border-zinc-700 bg-zinc-800 text-xs text-gray-400">
            {filteredLogs.length} message{filteredLogs.length !== 1 ? 's' : ''}
            {filter && ` (filtered from ${logMessages.length})`}
          </div>
        </>
      )}
    </div>
  );
};

export default Console;