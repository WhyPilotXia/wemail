const api = require('../../utils/api')
const sourceBooks = require('../../data/books')

Page({
  data: { books: sourceBooks, checking: true, allowed: false, gateError: '' },
  onShow() { this.checkAccess() },
  checkAccess() {
    const cached = getApp().globalData.profile
    if (cached && cached.contactId) {
      this.setData({ checking: false, allowed: true, gateError: '' })
      this.loadProgress()
      return
    }
    this.setData({ checking: true, gateError: '' })
    api.call('profile.get', {}, { loading: false, silent: true }).then((data) => {
      const profile = (data && data.profile) || {}
      getApp().globalData.profile = profile
      getApp().globalData.openid = data.openid
      const allowed = Boolean(profile.contactId)
      this.setData({ checking: false, allowed, gateError: '' })
      if (allowed) this.loadProgress()
    }).catch((error) => {
      this.setData({ checking: false, allowed: false, gateError: api.describeError(error) })
    })
  },
  retryAccess() { this.checkAccess() },
  goVerify() { wx.switchTab({ url: '/pages/profile/index' }) },
  loadProgress() {
    Promise.all(sourceBooks.map((book) => api.call('reading.get', { book: book.key }, { loading: false, silent: true }).catch(() => ({}))))
      .then((progressList) => {
        const books = sourceBooks.map((book, index) => {
          const progress = progressList[index] || {}
          const chapterIndex = Math.max(0, Number(progress.chapterIndex) || 0)
          const percentage = Math.round((Number(progress.progress) || 0) * 100)
          return {
            ...book,
            chapterIndex,
            percentage,
            completed: Boolean(progress.completed),
            readText: progress.completed ? '重新查看 →' : chapterIndex > 0 ? `继续第 ${chapterIndex + 1} 篇 →` : '进入查看 →'
          }
        })
        this.setData({ books })
      })
  },
  open(event) {
    const book = this.data.books.find((item) => item.key === event.currentTarget.dataset.key)
    const chapter = book ? book.chapterIndex : 0
    wx.navigateTo({ url: `/pages/reader/index?book=${encodeURIComponent(event.currentTarget.dataset.key)}&chapter=${chapter}` })
  }
})
