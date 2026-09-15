const api = require('../../utils/api')
const udp = require('../../utils/udp')
const config = require('../../config')

Page({
  data: {
    profile: { nickname: '', address: '', postcode: '' },
    udpHost: config.udpHost,
    udpPort: config.udpPort,
    testing: false,
    udpStatus: 'idle',
    udpStatusText: '尚未测试',
    udpDetail: ''
  },
  onLoad() {
    api.call('profile.get', {}, { loading: true }).then((data) => this.setData({ profile: data.profile })).catch(() => {})
  },
  input(event) {
    this.setData({ [`profile.${event.currentTarget.dataset.key}`]: event.detail.value })
  },
  save() {
    const { nickname, address, postcode } = this.data.profile
    api.call('profile.update', { patch: { nickname, address, postcode } }, { title: '保存中' }).then(() => {
      wx.showToast({ title: '已保存' })
      setTimeout(() => wx.navigateBack(), 500)
    }).catch(() => {})
  },
  testUdp() {
    if (this.data.testing) return
    this.setData({ testing: true, udpStatus: 'testing', udpStatusText: '正在等待服务器回包...', udpDetail: '' })
    const startedAt = Date.now()
    udp.echo().then((result) => {
      this.setData({
        testing: false,
        udpStatus: 'success',
        udpStatusText: 'UDP 收发成功',
        udpDetail: `往返 ${result.elapsed} ms · 本地端口 ${result.localPort} · ${result.remote}`
      })
    }).catch((error) => {
      this.setData({
        testing: false,
        udpStatus: 'failed',
        udpStatusText: 'UDP 测试失败',
        udpDetail: `${Date.now() - startedAt} ms · ${error.message || error}`
      })
    })
  }
})
