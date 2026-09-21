const stamps = require('../../utils/stamps')

Component({
  properties: {
    postageAmount: {
      type: null,
      value: null,
      observer(value) {
        if (typeof value !== 'number' || !(value > 0) || this.data.isUserInput) return
        this.setData({ amount: value.toFixed(2) }, () => this.recalculate())
      }
    }
  },
  data: {
    amount: '',
    isUserInput: false,
    denominations: stamps.DENOMINATIONS.map((value) => ({
      value,
      label: String(value),
      checked: stamps.DEFAULT_SELECTED.includes(value)
    })),
    result: null,
    hint: ''
  },
  methods: {
    inputAmount(event) {
      this.setData({ amount: event.detail.value, isUserInput: true }, () => this.recalculate())
    },
    toggleDenom(event) {
      const value = Number(event.currentTarget.dataset.value)
      const denominations = this.data.denominations.map((item) => (
        item.value === value ? { ...item, checked: !item.checked } : item
      ))
      this.setData({ denominations }, () => this.recalculate())
    },
    recalculate() {
      const selected = this.data.denominations.filter((item) => item.checked).map((item) => item.value)
      const amount = String(this.data.amount || '').trim()
      if (!amount) {
        this.setData({ result: null, hint: '' })
        return
      }
      if (!selected.length) {
        this.setData({ result: null, hint: '请至少选择一种邮票面值' })
        return
      }
      const target = Number(amount)
      if (!(target > 0) || target > stamps.MAX_TARGET_YUAN) {
        this.setData({ result: null, hint: `请输入 0.01 至 ${stamps.MAX_TARGET_YUAN} 元之间的邮资` })
        return
      }
      const result = stamps.compute(target, selected)
      if (!result) {
        this.setData({ result: null, hint: '暂时无法凑配，请检查输入或面值选择' })
        return
      }
      this.setData({
        result: { ...result, lines: result.lines.map((line) => `${line.label}元 × ${line.count}张`) },
        hint: ''
      })
    }
  }
})
