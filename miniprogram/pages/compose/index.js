const api = require('../../utils/api')
const { formatDate } = require('../../utils/date')

function prepare(contact) {
  const phone = String(contact.phone || '').trim()
  return { ...contact, pickerLabel: phone ? `${contact.name} · ${phone}` : contact.name }
}

Page({
  data: { contacts: [], mailTypes: ['平信', '挂号信', '明信片', '包裹'], recipientIndex: -1, senderIndex: -1, form: { sendDate: formatDate(new Date()), mailType: '平信', trackingNo: '' }, submitting: false },
  onLoad() {
    api.call('contacts.list', {}, { title: '读取通讯录' }).then((contacts) => {
      const prepared = contacts.map(prepare)
      const senderIndex = prepared.findIndex((item) => item.isMe)
      this.setData({ contacts: prepared, senderIndex })
    }).catch(() => {})
  },
  selectRecipient(event) {
    this.setData({ recipientIndex: Number(event.detail.value) })
  },
  selectSender(event) {
    this.setData({ senderIndex: Number(event.detail.value) })
  },
  openPostage() { wx.navigateTo({ url: '/pages/postage/index' }) },
  changeDate(event) { this.setData({ 'form.sendDate': event.detail.value }) },
  changeType(event) { this.setData({ 'form.mailType': this.data.mailTypes[Number(event.detail.value)] }) },
  input(event) { this.setData({ [`form.${event.currentTarget.dataset.key}`]: event.detail.value }) },
  scanTracking() {
    wx.scanCode({
      onlyFromCamera: false,
      scanType: ['barCode', 'qrCode'],
      success: (res) => {
        const code = String(res.result || '').trim()
        if (!code) return wx.showToast({ title: '未识别到编号内容', icon: 'none' })
        if (!/^[A-Za-z0-9-]+$/.test(code)) return wx.showToast({ title: '编号仅支持字母、数字和连字符', icon: 'none' })
        this.setData({ 'form.trackingNo': code })
        wx.showToast({ title: '已填入邮件编号', icon: 'success' })
      },
      fail: (err) => {
        if (err && err.errMsg && err.errMsg.includes('cancel')) return
        wx.showToast({ title: '扫码失败，请重试', icon: 'none' })
      }
    })
  },
  submit() {
    const { recipientIndex, senderIndex, contacts, form } = this.data
    if (recipientIndex < 0 || senderIndex < 0) return wx.showToast({ title: '请选择寄件人和收件人', icon: 'none' })
    if (recipientIndex === senderIndex) return wx.showToast({ title: '寄件人与收件人不能相同', icon: 'none' })
    const recipient = contacts[recipientIndex]
    if (!recipient.address1 && !recipient.address2) return wx.showToast({ title: '收件人没有可用地址', icon: 'none' })
    if (form.trackingNo && !/^[A-Za-z0-9-]+$/.test(form.trackingNo.trim())) return wx.showToast({ title: '邮件编号仅支持字母、数字和连字符', icon: 'none' })
    this.setData({ submitting: true })
    api.call('mail.create', { ...form, trackingNo: form.trackingNo.trim(), senderId: contacts[senderIndex].id, recipientId: recipient.id }, { title: '正在保存' }).then(() => {
      wx.showToast({ title: '寄件记录已保存', icon: 'success' })
      setTimeout(() => wx.navigateBack(), 700)
    }).catch(() => {}).finally(() => this.setData({ submitting: false }))
  }
})
