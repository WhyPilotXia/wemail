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

function isExpectedError(error) {
  if (error && error.code === 'IDENTITY_REQUIRED') return true
  const message = String((error && error.message) || '')
  return ['仅限已关联联系人身份', '请先在‘我的’中关联联系人身份', '请先在‘我的’中输入姓名与手机号', '仅限联系人表中已登记手机号'].some((text) => message.includes(text))
}

function showError(error, title = '获取失败') {
  console.error('[API] request failed', { message: error && error.message, requestId: error && error.requestId, action: error && error.action, attempts: error && error.attempts, elapsed: error && error.elapsed })
  if (isExpectedError(error)) return
  wx.showModal({ title, content: describeError(error), showCancel: false })
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

module.exports = { call, describeError, isExpectedError, showError }
