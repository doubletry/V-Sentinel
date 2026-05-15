import test from 'node:test'
import assert from 'node:assert/strict'

import { connectWebRTC } from './webrtc.js'

test('connectWebRTC sends a single POST offer with application/sdp', async () => {
  const calls = []

  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options })

    if (options.method === 'POST') {
      return {
        status: 201,
        text: async () => 'v=0\r\n',
        headers: {
          get(name) {
            return name.toLowerCase() === 'location' ? '/session/abc' : null
          },
        },
      }
    }

    throw new Error(`Unexpected method: ${options.method}`)
  }

  class MockPeerConnection {
    constructor(config) {
      this.config = config
      this.connectionState = 'new'
    }

    addTransceiver() {}

    createDataChannel() {}

    async createOffer() {
      return {
        sdp:
          'v=0\r\n'
          + 'm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
          + 'a=ice-ufrag:testufrag\r\n'
          + 'a=ice-pwd:testpwd\r\n'
          + 'm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n',
      }
    }

    async setLocalDescription(description) {
      this.localDescription = description
    }

    async setRemoteDescription(description) {
      this.remoteDescription = description
    }

    close() {}
  }

  globalThis.RTCPeerConnection = MockPeerConnection

  const connection = await connectWebRTC('cam1', null, 'http://localhost:8889', {
    username: 'alice',
    password: 'secret',
  })

  assert.ok(connection)
  assert.deepEqual(connection.pc.config.iceServers, [])
  assert.equal(calls.length, 1)
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(calls[0].options.headers.Authorization, 'Basic YWxpY2U6c2VjcmV0')
  assert.equal(calls[0].options.headers['Content-Type'], 'application/sdp')
})

test('connectWebRTC queues ICE candidates emitted during setLocalDescription', async () => {
  const calls = []

  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, options })

    if (options.method === 'POST') {
      return {
        status: 201,
        text: async () => 'v=0\r\n',
        headers: {
          get(name) {
            return name.toLowerCase() === 'location' ? '/session/queued' : null
          },
        },
      }
    }

    if (options.method === 'PATCH') {
      return { status: 204 }
    }

    throw new Error(`Unexpected method: ${options.method}`)
  }

  class MockPeerConnection {
    constructor() {
      this.connectionState = 'new'
      this.onicecandidate = null
    }

    addTransceiver() {}

    createDataChannel() {}

    async createOffer() {
      return {
        sdp:
          'v=0\r\n'
          + 'm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
          + 'a=ice-ufrag:testufrag\r\n'
          + 'a=ice-pwd:testpwd\r\n',
      }
    }

    async setLocalDescription(description) {
      this.localDescription = description
      this.onicecandidate?.({
        candidate: {
          candidate: 'candidate:1 1 UDP 2130706431 192.0.2.10 54400 typ host',
          sdpMid: '0',
          sdpMLineIndex: 0,
        },
      })
    }

    async setRemoteDescription(description) {
      this.remoteDescription = description
    }

    close() {}
  }

  globalThis.RTCPeerConnection = MockPeerConnection

  const connection = await connectWebRTC('cam1', null, 'http://localhost:8889')

  assert.ok(connection)
  assert.equal(calls.length, 2)
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(calls[1].options.method, 'PATCH')
  assert.match(calls[1].options.body, /candidate:1 1 UDP 2130706431 192\.0\.2\.10 54400 typ host/)
})
