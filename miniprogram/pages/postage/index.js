const { compute } = require('../../utils/stamps')

Page({
  data: { lastPostage: null },
  onPostageCalculated(event) {
    this.setData({ lastPostage: event.detail.total })
  }
})
