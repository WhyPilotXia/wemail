const api = require('../../utils/api')
const udp = require('../../utils/udp')
const config = require('../../config')

const CONTACT_KEYS = ['phone', 'email', 'qq', 'address1', 'postcode1', 'address2', 'postcode2']

Page({
  data: {
    profile: { nickname: '' },
    contact: { name: '' },
    fields: { phone: '', email: '', qq: '', address1: '', postcode1: '', address2: '', postcode2: '' },
    bound: false,
    saving: false,
    udpHost: config.udpHost,
    udpPort: config.udpPort,
    testing: false,
    udpStatus: 'idle',
    udpStatusText: '尚未测试',
    udpDetail: ''
  },
  onLoad() {
    api.call('profile.get', {}, { loading: true }).then((data) => {
      const profile = data.profile || {}
      const fields = {}
      CONTACT_KEYS.forEach((key) => {
        fields[key] = profile[`contact${key.charAt(0).toUpperCase()}${key.slice(1)}`] || ''
      })
      this.setData({
        profile: { nickname: profile.nickname || '' },
        contact: { name: profile.contactName || '' },
        fields,
        bound: !!profile.contactId
      })
    }).catch(() => {})
  },
  input(event) {
    const key = event.currentTarget.dataset.key
    if (key === 'nickname') {
      this.setData({ 'profile.nickname': event.detail.value })
    } else {
      this.setData({ [`fields.${key}`]: event.detail.value })
    }
  },
  save() {
    if (this.data.saving) return
    const { nickname } = this.data.profile
    if (!nickname.trim()) return wx.showToast({ title: '请填写昵称', icon: 'none' })
    const fields = this.data.fields
    const phone = (fields.phone || '').replace(/\s/g, '')
    if (phone && !/^1\d{10}$/.test(phone)) return wx.showToast({ title: '手机号需为 11 位数字', icon: 'none' })
    const email = (fields.email || '').trim()
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return wx.showToast({ title: '邮箱格式不正确', icon: 'none' })
    const patch = { nickname }
    if (this.data.bound) CONTACT_KEYS.forEach((key) => { patch[key] = (fields[key] || '').trim() })
    this.setData({ saving: true })
    api.call('profile.update', { patch }, { title: '保存中', silent: true }).then(() => {
      wx.showToast({ title: '已保存并同步 Notion' })
      setTimeout(() => wx.navigateBack(), 600)
    }).catch((error) => {
      api.showError(error, '保存失败')
    }).finally(() => this.setData({ saving: false }))
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
