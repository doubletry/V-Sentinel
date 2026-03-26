import config from '../config.js'

/**
 * Connect to a MediaMTX stream via WebRTC (WHEP protocol).
 * @param {string} streamPath - The stream path on MediaMTX (e.g. "camera1")
 * @param {HTMLVideoElement} videoEl - The video element to attach to
 * @returns {object} - { pc: RTCPeerConnection, stop: Function }
 */
export async function connectWebRTC(streamPath, videoEl) {
  const whepUrl = `${config.mediamtxWebrtcUrl}/${streamPath}/whep`

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

  // Send offer to MediaMTX WHEP endpoint
  let response
  try {
    response = await fetch(whepUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/sdp' },
      body: pc.localDescription.sdp,
    })
  } catch (err) {
    pc.close()
    throw new Error(`WHEP request failed: ${err.message}`)
  }

  if (!response.ok) {
    pc.close()
    throw new Error(`WHEP error: ${response.status} ${response.statusText}`)
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
