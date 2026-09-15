App({
  onLaunch() {
    if (typeof wx.createUDPSocket !== 'function') {
      wx.showModal({ title: '版本过低', content: '请升级微信后重试', showCancel: false })
    }
  },
  globalData: {
    profile: null,
    bootstrap: null,
    openid: ''
  }
})
