/**
 * Path Selector Component
 * 
 * A platform-aware directory selector that automatically chooses
 * between Windows and Linux path selection interfaces based on
 * the detected operating system of the server.
 * 
 * This component:
 * - Determines the OS type from backend API
 * - Renders the appropriate OS-specific selector component
 * - Passes through all props to the selected component
 * - Handles errors gracefully if OS detection fails
 * 
 * @module components/PathSelector
 */

import React, { useState, useEffect } from 'react';
import LinuxPathSelector from './LinuxPathSelector';
import WindowsPathSelector from './WindowsPathSelector';

/**
 * Platform-aware directory selection dialog
 * Automatically selects the appropriate OS-specific component
 * 
 * @param {Object} props - Component props to pass to the specific selector
 * @returns {JSX.Element} The appropriate path selector for the detected OS
 */
const PathSelector = (props) => {
  // OS detection state
  const [isWindows, setIsWindows] = useState(false);

  /**
   * Detect server OS type when component mounts
   * Uses the path separator character to identify the OS
   */
  useEffect(() => {
    fetch('/api/storage')
      .then(res => res.json())
      .then(data => {
        console.log('Storage response:', data);  // Debug log
        // Windows uses backslash (\) as separator, Unix uses forward slash (/)
        setIsWindows(data.separator === '\\');
      })
      .catch(err => {
        console.error('Error detecting OS:', err);
      });
  }, []);

  console.log('isWindows:', isWindows);  // Debug log

  // Render the appropriate OS-specific selector
  // All props are passed through to the specific component
  return isWindows ? (
    <WindowsPathSelector {...props} />
  ) : (
    <LinuxPathSelector {...props} />
  );
};

export default PathSelector;