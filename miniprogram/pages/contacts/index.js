const api = require('../../utils/api')

Page({
  data: { contacts: [], filtered: [], keyword: '', loading: true, loadError: '' },
  onLoad() { this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  load() {
    this.setData({ loading: true, loadError: '' })
    return api.call('contacts.list', {}, { loading: false, silent: true }).then((contacts) => {
      this.setData({ contacts, filtered: contacts, loading: false, loadError: '' })
    }).catch((error) => {
      this.setData({ loading: false, contacts: [], filtered: [], loadError: api.describeError(error) })
      api.showError(error, '通讯录获取失败')
    })
  },
  retryLoad() { this.load() },
  search(event) {
    const keyword = event.detail.value.trim().toLowerCase()
    this.setData({ keyword, filtered: this.data.contacts.filter((contact) => `${contact.name}${contact.phone || ''}${contact.qq || ''}`.toLowerCase().includes(keyword)) })
  },
  copy(event) { wx.setClipboardData({ data: event.currentTarget.dataset.value || '' }) }
})
