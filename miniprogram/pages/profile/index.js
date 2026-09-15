const api = require('../../utils/api')

Page({
  data: { loading: true, loadError: '', profile: null, stats: { sent: 0, received: 0, unsigned: 0 }, recent: [] },
  onShow() { this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  load() {
    this.setData({ loading: true, loadError: '' })
    return api.call('profile.get', {}, { loading: false, silent: true }).then((data) => {
      const profile = data.profile || {}
      profile.initial = (profile.nickname || '我').slice(0, 1)
      profile.identityText = profile.contactName || (profile.phoneMasked ? '手机号已绑定' : '尚未匹配联系人')
      getApp().globalData.profile = profile
      getApp().globalData.openid = data.openid
      this.setData({ ...data, profile, loading: false, loadError: '' })
    }).catch((error) => {
      const loadError = api.describeError(error)
      this.setData({ loading: false, loadError })
      api.showError(error, '个人资料获取失败')
    })
  },
  retryLoad() { this.load() },
  chooseAvatar(event) {
    const tempFilePath = event.detail.avatarUrl
    wx.showLoading({ title: '处理头像', mask: true })
    wx.compressImage({ src: tempFilePath, quality: 35 }).then(({ tempFilePath: compressedPath }) => {
      return new Promise((resolve, reject) => {
        wx.getFileSystemManager().readFile({
          filePath: compressedPath,
          encoding: 'base64',
          success: ({ data }) => resolve(`data:image/jpeg;base64,${data}`),
          fail: reject
        })
      })
    }).then((avatarData) => {
      if (avatarData.length > 64000) throw new Error('头像仍然过大，请裁剪后重试')
      this.setData({ 'profile.avatarUrl': avatarData })
      return this.save({ avatarData }, false)
    }).then(() => wx.showToast({ title: '头像已保存' }))
      .catch((error) => wx.showToast({ title: error.message || '头像上传失败', icon: 'none' }))
      .finally(() => wx.hideLoading())
  },
  nickname(event) { this.setData({ 'profile.nickname': event.detail.value }) },
  saveNickname(event) {
    const nickname = String((event && event.detail && event.detail.value) || this.data.profile.nickname || '').trim()
    this.setData({ 'profile.nickname': nickname })
    return this.save({ nickname }).catch(() => {})
  },
  save(patch, showLoading = true) {
    return api.call('profile.update', { patch }, { title: '保存中', loading: showLoading })
      .then((profile) => {
        const next = { ...this.data.profile, ...profile }
        next.initial = (next.nickname || '我').slice(0, 1)
        next.identityText = next.contactName || (next.phoneMasked ? '手机号已绑定' : '尚未匹配联系人')
        getApp().globalData.profile = next
        this.setData({ profile: next })
        if (showLoading) wx.showToast({ title: '已保存' })
        return next
      })
  },
  getPhone(event) {
    if (!event.detail.code) {
      const detail = event.detail.errMsg || '微信未返回授权凭证'
      const message = detail.includes('deny') ? '你已取消手机号授权' : `手机号能力不可用：${detail}`
      return wx.showModal({ title: '无法获取手机号', content: message, showCancel: false })
    }
    api.call('profile.bindPhone', { code: event.detail.code }, { title: '匹配联系人' }).then((data) => {
      const profile = data.profile
      profile.initial = (profile.nickname || '我').slice(0, 1)
      profile.identityText = profile.contactName || '手机号已绑定'
      this.setData({ profile })
      wx.showToast({ title: profile.contactId ? '匹配成功' : '手机号已绑定', icon: 'success' })
    }).catch(() => {})
  },
  settings() { wx.navigateTo({ url: '/pages/settings/index' }) },
  compose() { wx.navigateTo({ url: '/pages/compose/index' }) }
})
