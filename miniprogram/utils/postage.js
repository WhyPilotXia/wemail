const data = require('../data/postage.generated')

const SERVICES = [
  { id: 'LETTER', name: '国内平信' },
  { id: 'REGISTERED_LETTER', name: '国内挂号信' },
  { id: 'POSTCARD', name: '国内明信片' },
  { id: 'PRINTED_MATTER', name: '国内印刷品' },
  { id: 'ORDINARY_PARCEL', name: '国内普通包裹' },
  { id: 'HOMETOWN_PARCEL', name: '家乡包裹贴' }
]

const DISCOUNTS = [
  { id: '', name: '不使用优惠', multiplier: 1 },
  { id: 'EIGHTY_PERCENT', name: '8折凭证', multiplier: 0.8 },
  { id: 'SEVENTY_PERCENT', name: '7折凭证', multiplier: 0.7 }
]

function number(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function money(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100
}

function findRate(id) {
  return data.specialRates.find((item) => item.id === id)
}

function flatSpecial(id) {
  const rate = findRate(id)
  return rate && rate.pricing && rate.pricing.price ? rate.pricing.price : 0
}

function calculateTiered(weight, rate, locality) {
  let total = 0
  rate.tiers.forEach((tier) => {
    const covered = Math.min(weight, tier.toWeight) - tier.fromWeightExclusive
    if (covered <= 0) return
    const price = tier.prices ? tier.prices[locality] : tier.price
    total += Math.ceil(covered / tier.incrementWeight) * price
  })
  return money(total)
}

function calculateOrdinaryByWeight(weight, originId, destinationId) {
  const config = data.ordinaryParcel
  const origin = config.originRates[originId]
  if (!origin) throw new Error('当前起寄省暂无普通包裹资费数据')
  const band = config.weightBands.find((item) => weight > item.minWeightExclusive && weight <= item.maxWeight)
  if (!band) throw new Error('普通包裹重量须大于0且不超过50千克')
  const group = origin.routeGroups.find((item) => item.destinations.includes(destinationId))
  if (!group) throw new Error('当前寄递路向暂无资费数据')
  const prices = group.prices[band.id]
  const increments = weight <= band.baseWeight ? 0 : Math.ceil((weight - band.baseWeight) / band.incrementWeight)
  return money(prices.basePrice + increments * prices.incrementPrice)
}

function insuranceFee(serviceId, declaredValue) {
  if (!declaredValue) return 0
  if (serviceId === 'ORDINARY_PARCEL' || serviceId === 'HOMETOWN_PARCEL') return money(declaredValue * 0.01)
  return money(Math.max(1, Math.ceil(declaredValue) * 0.01))
}

function calculate(input) {
  const serviceId = input.serviceId
  const weight = number(input.weight)
  const isPostcard = serviceId === 'POSTCARD'
  if (!isPostcard && weight <= 0) throw new Error('请输入大于0克的重量')

  let base = 0
  let actualWeightPostage = 0
  let volumetricWeight = 0
  let volumetricPostage = 0
  const details = []

  if (serviceId === 'LETTER' || serviceId === 'REGISTERED_LETTER' || serviceId === 'PRINTED_MATTER') {
    const type = serviceId === 'PRINTED_MATTER' ? 'PRINTED_MATTER' : 'LETTER'
    const rate = data.domesticBasic[type]
    if (weight > rate.maxWeight) throw new Error(`${type === 'LETTER' ? '信函' : '印刷品'}重量不能超过${rate.maxWeight}克`)
    base = calculateTiered(weight, rate, input.locality || 'NON_LOCAL')
  } else if (isPostcard) {
    base = data.domesticBasic.POSTCARD.price
  } else if (serviceId === 'HOMETOWN_PARCEL') {
    const tier = data.hometownParcel.tiers.find((item) => weight > item.minWeightExclusive && weight <= item.maxWeight)
    if (!tier) throw new Error('家乡包裹贴重量须大于0且不超过10千克')
    base = tier.price
  } else if (serviceId === 'ORDINARY_PARCEL') {
    if (!input.originId || !input.destinationId) throw new Error('请选择起寄省和目的省')
    actualWeightPostage = calculateOrdinaryByWeight(weight, input.originId, input.destinationId)
    base = actualWeightPostage
    const length = number(input.length)
    const width = number(input.width)
    const height = number(input.height)
    const dimensions = [length, width, height]
    if (dimensions.some((item) => item > 0) && !dimensions.every((item) => item > 0)) throw new Error('长、宽、高需全部填写或全部留空')
    if (dimensions.every((item) => item > 0)) {
      volumetricWeight = length * width * height / data.ordinaryParcel.volumetricWeight.divisor * 1000
      volumetricPostage = calculateOrdinaryByWeight(volumetricWeight, input.originId, input.destinationId)
      base = Math.max(actualWeightPostage, volumetricPostage)
    }
    const discount = DISCOUNTS.find((item) => item.id === input.discountId) || DISCOUNTS[0]
    if (discount.multiplier < 1) {
      details.push(`基础资费${discount.name}`)
      base = money(base * discount.multiplier)
    }
  } else {
    throw new Error('暂不支持该寄送方式')
  }

  details.unshift(`基础资费 ¥${base.toFixed(2)}`)
  let special = 0
  const letterPost = ['LETTER', 'REGISTERED_LETTER', 'POSTCARD', 'PRINTED_MATTER'].includes(serviceId)
  const registered = serviceId === 'REGISTERED_LETTER' || Boolean(input.registered) || Boolean(input.receipt) || Boolean(input.insured) || Boolean(input.appointed)

  if (letterPost && registered) {
    const fee = flatSpecial('REGISTRATION_FEE')
    special += fee
    details.push(`挂号费 ¥${fee.toFixed(2)}`)
  }
  if (input.receipt) {
    const fee = flatSpecial('ADVICE_OF_DELIVERY_FEE')
    special += fee
    details.push(`回执 ¥${fee.toFixed(2)}`)
  }
  if (input.appointed && (serviceId === 'LETTER' || serviceId === 'REGISTERED_LETTER')) {
    const fee = flatSpecial('APPOINTED_DELIVERY_FEE')
    special += fee
    details.push(`约投服务费 ¥${fee.toFixed(2)}`)
  }
  if (input.insured) {
    const declaredValue = number(input.declaredValue)
    const maxValue = serviceId === 'ORDINARY_PARCEL' || serviceId === 'HOMETOWN_PARCEL' ? 100000 : 20000
    if (declaredValue <= 0 || declaredValue > maxValue) throw new Error(`保价金额须大于0且不超过${maxValue}元`)
    const fee = insuranceFee(serviceId, declaredValue)
    special += fee
    details.push(`保价费 ¥${fee.toFixed(2)}`)
  }

  return {
    total: money(base + special),
    base: money(base),
    special: money(special),
    actualWeightPostage,
    volumetricWeight: money(volumetricWeight),
    volumetricPostage,
    details,
    sourceVersion: data.standardVersion
  }
}

function inferRegionId(address) {
  const text = String(address || '')
  const region = data.regions.find((item) => text.includes(item.nameZh) || text.includes(item.shortNameZh))
  return region ? region.id : ''
}

module.exports = { SERVICES, DISCOUNTS, calculate, inferRegionId, regions: data.regions, source: data }
