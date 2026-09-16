const api = require('../../utils/api')

function text(value) {
  return String(value || '').trim()
}

function prepare(contact) {
  const fields = ['name', 'phone', 'email', 'qq', 'address1', 'postcode1', 'address2', 'postcode2']
  const item = { ...contact }
  item.searchText = fields.map((key) => text(item[key])).join(' ').toLowerCase()
  item.copyText = [
    `姓名：${text(item.name)}`,
    item.phone ? `电话：${text(item.phone)}` : '',
    item.email ? `邮箱：${text(item.email)}` : '',
    item.qq ? `QQ：${text(item.qq)}` : '',
    item.address1 || item.postcode1 ? `地址1：${text(item.postcode1)} ${text(item.address1)}`.trim() : '',
    item.address2 || item.postcode2 ? `地址2：${text(item.postcode2)} ${text(item.address2)}`.trim() : ''
  ].filter(Boolean).join('\n')
  return item
}

Page({
  data: { contacts: [], filtered: [], keyword: '', loading: true, loadError: '' },
  onLoad() { this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  load() {
    this.setData({ loading: true, loadError: '' })
    return api.call('contacts.list', {}, { loading: false, silent: true }).then((contacts) => {
      const prepared = contacts.map(prepare)
      this.setData({ contacts: prepared, filtered: prepared, loading: false, loadError: '' })
    }).catch((error) => {
      this.setData({ loading: false, contacts: [], filtered: [], loadError: api.describeError(error) })
      api.showError(error, '通讯录获取失败')
    })
  },
  retryLoad() { this.load() },
  search(event) {
    const keyword = event.detail.value.trim().toLowerCase()
    this.setData({ keyword, filtered: this.data.contacts.filter((contact) => contact.searchText.includes(keyword)) })
  },
  copy(event) { wx.setClipboardData({ data: event.currentTarget.dataset.value || '' }) }
})
