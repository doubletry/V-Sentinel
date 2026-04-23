const WHEP_ENDPOINT_PATTERN = /\/whep\/?$/i

export function normalizeBaseUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

export function normalizeRoutePath(value) {
  return String(value || '').trim().replace(/^\/+/, '').replace(/\/+$/, '')
}

function joinUrlPath(...segments) {
  return `/${segments
    .map((segment) => String(segment || '').replace(/^\/+|\/+$/g, ''))
    .filter(Boolean)
    .join('/')}`
}

export function buildWhepUrl(webrtcBaseUrl, streamPath) {
  const base = normalizeBaseUrl(webrtcBaseUrl)
  const route = normalizeRoutePath(streamPath)
  if (!base) return ''

  try {
    const parsed = new URL(base)
    if (WHEP_ENDPOINT_PATTERN.test(parsed.pathname)) {
      return parsed.toString()
    }
    if (!route) return ''

    // Build `/optional-base-path/{streamPath}/whep` while trimming only segment boundaries.
    parsed.pathname = joinUrlPath(parsed.pathname, route, 'whep')
    return parsed.toString()
  } catch (error) {
    if (import.meta.env.DEV) {
      const safeBase = base.split('?')[0]
      console.warn(`Failed to parse WebRTC address as URL, using string fallback: ${safeBase}`, error)
    }
    // Keep a string-based fallback for non-standard or partially typed addresses.
    if (WHEP_ENDPOINT_PATTERN.test(base)) {
      return base
    }
    if (!route) return ''
    return `${base}/${route}/whep`
  }
}

export function buildBasicAuthHeader(username, password) {
  const user = String(username || '').trim()
  if (!user) return {}

  const raw = `${user}:${String(password || '')}`
  if (typeof btoa === 'function' && typeof TextEncoder !== 'undefined') {
    const utf8Bytes = new TextEncoder().encode(raw)
    let binaryString = ''
    for (let i = 0; i < utf8Bytes.length; i += 1) {
      binaryString += String.fromCharCode(utf8Bytes[i])
    }
    return { Authorization: `Basic ${btoa(binaryString)}` }
  }

  return {
    Authorization: `Basic ${Buffer.from(raw, 'utf-8').toString('base64')}`,
  }
}

export function buildWhepEndpointHeaders(username, password, extraHeaders = {}) {
  return {
    ...buildBasicAuthHeader(username, password),
    ...extraHeaders,
  }
}

export function buildWhepPatchHeaders() {
  return {
    'Content-Type': 'application/trickle-ice-sdpfrag',
    'If-Match': '*',
  }
}

export function parseOfferData(sdp) {
  const offerData = { iceUfrag: '', icePwd: '', medias: [] }

  for (const line of String(sdp || '').split('\r\n')) {
    if (line.startsWith('m=')) {
      offerData.medias.push(line.slice(2))
    } else if (!offerData.iceUfrag && line.startsWith('a=ice-ufrag:')) {
      offerData.iceUfrag = line.slice('a=ice-ufrag:'.length)
    } else if (!offerData.icePwd && line.startsWith('a=ice-pwd:')) {
      offerData.icePwd = line.slice('a=ice-pwd:'.length)
    }
  }

  return offerData
}

export function generateSdpFragment(offerData, candidates) {
  const candidatesByMedia = {}
  for (const candidate of candidates || []) {
    const mediaIndex = candidate.sdpMLineIndex
    if (candidatesByMedia[mediaIndex] === undefined) {
      candidatesByMedia[mediaIndex] = []
    }
    candidatesByMedia[mediaIndex].push(candidate)
  }

  let fragment = `a=ice-ufrag:${offerData.iceUfrag}\r\n`
  fragment += `a=ice-pwd:${offerData.icePwd}\r\n`

  for (let mediaIndex = 0; mediaIndex < offerData.medias.length; mediaIndex += 1) {
    if (!candidatesByMedia[mediaIndex]?.length) continue

    fragment += `m=${offerData.medias[mediaIndex]}\r\n`
    fragment += `a=mid:${mediaIndex}\r\n`
    for (const candidate of candidatesByMedia[mediaIndex]) {
      fragment += `a=${candidate.candidate}\r\n`
    }
  }

  return fragment
}
