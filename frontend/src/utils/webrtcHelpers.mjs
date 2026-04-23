export function normalizeBaseUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

export function normalizeRoutePath(value) {
  return String(value || '').trim().replace(/^\/+/, '').replace(/\/+$/, '')
}

export function buildWhepUrl(webrtcBaseUrl, streamPath) {
  const base = normalizeBaseUrl(webrtcBaseUrl)
  const route = normalizeRoutePath(streamPath)
  if (!base) return ''

  try {
    const parsed = new URL(base)
    if (/\/whep\/?$/i.test(parsed.pathname)) {
      return parsed.toString()
    }
    if (!route) return ''

    const basePath = parsed.pathname.replace(/^\/+|\/+$/g, '')
    parsed.pathname = `/${[basePath, route, 'whep'].filter(Boolean).join('/')}`
    return parsed.toString()
  } catch (_) {
    // Keep a string-based fallback for non-standard or partially typed addresses.
    if (/\/whep\/?$/i.test(base)) {
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

export function linkHeaderToIceServers(linkHeader) {
  const decodeQuotedValue = (value) => String(value || '').replace(/\\(.)/g, '$1')

  return linkHeader
    ? linkHeader.split(', ').map((link) => {
        const match = link.match(
          /^<(.+?)>; rel="ice-server"(; username="(.*?)"; credential="(.*?)"; credential-type="password")?/i
        )
        if (!match) {
          return null
        }

        const server = { urls: [match[1]] }
        if (match[3] !== undefined) {
          server.username = decodeQuotedValue(match[3])
          server.credential = decodeQuotedValue(match[4])
          server.credentialType = 'password'
        }
        return server
      }).filter(Boolean)
    : []
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
