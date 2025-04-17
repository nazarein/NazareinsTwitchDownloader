/**
 * Web Vitals Reporting Utility
 * 
 * This module provides a function to collect and report Core Web Vitals metrics.
 * It uses the web-vitals library to measure important user experience metrics:
 * 
 * - CLS (Cumulative Layout Shift): Visual stability
 * - FID (First Input Delay): Interactivity
 * - FCP (First Contentful Paint): Initial rendering
 * - LCP (Largest Contentful Paint): Loading performance
 * - TTFB (Time to First Byte): Server response time
 * 
 * These metrics can be reported to an analytics endpoint, console, or other monitoring tool.
 * 
 * @param {Function} onPerfEntry - Callback function to handle the metrics
 */
const reportWebVitals = onPerfEntry => {
  // Only process if a valid callback function is provided
  if (onPerfEntry && onPerfEntry instanceof Function) {
    // Dynamically import the web-vitals library to reduce initial load time
    import('web-vitals').then(({ getCLS, getFID, getFCP, getLCP, getTTFB }) => {
      // Measure Cumulative Layout Shift
      getCLS(onPerfEntry);
      // Measure First Input Delay
      getFID(onPerfEntry);
      // Measure First Contentful Paint
      getFCP(onPerfEntry);
      // Measure Largest Contentful Paint
      getLCP(onPerfEntry);
      // Measure Time To First Byte
      getTTFB(onPerfEntry);
    });
  }
};

export default reportWebVitals;