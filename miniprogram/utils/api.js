const udp = require('./udp')

function describeError(error) {
  const message = (error && error.message) || '未知错误'
  const requestId = error && (error.requestId || error.requestID)
  const action = error && error.action
  const details = []
  if (action) details.push(`接口：${action}`)
  if (requestId) details.push(`请求ID：${requestId}`)
  return details.length ? `${message}\n${details.join(' · ')}` : message
}

function showError(error, title = '获取失败') {
  const content = describeError(error)
  console.error('[API] request failed', { message: error && error.message, requestId: error && error.requestId, action: error && error.action, attempts: error && error.attempts, elapsed: error && error.elapsed })
  wx.showModal({ title, content, showCancel: false })
}

function call(action, data = {}, options = {}) {
  if (options.loading !== false) wx.showLoading({ title: options.title || '加载中', mask: true })
  return udp.call(action, data).then((result) => {
    if (!result || result.ok === false) {
      const error = new Error((result && result.message) || '服务器返回空响应')
      error.code = result && result.code
      error.requestId = result && result.requestId
      error.action = action
      throw error
    }
    return result.data
  }).catch((error) => {
    if (!error.action) error.action = action
    if (!options.silent) showError(error, options.errorTitle || '操作失败')
    throw error
  }).finally(() => {
    if (options.loading !== false) wx.hideLoading()
  })
}

module.exports = { call, describeError, showError }
