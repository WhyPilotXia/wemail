import json
from pathlib import Path

SOURCE = Path('/Users/lhc/Documents/git包/小说/_site')
TARGET = Path('/Users/lhc/Documents/git包/wemail/miniprogram/data/books')
TARGET.mkdir(parents=True, exist_ok=True)
intros = {
    '李氏庄园': '十七岁的李明修就读于广西贵族自治区千色高级中学，出身与本地教育史深度交织的家族。在这座暗流涌动的世界中，他们将会碰撞出什么样的火花？',
    '回信券风暴': '重庆国际学校高中生小叶迷恋这个时代最慢的通信方式。几张国际回信券，意外成为撬动世界经济的第一块多米诺骨牌。',
    '股神牛久盛': '恒申破产之后，熊久盛拜姓牛的牛来为师并改名牛久盛。他最终会成为真正的股神，还是市场里最大的笑话？',
    '名将之后': '李铭修写的故事。',
    '心非黍离专栏': '李铭修写的一系列随笔与专栏文章。',
}
colors = {'李氏庄园':'#2C806F','回信券风暴':'#D65A43','股神牛久盛':'#C18A2F','名将之后':'#53658C','心非黍离专栏':'#8A4FBF'}
books = []
for folder in sorted(SOURCE.iterdir()):
    catalog_file = folder / 'chapters.json'
    if not folder.is_dir() or not catalog_file.exists():
        continue
    catalog = json.loads(catalog_file.read_text(encoding='utf-8-sig'))
    key = folder.name
    chapters = []
    for item in catalog:
        chapter_file = folder / item['file']
        if not chapter_file.exists():
            continue
        text = chapter_file.read_text(encoding='utf-8-sig').strip()
        if text.startswith('# '):
            text = '\n'.join(text.splitlines()[1:]).strip()
        chapters.append({'num': item.get('num',''), 'title': item.get('title',''), 'content': text})
    if not chapters:
        continue
    output = TARGET / f'{key}.js'
    output.write_text('module.exports = ' + json.dumps(chapters, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    books.append({'key':key,'title':key,'intro':intros.get(key,''),'color':colors.get(key,'#1769FF'),'chapters':len(chapters)})
index = Path('/Users/lhc/Documents/git包/wemail/miniprogram/data/books.js')
index.parent.mkdir(parents=True, exist_ok=True)
index.write_text('module.exports = ' + json.dumps(books, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'imported {len(books)} books, {sum(x["chapters"] for x in books)} chapters')
