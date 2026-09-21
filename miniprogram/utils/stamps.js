// 邮票凑配计算：与邮费资费数据源相互独立，面值列表与默认勾选在此维护。
const DENOMINATIONS = [0.1, 0.8, 1.2, 1.5, 3]
const DEFAULT_SELECTED = [0.8, 1.2]
const PRICE_RATIO = 0.55
const MAX_TARGET_YUAN = 1000

function toCents(value) {
  return Math.round(Number(value) * 100)
}

// 大面值优先的离散凑配：优先取最大面值，凑不齐时回退更小面值；
// 无法正好达到目标值时，返回不小于目标值的最小可行组合。
function compute(target, denominations) {
  const cents = toCents(target)
  if (!(cents > 0) || cents > MAX_TARGET_YUAN * 100) return null
  const unique = []
  for (const item of denominations || []) {
    const value = toCents(item)
    if (value > 0 && !unique.includes(value)) unique.push(value)
  }
  if (!unique.length) return null
  unique.sort((a, b) => b - a)

  const limit = cents + unique[0]
  const achievable = new Array(limit + 1).fill(false)
  achievable[0] = true
  for (let sum = 1; sum <= limit; sum++) {
    for (const value of unique) {
      if (value <= sum && achievable[sum - value]) {
        achievable[sum] = true
        break
      }
    }
  }

  let best = -1
  for (let sum = cents; sum <= limit; sum++) {
    if (achievable[sum]) {
      best = sum
      break
    }
  }
  if (best < 0) return null

  const counts = {}
  let remaining = best
  for (const value of unique) {
    let count = Math.floor(remaining / value)
    while (count > 0 && !achievable[remaining - count * value]) count--
    if (count > 0) counts[value] = count
    remaining -= count * value
  }

  const lines = unique
    .filter((value) => counts[value] > 0)
    .map((value) => ({ label: String(value / 100), value: value / 100, count: counts[value] }))
  const pieces = lines.reduce((sum, line) => sum + line.count, 0)
  const price = Math.round(best * PRICE_RATIO) / 100
  return {
    exact: best === cents,
    targetText: (cents / 100).toFixed(2),
    total: best / 100,
    totalText: (best / 100).toFixed(2),
    price,
    priceText: price.toFixed(2),
    pieces,
    lines
  }
}

module.exports = { DENOMINATIONS, DEFAULT_SELECTED, PRICE_RATIO, MAX_TARGET_YUAN, compute }
