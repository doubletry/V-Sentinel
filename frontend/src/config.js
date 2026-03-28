export default {
  siteName: 'V-Sentinel',
  siteDescription: 'AI Video Surveillance Analysis Platform',
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  wsBaseUrl: import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000',
  mediamtxWebrtcUrl: import.meta.env.VITE_MEDIAMTX_WEBRTC_URL || 'http://localhost:8889',
}
