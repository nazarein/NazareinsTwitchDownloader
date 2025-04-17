/**
 * Cookie Helper Component
 * 
 * A guided interface that helps users extract and save their Twitch authentication
 * cookie for ad-free stream downloads. The component includes:
 * - Step-by-step instructions with a copy feature
 * - Direct link to Twitch.tv
 * - Code snippet for extracting the auth token
 * - Input field for the extracted cookie value
 * - Save functionality with success/error feedback
 * 
 * This component abstracts the technical process of extracting browser cookies
 * into a user-friendly workflow.
 * 
 * @module components/CookieHelper
 */

import React, { useState } from 'react';
import { Copy, ExternalLink, Check } from 'lucide-react';

/**
 * Twitch authentication cookie helper dialog
 * 
 * @returns {JSX.Element} Cookie helper interface
 */
const CookieHelper = () => {
  // UI state management
  const [cookieValue, setCookieValue] = useState(''); // Extracted cookie value
  const [copied, setCopied] = useState(false); // Instructions copy state
  const [isSaving, setIsSaving] = useState(false); // Save operation in progress
  const [saveSuccess, setSaveSuccess] = useState(false); // Save completed successfully
  const [saveError, setSaveError] = useState(null); // Save operation error

  /**
   * Copy the instructions to clipboard
   * Shows temporary confirmation feedback
   */
  const handleCopyInstructions = () => {
    navigator.clipboard.writeText(`
1. Open a new tab and go to https://www.twitch.tv
2. Make sure you're logged in
3. Open developer tools (F12 or right-click > Inspect)
4. Go to the Console tab
5. Paste and run this command: 
   document.cookie.split("; ").find(item => item.startsWith("auth-token="))?.split("=")[1]
6. Copy the output (it will be a long string)
7. Paste it in the text field in this app
    `);
    
    // Show temporary confirmation
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  /**
   * Open Twitch.tv in a new browser tab
   */
  const openTwitchInNewTab = () => {
    window.open('https://www.twitch.tv', '_blank');
  };

  /**
   * Save the extracted cookie value to the backend
   * Handles validation, feedback, and broadcasts the login event
   */
  const handleSaveCookie = async () => {
    // Validate input
    if (!cookieValue.trim()) {
      setSaveError('Please enter a cookie value');
      return;
    }
  
    try {
      setIsSaving(true);
      setSaveError(null);
      
      // Send cookie to backend API
      const response = await fetch('/api/auth/twitch-cookie', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ auth_token: cookieValue }),
      });
  
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to save cookie');
      }
  
      // Store cookie status in localStorage and broadcast login event
      localStorage.setItem('twitch_cookie_saved', 'true');
      window.dispatchEvent(new Event('cookieLogin'));
      
      // Show success message temporarily
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (error) {
      console.error('Error saving cookie:', error);
      setSaveError(error.message || 'Failed to save cookie');
    } finally {
      setIsSaving(false);
    }
  };
  
  return (
    <div className="bg-zinc-800 rounded-lg p-6 mb-6">
      <h2 className="text-lg font-semibold text-white mb-4">Twitch Auth Cookie Helper</h2>
      
      {/* Instructions section */}
      <div className="bg-zinc-900 rounded-lg p-4 mb-4">
        <div className="flex justify-between mb-2">
          <h3 className="text-md font-medium text-white">Instructions</h3>
          
          {/* Copy instructions button */}
          <button 
            onClick={handleCopyInstructions}
            className="text-purple-400 hover:text-purple-300 flex items-center gap-1 text-sm"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
            {copied ? 'Copied!' : 'Copy Instructions'}
          </button>
        </div>
        
        {/* Step-by-step instructions */}
        <ol className="list-decimal list-inside text-gray-300 text-sm space-y-2">
          <li>Open <button 
              onClick={openTwitchInNewTab}
              className="text-purple-400 hover:text-purple-300 inline-flex items-center gap-1"
            >
              Twitch.tv <ExternalLink size={12} />
            </button> in a new tab</li>
          <li>Make sure you're logged in</li>
          <li>Open developer tools (F12 or right-click > Inspect)</li>
          <li>Go to the Console tab</li>
          <li>Paste and run this command:
            <pre className="bg-zinc-800 p-2 rounded mt-1 overflow-x-auto text-xs">
              document.cookie.split("; ").find(item => item.startsWith("auth-token="))?.split("=")[1]
            </pre>
          </li>
          <li>Copy the output (it will be a long string)</li>
          <li>Paste it below and click "Save Cookie"</li>
        </ol>
      </div>
      
      {/* Cookie input section */}
      <div className="mb-4">
        <label htmlFor="cookie-input" className="block text-sm font-medium text-gray-300 mb-2">
          Twitch Auth Cookie
        </label>
        <textarea
          id="cookie-input"
          value={cookieValue}
          onChange={(e) => setCookieValue(e.target.value)}
          placeholder="Paste your auth-token cookie value here..."
          className="w-full bg-zinc-900 text-white p-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-purple-500 text-sm h-20"
        />
      </div>
      
      {/* Action section with status feedback */}
      <div className="flex items-center justify-between">
        <div>
          {/* Error message */}
          {saveError && (
            <p className="text-red-400 text-sm">{saveError}</p>
          )}
          {/* Success message */}
          {saveSuccess && (
            <p className="text-green-400 text-sm flex items-center gap-1">
              <Check size={14} /> Cookie saved successfully!
            </p>
          )}
        </div>
        
        {/* Save button */}
        <button
          onClick={handleSaveCookie}
          disabled={isSaving || !cookieValue.trim()}
          className={`
            ${isSaving ? 'bg-purple-400' : 'bg-purple-500 hover:bg-purple-600'}
            text-white px-4 py-2 rounded-lg flex items-center gap-2 transition-colors
            ${isSaving || !cookieValue.trim() ? 'cursor-not-allowed opacity-70' : 'cursor-pointer'}
          `}
        >
          {isSaving ? 'Saving...' : 'Save Cookie'}
        </button>
      </div>
    </div>
  );
};

export default CookieHelper;