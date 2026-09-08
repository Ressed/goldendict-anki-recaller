# goldendict-anki-recaller

从 GoldenDict-ng 查找 Anki 中已有的卡片，选择义项后，将新卡设为**今天到期的复习卡（绿卡）**。不创建笔记或重复卡片。

Anki 端只需要 **AnkiConnect**。提队使用标准 `setDueDate(cards=[id], days="0")`，不安装自定义队列插件、不接管作答或维护当天学习计划。

## 行为

- 查询、词形还原和选择义项只读；点击「提队所选卡」才修改卡片。
- 所选新卡转为今天到期的复习卡，跳过首次新卡学习阶段。
- 不受新卡额度影响，包括新卡额度为 0 的子牌组；仍受父牌组和子牌组的**复习额度**、埋藏等原生规则影响。
- 牌组归属不变，后续作答、混排、复习和同步全部由 Anki 管理。
- 不保证所选卡排第一，也不冻结原有队列的逐张顺序；队列重建时按 Anki 当前配置安排。
- 暂停的新卡需勾选解除暂停；程序会确认卡片已恢复为未暂停的新卡，再设置今天到期。已经学习、复习、埋藏或位于筛选牌组中的卡片不会被本操作改动。
- 无需预先选择指定父牌组，不主动切换牌组或翻动当前题目。数量或画面尚未更新时，返回牌组概览后重新进入学习。

## 环境与安装

需要 Windows、Python 3.10+、uv、GoldenDict-ng，以及安装并启用 AnkiConnect 的 Anki 桌面版。查词环境使用 Python 3.14 验证。

```powershell
uv sync --frozen
Copy-Item config.example.json config.json
```

已有 `config.json` 时保留原文件。配置示例：

```json
{
  "url": "http://127.0.0.1:8765",
  "deck": "English",
  "field": "Word",
  "sense_fields": ["DefinitionTR", "Definition"],
  "label_fields": ["PoS", "Label"],
  "lemmatize": true,
  "case_sensitive": false,
  "timeout": 10,
  "api_key": null
}
```

`deck` 限定检索范围（包括子牌组），`null` 表示整个集合。`field` 是词头字段；释义和标签字段按实际笔记类型填写。若 AnkiConnect 配置了 API key，填写 `api_key` 或设置 `ANKICONNECT_API_KEY` 环境变量。

**从旧版本升级：在 Anki 中删除或禁用 GoldenDict Anki Recaller 自定义插件，保留 AnkiConnect，然后重启 Anki。** 旧插件已经加载的队列补丁需要重启才能解除。当前版本不再发布 `.ankiaddon` 文件。

## GoldenDict 设置

「编辑 → 词典 → 来源 → 程序 / Programs」新增 **HTML** 程序，将项目路径替换为实际路径：

```text
"C:\Tools\goldendict-anki-recaller\.venv\Scripts\python.exe" "C:\Tools\goldendict-anki-recaller\anki_recall.py" -- "%GDWORD%"
```

已有命令无需修改，更新代码后重新查词即可。不要把 `--promote` 加进自动查询命令。

查到卡片后，默认选中第一张；按义项选择，点击「提队所选卡」，成功后显示“今天到期（绿卡）”。页面等待过久或提交结果不确定时，重新查词后再核对，不自动重试写操作。

GoldenDict 会改写 HTTP Origin，因此按钮通过自动启动的**本地 Python 转发服务**访问 AnkiConnect。该服务只监听随机的 `127.0.0.1` 端口，同一项目路径、配置和转发代码版本复用进程，空闲 30 分钟退出；无需手动启动或新增 Anki 插件。它不提供任意 Anki API 转发，只接受带随机令牌的提队请求并重新检查卡片。

无需为本项目修改 AnkiConnect 的 CORS 白名单。之前添加的来源可以保留；不需要 `*`。API key 留在 Python 端，不进入词典 HTML。生成页面中的本地操作令牌也不要分享。

## 词形还原

默认使用离线 Simplemma 同时检索输入词和原形，例如 `tournaments → tournament`、`children → child`、`running/ran → run`。两者都有卡片时分别显示，避免 `saw` 等歧义词被覆盖。多词短语和非英语输入仍精确查询；`lemmatize: false` 可关闭还原。

![词形还原查询](docs/images/lookup-inflection.png)

![按义项选择已有卡片](docs/images/select-sense.png)

截图中的词典内容仅供演示，项目不包含词库；截图可能包含旧版按钮说明。

## 命令行

```powershell
uv run --frozen python anki_recall.py --inspect --format text
uv run --frozen python anki_recall.py --format text -- tournament
uv run --frozen python anki_recall.py --promote --card-id 1234567890000 --format text -- tournament
```

多张可用新卡必须指定 `--card-id`。解除暂停需同时指定 `--promote --unsuspend`。`--stdin` 从标准输入读取词头；`--full-scan` 可检查整个目标范围。文本和 JSON 输出不启动本地按钮服务，命令行提队直接访问 AnkiConnect。

## 更新与故障排查

- **更新代码后怎么生效？** 重新查询词条，让 GoldenDict 生成新页面。转发代码变更后会自动启动对应版本的服务；旧页面仍可能连接旧服务，不要继续使用。通常无需重启 Anki，只有移除旧自定义队列插件时需要重启。
- **解除暂停后报错，卡片仍是新卡？** 解除暂停与设置到期日是两个独立操作。重新查词确认状态：若已是未暂停的新卡，直接提队；若已是复习卡，则不要重复操作。当前实现按解除暂停后的实际状态判断成功，兼容 AnkiConnect 返回 `null` 的情况。
- **报 `is:filtered` 搜索无效？** 这是旧版代码的错误语法，当前已改用 `deck:filtered`。更新代码并重新查词，避免继续连接旧页面的服务。
- **显示今天到期，却没有立即出现？** 检查正在学习的牌组范围、父子牌组复习限额及卡片埋藏状态；必要时返回概览再进入学习。今天到期不等于强制插入当前队列首位。
- **提示服务不可用或提队未确认？** 先确认 Anki 已打开、AnkiConnect 已启用及 API key 正确，再重新查词。空闲服务会自动退出；超时或断线不代表写入失败，核对卡片状态后再操作。

## 开发与打包

见 [参与开发](CONTRIBUTING.md) 和 [行为说明](docs/behavior.md)。

```powershell
uv run --frozen python -m unittest discover -v
npm ci --prefix .test-tools
uv run --frozen node tests/test_ui.js
uv run --frozen python scripts/build_release.py
```

发布包为 `dist/goldendict-anki-recaller-source.zip`，不包含本地配置、运行令牌、学习数据或旧队列插件。

默认 Python 测试会跳过需要本机 Anki 运行时的原生测试；运行方法见 [参与开发](CONTRIBUTING.md)。
