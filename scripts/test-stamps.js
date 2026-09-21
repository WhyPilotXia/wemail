const assert = require('assert')
const stamps = require('../miniprogram/utils/stamps')

assert.strictEqual(stamps.DENOMINATIONS.join(','), '0.1,0.8,1.2,1.5,3')
assert.deepStrictEqual(stamps.DEFAULT_SELECTED, [0.8, 1.2])
assert.strictEqual(stamps.PRICE_RATIO, 0.55)

// 正好凑出：0.8 = 0.8；1.2 = 1.2；2.0 = 1.2 + 0.8
let result = stamps.compute(0.8, [0.1, 0.8, 1.2, 1.5, 3])
assert.strictEqual(result.exact, true)
assert.strictEqual(result.total, 0.8)
assert.strictEqual(result.pieces, 1)
result = stamps.compute(1.2, [0.8, 1.2])
assert.strictEqual(result.exact, true)
assert.strictEqual(result.pieces, 1)
result = stamps.compute(2, [0.8, 1.2])
assert.strictEqual(result.exact, true)
assert.strictEqual(result.pieces, 2)

// 大面值优先：4.4 = 3 + 1.2 + 0.1 + 0.1
result = stamps.compute(4.4, [0.1, 0.8, 1.2, 1.5, 3])
assert.strictEqual(result.exact, true)
assert.strictEqual(result.total, 4.4)
assert.deepStrictEqual(result.lines.map((line) => `${line.label}元 × ${line.count}`), ['3元 × 1', '1.2元 × 1', '0.1元 × 2'])

// 无法正好凑出：不含 0.1 面值时 0.3 只能取 0.8（回退到不小于目标的最小组合）
result = stamps.compute(0.3, [0.8, 1.2])
assert.strictEqual(result.exact, false)
assert.strictEqual(result.total, 0.8)
assert.strictEqual(result.pieces, 1)

// 不含 0.1 面值时无法凑出 1.9，最优为 2.0（1.2 + 0.8）；加 0.1 面值后即可正好凑出
result = stamps.compute(1.9, [0.8, 1.2, 1.5, 3])
assert.strictEqual(result.exact, false)
assert.strictEqual(result.total, 2)
result = stamps.compute(1.9, [0.1, 0.8, 1.2, 1.5, 3])
assert.strictEqual(result.exact, true)
assert.strictEqual(result.total, 1.9)

// 折价：55% 的 4.4 = 2.42
result = stamps.compute(4.4, [0.1, 0.8, 1.2, 1.5, 3])
assert.strictEqual(result.price, 2.42)
assert.strictEqual(result.priceText, '2.42')

// 边界与非法输入
assert.strictEqual(stamps.compute(0, stamps.DENOMINATIONS), null)
assert.strictEqual(stamps.compute(-1, stamps.DENOMINATIONS), null)
assert.strictEqual(stamps.compute('abc', stamps.DENOMINATIONS), null)
assert.strictEqual(stamps.compute(5, []), null)
assert.strictEqual(stamps.compute(5, null), null)

// 目标超出上限不计算
assert.strictEqual(stamps.compute(2000, stamps.DENOMINATIONS), null)

// 只选小面值也能正好凑出 1.2（0.8 + 0.1×4）
result = stamps.compute(1.2, [0.1, 0.8])
assert.strictEqual(result.exact, true)
assert.strictEqual(result.pieces, 5)

console.log('stamp calculator tests passed')
