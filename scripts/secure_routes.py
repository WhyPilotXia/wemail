from pathlib import Path

path = Path('/Users/lhc/Documents/git包/wemail/cloudfunctions/wemail/index.js')
source = path.read_text(encoding='utf-8')
old = "case'mail.create':await createMail(event);return ok({created:true});case'mail.sign':await notion(`/pages/${event.pageId}`,'PATCH',{properties:{'签收':{checkbox:true}}});return ok({signed:true})"
new = "case'mail.create':await createMail(openid,event);return ok({created:true});case'mail.sign':await signMail(openid,event.pageId);return ok({signed:true})"
if old not in source:
    raise SystemExit('route text not found')
path.write_text(source.replace(old, new, 1), encoding='utf-8')
print('secured mail routes')
