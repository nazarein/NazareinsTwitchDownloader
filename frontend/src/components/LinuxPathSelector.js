/**
 * Linux Path Selector Component
 * 
 * A specialized file system navigator for Linux environments that allows users
 * to browse and select directories through a familiar interface. Features include:
 * - Unix-style path navigation
 * - Forward slash separators
 * - Navigation history with back functionality
 * - Home directory shortcut
 * - Directory contents preview
 * 
 * This component handles Linux/Unix specific path conventions using forward slashes
 * and standard Unix paths (/home, etc).
 * 
 * @module components/LinuxPathSelector
 */

import React, { useState, useEffect } from 'react';
import { ChevronRight, FolderOpen, Home, ArrowLeft } from 'lucide-react';

/**
 * Linux-specific directory selection dialog
 * 
 * @param {Object} props - Component props
 * @param {Function} props.onSelect - Callback when a directory is selected, receives path string
 * @param {Function} props.onCancel - Callback when selection is cancelled
 * @param {string} props.initialPath - Initial directory path to display, defaults to /home
 * @returns {JSX.Element} Linux path selector dialog
 */
const LinuxPathSelector = ({ onSelect, onCancel, initialPath = '/home' }) => {
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
      const response = await fetch('/api/available-paths', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      const data = await response.json();
      
      // Handle error or set directory contents
      if (data.error) {
        setContents({ dirs: [], error: data.error });
      } else {
        setContents({ dirs: data.dirs || [], error: null });
      }
    } catch (error) {
      setContents({ dirs: [], error: 'Failed to fetch directory contents' });
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * Navigate to a directory or special location
   * 
   * @param {string} dir - Directory name or special navigation token (..)
   */
  const navigateToDirectory = (dir) => {
    // Handle parent directory special case
    const newPath = dir === '..' 
      ? currentPath.split('/').slice(0, -1).join('/') || '/'
      // For regular directory, append to current path with proper slash handling
      : `${currentPath === '/' ? '' : currentPath}/${dir}`;
    
    // Update path and history
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
   * Navigate to home directory
   */
  const goHome = () => {
    setCurrentPath('/home');
    setPathHistory(['/home']);
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
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        
        {/* Home button */}
        <button
          onClick={goHome}
          className="p-2 rounded hover:bg-zinc-700"
        >
          <Home className="w-4 h-4" />
        </button>
        
        {/* Current path display */}
        <div className="flex-1 bg-zinc-900 rounded px-3 py-2 text-sm truncate">
          {currentPath}
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
            {currentPath !== '/' && (
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
                <FolderOpen className="w-4 h-4 text-purple-400" />
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

export default LinuxPathSelector;