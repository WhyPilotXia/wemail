const api = require('../../utils/api')
const { formatDate, defaultDeadline } = require('../../utils/date')

Page({
  data: { tab: 'lottery', events: [], isAdmin: false, loading: true, showForm: false, form: { title: '', description: '', deadline: defaultDeadline(), limit: '' } },
  onLoad(query) { this.setData({ tab: query.type || 'lottery' }); this.load() },
  onPullDownRefresh() { this.load().finally(() => wx.stopPullDownRefresh()) },
  load() {
    return api.call('events.list', { type: this.data.tab }, { loading: false, silent: true }).then((data) => {
      const events = Array.isArray(data) ? data : (data.events || [])
      this.setData({ events: events.map((item) => ({ ...item, deadlineText: formatDate(item.deadline, true) })), isAdmin: Boolean(data && data.isAdmin), loading: false })
    }).catch(() => this.setData({ loading: false, events: [], isAdmin: false }))
  },
  changeTab(event) { this.setData({ tab: event.currentTarget.dataset.tab, showForm: false, loading: true }); this.load() },
  toggleForm() {
    if (!this.data.isAdmin) return
    this.setData({ showForm: !this.data.showForm })
  },
  input(event) { this.setData({ [`form.${event.currentTarget.dataset.key}`]: event.detail.value }) },
  changeDate(event) { this.setData({ 'form.deadline': `${event.detail.value} 20:00` }) },
  create() {
    if (!this.data.isAdmin) return wx.showToast({ title: '仅管理员可发布活动', icon: 'none' })
    const form = this.data.form
    if (!form.title.trim()) return wx.showToast({ title: '请填写标题', icon: 'none' })
    api.call('events.create', { type: this.data.tab, ...form, limit: Number(form.limit) || 0 }, { title: '正在发布' }).then(() => {
      wx.showToast({ title: '发布成功' })
      this.setData({ showForm: false, form: { title: '', description: '', deadline: defaultDeadline(), limit: '' } })
      this.load()
    }).catch(() => {})
  },
  join(event) { api.call('events.join', { eventId: event.currentTarget.dataset.id }, { title: '报名中' }).then(() => { wx.showToast({ title: '参与成功' }); this.load() }).catch(() => {}) },
  draw(event) { api.call('events.draw', { eventId: event.currentTarget.dataset.id }, { title: '开奖中' }).then((data) => { wx.showModal({ title: '开奖结果', content: data.winnerName ? `恭喜 ${data.winnerName}` : '暂无参与者', showCancel: false }); this.load() }).catch(() => {}) }
})
