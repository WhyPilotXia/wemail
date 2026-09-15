const api = require('../../utils/api')
const { formatDate } = require('../../utils/date')

Page({
  data: { contacts: [], mailTypes: ['平信', '挂号信', '明信片', '包裹'], recipientIndex: -1, senderIndex: -1, form: { sendDate: formatDate(new Date()), mailType: '平信', trackingNo: '', title: '' }, submitting: false },
  onLoad() {
    api.call('contacts.list', {}, { title: '读取通讯录' }).then((contacts) => {
      this.setData({ contacts, senderIndex: contacts.findIndex((item) => item.isMe) })
    }).catch(() => {})
  },
  selectRecipient(event) { this.setData({ recipientIndex: Number(event.detail.value) }) },
  selectSender(event) { this.setData({ senderIndex: Number(event.detail.value) }) },
  changeDate(event) { this.setData({ 'form.sendDate': event.detail.value }) },
  changeType(event) { this.setData({ 'form.mailType': this.data.mailTypes[Number(event.detail.value)] }) },
  input(event) { this.setData({ [`form.${event.currentTarget.dataset.key}`]: event.detail.value }) },
  submit() {
    const { recipientIndex, senderIndex, contacts, form } = this.data
    if (recipientIndex < 0 || senderIndex < 0) return wx.showToast({ title: '请选择寄件人和收件人', icon: 'none' })
    this.setData({ submitting: true })
    api.call('mail.create', { ...form, senderId: contacts[senderIndex].id, recipientId: contacts[recipientIndex].id }, { title: '正在寄出' }).then(() => {
      wx.showToast({ title: '已记录', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 700)
    }).catch(() => {}).finally(() => this.setData({ submitting: false }))
  }
})
