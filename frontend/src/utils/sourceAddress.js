export function normalizeRoutePath(value) {
  return String(value || '').trim().replace(/^\/+/, '').replace(/\/+$/, '')
}

export function normalizeBaseAddress(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

export function buildRtspUrl(rtspBaseAddress, routePath) {
  const base = normalizeBaseAddress(rtspBaseAddress)
  const route = normalizeRoutePath(routePath)
  if (!base || !route) return ''
  return `${base}/${route}`
}

export function extractRoutePath(rtspUrl, rtspBaseAddress) {
  const full = String(rtspUrl || '').trim()
  if (!full) return ''

  const base = normalizeBaseAddress(rtspBaseAddress)
  if (base && full.startsWith(`${base}/`)) {
    return normalizeRoutePath(full.slice(base.length + 1))
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
