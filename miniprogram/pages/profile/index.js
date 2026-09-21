const api = require('../../utils/api')

Page({
  data: {
    loading: true,
    loadError: '',
    profile: null,
    stats: { sent: 0, received: 0, unsigned: 0 },
    recent: [],
    bindName: '',
    bindPhone: '',
    bindToken: '',
    bindConflict: null,
    submitting: false
  },
  onShow() { this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  load() {
    this.setData({ loading: true, loadError: '' })
    return api.call('profile.get', {}, { loading: false, silent: true }).then((data) => {
      const profile = this.decorate(data.profile || {})
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
  decorate(profile) {
    profile.initial = (profile.nickname || '我').slice(0, 1)
    profile.identityText = profile.contactName || (profile.phoneNumber ? '资料已关联' : '尚未关联身份')
    return profile
  },
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
        const next = this.decorate({ ...this.data.profile, ...profile })
        getApp().globalData.profile = next
        this.setData({ profile: next })
        if (showLoading) wx.showToast({ title: '已保存' })
        return next
      })
  },
  bindNameInput(event) { this.setData({ bindName: event.detail.value }) },
  bindPhoneInput(event) { this.setData({ bindPhone: event.detail.value }) },
  verifyIdentity() {
    const name = this.data.bindName.trim()
    const phone = this.data.bindPhone.trim()
    if (!name) return wx.showToast({ title: '请输入姓名', icon: 'none' })
    if (!/^1\d{10}$/.test(phone.replace(/\D/g, ''))) return wx.showToast({ title: '请输入 11 位手机号', icon: 'none' })
    if (this.data.submitting) return
    this.setData({ submitting: true })
    api.call('profile.bindIdentity', { name, phone }, { title: '验证中', silent: true }).then((data) => {
      if (data.state === 'bound_self') {
        this.setData({ submitting: false, bindToken: '', bindConflict: null })
        return wx.showToast({ title: '该身份已绑定当前账号', icon: 'none' })
      }
      if (data.state === 'bound_other') {
        this.setData({ submitting: false })
        return wx.showModal({
          title: '身份已被绑定',
          content: `当前身份信息已被${data.boundNickname || '其他用户'}(${data.boundOpenid.slice(0, 12)}…)绑定，是否继续？继续将解绑原账户。`,
          confirmText: '继续绑定',
          cancelText: '取消',
          success: (res) => {
            if (!res.confirm) return
            this.setData({ submitting: true })
            api.call('profile.bindIdentity', { confirmToken: data.confirmToken, force: true, nickname: (this.data.profile.nickname || '').trim() }, { title: '绑定中', silent: true }).then((result) => {
              this.applyBoundProfile(result.profile)
              wx.showToast({ title: '绑定成功，已解绑原账户', icon: 'success' })
            }).catch((error) => {
              api.showError(error, '绑定失败')
            }).finally(() => this.setData({ submitting: false }))
          }
        })
      }
      // pending：提示确认绑定
      this.setData({ bindToken: data.confirmToken })
      wx.showModal({
        title: `绑定 ${data.contactName}`,
        content: `是否绑定${data.contactName}至当前${(this.data.profile.nickname || '').trim() || '微信用户'}？`,
        confirmText: '绑定',
        cancelText: '取消',
        success: (res) => {
          if (!res.confirm) { this.setData({ bindToken: '' }); return }
          this.setData({ submitting: true })
          api.call('profile.bindIdentity', { confirmToken: this.data.bindToken, nickname: (this.data.profile.nickname || '').trim() }, { title: '绑定中', silent: true }).then((result) => {
            this.applyBoundProfile(result.profile)
            wx.showToast({ title: '绑定成功', icon: 'success' })
          }).catch((error) => {
            api.showError(error, '绑定失败')
          }).finally(() => this.setData({ submitting: false, bindToken: '' }))
        }
      })
    }).catch((error) => {
      api.showError(error, '验证失败')
    }).finally(() => this.setData({ submitting: false }))
  },
  applyBoundProfile(raw) {
    const profile = this.decorate(raw)
    getApp().globalData.profile = profile
    this.setData({ profile, bindConflict: null, bindToken: '', bindName: '', bindPhone: '' })
  },
  settings() { wx.navigateTo({ url: '/pages/settings/index' }) },
  compose() { wx.navigateTo({ url: '/pages/compose/index' }) }
})
