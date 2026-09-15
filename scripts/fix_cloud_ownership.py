from pathlib import Path

path = Path('/Users/lhc/Documents/git包/wemail/cloudfunctions/wemail/index.js')
source = path.read_text(encoding='utf-8')
replacements = {
    "where({_openid:openid})": "where({openid})",
    "data:{...safe,createdAt:db.serverDate()}": "data:{...safe,openid,createdAt:db.serverDate()}",
    "isOwner:e._openid===openid": "isOwner:e.ownerOpenid===openid",
    "ownerName:profile.contactName||profile.nickname,createdAt:db.serverDate()": "ownerName:profile.contactName||profile.nickname,ownerOpenid:openid,createdAt:db.serverDate()",
    "if(item._openid!==openid)": "if(item.ownerOpenid!==openid)",
}
for old, new in replacements.items():
    if old not in source:
        raise SystemExit(f'missing: {old}')
    source = source.replace(old, new)
path.write_text(source, encoding='utf-8')
print('fixed cloud ownership fields')
