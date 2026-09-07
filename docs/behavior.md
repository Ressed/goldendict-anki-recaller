# goldendict-anki-recaller：已有卡片提队规则

本项目从完整牌组中查找已有卡片并调整学习顺序，不创建笔记或卡片。Windows，Python 3.10+；队列插件已用本机 Anki 26.8.1 的真实调度器在独立测试集合中验证。

## 当前行为

正常查词和选择义项只读取卡片。点击「提队所选卡」才改变当天的学习计划：

1. 在 Anki 先选择配置中的父牌组 `English`。可处于该牌组概览或学习界面。
2. 第一次插队时，保存 Anki 已按各子牌组限额和随机规则选出的待学新卡顺序。
3. 所选新卡插到队列最前面，并立即在 Anki 学习界面显示。当前尚未作答的卡不会被当作已学。
4. 如果「父牌组今天已学新卡数＋插入后的待学新卡数」超出父牌组新卡限额，移出末尾未学新卡，直到符合限额。仅移出当天计划，不删除、不暂停、不埋藏卡片。
5. 若父牌组今天已学数已经达到或超过限额，额外加入所选卡，不挤掉现有待学卡。这里“达到”也视为额度用完。
6. 已在计划中的卡仅移到最前面，不重复增加名额。连续插队时，最新点击的卡最先显示。

所选卡可来自限额为 0 的子牌组。这是用户显式指定的例外；其他普通新卡仍来自原来选出的学习计划。各牌组的原始限额、随机收集/排序设置、卡片所属牌组和新卡位置不被改写。

这里的限额指父牌组的**每日新卡限额**，并非新卡、复习卡和学习步骤次数的总和。踢出的仅是未学新卡，不会丢弃到期复习卡或学习步骤。插队卡首次作答后，后续学习步骤重新由 Anki 原生调度器安排。

## 更新与使用

- 当前版本新增 `addon/priority_queue.py`，必须在 Anki「工具 → 插件 → 从文件安装」重新安装 `dist/goldendict-anki-recaller.ankiaddon`，然后重启 Anki。
- 保留现有 GoldenDict Program 命令，重新查词即可读取新的 HTML/JS。
- 只要查询有结果，默认选中返回的第一张卡；需要其他义项时再点击对应单选框。随后点「提队所选卡」。暂停的新卡需明确勾选解除暂停。学习中、复习、埋藏和筛选牌组中的卡不支持本操作。
- 成功后会显示当前队列首位及移出的卡片数量。按钮防止重复提交；写入结果不确定时需重新查词、核对 Anki 后再操作。
- 界面会检查插件返回的行为版本，避免旧版仅重排位置却被显示为插队成功。

## 当天计划与限制

当天计划保存在插件的 `user_files` 目录，按 Anki 集合路径隔离；重启后仍可继续，跨 Anki 学习日自动失效。它仅影响当前电脑且插件启用时的学习队列，不通过 Anki 同步到手机。

计划中的卡若被删除、移出父牌组、暂停、埋藏或已开始学习，将不再作为待学新卡出现。首次作答后可以使用 Anki 原生撤销恢复该卡；继续插队或更改计划后，旧计划不提供独立撤销历史。

父牌组总限额在当天修改后，会在下一次取队列时调整容量；增加容量时从原生队列补充。首次插队后，普通新卡的选择顺序保持稳定；若只修改子牌组的限额，已有计划不会重新随机抽签，翌日按新配置收集。

数量以**学习界面**显示的待学数为准。牌组列表使用 Anki 原生牌组统计，不保证展示临时插队计划的数量。若 Anki 正在提交作答，插件会要求稍后重试。

## HTML 与字段配置

- `goldendict_anki/cli.py`：精确匹配、卡片摘要、命令行接口。
- `goldendict_anki/html_view.py` / `goldendict_anki/templates/lookup.html`：Jinja2 文件模板，自动转义文本，安全序列化脚本配置。
- `goldendict_anki/static/lookup.css` / `goldendict_anki/static/lookup.js`：局部样式、选卡和请求处理。
- `addon/__init__.py`：执行前检查、AnkiConnect action 及 CORS 兼容。
- `addon/priority_queue.py`：当天新卡计划、原生队列读取适配、原生作答及撤销合并。

当前 `config.json` 的 `sense_fields` 为 `DefinitionTR`、`Definition`，`label_fields` 为 `PoS`、`Label`。每张卡显示独立义项，也可展开卡面文本摘要；不执行原始卡面脚本。

## 英语词形还原查询

默认启用 `"lemmatize": true`。程序使用随项目离线提供的 Simplemma 2.0.0，将单个英语词的复数、时态、比较级等还原为词典原形，例如 `tournaments → tournament`、`children → child`、`running/ran → run`、`went → go`、`studies/studied → study`、`better → good`。

一次 Anki 搜索会同时检查用户输入词头和还原后的原形：

- 只有原形存在时，标题显示 `输入 → 原形`。
- 两者都存在时，两组卡都显示，并在每张卡上标注实际词头，避免把 `saw` 之类的名词词条静默覆盖成动词 `see`。
- 选择卡片后，提队插件按该卡的实际词头二次验证，不会拿变形词误验原形卡。
- 多词短语、数字、标点或非英语输入不做词形变换，继续精确查询。

Simplemma 不使用上下文和词性，个别歧义词可能给出不符合当前语境的原形；保留输入词头结果就是为用户提供人工选择。若希望恢复只查原词，将 `config.json` 的 `lemmatize` 改为 `false`。该库是纯 Python、无运行时网络请求，也不需要下载语言模型。

复制项目时保留 `goldendict_anki` 和 `vendor`。缺少依赖时，在项目目录运行：

```powershell
python -m pip install --target vendor --upgrade -r requirements.txt
```

也可用 `--stdin` 让 GoldenDict 通过标准输入传词。不要把 `--promote` 写入自动查询命令。

命令行显式操作也使用当前学习队列插队：

```powershell
python anki_lookup.py --format text -- tournament
python anki_lookup.py --promote --card-id 1234567890000 --format text -- tournament
```

多张可用新卡必须指定卡片 ID。默认精确匹配词头（去 HTML、合并空白、Unicode NFC、忽略大小写）；`--full-scan` 可完整扫描目标范围，`--inspect` 可检查牌组和字段。

## AnkiConnect 来源设置

本机 AnkiConnect 保持监听 `127.0.0.1:8765`，来源设置：

```json
"webCorsOriginList": ["http://localhost", "gdlookup://localhost"]
```

GoldenDict 的网络拦截器会改写 POST 的 Origin。插件仅对标记为本桥接请求、指定 action、本机地址和端口匹配、且 `gdlookup://localhost` 已明确加入白名单的请求纠正 CORS 响应。API key 和卡片状态验证仍生效。不要用 `no-cors` 或 `*` 代替。

如仍失败，在 GoldenDict F12 → Console 查看具体错误。`api_key` 会进入本地交互 HTML，不要分享含密钥的生成页面。

## 验证

```powershell
python -m unittest tests.test_bridge -v
node tests/test_ui.js
```

交互测试依赖 `.test-tools` 的 jsdom，可用 `npm ci --prefix .test-tools` 恢复。HTTP 全部模拟。

真实调度器集成测试环境见 [参与开发](../CONTRIBUTING.md)。

仅在项目内创建独立临时集合，不操作用户数据。覆盖零额度子牌组插队、末尾替换、额度用尽追加、重复插队、随机顺序保留、正常作答/复习记录、Again/撤销、计划重载、跨天、父牌组限额修改及插件 action 刷新调用。真实 GoldenDict → Anki 界面链路需安装新版插件后确认。

Anki 的底层队列不提供公开的任意插队接口。本插件适配 V3 Python 取卡/作答入口，并在计划启用时用原生卡片更新使旧队列失效，再执行原生作答；这两个步骤合并为一次可撤销操作。Anki 大版本升级或其他修改调度器的插件可能需要重新适配。
