/**
 * Login Banners Component
 * 
 * Displays informational banners about authentication requirements.
 * Shows two types of banners:
 * 1. Twitch OAuth login banner - For EventSub WebSocket authentication
 * 2. Cookie login banner - For ad-free downloads
 * 
 * Banners are shown based on authentication state and can be dismissed
 * individually. Each banner disappears automatically when the
 * corresponding authentication is detected.
 * 
 * @module components/LoginBanners
 */

import React, { useState, useEffect } from 'react';
import { AlertCircle, X } from 'lucide-react';

/**
 * Display authentication requirement banners
 * 
 * @returns {JSX.Element|null} Login requirement banners or null if not needed
 */
const LoginBanners = () => {
  // Authentication state
  const [isTwitchLoggedIn, setIsTwitchLoggedIn] = useState(false);
  const [isCookieLoggedIn, setIsCookieLoggedIn] = useState(false);
  
  // Banner dismissal state
  const [dismissedTwitch, setDismissedTwitch] = useState(false);
  const [dismissedCookie, setDismissedCookie] = useState(false);

  /**
   * Check authentication status and set up event listeners
   * Monitors both OAuth token and cookie authentication
   */
  useEffect(() => {
    /**
     * Check login status from backend and localStorage
     */
    const checkLoginStatus = async () => {
      try {
        // Check for Twitch OAuth token
        const tokenResponse = await fetch('/api/auth/token');
        const tokenData = await tokenResponse.json();
        setIsTwitchLoggedIn(!!tokenData.access_token);
        
        // Check for cookie authentication via backend and fallback
        try {
          const cookieCheckResponse = await fetch('/api/auth/check-cookie-file');
          if (cookieCheckResponse.ok) {
            const cookieData = await cookieCheckResponse.json();
            setIsCookieLoggedIn(cookieData.exists);
          } else {
            // Fallback to localStorage if backend check fails
            const hasSavedCookie = localStorage.getItem('twitch_cookie_saved') === 'true';
            setIsCookieLoggedIn(hasSavedCookie);
          }
        } catch (error) {
          console.error('Error checking cookie file:', error);
          // Fallback to localStorage
          const hasSavedCookie = localStorage.getItem('twitch_cookie_saved') === 'true';
          setIsCookieLoggedIn(hasSavedCookie);
        }
      } catch (error) {
        console.error('Error checking login status:', error);
      }
    };

    // Check login status immediately on mount
    checkLoginStatus();

    /**
     * Event handlers for authentication events
     */
    const handleTwitchLogin = () => setIsTwitchLoggedIn(true);
    const handleTwitchLogout = () => setIsTwitchLoggedIn(false);
    const handleCookieLogin = () => {
      setIsCookieLoggedIn(true);
      // Save to localStorage for persistence
      localStorage.setItem('twitch_cookie_saved', 'true');
    };

    // Set up event listeners for auth state changes
    window.addEventListener('twitchLogin', handleTwitchLogin);
    window.addEventListener('twitchLogout', handleTwitchLogout);
    window.addEventListener('cookieLogin', handleCookieLogin);

    // Clean up event listeners on unmount
    return () => {
      window.removeEventListener('twitchLogin', handleTwitchLogin);
      window.removeEventListener('twitchLogout', handleTwitchLogout);
      window.removeEventListener('cookieLogin', handleCookieLogin);
    };
  }, []);

  /**
   * Hide component entirely if:
   * - Both auth methods are present, or
   * - Both banners are dismissed, or
   * - OAuth is present and cookie banner is dismissed, or
   * - Cookie is present and OAuth banner is dismissed
   */
  if ((isTwitchLoggedIn && isCookieLoggedIn) || 
      (dismissedTwitch && dismissedCookie) || 
      (isTwitchLoggedIn && dismissedCookie) || 
      (dismissedTwitch && isCookieLoggedIn)) {
    return null;
  }

  return (
    <div className="space-y-2 mb-4">
      {/* Twitch OAuth Login Banner */}
      {!isTwitchLoggedIn && !dismissedTwitch && (
        <div className="bg-purple-900 bg-opacity-50 border border-purple-500 rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="text-purple-400 w-5 h-5" />
            <span className="text-white">
              Twitch login is needed for automatic stream detection via WebSockets
            </span>
          </div>
          <button 
            onClick={() => setDismissedTwitch(true)}
            className="text-gray-400 hover:text-white"
            aria-label="Dismiss banner"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      )}

      {/* Cookie Login Banner */}
      {!isCookieLoggedIn && !dismissedCookie && (
        <div className="bg-blue-900 bg-opacity-50 border border-blue-500 rounded-lg p-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="text-blue-400 w-5 h-5" />
            <span className="text-white">
              Cookie login is needed for ad-free recording
            </span>
          </div>
          <button 
            onClick={() => setDismissedCookie(true)}
            className="text-gray-400 hover:text-white"
            aria-label="Dismiss banner"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
      )}
    </div>
  );
};

export default LoginBanners;