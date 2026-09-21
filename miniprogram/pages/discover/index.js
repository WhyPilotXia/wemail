Page({
  openBooks() { wx.navigateTo({ url: '/pages/books/index' }) },
  openPostage() { wx.navigateTo({ url: '/pages/postage/index' }) },
  openEvents(event) { wx.navigateTo({ url: `/pages/events/index?type=${event.currentTarget.dataset.type || ''}` }) }
})
