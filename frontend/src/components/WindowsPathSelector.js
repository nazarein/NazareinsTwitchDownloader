/**
 * Windows Path Selector Component
 * 
 * A specialized file system navigator for Windows environments that allows users
 * to browse and select directories through a familiar interface. Features include:
 * - Drive letter navigation
 * - Network path support
 * - Breadcrumb-style path display
 * - Browsing history with back navigation
 * - Shortcuts to common locations
 * - Directory contents preview
 * 
 * This component provides Windows-specific path handling logic including proper
 * backslash separators and drive letter recognition.
 * 
 * @module components/WindowsPathSelector
 */

import React, { useState, useEffect } from 'react';
import { ChevronRight, FolderOpen, Home, ArrowLeft, HardDrive, Network } from 'lucide-react';

/**
 * Windows-specific directory selection dialog
 * 
 * @param {Object} props - Component props
 * @param {Function} props.onSelect - Callback when a directory is selected, receives path string
 * @param {Function} props.onCancel - Callback when selection is cancelled
 * @param {string} props.initialPath - Initial directory path to display
 * @returns {JSX.Element} Windows path selector dialog
 */
const WindowsPathSelector = ({ onSelect, onCancel, initialPath = '' }) => {
  // Path state management
  const [currentPath, setCurrentPath] = useState(initialPath); // Current directory path
  const [contents, setContents] = useState({ dirs: [], error: null }); // Directory contents
  const [isLoading, setIsLoading] = useState(true); // Loading state for directory fetch
  const [pathHistory, setPathHistory] = useState([initialPath]); // Navigation history

  /**
   * Fetch directory contents when path changes
   */
  useEffect(() => {
    fetchDirectoryContents(currentPath);
  }, [currentPath]);

  /**
   * Fetch available directories at the current path
   * 
   * @param {string} path - Directory path to fetch contents for
   * @returns {Promise<void>}
   */
  const fetchDirectoryContents = async (path) => {
    setIsLoading(true);
    try {
      // Special case: empty path means list drives
      const response = await fetch('/api/available-paths', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: path || '/' }) // '/' is special token for root/drives
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      console.log('Directory response:', data); // Debug log

      // Handle error or set directory contents
      if (data.error) {
        setContents({ dirs: [], error: data.error });
      } else {
        setContents({ 
          dirs: data.dirs || [], 
          error: null,
          current_path: data.current_path
        });
      }
    } catch (error) {
      console.error('Error fetching directories:', error);
      setContents({ dirs: [], error: 'Failed to fetch directory contents' });
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Check if path is a Windows drive letter (e.g., "C:\")
   * 
   * @param {string} path - Path to check
   * @returns {boolean} True if path is a drive letter
   */
  const isDriveLetter = (path) => /^[A-Z]:\\$/.test(path);
  
  /**
   * Check if path is a Windows network path (e.g., "\\server\share")
   * 
   * @param {string} path - Path to check
   * @returns {boolean} True if path is a network path
   */
  const isNetworkPath = (path) => path.startsWith('\\\\');

  /**
   * Navigate to a new directory or location
   * 
   * Handles special cases like:
   * - Network paths
   * - Root/drive listing
   * - Drive letters
   * - Parent directory
   * - Regular subdirectories
   * 
   * @param {string} dir - Directory name or special navigation token
   */
  const navigateToDirectory = (dir) => {
    // Special case for network paths
    if (dir.startsWith('\\\\')) {
      setCurrentPath(dir);
      setPathHistory([...pathHistory, dir]);
      return;
    }

    // For root directory (drive selection)
    if (dir === '/') {
      setCurrentPath('');
      setPathHistory([...pathHistory, '']);
      return;
    }

    // For drive letters
    if (isDriveLetter(dir)) {
      setCurrentPath(dir);
      setPathHistory([...pathHistory, dir]);
      return;
    }

    // For going up a directory
    if (dir === '..') {
      const parentPath = currentPath.split('\\').slice(0, -1).join('\\');
      // If we're at a drive root, go to drive selection
      if (isDriveLetter(currentPath)) {
        setCurrentPath('');
        setPathHistory([...pathHistory, '']);
      } else {
        setCurrentPath(parentPath || '');
        setPathHistory([...pathHistory, parentPath]);
      }
      return;
    }

    // Normal directory navigation - append to current path
    const newPath = currentPath
      ? `${currentPath}${currentPath.endsWith('\\') ? '' : '\\'}${dir}`
      : dir;

    setCurrentPath(newPath);
    setPathHistory([...pathHistory, newPath]);
  };

  /**
   * Go back to previous directory in history
   */
  const goBack = () => {
    if (pathHistory.length > 1) {
      const newHistory = [...pathHistory.slice(0, -1)];
      setPathHistory(newHistory);
      setCurrentPath(newHistory[newHistory.length - 1]);
    }
  };

  /**
   * Navigate to Users home directory
   */
  const goHome = () => {
    const homePath = 'C:\\Users';
    setCurrentPath(homePath);
    setPathHistory([...pathHistory, homePath]);
  };

  return (
    <div className="bg-zinc-800 rounded-lg p-4 w-full max-w-2xl">
      {/* Navigation toolbar */}
      <div className="flex items-center gap-2 mb-4">
        {/* Back button */}
        <button
          onClick={goBack}
          disabled={pathHistory.length <= 1}
          className="p-2 rounded hover:bg-zinc-700 disabled:opacity-50"
          title="Go Back"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        
        {/* Home button - go to Users directory */}
        <button
          onClick={goHome}
          className="p-2 rounded hover:bg-zinc-700"
          title="Go to Users folder"
        >
          <Home className="w-4 h-4" />
        </button>
        
        {/* Show drives button */}
        <button
          onClick={() => navigateToDirectory('/')}
          className="p-2 rounded hover:bg-zinc-700"
          title="Show All Drives"
        >
          <HardDrive className="w-4 h-4" />
        </button>
        
        {/* Current path display */}
        <div className="flex-1 bg-zinc-900 rounded px-3 py-2 text-sm truncate">
          {currentPath || 'Computer'}
        </div>
      </div>

      {/* Directory contents area */}
      <div className="bg-zinc-900 rounded-lg mb-4 max-h-96 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 text-center text-gray-400">Loading...</div>
        ) : contents.error ? (
          <div className="p-4 text-center text-red-400">{contents.error}</div>
        ) : (
          <div className="divide-y divide-zinc-800">
            {/* Parent directory button - only show if not at root */}
            {currentPath && (
              <button
                onClick={() => navigateToDirectory('..')}
                className="w-full px-4 py-2 text-left hover:bg-zinc-800 flex items-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" />
                <span>Parent Directory</span>
              </button>
            )}
            
            {/* Directory list */}
            {contents.dirs.map((dir) => (
              <button
                key={dir}
                onClick={() => navigateToDirectory(dir)}
                className="w-full px-4 py-2 text-left hover:bg-zinc-800 flex items-center gap-2"
              >
                {/* Icon selection based on directory type */}
                {isDriveLetter(dir) ? (
                  <HardDrive className="w-4 h-4 text-purple-400" />
                ) : isNetworkPath(dir) ? (
                  <Network className="w-4 h-4 text-purple-400" />
                ) : (
                  <FolderOpen className="w-4 h-4 text-purple-400" />
                )}
                <span className="flex-1 truncate">{dir}</span>
                <ChevronRight className="w-4 h-4 text-gray-400" />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex justify-end gap-2">
        <button
          onClick={onCancel}
          className="px-4 py-2 rounded bg-zinc-700 hover:bg-zinc-600"
        >
          Cancel
        </button>
        <button
          onClick={() => onSelect(currentPath)}
          className="px-4 py-2 rounded bg-purple-500 hover:bg-purple-600"
        >
          Select Directory
        </button>
      </div>
    </div>
  );
};

export default WindowsPathSelector;