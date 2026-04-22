import {
  buildBasicAuthHeader,
  buildWhepUrl,
  generateSdpFragment,
  linkHeaderToIceServers,
  parseOfferData,
} from './webrtcHelpers.mjs'

async function requestIceServers(whepUrl, authHeaders) {
  const response = await fetch(whepUrl, {
    method: 'OPTIONS',
    headers: authHeaders,
  })

  if (!response.ok) {
    throw new Error(`WHEP ICE request failed: ${response.status} ${response.statusText}`)
  }

  return linkHeaderToIceServers(response.headers.get('Link'))
}

async function sendOffer(whepUrl, offerSdp, authHeaders) {
  const response = await fetch(whepUrl, {
    method: 'POST',
    headers: {
      ...authHeaders,
      'Content-Type': 'application/sdp',
    },
    body: offerSdp,
  })

  switch (response.status) {
    case 201:
      return {
        answerSdp: await response.text(),
        sessionUrl: new URL(response.headers.get('location'), whepUrl).toString(),
      }
    case 404: {
      const error = new Error('stream not found')
      error.name = 'WHEPError'
      error.status = 404
      throw error
    }
    default: {
      const error = new Error(`WHEP error: ${response.status} ${response.statusText}`)
      error.name = 'WHEPError'
      error.status = response.status
      throw error
    }
  }
}

function patchLocalCandidates(sessionUrl, offerData, candidates, authHeaders) {
  if (!sessionUrl || !candidates.length) return

  fetch(sessionUrl, {
    method: 'PATCH',
    headers: {
      ...authHeaders,
      'Content-Type': 'application/trickle-ice-sdpfrag',
      'If-Match': '*',
    },
    body: generateSdpFragment(offerData, candidates),
  }).catch((error) => {
    console.warn(
      'Failed to send ICE candidates to WHEP session (connection quality may be affected):',
      error
    )
  })
}

function deleteSession(sessionUrl, authHeaders) {
  if (!sessionUrl) return

  fetch(sessionUrl, {
    method: 'DELETE',
    headers: authHeaders,
  }).catch(() => {
    // Ignore cleanup failures.
  })
}

/**
 * Connect to a MediaMTX stream via its documented WHEP browser flow.
 * @param {string} streamPath
 * @param {HTMLVideoElement} videoEl
 * @param {string} webrtcBaseUrl
 * @param {object} [options]
 * @returns {object} - { pc, stop }
 */
export async function connectWebRTC(streamPath, videoEl, webrtcBaseUrl, options = {}) {
  const whepUrl = buildWhepUrl(webrtcBaseUrl, streamPath)
  if (!whepUrl) {
    throw new Error('Missing WebRTC gateway address')
  }

  const authHeaders = buildBasicAuthHeader(options.username, options.password)
  const iceServers = await requestIceServers(whepUrl, authHeaders)
  const pc = new RTCPeerConnection({
    iceServers,
    sdpSemantics: 'unified-plan',
  })

  let sessionUrl = null
  let stopped = false
  const queuedCandidates = []
  const transceiverDirection = 'recvonly'

  pc.addTransceiver('video', { direction: transceiverDirection })
  pc.addTransceiver('audio', { direction: transceiverDirection })
  // MediaMTX's documented browser WHEP flow creates a local data channel so
  // the peer connection can receive server-side data channels when available.
  pc.createDataChannel('')

  pc.ontrack = (event) => {
    if (videoEl && !videoEl.srcObject) {
      videoEl.srcObject = event.streams[0]
    }
  }

  const offer = await pc.createOffer()
  await pc.setLocalDescription(offer)
  const offerData = parseOfferData(offer.sdp)

  pc.onicecandidate = (event) => {
    if (stopped || !event.candidate) return

    if (!sessionUrl) {
      queuedCandidates.push(event.candidate)
      return
    }

    patchLocalCandidates(sessionUrl, offerData, [event.candidate], authHeaders)
  }

  let answerSdp
  try {
    const result = await sendOffer(whepUrl, offer.sdp, authHeaders)
    sessionUrl = result.sessionUrl
    answerSdp = result.answerSdp
  } catch (error) {
    pc.close()
    throw error
  }

  await pc.setRemoteDescription({
    type: 'answer',
    sdp: answerSdp,
  })

  if (queuedCandidates.length) {
    patchLocalCandidates(sessionUrl, offerData, queuedCandidates.splice(0), authHeaders)
  }

  return {
    pc,
    stop: () => {
      if (stopped) return
      stopped = true
      deleteSession(sessionUrl, authHeaders)
      pc.close()
    },
  }
}
