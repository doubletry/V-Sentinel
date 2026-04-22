import config from '../config.js'

function normalizeBaseUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

function normalizeRoutePath(value) {
  return String(value || '').trim().replace(/^\/+/, '').replace(/\/+$/, '')
}

/**
 * Connect to a MediaMTX stream via WebRTC (WHEP protocol).
 * @param {string} streamPath - The stream path on MediaMTX (e.g. "camera1")
 * @param {HTMLVideoElement} videoEl - The video element to attach to
 * @param {string} webrtcBaseUrl - MediaMTX WebRTC base address from settings
 * @param {object} [options] - Optional auth options { username, password }
 * @returns {object} - { pc: RTCPeerConnection, stop: Function }
 */
export async function connectWebRTC(streamPath, videoEl, webrtcBaseUrl, options = {}) {
  const base = normalizeBaseUrl(webrtcBaseUrl || config.mediamtxWebrtcUrl)
  const route = normalizeRoutePath(streamPath)
  const whepUrl = `${base}/${route}/whep`

  const pc = new RTCPeerConnection({
    iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
  })

  // Add transceivers to receive audio and video
  pc.addTransceiver('video', { direction: 'recvonly' })
  pc.addTransceiver('audio', { direction: 'recvonly' })

  // Attach stream to video element when tracks arrive
  pc.ontrack = (event) => {
    if (videoEl) {
      if (!videoEl.srcObject) {
        videoEl.srcObject = event.streams[0]
      }
    }
  }

  // Create SDP offer
  const offer = await pc.createOffer()
  await pc.setLocalDescription(offer)

  // Wait for ICE gathering to complete (or timeout)
  await waitForIceGathering(pc)

  // Build request headers, optionally including HTTP Basic auth for MediaMTX.
  const headers = { 'Content-Type': 'application/sdp' }
  const username = String(options.username || '')
  if (username) {
    const password = String(options.password || '')
    headers.Authorization = 'Basic ' + buildBasicAuthToken(username, password)
  }

  // Send offer to MediaMTX WHEP endpoint
  let response
  try {
    response = await fetch(whepUrl, {
      method: 'POST',
      headers,
      body: pc.localDescription.sdp,
    })
  } catch (err) {
    pc.close()
    throw new Error(`WHEP request failed: ${err.message}`)
  }

  if (!response.ok) {
    pc.close()
    const error = new Error(`WHEP error: ${response.status} ${response.statusText}`)
    error.name = 'WHEPError'
    error.status = response.status
    throw error
  }

  const answerSdp = await response.text()
  await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp })

  return {
    pc,
    stop: () => pc.close(),
  }
}

/**
 * Wait for ICE gathering to complete (or timeout after 3s).
 */
function waitForIceGathering(pc) {
  return new Promise((resolve) => {
    if (pc.iceGatheringState === 'complete') {
      resolve()
      return
    }
    const timeout = setTimeout(resolve, 3000)
    pc.addEventListener('icegatheringstatechange', () => {
      if (pc.iceGatheringState === 'complete') {
        clearTimeout(timeout)
        resolve()
      }
    })
  })
}

/**
 * Build a base64-encoded HTTP Basic auth token from username/password.
 * Uses btoa when available (browsers); falls back to Buffer for Node tests.
 */
function buildBasicAuthToken(username, password) {
  const raw = `${username}:${password}`
  if (typeof btoa === 'function' && typeof TextEncoder !== 'undefined') {
    // btoa requires a binary (latin-1) string; encode UTF-8 first via
    // TextEncoder to support non-ASCII credentials safely.
    const utf8Bytes = new TextEncoder().encode(raw)
    let binary = ''
    for (let i = 0; i < utf8Bytes.length; i += 1) {
      binary += String.fromCharCode(utf8Bytes[i])
    }
    return btoa(binary)
  }
  // Node fallback for test environments where btoa/TextEncoder are unavailable.
  return Buffer.from(raw, 'utf-8').toString('base64')
}
