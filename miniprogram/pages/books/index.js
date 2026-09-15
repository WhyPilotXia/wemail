const api = require('../../utils/api')
const sourceBooks = require('../../data/books')

Page({
  data: { books: sourceBooks },
  onShow() { this.loadProgress() },
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
            readText: progress.completed ? '重新阅读 →' : chapterIndex > 0 ? `继续第 ${chapterIndex + 1} 章 →` : '开始阅读 →'
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
