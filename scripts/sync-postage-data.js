const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const sourceRoot = path.resolve(process.argv[2] || process.env.MAIL_POSTAGE_DATA_DIR || '')
if (!sourceRoot || !fs.existsSync(path.join(sourceRoot, 'postage', 'index.json'))) {
  throw new Error('用法：node scripts/sync-postage-data.js /path/to/mail-postage-data')
}

function read(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(sourceRoot, relativePath), 'utf8'))
}

const index = read('postage/index.json')
if (index.standardVersion !== '1.5.0') {
  throw new Error(`上游规范版本已变为 ${index.standardVersion}，请先检查计算引擎兼容性`)
}

const ordinary = read('postage/rates/domestic/ordinary-parcel/index.json')
const originRates = {}
Object.keys(ordinary.originFiles).forEach((regionId) => {
  originRates[regionId] = read(`postage/rates/domestic/ordinary-parcel/${regionId}.json`)
})

let sourceCommit = 'unknown'
try {
  sourceCommit = execFileSync('git', ['-C', sourceRoot, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
} catch (error) {}

const payload = {
  sourceRepo: 'https://github.com/ImMrCloud/mail-postage-data',
  sourceCommit,
  standardVersion: index.standardVersion,
  regions: read('postage/domestic/provinces.json').regions,
  domesticBasic: read('postage/rates/domestic/basic.json').mailTypes,
  ordinaryParcel: {
    weightBands: ordinary.weightBands,
    volumetricWeight: ordinary.volumetricWeight,
    discounts: ordinary.discounts,
    originRates
  },
  hometownParcel: read('postage/rates/domestic/hometown-parcel-sticker.json'),
  specialRates: read('postage/special-rates/domestic.json').rates
}

const output = path.resolve(__dirname, '../miniprogram/data/postage.generated.js')
fs.mkdirSync(path.dirname(output), { recursive: true })
fs.writeFileSync(output, `module.exports = ${JSON.stringify(payload, null, 2)}\n`)
console.log(`已生成 ${output}`)
console.log(`来源提交 ${sourceCommit}`)
