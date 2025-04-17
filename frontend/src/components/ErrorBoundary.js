/**
 * Error Boundary Component
 * 
 * A React error boundary that catches JavaScript errors in child component trees
 * and displays a fallback UI instead of crashing the entire application.
 * Features include:
 * - Error state isolation to prevent cascading failures
 * - Detailed error display for debugging
 * - Custom fallback UI support
 * - Error logging to console for diagnostics
 * - Higher-order component (HOC) wrapper for easy usage
 * 
 * This component implements the React Error Boundary pattern using
 * lifecycle methods to catch and handle errors gracefully.
 * 
 * @module components/ErrorBoundary
 */

import React from 'react';

/**
 * Error boundary component for catching and handling render errors
 * 
 * @extends {React.Component}
 */
class ErrorBoundary extends React.Component {
  /**
   * Initialize the error boundary state
   * 
   * @param {Object} props - Component props
   * @param {React.ReactNode} props.children - Child components to render
   * @param {React.ReactNode} props.fallback - Optional fallback UI to show when error occurs
   */
  constructor(props) {
    super(props);
    this.state = { 
      hasError: false, // Whether an error has been caught
      error: null,     // The error object
      errorInfo: null  // React component stack information
    };
  }

  /**
   * Update state when an error is caught
   * This is a static lifecycle method invoked before render when an error occurs
   * 
   * @static
   * @param {Error} error - The error that was thrown
   * @returns {Object} New state object to update component with
   */
  static getDerivedStateFromError(error) {
    // Update state to render fallback UI on next render
    return { hasError: true, error };
  }

  /**
   * Lifecycle method called after an error is caught
   * Used for logging errors and capturing component stack trace
   * 
   * @param {Error} error - The error that was thrown
   * @param {Object} errorInfo - React component stack information
   */
  componentDidCatch(error, errorInfo) {
    // Update state with error details for display
    this.setState({
      error,
      errorInfo
    });
    
    // Log error to console for debugging
    console.error('Error caught by boundary:', error, errorInfo);
  }

  /**
   * Render either the error UI or normal children
   * 
   * @returns {React.ReactNode} Error UI or wrapped children
   */
  render() {
    // If an error occurred, render error UI
    if (this.state.hasError) {
      return (
        <div className="p-4 bg-red-500 bg-opacity-10 border border-red-500 rounded-lg">
          <h2 className="text-red-500 text-lg font-semibold mb-2">
            Something went wrong
          </h2>
          <div className="text-gray-300 text-sm">
            {this.state.error && this.state.error.toString()}
          </div>
          {/* Render custom fallback if provided */}
          {this.props.fallback}
        </div>
      );
    }

    // Otherwise, render children normally
    return this.props.children;
  }
}

/**
 * Higher-Order Component that wraps a component with an ErrorBoundary
 * 
 * @param {React.Component} WrappedComponent - Component to wrap with error boundary
 * @param {React.ReactNode} fallback - Optional fallback UI for errors
 * @returns {React.FC} New component wrapped with error boundary
 */
export const withErrorBoundary = (WrappedComponent, fallback) => {
  return function WithErrorBoundary(props) {
    return (
      <ErrorBoundary fallback={fallback}>
        <WrappedComponent {...props} />
      </ErrorBoundary>
    );
  };
};

export default ErrorBoundary;