# WeMail 微信小程序

个人信件与发现工具。界面参考 Mail Web，针对移动端重构为“信件、发现、我的”三个标签页。

## 已实现

- 信件：近 14 天统计、全部/寄出/收到/待签收筛选、登记寄件、签收、通讯录和地址复制；寄件记录仅寄件人与收件人可见，不提供信件正文或留言。
- 发现：小说书架、53 章本地阅读、字号调节、章节目录、无需登录的本地邮费试算、抽奖和限额报名；活动仅管理员发布，普通用户只能参与。
- 我的：微信头像昵称、姓名与手机号关联（核验 Notion 联系人表）、仪表盘、资料与地址编辑。
- 安全：仅联系人表中身份核验成功的用户可访问通讯录、寄件记录和活动；一个联系人身份同时只绑定一个微信账号；寄件人、收件人、签收及管理员权限均在服务端校验。

邮费试算使用随小程序发布的本地数据，不调用后端，也不保存重量、尺寸或试算金额。更新数据时克隆或拉取 `https://github.com/ImMrCloud/mail-postage-data`，执行 `npm run sync:postage -- /path/to/mail-postage-data`，确认测试后重新发布小程序。数据许可见 `THIRD_PARTY_NOTICES.md`。

## 目录

- `miniprogram/`：原生微信小程序前端。
- `cloudfunctions/wemail/`：统一业务云函数。
- `scripts/import_books.py`：从小说项目重新导入书籍的脚本。

## 首次部署

仓库包含完整源码、内置书籍数据、测试、启动脚本和安全配置模板。克隆后仅需自行提供微信小程序 `WECHAT_APP_SECRET` 与 Notion `NOTION_TOKEN` 两项凭据；服务器地址、AppID、数据源 ID 和其他运行参数均已有可修改默认值。

1. 使用微信开发者工具打开本目录，确认 AppID 为 `wx740d98c545a2eed0`。
2. 在“云开发”中选择或创建环境，并将 `miniprogram/config.js` 的 `envId` 改为该环境 ID。
3. 在云数据库创建 `users` 与 `events` 两个集合。两个集合都应设置为“仅创建者可读写”，业务写入仍统一经过云函数。
4. 右键 `cloudfunctions/wemail`，选择“上传并部署：云端安装依赖”。
5. 在该云函数的环境变量中设置：

```text
NOTION_TOKEN=现有 Notion Integration Token
NOTION_VERSION=2025-09-03
CONTACT_DATA_SOURCE_ID=31e70d82-c716-8034-b23d-000ba20878af
RAS_DATA_SOURCE_ID=31e70d82-c716-80ba-b4d2-000b1892f62c
RAS_DATABASE_ID=31e70d82-c716-80d3-9f2d-e73dcc4033b3
ADMIN_PHONE=管理员在联系人表中的手机号
MAIL_NOTE_ENABLED=false
```

`ADMIN_PHONE` 对应的手机号必须已存在于联系人表。`MAIL_NOTE_ENABLED=false` 时前后端均不提供寄件备注，服务端也会忽略客户端伪造的备注参数；个人主体版本请保持关闭。

6. 编译后依次验收“信件、发现、我的”，并使用两个微信账号测试寄信、签收和活动参与；同一联系人身份换绑时会提示解绑原账户。

## Notion 要求

联系人数据源字段：`姓名/昵称`、`电话`、`电子邮箱`、`地址1`、`邮编1`、`地址2`、`邮编2`、`QQ`。

联系人信息不脱敏。

信件数据源字段：标题字段 ` `、`寄件人`、`收件人`、`寄出日期`、`备注`、`邮件编号`、`签收`。其中标题字段由服务端写入固定系统文案，`备注`字段仅保存邮件类型，不接收用户自由文本。

Notion Integration 必须被邀请到联系人数据库和信件数据库，否则云函数无法访问。

## 本地检查

```bash
find miniprogram cloudfunctions/wemail -type f -name '*.js' -print0 | xargs -0 -n1 node --check
```

小说源更新后重新执行：

```bash
python3 scripts/import_books.py
```

## 注意

小程序仅登记线下实体邮件信息，不提供信件正文、留言、评论、用户内容发布、在线邮寄、支付或物流承运服务。寄件记录仅寄件人与收件人可见。抽奖和报名由小程序管理员统一发布，普通用户不能发布或编辑活动内容；活动不涉及付费参与、现金奖品、强制分享或商业营销。
