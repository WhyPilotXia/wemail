const api = require('../../utils/api')

const loaders = {
  李氏庄园: () => require('../../data/books/李氏庄园'),
  回信券风暴: () => require('../../data/books/回信券风暴'),
  股神牛久盛: () => require('../../data/books/股神牛久盛'),
  名将之后: () => require('../../data/books/名将之后'),
  心非黍离专栏: () => require('../../data/books/心非黍离专栏')
}

const imageSources = {
  李氏庄园: {
    'assets/image.png': '/assets/books/李氏庄园/image-optimized.jpg',
    'assets/22091.jpg': '/assets/books/李氏庄园/22091.jpg',
    'assets/22092.jpg': '/assets/books/李氏庄园/22092.jpg',
    'assets/22863.jpg': '/assets/books/李氏庄园/22863.jpg',
    'assets/24939.jpg': '/assets/books/李氏庄园/24939.jpg'
  },
  股神牛久盛: {
    'assets/24159.jpg': '/assets/books/股神牛久盛/24159.jpg'
  },
  心非黍离专栏: {
    'assets/xinfei.jpg': '/assets/books/心非黍离专栏/xinfei.jpg'
  },
  名将之后: {
    'assets/22834.jpg': '/assets/books/名将之后/22834-optimized.jpg'
  }
}

function renderContent(book, content) {
  const blocks = []
  const source = String(content || '')
  const pattern = /!\[([^\]]*)\]\(([^)]+)\)/g
  let cursor = 0
  let match
  while ((match = pattern.exec(source))) {
    if (match.index > cursor) blocks.push({ type: 'text', content: source.slice(cursor, match.index) })
    const path = (imageSources[book] || {})[match[2]]
    if (path) blocks.push({ type: 'image', src: path, alt: match[1] || '正文图片' })
    else blocks.push({ type: 'text', content: match[0] })
    cursor = match.lastIndex
  }
  if (cursor < source.length) blocks.push({ type: 'text', content: source.slice(cursor, source.length) })
  return blocks.length ? blocks : [{ type: 'text', content: source }]
}

function prepareChapter(book, chapter) {
  return chapter ? { ...chapter, blocks: renderContent(book, chapter.content) } : null
}

Page({
  data: { book: '', chapters: [], index: 0, current: null, showCatalog: false, fontSize: 36, loaded: false, checking: true, allowed: false, gateError: '' },
  onLoad(query) {
    const book = decodeURIComponent(query.book || '')
    this.bookName = book
    wx.setNavigationBarTitle({ title: book || '文集' })
    this.checkAccess(query)
  },
  checkAccess(query) {
    const cached = getApp().globalData.profile
    if (cached && cached.contactId) {
      this.setData({ checking: false, allowed: true, gateError: '' })
      this.start(query)
      return
    }
    this.setData({ checking: true, gateError: '' })
    api.call('profile.get', {}, { loading: false, silent: true }).then((data) => {
      const profile = (data && data.profile) || {}
      getApp().globalData.profile = profile
      getApp().globalData.openid = data.openid
      const allowed = Boolean(profile.contactId)
      this.setData({ checking: false, allowed, gateError: '' })
      if (allowed) this.start(query)
    }).catch((error) => {
      this.setData({ checking: false, allowed: false, gateError: api.describeError(error) })
    })
  },
  retryAccess() { this.checkAccess(this.lastQuery || {}) },
  goVerify() { wx.switchTab({ url: '/pages/profile/index' }) },
  start(query) {
    this.lastQuery = query || {}
    const book = this.bookName
    const chapters = loaders[book] ? loaders[book]() : []
    const queryIndex = Number(query.chapter)
    const hasQueryIndex = Number.isFinite(queryIndex) && query.chapter !== undefined
    if (hasQueryIndex) {
      this.showChapter(book, chapters, queryIndex)
      return
    }
    api.call('reading.get', { book }, { loading: false, silent: true }).then((progress) => {
      this.showChapter(book, chapters, progress.chapterIndex || 0)
    }).catch(() => this.showChapter(book, chapters, 0))
  },
  onHide() { this.saveProgress() },
  onUnload() { this.saveProgress() },
  showChapter(book, chapters, index) {
    const safeIndex = Math.max(0, Math.min(Number(index) || 0, Math.max(0, chapters.length - 1)))
    this.setData({ book, chapters, index: safeIndex, current: prepareChapter(book, chapters[safeIndex]), loaded: true })
  },
  saveProgress() {
    const { book, chapters, index, current, loaded } = this.data
    if (!loaded || !book || !chapters.length) return Promise.resolve()
    const completed = index === chapters.length - 1
    return api.call('reading.save', {
      book,
      chapterIndex: index,
      chapterTitle: current ? current.title : '',
      completed,
      progress: (index + 1) / chapters.length
    }, { loading: false, silent: true }).catch(() => {})
  },
  catalog() { this.setData({ showCatalog: !this.data.showCatalog }) },
  select(event) { this.change(Number(event.currentTarget.dataset.index)) },
  prev() { this.change(this.data.index - 1) },
  next() { this.change(this.data.index + 1) },
  change(index) {
    if (index < 0 || index >= this.data.chapters.length) return
    this.setData({ index, current: prepareChapter(this.data.book, this.data.chapters[index]), showCatalog: false })
    wx.pageScrollTo({ scrollTop: 0, duration: 200 })
    this.saveProgress()
  },
  font(event) {
    this.setData({ fontSize: Math.max(28, Math.min(48, this.data.fontSize + Number(event.currentTarget.dataset.delta))) })
  },
  previewImage(event) {
    wx.previewImage({ current: event.currentTarget.dataset.src, urls: [event.currentTarget.dataset.src] })
  },
  onShareAppMessage() {
    return {
      title: `WeMail 文集 · ${this.data.book}`,
      path: `/pages/reader/index?book=${encodeURIComponent(this.data.book)}&chapter=${this.data.index}`
    }
  }
})
