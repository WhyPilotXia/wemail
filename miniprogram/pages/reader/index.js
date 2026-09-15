const api = require('../../utils/api')

const loaders = {
  李氏庄园: () => require('../../data/books/李氏庄园'),
  回信券风暴: () => require('../../data/books/回信券风暴'),
  股神牛久盛: () => require('../../data/books/股神牛久盛'),
  名将之后: () => require('../../data/books/名将之后')
}

const imageSources = {
  李氏庄园: {
    'assets/image.png': '/assets/books/李氏庄园/image-optimized.jpg',
    'assets/22091.jpg': '/assets/books/李氏庄园/22091.jpg',
    'assets/22092.jpg': '/assets/books/李氏庄园/22092.jpg'
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
    cursor = pattern.lastIndex
  }
  if (cursor < source.length) blocks.push({ type: 'text', content: source.slice(cursor) })
  return blocks.length ? blocks : [{ type: 'text', content: source }]
}

function prepareChapter(book, chapter) {
  return chapter ? { ...chapter, blocks: renderContent(book, chapter.content) } : null
}

Page({
  data: { book: '', chapters: [], index: 0, current: null, showCatalog: false, fontSize: 36, loaded: false },
  onLoad(query) {
    const book = decodeURIComponent(query.book || '')
    const chapters = loaders[book] ? loaders[book]() : []
    const queryIndex = Number(query.chapter)
    const hasQueryIndex = Number.isFinite(queryIndex) && query.chapter !== undefined
    wx.setNavigationBarTitle({ title: book || '阅读' })
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
      title: `《${this.data.book}》${this.data.current.title}`,
      path: `/pages/reader/index?book=${encodeURIComponent(this.data.book)}&chapter=${this.data.index}`
    }
  }
})
