import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildBasicAuthHeader,
  buildWhepEndpointHeaders,
  buildWhepPatchHeaders,
  buildWhepUrl,
  generateSdpFragment,
  linkHeaderToIceServers,
  parseOfferData,
} from './webrtcHelpers.mjs'

test('buildWhepUrl normalizes the base URL and route path', () => {
  assert.equal(
    buildWhepUrl('http://localhost:8889/', '/cam1/'),
    'http://localhost:8889/cam1/whep'
  )
})

test('buildWhepUrl accepts a full WHEP endpoint URL unchanged', () => {
  assert.equal(
    buildWhepUrl('http://localhost:8889/cam1/whep', '/ignored/'),
    'http://localhost:8889/cam1/whep'
  )
})

test('buildWhepUrl preserves query parameters on a full WHEP endpoint URL', () => {
  assert.equal(
    buildWhepUrl('http://localhost:8889/cam1/whep?token=abc', '/ignored/'),
    'http://localhost:8889/cam1/whep?token=abc'
  )
})

test('buildBasicAuthHeader encodes username and password', () => {
  assert.deepEqual(buildBasicAuthHeader('alice', 'secret'), {
    Authorization: 'Basic YWxpY2U6c2VjcmV0',
  })
})

test('buildWhepEndpointHeaders includes auth on WHEP endpoint requests', () => {
  assert.deepEqual(
    buildWhepEndpointHeaders('alice', 'secret', { 'Content-Type': 'application/sdp' }),
    {
      Authorization: 'Basic YWxpY2U6c2VjcmV0',
      'Content-Type': 'application/sdp',
    }
  )
})

test('buildWhepPatchHeaders omits auth on session PATCH requests', () => {
  assert.deepEqual(buildWhepPatchHeaders(), {
    'Content-Type': 'application/trickle-ice-sdpfrag',
    'If-Match': '*',
  })
})

test('linkHeaderToIceServers parses ice server links', () => {
  assert.deepEqual(
    linkHeaderToIceServers(
      '<stun:stun.example.com>; rel="ice-server", <turn:turn.example.com?transport=udp>; rel="ice-server"; username="alice"; credential="secret"; credential-type="password"'
    ),
    [
      { urls: ['stun:stun.example.com'] },
      {
        urls: ['turn:turn.example.com?transport=udp'],
        username: 'alice',
        credential: 'secret',
        credentialType: 'password',
      },
    ]
  )
})

test('parseOfferData and generateSdpFragment build a trickle ICE payload', () => {
  const offerData = parseOfferData(
    'v=0\r\n'
    + 'm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
    + 'a=ice-ufrag:testufrag\r\n'
    + 'a=ice-pwd:testpwd\r\n'
    + 'm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n'
  )

  const fragment = generateSdpFragment(offerData, [
    {
      sdpMLineIndex: 0,
      candidate: 'candidate:1 1 udp 2130706431 127.0.0.1 5000 typ host',
    },
  ])

  assert.equal(
    fragment,
    'a=ice-ufrag:testufrag\r\n'
      + 'a=ice-pwd:testpwd\r\n'
      + 'm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
      + 'a=mid:0\r\n'
      + 'a=candidate:1 1 udp 2130706431 127.0.0.1 5000 typ host\r\n'
  )
})
