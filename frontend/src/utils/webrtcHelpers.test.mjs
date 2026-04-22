import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildBasicAuthHeader,
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

test('buildBasicAuthHeader encodes username and password', () => {
  assert.deepEqual(buildBasicAuthHeader('alice', 'secret'), {
    Authorization: 'Basic YWxpY2U6c2VjcmV0',
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
