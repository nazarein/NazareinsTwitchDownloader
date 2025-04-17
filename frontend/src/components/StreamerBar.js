/**
 * StreamerBar Component
 * 
 * Displays a single streamer card with real-time status information,
 * thumbnail, and controls for download settings. This component:
 * - Shows live/offline status with visual indicators
 * - Displays stream thumbnails that update in real-time
 * - Provides controls for download configuration
 * - Shows download status with color-coded indicators
 * - Allows selection of stream resolution
 * - Supports path customization for downloads
 * 
 * The component uses optimistic UI updates for a responsive experience
 * and features a pulsing border effect for active downloads.
 * 
 * @module components/StreamerBar
 */

import React, { memo, useState, useEffect, useRef } from 'react';
import { Trash2, Folder, ToggleLeft, ToggleRight, Download, CheckCircle, AlertCircle, RefreshCw, Clock } from 'lucide-react';
import { updateStreamerSettings } from '../utils/api';
import PathSelector from './PathSelector';

/**
 * StreamerBar component for displaying and managing a Twitch streamer
 * 
 * @param {Object} props - Component props
 * @param {string} props.streamer - Twitch username of the streamer
 * @param {boolean} props.isOnline - Whether the streamer is currently live
 * @param {string} props.thumbnail - URL of stream thumbnail (if live)
 * @param {string} props.offlineImageURL - URL of offline image to show when not live
 * @param {string} props.profileImageURL - URL of streamer's profile image
 * @param {string} props.title - Stream title or "Offline" when not live
 * @param {Function} props.onDelete - Callback when streamer is deleted
 * @param {boolean} props.downloads_enabled - Whether automatic downloads are enabled
 * @param {string} props.downloadStatus - Current download status 
 *                 (downloading, error, completed, stopped, preparing, retrying, waiting)
 * @param {string} props.stream_resolution - Selected stream resolution for downloads
 * @param {Function} props.onUpdateSettings - Callback when settings are updated
 * @returns {JSX.Element} StreamerBar component
 */
const StreamerBar = memo(({ 
  streamer, 
  isOnline, 
  thumbnail, 
  offlineImageURL,
  profileImageURL,
  title, 
  onDelete,
  downloads_enabled = false,
  downloadStatus = null,
  stream_resolution = "best",
  onUpdateSettings
}) => {
  // Local UI state tracking
  const [isToggled, setIsToggled] = useState(downloads_enabled);
  const [downloadState, setDownloadState] = useState(downloadStatus);
  const [storagePath, setStoragePath] = useState('');
  const [showPathModal, setShowPathModal] = useState(false);
  const [thumbnailUrl, setThumbnailUrl] = useState('');
  const [selectedResolution, setSelectedResolution] = useState(stream_resolution || "best");
  
  // Ref for cache-busting thumbnails
  const thumbnailTimeRef = useRef(Date.now());

  // Synchronize toggle state with props
  useEffect(() => {
    setIsToggled(downloads_enabled);
  }, [downloads_enabled]);
  
  // Synchronize download status with props
  useEffect(() => {
    setDownloadState(downloadStatus);
  }, [downloadStatus]);

  /**
   * Update thumbnail source when stream status changes
   * Uses either offline image or live thumbnail with cache-busting
   */
  useEffect(() => {
    if (!isOnline && offlineImageURL) {
      // Show offline image when streamer is not live
      setThumbnailUrl(offlineImageURL);
    } 
    else if (thumbnail) {
      // Add cache-busting timestamp to force thumbnail refresh
      const hasQueryParams = thumbnail.includes('?');
      const refreshedUrl = hasQueryParams 
        ? `${thumbnail}&t=${Date.now()}` 
        : `${thumbnail}?t=${Date.now()}`;
      
      // Update the timestamp ref for the key prop
      thumbnailTimeRef.current = Date.now();
      setThumbnailUrl(refreshedUrl);
    }
  }, [thumbnail, offlineImageURL, isOnline, streamer]);

  /**
   * Fetch and set the streamer's storage path when component mounts
   * Falls back to global storage path if streamer-specific not found
   */
  useEffect(() => {
    const getStreamerPath = async () => {
      try {
        // Fetch streamer-specific storage path
        const response = await fetch(`/api/streamers/${streamer}/status`);
        const data = await response.json();
        
        if (data.storage_path) {
          setStoragePath(data.storage_path);
        } else {
          // Fall back to global storage path
          const globalResponse = await fetch('/api/storage');
          const globalData = await globalResponse.json();
          setStoragePath(globalData.path);
        }
      } catch (err) {
        console.error('Failed to fetch storage path:', err);
      }
    };
    
    getStreamerPath();
  }, [streamer]);

  /**
   * Add pulsing border animation style to document if not already present
   * This creates the visual effect for active downloads
   */
  useEffect(() => {
    if (!document.getElementById('pulse-animation-style')) {
      const style = document.createElement('style');
      style.id = 'pulse-animation-style';
      style.innerHTML = `
        @keyframes pulseBorderPurple {
          0% { border-color: #c026d3; }
          50% { border-color: #000000; }
          100% { border-color: #c026d3; }
        }
      `;
      document.head.appendChild(style);
    }
  }, []);

  /**
   * Handle stream resolution change
   * Updates local state and propagates to parent via callback
   * 
   * @param {Event} e - Change event from select element
   */
  const handleResolutionChange = async (e) => {
    const newResolution = e.target.value;
    // Update local state
    setSelectedResolution(newResolution);
    
    // Propagate change to parent component if callback provided
    if (onUpdateSettings) {
      onUpdateSettings({ stream_resolution: newResolution });
    }
  };

  /**
   * Handle double-click on the streamer card
   * Opens the Twitch stream in a new tab if streamer is live
   */
  const handleDoubleClick = () => {
    if (isOnline) {
      // Only open stream if the streamer is live
      window.open(`https://twitch.tv/${streamer}`, '_blank');
    }
  };

  /**
   * Toggle automatic downloads for the streamer
   * Updates local state optimistically and sends to server
   */
  const handleToggle = async () => {
    const newToggleState = !isToggled;
    try {
      // Update UI immediately for responsive feedback
      setIsToggled(newToggleState);
      
      // Use callback if provided, otherwise make direct API call
      if (onUpdateSettings) {
        onUpdateSettings({ downloads_enabled: newToggleState });
      } 
      else {
        await updateStreamerSettings(streamer, {
          downloads_enabled: newToggleState
        });
      }
    } catch (error) {
      // Revert UI state on error
      console.error('Failed to toggle downloads:', error);
      setIsToggled(!newToggleState);
    }
  };

  /**
   * Show path selection modal to customize download location
   */
  const handleFolderSelect = () => {
    setShowPathModal(true);
  };

  // Determine if the pulsing border should be shown (when live and downloads enabled)
  const shouldShowPulsingBorder = isOnline && isToggled;
  
  return (
    <>
      {/* Main streamer card with conditional pulsing border */}
      <div 
        style={{
          border: shouldShowPulsingBorder ? '2px solid #c026d3' : 'none',
          animation: shouldShowPulsingBorder ? 'pulseBorderPurple 2s infinite' : 'none',
          borderRadius: '0.5rem',
          padding: '1rem',
          marginBottom: '1rem',
          backgroundColor: 'rgb(39 39 42)',
          transition: 'all 0.3s',
          position: 'relative'
        }}
        className="hover:bg-zinc-700 hover:scale-[1.02] group"
        onDoubleClick={handleDoubleClick}
      >
        <div className="flex gap-4">
          {/* Thumbnail section */}
          <div className="w-48 h-28 overflow-hidden rounded bg-zinc-900 relative">
            {thumbnailUrl && (
              <img 
                key={`${streamer}-${thumbnailTimeRef.current}`}
                src={thumbnailUrl}
                alt={`${streamer}'s ${isOnline ? 'stream' : 'offline'} thumbnail`}
                className="w-full h-full object-cover transition-opacity duration-300"
                onError={(e) => {
                  e.target.style.opacity = 0;
                }}
              />
            )}
          </div>

          {/* Streamer info section */}
          <div className="flex-1 min-w-0">
            <div>
              {/* Profile image with live status indicator */}
              <div className="relative inline-block">
                {profileImageURL && (
                  <img 
                    src={profileImageURL}
                    alt={`${streamer}'s profile`}
                    className="w-10 h-10 rounded-full"
                    onError={(e) => e.target.style.display = 'none'}
                  />
                )}
                {/* Live status indicator dot */}
                <div className={`w-2.5 h-2.5 rounded-full ${isOnline ? 'bg-green-500' : 'bg-red-500'} absolute -bottom-0.5 -right-0.5 border-2 border-zinc-800 group-hover:border-zinc-700`} />
              </div>

              {/* Streamer details section */}
              <div className="mt-2 max-w-[600px]">
                {/* Streamer name */}
                <div className="text-white text-sm font-medium truncate transition-colors">{streamer}</div>
                
                {/* Stream title (if available) */}
                {title && (
                  <div className="text-gray-400 text-sm truncate mt-0.5 group-hover:text-gray-300">{title}</div>
                )}
                
                {/* Storage path display */}
                {storagePath && (
                  <div className="text-gray-400 text-xs truncate mt-0.5 group-hover:text-gray-300">
                    {storagePath}
                  </div>
                )}
                
                {/* Download status indicator with conditional display and styling */}
                {downloadState && (
                  <div className={`flex items-center gap-1 text-xs mt-1 ${
                    downloadState === 'downloading' ? 'text-green-400' : 
                    downloadState === 'error' ? 'text-red-400' : 
                    downloadState === 'completed' ? 'text-purple-400' : 
                    downloadState === 'preparing' ? 'text-blue-400' :
                    downloadState === 'retrying' ? 'text-yellow-400' :
                    downloadState === 'waiting' ? 'text-blue-300' :
                    'text-gray-400'
                  }`}>
                    {/* Conditional rendering based on download state */}
                    {downloadState === 'downloading' && (
                      <>
                        <Download size={12} className="animate-pulse" />
                        <span>Recording</span>
                      </>
                    )}
                    {downloadState === 'error' && (
                      <>
                        <AlertCircle size={12} />
                        <span>Download error</span>
                      </>
                    )}
                    {downloadState === 'completed' && (
                      <>
                        <CheckCircle size={12} />
                        <span>Download complete</span>
                      </>
                    )}
                    {downloadState === 'stopped' && (
                      <>
                        <Download size={12} />
                        <span>Download stopped</span>
                      </>
                    )}
                    {downloadState === 'preparing' && (
                      <>
                        <Clock size={12} className="animate-pulse" />
                        <span>Preparing download</span>
                      </>
                    )}
                    {downloadState === 'retrying' && (
                      <>
                        <RefreshCw size={12} className="animate-spin" />
                        <span>Retrying download</span>
                      </>
                    )}
                    {downloadState === 'waiting' && (
                      <>
                        <Clock size={12} />
                        <span>Waiting for stream</span>
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
          
          {/* Controls section */}
          <div className="flex flex-col justify-between items-end">
            {/* Resolution selector dropdown */}
            <select
              value={selectedResolution}
              onChange={handleResolutionChange}
              className="bg-zinc-700 text-white text-xs p-1 rounded"
              title="Stream Resolution"
            >
              <option value="best">Best</option>
              <option value="1080p60">1080p60</option>
              <option value="720p60">720p60</option>
              <option value="480p">480p</option>
              <option value="360p">360p</option>
              <option value="160p">160p</option>
              <option value="audio_only">Audio Only</option>
            </select>

            {/* Control buttons */}
            <div className="flex flex-col gap-2">
              {/* Toggle downloads button */}
              <button
                onClick={handleToggle}
                className={`transition-colors ${isToggled ? 'text-purple-500 hover:text-purple-400' : 'text-gray-400 hover:text-purple-500'}`}
                title={isToggled ? "Disable downloads" : "Enable downloads"}
              >
                {isToggled ? (
                  <ToggleRight className="w-5 h-5" />
                ) : (
                  <ToggleLeft className="w-5 h-5" />
                )}
              </button>

              {/* Folder selection button */}
              <button
                onClick={handleFolderSelect}
                className="text-purple-500 hover:text-purple-400 transition-colors"
                title={`Storage Path: ${storagePath}`}
              >
                <Folder className="w-5 h-5" />
              </button>

              {/* Delete streamer button */}
              <button
                onClick={() => onDelete(streamer)}
                className="text-gray-400 hover:text-red-500 transition-colors"
                title="Delete streamer"
              >
                <Trash2 className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Path selector modal (conditionally rendered) */}
      {showPathModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <PathSelector
            onSelect={async (selectedPath) => {
              try {
                // Send updated path to the backend
                const res = await fetch('/api/streamers/' + streamer + '/storage', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json'
                  },
                  body: JSON.stringify({ 
                    path: selectedPath
                  })
                });

                if (!res.ok) {
                  throw new Error('Failed to update storage path');
                }

                // Update local state with the new path
                const data = await res.json();
                setStoragePath(data.path);
                setShowPathModal(false);
                
                // Notify parent component about the change
                if (onUpdateSettings) {
                  onUpdateSettings({ storage_path: selectedPath });
                }
              } catch (error) {
                console.error('Failed to update storage path:', error);
              }
            }}
            onCancel={() => setShowPathModal(false)}
            initialPath={storagePath || 'C:\\'}
          />
        </div>
      )}
    </>
  );
});

export default StreamerBar;