const postage = require('../../utils/postage')

const ORIGINS = Object.keys(postage.source.ordinaryParcel.originRates)
  .map((id) => postage.regions.find((item) => item.id === id))
  .filter(Boolean)

function initialForm() {
  return { weight: '', length: '', width: '', height: '', registered: false, receipt: false, appointed: false, insured: false, declaredValue: '', discountId: '' }
}

Component({
  properties: {
    compact: { type: Boolean, value: false },
    initialService: { type: String, value: '' },
    originAddress: { type: String, value: '' },
    destinationAddress: { type: String, value: '' }
  },
  data: {
    services: postage.SERVICES,
    serviceNames: postage.SERVICES.map((item) => item.name),
    serviceIndex: 0,
    localityNames: ['本埠', '外埠'],
    localityIndex: 1,
    origins: ORIGINS,
    originNames: ORIGINS.map((item) => item.nameZh),
    originIndex: -1,
    regions: postage.regions,
    regionNames: postage.regions.map((item) => item.nameZh),
    destinationIndex: -1,
    discountNames: postage.DISCOUNTS.map((item) => item.name),
    discountIndex: 0,
    form: initialForm(),
    result: null,
    error: '',
    sourceVersion: postage.source.standardVersion,
    needsWeight: true,
    showLocality: true,
    isOrdinaryParcel: false,
    showSpecials: true,
    canRegister: true,
    forcedRegistered: false,
    canReceipt: true,
    canAppointed: true,
    canInsure: true
  },
  observers: {
    initialService(value) {
      if (!value) return
      const mapping = { 平信: 'LETTER', 挂号信: 'REGISTERED_LETTER', 明信片: 'POSTCARD', 包裹: 'ORDINARY_PARCEL' }
      const index = postage.SERVICES.findIndex((item) => item.id === mapping[value])
      if (index >= 0 && index !== this.data.serviceIndex) this.applyService(index)
    },
    originAddress(value) { this.applyAddressRegion(value, true) },
    destinationAddress(value) { this.applyAddressRegion(value, false) }
  },
  lifetimes: {
    attached() { this.applyService(this.data.serviceIndex) }
  },
  methods: {
    applyAddressRegion(address, isOrigin) {
      const id = postage.inferRegionId(address)
      if (!id) return
      if (isOrigin) {
        const index = ORIGINS.findIndex((item) => item.id === id)
        if (index >= 0) this.setData({ originIndex: index }, () => this.recalculate())
      } else {
        const index = postage.regions.findIndex((item) => item.id === id)
        if (index >= 0) this.setData({ destinationIndex: index }, () => this.recalculate())
      }
    },
    applyService(index) {
      const service = postage.SERVICES[index]
      const id = service.id
      const parcel = id === 'ORDINARY_PARCEL'
      const hometown = id === 'HOMETOWN_PARCEL'
      const registeredLetter = id === 'REGISTERED_LETTER'
      const letter = id === 'LETTER' || registeredLetter
      const form = { ...this.data.form, registered: registeredLetter, receipt: hometown ? false : this.data.form.receipt, appointed: letter ? this.data.form.appointed : false, insured: (letter || parcel || hometown) ? this.data.form.insured : false }
      this.setData({
        serviceIndex: index,
        form,
        needsWeight: id !== 'POSTCARD',
        showLocality: ['LETTER', 'REGISTERED_LETTER', 'PRINTED_MATTER'].includes(id),
        isOrdinaryParcel: parcel,
        canRegister: ['LETTER', 'REGISTERED_LETTER', 'POSTCARD', 'PRINTED_MATTER'].includes(id),
        forcedRegistered: registeredLetter,
        canReceipt: !hometown,
        canAppointed: letter,
        canInsure: letter || parcel || hometown
      }, () => this.recalculate())
    },
    changeService(event) { this.applyService(Number(event.detail.value)) },
    changeLocality(event) { this.setData({ localityIndex: Number(event.detail.value) }, () => this.recalculate()) },
    changeOrigin(event) { this.setData({ originIndex: Number(event.detail.value) }, () => this.recalculate()) },
    changeDestination(event) { this.setData({ destinationIndex: Number(event.detail.value) }, () => this.recalculate()) },
    changeDiscount(event) {
      const discountIndex = Number(event.detail.value)
      this.setData({ discountIndex, 'form.discountId': postage.DISCOUNTS[discountIndex].id }, () => this.recalculate())
    },
    input(event) { this.setData({ [`form.${event.currentTarget.dataset.key}`]: event.detail.value }, () => this.recalculate()) },
    toggle(event) {
      const key = event.currentTarget.dataset.key
      const updates = { [`form.${key}`]: event.detail.value }
      if (key === 'receipt' && event.detail.value && this.data.canRegister) updates['form.registered'] = true
      if (key === 'appointed' && event.detail.value) {
        updates['form.registered'] = true
        updates['form.insured'] = false
      }
      if (key === 'insured' && event.detail.value && this.data.canRegister) {
        updates['form.registered'] = true
        updates['form.appointed'] = false
      }
      if (key === 'registered' && !event.detail.value) {
        updates['form.receipt'] = false
        updates['form.appointed'] = false
        updates['form.insured'] = false
      }
      this.setData(updates, () => this.recalculate())
    },
    recalculate() {
      const service = postage.SERVICES[this.data.serviceIndex]
      const origin = ORIGINS[this.data.originIndex]
      const destination = postage.regions[this.data.destinationIndex]
      try {
        const calculated = postage.calculate({
          ...this.data.form,
          serviceId: service.id,
          locality: this.data.localityIndex === 0 ? 'LOCAL' : 'NON_LOCAL',
          originId: origin && origin.id,
          destinationId: destination && destination.id
        })
        this.setData({ result: { ...calculated, totalText: calculated.total.toFixed(2), volumetricText: calculated.volumetricWeight ? calculated.volumetricWeight.toFixed(0) : '' }, error: '' })
      } catch (error) {
        this.setData({ result: null, error: error.message })
      }
    }
  }
})
