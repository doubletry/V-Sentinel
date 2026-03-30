/**
 * Application configuration.
 *
 * In production the frontend is served by FastAPI from the same origin,
 * so API / WS base URLs default to the current browser origin (no hard-coded
 * port).  During Vite dev-server development requests are proxied to the
 * backend automatically.
 *
 * Override via environment variables when needed:
 *   VITE_API_BASE_URL, VITE_WS_BASE_URL, VITE_MEDIAMTX_WEBRTC_URL
 */
function detectApiBase() {
  if (import.meta.env.VITE_API_BASE_URL) return import.meta.env.VITE_API_BASE_URL
  // In dev mode Vite proxy handles /api → backend, so use '' (relative)
  if (import.meta.env.DEV) return ''
  // Production: same origin as the page
  return window.location.origin
}

function detectWsBase() {
  if (import.meta.env.VITE_WS_BASE_URL) return import.meta.env.VITE_WS_BASE_URL
  if (import.meta.env.DEV) return ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
}

export default {
  siteName: 'V-Sentinel',
  siteDescription: 'AI Video Surveillance Analysis Platform',
  apiBaseUrl: detectApiBase(),
  wsBaseUrl: detectWsBase(),
  mediamtxWebrtcUrl: import.meta.env.VITE_MEDIAMTX_WEBRTC_URL || 'http://localhost:8889',
}
