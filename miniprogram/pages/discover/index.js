Page({
  openBooks() { wx.navigateTo({ url: '/pages/books/index' }) },
  openEvents(event) { wx.navigateTo({ url: `/pages/events/index?type=${event.currentTarget.dataset.type || ''}` }) }
})
