const cloud = require('wx-server-sdk')
const https = require('https')
const crypto = require('crypto')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })
const db = cloud.database()
const NOTION_VERSION = process.env.NOTION_VERSION || '2025-09-03'
const CONTACT_SOURCE = process.env.CONTACT_DATA_SOURCE_ID || '31e70d82-c716-8034-b23d-000ba20878af'
const MAIL_SOURCE = process.env.RAS_DATA_SOURCE_ID || '31e70d82-c716-80ba-b4d2-000b1892f62c'
const MAIL_DATABASE = process.env.RAS_DATABASE_ID || '31e70d82-c716-80d3-9f2d-e73dcc4033b3'
const ADMIN_PHONE = phoneKey(process.env.ADMIN_PHONE)
const MAIL_NOTE_ENABLED = /^(1|true|yes|on)$/i.test(process.env.MAIL_NOTE_ENABLED || 'false')

const ok = (data) => ({ ok: true, data })
const fail = (message) => ({ ok: false, message })
const docId = (...parts) => crypto.createHash('sha256').update(parts.join(':')).digest('hex')

function notion(path, method = 'GET', body) {
  return new Promise((resolve, reject) => {
    if (!process.env.NOTION_TOKEN) return reject(new Error('云函数尚未配置 NOTION_TOKEN'))
    const payload = body ? JSON.stringify(body) : ''
    const req = https.request({
      hostname: 'api.notion.com',
      path: `/v1${path}`,
      method,
      headers: {
        Authorization: `Bearer ${process.env.NOTION_TOKEN}`,
        'Notion-Version': NOTION_VERSION,
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload)
      }
    }, (res) => {
      let text = ''
      res.on('data', (chunk) => { text += chunk })
      res.on('end', () => {
        let data = {}
        try { data = JSON.parse(text) } catch (error) {}
        if (res.statusCode >= 200 && res.statusCode < 300) resolve(data)
        else reject(new Error(data.message || `Notion ${res.statusCode}`))
      })
    })
    req.on('error', reject)
    if (payload) req.write(payload)
    req.end()
  })
}

function read(prop = {}) {
  if (prop.type === 'title') return (prop.title || []).map((item) => item.plain_text || '').join('').trim()
  if (prop.type === 'rich_text') return (prop.rich_text || []).map((item) => item.plain_text || '').join('').trim()
  if (['phone_number', 'email', 'url', 'number', 'checkbox'].includes(prop.type)) return prop[prop.type]
  if (prop.type === 'date') return prop.date ? prop.date.start : ''
  if (prop.type === 'relation') return (prop.relation || []).map((item) => item.id)
  if (prop.type === 'select') return prop.select ? prop.select.name : ''
  return ''
}

async function queryAll(sourceId, options = {}) {
  let results = []
  let cursor
  do {
    const body = { page_size: options.pageSize || 100 }
    if (cursor) body.start_cursor = cursor
    if (options.filter) body.filter = options.filter
    if (options.sorts) body.sorts = options.sorts
    const response = await notion(`/data_sources/${sourceId}/query`, 'POST', body)
    results = results.concat(response.results || [])
    cursor = response.has_more ? response.next_cursor : null
  } while (cursor && results.length < 300)
  return results
}

function contact(row) {
  const props = row.properties || {}
  return {
    id: row.id,
    name: read(props['姓名/昵称']),
    phone: read(props['电话']),
    email: read(props['电子邮箱']),
    address1: read(props['地址1']),
    postcode1: read(props['邮编1']),
    address2: read(props['地址2']),
    postcode2: read(props['邮编2']),
    qq: read(props.QQ)
  }
}

function phoneKey(value) {
  return String(value || '').replace(/[^0-9]/g, '').replace(/^86(?=1\d{10}$)/, '')
}

function isAdmin(profile) {
  return Boolean(ADMIN_PHONE && phoneKey(profile.phoneNumber) === ADMIN_PHONE)
}

function requireContact(profile) {
  if (!profile.contactId) throw new Error('仅限已关联联系人身份的用户访问，请先在“我的”中输入姓名与手机号关联')
}

function publicProfile(profile) {
  const result = { ...profile, isAdmin: isAdmin(profile) }
  delete result._id
  delete result.openid
  return result
}

async function getProfile(openid) {
  const response = await db.collection('users').where({ openid }).limit(1).get()
  return response.data[0] || {
    nickname: '微信用户',
    avatarUrl: '',
    phoneNumber: '',
    contactId: '',
    contactName: '',
    address: '',
    postcode: ''
  }
}

async function saveProfile(openid, patch) {
  const response = await db.collection('users').where({ openid }).limit(1).get()
  const safe = {}
  const fields = ['nickname', 'avatarUrl', 'phoneNumber', 'contactId', 'contactName', 'address', 'postcode']
  fields.forEach((key) => {
    if (patch[key] !== undefined) safe[key] = String(patch[key] || '').slice(0, key === 'address' ? 300 : 200)
  })
  safe.updatedAt = db.serverDate()
  if (response.data.length) {
    await db.collection('users').doc(response.data[0]._id).update({ data: safe })
  } else {
    await db.collection('users').add({ data: { ...safe, openid, createdAt: db.serverDate() } })
  }
  return getProfile(openid)
}

async function contacts(openid) {
  const rows = await queryAll(CONTACT_SOURCE)
  const profile = openid ? await getProfile(openid) : {}
  return rows.map(contact).filter((item) => item.name || item.phone).map((item) => ({
    ...item,
    isMe: profile.contactId === item.id
  }))
}

async function resolveNames(records) {
  const list = await contacts('')
  const names = Object.fromEntries(list.map((item) => [item.id, item.name]))
  return records.map((row) => {
    const props = row.properties || {}
    const senders = read(props['寄件人']) || []
    const recipients = read(props['收件人']) || []
    return {
      pageId: row.id,
      sendDate: read(props['寄出日期']),
      trackingNo: read(props['邮件编号']),
      mailType: read(props['备注']) || '平信',
      received: Boolean(read(props['签收'])),
      senderId: senders[0] || '',
      recipientId: recipients[0] || '',
      senderName: names[senders[0]] || '',
      recipientName: names[recipients[0]] || ''
    }
  })
}

async function mailList(openid) {
  if (!process.env.NOTION_TOKEN) return { records: [], stats: { sent: 0, received: 0, unsigned: 0 }, setupRequired: true }
  const profile = await getProfile(openid)
  const rows = await queryAll(MAIL_SOURCE, { pageSize: 50, sorts: [{ property: '寄出日期', direction: 'descending' }] })
  const all = await resolveNames(rows)
  const mine = profile.contactId ? all.filter((item) => item.senderId === profile.contactId || item.recipientId === profile.contactId) : []
  mine.forEach((item) => { item.direction = item.senderId === profile.contactId ? 'sent' : 'received' })
  const since = Date.now() - 14 * 86400000
  return {
    records: mine,
    stats: {
      sent: mine.filter((item) => item.senderId === profile.contactId && new Date(item.sendDate).getTime() >= since).length,
      received: mine.filter((item) => item.recipientId === profile.contactId && new Date(item.sendDate).getTime() >= since).length,
      unsigned: mine.filter((item) => item.recipientId === profile.contactId && !item.received).length
    }
  }
}

async function createMail(openid, data) {
  const profile = await getProfile(openid)
  requireContact(profile)
  if (data.senderId !== profile.contactId) throw new Error('寄件人必须是当前登录用户')
  const list = await contacts(openid)
  if (!list.some((item) => item.id === data.recipientId)) throw new Error('收件人不存在')
  const trackingNo = String(data.trackingNo || '').trim().slice(0, 100)
  if (trackingNo && !/^[A-Za-z0-9-]+$/.test(trackingNo)) throw new Error('邮件编号仅支持字母、数字和连字符')
  const title = MAIL_NOTE_ENABLED ? String(data.title || '').slice(0, 100) : '由 WeMail 小程序登记'
  const properties = {
    ' ': { title: [{ text: { content: title || '由 WeMail 小程序登记' } }] },
    寄件人: { relation: [{ id: profile.contactId }] },
    收件人: { relation: [{ id: data.recipientId }] },
    寄出日期: { date: { start: data.sendDate } },
    备注: { rich_text: [{ text: { content: String(data.mailType || '平信') } }] },
    签收: { checkbox: false }
  }
  if (trackingNo) properties['邮件编号'] = { rich_text: [{ text: { content: trackingNo } }] }
  return notion('/pages', 'POST', { parent: { database_id: MAIL_DATABASE }, properties })
}

async function signMail(openid, pageId) {
  const profile = await getProfile(openid)
  if (!profile.contactId) throw new Error('请先匹配联系人')
  const row = await notion(`/pages/${pageId}`)
  const recipients = read((row.properties || {})['收件人']) || []
  if (!recipients.includes(profile.contactId)) throw new Error('只有收件人可以签收')
  await notion(`/pages/${pageId}`, 'PATCH', { properties: { 签收: { checkbox: true } } })
}

async function listEvents(openid, type) {
  const response = await db.collection('events').where({ type }).limit(50).get()
  response.data.sort((left, right) => new Date(right.createdAt || 0).getTime() - new Date(left.createdAt || 0).getTime())
  const entryIds = response.data.map((event) => docId(event._id, openid))
  const joined = new Set()
  for (let index = 0; index < entryIds.length; index += 20) {
    const batch = entryIds.slice(index, index + 20)
    if (!batch.length) continue
    const entries = await db.collection('event_entries').where({ _id: db.command.in(batch) }).get()
    entries.data.forEach((entry) => joined.add(entry.eventId))
  }
  return response.data.map((event) => ({
    ...event,
    joined: joined.has(event._id),
    isOwner: event.ownerOpenid === openid,
    statusText: event.status === 'open' ? '进行中' : event.status === 'drawn' ? '已开奖' : event.status === 'full' ? '已满员' : '已截止'
  }))
}

async function joinEvent(openid, eventId) {
  const profile = await getProfile(openid)
  const entryId = docId(eventId, openid)
  await db.runTransaction(async (transaction) => {
    const eventRef = db.collection('events').doc(eventId)
    const entryRef = db.collection('event_entries').doc(entryId)
    const eventResult = await transaction.get(eventRef)
    const event = eventResult.data
    if (!event) throw new Error('活动不存在')
    if (event.status !== 'open') throw new Error('活动已结束')
    if (new Date(event.deadline).getTime() < Date.now()) throw new Error('活动已截止')
    try {
      await transaction.get(entryRef)
      throw new Error('你已经参与过了')
    } catch (error) {
      if (error.message === '你已经参与过了') throw error
    }
    const count = Number(event.participantCount) || 0
    if (event.limit && count >= event.limit) throw new Error('报名人数已满')
    const nextCount = count + 1
    transaction.set(entryRef, {
      eventId,
      openid,
      name: profile.contactName || profile.nickname || '微信用户',
      avatarUrl: profile.avatarUrl || '',
      createdAt: db.serverDate()
    })
    transaction.update(eventRef, {
      data: {
        participantCount: nextCount,
        status: event.limit && nextCount >= event.limit ? 'full' : 'open',
        updatedAt: db.serverDate()
      }
    })
  })
  return { joined: true }
}

async function drawEvent(openid, eventId) {
  const eventResult = await db.collection('events').doc(eventId).get()
  const event = eventResult.data
  if (event.ownerOpenid !== openid) throw new Error('只有发起人可以开奖')
  if (event.status === 'drawn') throw new Error('活动已经开奖')
  const entries = await db.collection('event_entries').where({ eventId }).limit(1000).get()
  const winner = entries.data.length ? entries.data[Math.floor(Math.random() * entries.data.length)] : null
  await db.collection('events').doc(eventId).update({
    data: { status: 'drawn', winnerName: winner ? winner.name : '', winnerOpenid: winner ? winner.openid : '', drawnAt: db.serverDate() }
  })
  return { winnerName: winner ? winner.name : '' }
}

async function getReadingProgress(openid, book) {
  const id = docId(openid, book)
  try {
    const response = await db.collection('reading_progress').doc(id).get()
    return response.data
  } catch (error) {
    return { book, chapterIndex: 0, completed: false }
  }
}

async function saveReadingProgress(openid, event) {
  const book = String(event.book || '').slice(0, 100)
  if (!book) throw new Error('缺少书名')
  const id = docId(openid, book)
  const chapterIndex = Math.max(0, Number(event.chapterIndex) || 0)
  const data = {
    openid,
    book,
    chapterIndex,
    chapterTitle: String(event.chapterTitle || '').slice(0, 200),
    completed: Boolean(event.completed),
    progress: Math.max(0, Math.min(1, Number(event.progress) || 0)),
    updatedAt: db.serverDate()
  }
  await db.collection('reading_progress').doc(id).set({ data })
  return data
}

async function handler(event, openid) {
  switch (event.action) {
    case 'profile.get': {
      const profile = await getProfile(openid)
      const mail = await mailList(openid)
      return ok({ openid, profile: publicProfile(profile), stats: mail.stats, recent: mail.records.slice(0, 3) })
    }
    case 'profile.update':
      return ok(publicProfile(await saveProfile(openid, event.patch || {})))
    case 'profile.bindPhone':
      throw new Error('手机号快捷登录已下线，请在“我的”中输入姓名与手机号关联联系人身份')
    case 'contacts.list': {
      const profile = await getProfile(openid)
      requireContact(profile)
      return ok(await contacts(openid))
    }
    case 'mail.list': {
      const profile = await getProfile(openid)
      requireContact(profile)
      return ok(await mailList(openid))
    }
    case 'mail.create':
      await createMail(openid, event)
      return ok({ created: true })
    case 'mail.sign': {
      const profile = await getProfile(openid)
      requireContact(profile)
      await signMail(openid, event.pageId)
      return ok({ signed: true })
    }
    case 'events.list': {
      const profile = await getProfile(openid)
      requireContact(profile)
      return ok({ events: await listEvents(openid, event.type || 'lottery'), isAdmin: isAdmin(profile) })
    }
    case 'events.create': {
      const profile = await getProfile(openid)
      requireContact(profile)
      if (!isAdmin(profile)) throw new Error('仅管理员可以发布活动')
      const document = {
        type: event.type === 'signup' ? 'signup' : 'lottery',
        title: String(event.title || '').slice(0, 80),
        description: String(event.description || '').slice(0, 500),
        deadline: new Date(String(event.deadline).replace(' ', 'T')),
        limit: Math.max(0, Number(event.limit) || 0),
        status: 'open',
        participantCount: 0,
        ownerName: profile.contactName || profile.nickname,
        ownerOpenid: openid,
        createdAt: db.serverDate(),
        updatedAt: db.serverDate()
      }
      const result = await db.collection('events').add({ data: document })
      return ok({ _id: result._id })
    }
    case 'events.join': {
      const profile = await getProfile(openid)
      requireContact(profile)
      return ok(await joinEvent(openid, event.eventId))
    }
    case 'events.draw': {
      const profile = await getProfile(openid)
      requireContact(profile)
      if (!isAdmin(profile)) throw new Error('仅管理员可以开奖')
      return ok(await drawEvent(openid, event.eventId))
    }
    case 'reading.get':
      return ok(await getReadingProgress(openid, String(event.book || '')))
    case 'reading.save':
      return ok(await saveReadingProgress(openid, event))
    default:
      return fail('未知操作')
  }
}

exports.main = async (event) => {
  try {
    const { OPENID } = cloud.getWXContext()
    return await handler(event, OPENID)
  } catch (error) {
    console.error(error && error.stack ? error.stack : error)
    return fail(error.message || '服务异常')
  }
}
