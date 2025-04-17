/**
 * Application Entry Point
 * 
 * This is the main entry file for the React application that:
 * 1. Imports and applies global styles
 * 2. Renders the root App component inside React's StrictMode
 * 3. Initiates performance monitoring with Web Vitals
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
// Import global styles
import './index.css';
// Import the main application component
import App from './App';
// Import performance monitoring utility
import reportWebVitals from './reportWebVitals';

// Create a React root at the DOM element with id 'root'
const root = ReactDOM.createRoot(document.getElementById('root'));

// Render the App component inside React StrictMode
// StrictMode performs additional checks and warnings in development
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Initialize performance monitoring
// This collects and reports web vitals metrics
reportWebVitals();