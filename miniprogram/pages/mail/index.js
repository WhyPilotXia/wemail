const api = require('../../utils/api')
const { formatDate } = require('../../utils/date')

Page({
  data: { loading: true, loadError: '', filter: 'all', records: [], displayRecords: [], stats: { sent: 0, received: 0, unsigned: 0 } },
  onShow() { this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  load() {
    this.setData({ loading: true, loadError: '' })
    return api.call('mail.list', {}, { loading: false, silent: true }).then((data) => {
      const records = (data.records || []).map((item) => ({ ...item, dateText: formatDate(item.sendDate) }))
      this.setData({ records, stats: data.stats || { sent: 0, received: 0, unsigned: 0 }, loading: false, loadError: '' })
      this.applyFilter(this.data.filter)
    }).catch((error) => {
        const loadError = api.isExpectedError(error) ? '请先在“我的”中输入姓名与手机号关联联系人身份' : api.describeError(error)
      this.setData({ loading: false, records: [], displayRecords: [], loadError })
      api.showError(error, '信件获取失败')
    })
  },
  retryLoad() { this.load() },
  setFilter(event) { this.applyFilter(event.currentTarget.dataset.filter) },
  applyFilter(filter) {
    const openid = getApp().globalData.openid
    const displayRecords = this.data.records.filter((item) => {
      if (filter === 'unsigned') return !item.received
      if (filter === 'sent') return !openid || item.senderOpenid === openid || item.direction === 'sent'
      if (filter === 'received') return !openid || item.recipientOpenid === openid || item.direction === 'received'
      return true
    })
    this.setData({ filter, displayRecords })
  },
  compose() { wx.navigateTo({ url: '/pages/compose/index' }) },
  contacts() { wx.navigateTo({ url: '/pages/contacts/index' }) },
  sign(event) {
    api.call('mail.sign', { pageId: event.currentTarget.dataset.id }, { title: '签收中' }).then(() => {
      wx.showToast({ title: '已签收', icon: 'success' })
      this.load()
    }).catch(() => {})
  }
})
