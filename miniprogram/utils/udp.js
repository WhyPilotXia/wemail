const config = require('../config')
const pako = require('./pako_inflate.min')

const CHUNK_SIZE = 12000
const TIMEOUT_MS = 10000
const MAX_ATTEMPTS = 4
const SESSION_KEY = 'wemail_udp_session'

let socket = null
let localPort = 0
const pending = new Map()

function log(event, detail = {}) {
  console.info(`[UDP] ${event}`, detail)
}

function errorWithDetail(message, detail = {}) {
  const error = new Error(message)
  Object.assign(error, detail)
  return error
}

function id() {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`
}

function bytesToUtf8(buffer) {
  const bytes = new Uint8Array(buffer)
  let encoded = ''
  for (let index = 0; index < bytes.length; index += 1) encoded += `%${bytes[index].toString(16).padStart(2, '0')}`
  try {
    return decodeURIComponent(encoded)
  } catch (error) {
    return ''
  }
}

function makePackets(requestId, payload) {
  const text = JSON.stringify({ ...payload, timestamp: Date.now() })
  const total = Math.ceil(text.length / CHUNK_SIZE) || 1
  const packets = []
  for (let part = 0; part < total; part += 1) {
    packets.push(JSON.stringify({
      v: 2,
      t: 'q',
      id: requestId,
      p: part,
      n: total,
      d: text.slice(part * CHUNK_SIZE, (part + 1) * CHUNK_SIZE)
    }))
  }
  return packets
}

function ensureSocket() {
  if (socket) return socket
  if (typeof wx.createUDPSocket !== 'function') throw new Error('当前微信版本不支持 UDP')
  socket = wx.createUDPSocket()
  socket.onMessage(onMessage)
  socket.onError((error) => {
    const message = (error && (error.errMsg || error.message)) || 'UDP 网络错误'
    console.error('[UDP] socket error', { message, localPort })
    pending.forEach((state, requestId) => {
      clearTimeout(state.timer)
      state.reject(errorWithDetail(`UDP Socket 异常：${message}`, { requestId, action: state.action, attempts: state.attempt, elapsed: Date.now() - state.startedAt }))
    })
    pending.clear()
  })
  localPort = socket.bind()
  log('socket ready', { localPort, remote: `${config.udpHost}:${config.udpPort}` })
  return socket
}

function onMessage({ message }) {
  let packet
  try {
    packet = JSON.parse(bytesToUtf8(message))
  } catch (error) {
    return
  }
  if (!packet || packet.v !== 2 || packet.t !== 's' || !pending.has(packet.id)) return
  const state = pending.get(packet.id)
  state.parts[packet.p] = packet.d
  if (state.parts.filter((item) => item !== undefined).length !== packet.n) return
  clearTimeout(state.timer)
  pending.delete(packet.id)
  try {
    const joined = state.parts.join('')
    const text = packet.z === 1
      ? bytesToUtf8(pako.inflate(new Uint8Array(wx.base64ToArrayBuffer(joined))))
      : joined
    const response = JSON.parse(text)
    log('response', { requestId: packet.id, action: state.action, attempt: state.attempt, elapsed: Date.now() - state.startedAt, packets: packet.n, ok: response.ok })
    state.resolve(response)
  } catch (error) {
    console.error('[UDP] response parse failed', { requestId: packet.id, action: state.action, message: error.message })
    state.reject(errorWithDetail('服务器响应解析失败', { requestId: packet.id, action: state.action, attempts: state.attempt, elapsed: Date.now() - state.startedAt }))
  }
}

function sendPackets(list) {
  const udp = ensureSocket()
  list.forEach((message) => udp.send({ address: config.udpHost, port: config.udpPort, message }))
}

function request(payload, options = {}) {
  const requestId = options.requestId || id()
  const packets = makePackets(requestId, payload)
  const action = payload.action || 'unknown'
  return new Promise((resolve, reject) => {
    const state = { resolve, reject, parts: [], attempt: 0, timer: null, action, startedAt: Date.now() }
    const transmit = () => {
      state.attempt += 1
      log('send', { requestId, action, attempt: state.attempt, packets: packets.length, localPort, remote: `${config.udpHost}:${config.udpPort}` })
      try {
        sendPackets(packets)
      } catch (error) {
        pending.delete(requestId)
        reject(errorWithDetail(`UDP 发包失败：${error.message || error}`, { requestId, action, attempts: state.attempt, elapsed: Date.now() - state.startedAt }))
        return
      }
      state.timer = setTimeout(() => {
        if (!pending.has(requestId)) return
        if (state.attempt < (options.attempts || MAX_ATTEMPTS)) {
          log('retry', { requestId, action, nextAttempt: state.attempt + 1, elapsed: Date.now() - state.startedAt })
          transmit()
        } else {
          pending.delete(requestId)
          const elapsed = Date.now() - state.startedAt
          reject(errorWithDetail(`服务器 ${config.udpHost}:${config.udpPort} 未在 ${elapsed} ms 内返回，已发送 ${state.attempt} 次`, { requestId, action, attempts: state.attempt, elapsed }))
        }
      }, options.timeout || TIMEOUT_MS)
    }
    pending.set(requestId, state)
    transmit()
  })
}

function wxLogin() {
  return new Promise((resolve, reject) => wx.login({ success: resolve, fail: reject }))
}

async function login(force = false) {
  if (!force) {
    const cached = wx.getStorageSync(SESSION_KEY)
    if (cached && cached.token && Number(cached.expiresAt) > Date.now() + 60000) return cached
  }
  const result = await wxLogin()
  if (!result.code) throw new Error('微信登录未返回临时凭证')
  const response = await request({ action: 'auth.login', code: result.code }, { attempts: 2 })
  if (!response.ok) throw new Error(response.message || '登录失败')
  wx.setStorageSync(SESSION_KEY, response.data)
  return response.data
}

async function call(action, data = {}) {
  let session = await login(false)
  let response = await request({ action, token: session.token, ...data })
  if (!response.ok && response.code === 'UNAUTHORIZED') {
    session = await login(true)
    response = await request({ action, token: session.token, ...data })
  }
  return response
}

function echo() {
  const requestId = id()
  const message = JSON.stringify({ type: 'wemail-udp-echo', requestId })
  const startedAt = Date.now()
  return new Promise((resolve, reject) => {
    const testSocket = wx.createUDPSocket()
    let timer
    let boundPort = 0
    const close = () => {
      if (timer) clearTimeout(timer)
      try { testSocket.close() } catch (error) {}
    }
    testSocket.onMessage(({ message: response, remoteInfo }) => {
      const text = bytesToUtf8(response)
      close()
      if (text !== message) return reject(new Error('收到回包，但内容不一致'))
      resolve({ elapsed: Date.now() - startedAt, localPort: boundPort, remote: remoteInfo ? `${remoteInfo.address}:${remoteInfo.port}` : `${config.udpHost}:${config.udpPort}` })
    })
    testSocket.onError((error) => {
      close()
      reject(new Error((error && (error.errMsg || error.message)) || 'UDP 网络错误'))
    })
    boundPort = testSocket.bind()
    testSocket.send({ address: config.udpHost, port: config.udpPort, message })
    timer = setTimeout(() => {
      close()
      reject(new Error(`已向 ${config.udpHost}:${config.udpPort} 发包，但 5 秒内没有收到响应`))
    }, TIMEOUT_MS)
  })
}

function close() {
  if (socket) {
    try { socket.close() } catch (error) {}
    socket = null
    localPort = 0
  }
}

module.exports = { call, echo, close, getLocalPort: () => localPort }
