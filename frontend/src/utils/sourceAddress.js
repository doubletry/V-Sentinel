export function normalizeRoutePath(value) {
  return String(value || '').trim().replace(/^\/+/, '').replace(/\/+$/, '')
}

export function normalizeBaseAddress(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

export function buildRtspUrl(rtspBaseAddress, routePath, username = '', password = '') {
  const base = normalizeBaseAddress(rtspBaseAddress)
  const route = normalizeRoutePath(routePath)
  if (!base || !route) return ''

  try {
    const parsed = new URL(base)
    const user = String(username || '').trim()
    if (user) {
      parsed.username = user
      parsed.password = String(password || '')
    } else {
      parsed.username = ''
      parsed.password = ''
    }
    const href = parsed.toString().replace(/\/+$/, '')
    return `${href}/${route}`
  } catch (_) {
    return `${base}/${route}`
  }
}

export function extractRoutePath(rtspUrl, rtspBaseAddress) {
  const full = String(rtspUrl || '').trim()
  if (!full) return ''

  const base = normalizeBaseAddress(rtspBaseAddress)
  if (base) {
    try {
      const fullUrl = new URL(full)
      const baseUrl = new URL(base)
      if (
        fullUrl.protocol === baseUrl.protocol &&
        fullUrl.hostname === baseUrl.hostname &&
        fullUrl.port === baseUrl.port &&
        fullUrl.pathname.startsWith(`${baseUrl.pathname.replace(/\/+$/, '')}/`)
      ) {
        const prefix = `${baseUrl.pathname.replace(/\/+$/, '')}/`
        return normalizeRoutePath(fullUrl.pathname.slice(prefix.length))
      }
    } catch (_) {
      if (full.startsWith(`${base}/`)) {
        return normalizeRoutePath(full.slice(base.length + 1))
      }
    }
  }

  try {
    const parsed = new URL(full)
    return normalizeRoutePath(parsed.pathname)
  } catch (_) {
    const marker = full.indexOf('://')
    if (marker >= 0) {
      const firstSlash = full.indexOf('/', marker + 3)
      if (firstSlash >= 0) {
        return normalizeRoutePath(full.slice(firstSlash + 1))
      }
    }
  }

  return normalizeRoutePath(full)
}
