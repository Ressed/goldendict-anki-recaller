# 提队行为与实现

提队完全使用 AnkiConnect 标准 API：选中的未学新卡通过 `setDueDate(cards=[id], days="0")` 转成今天到期的复习卡（绿卡）。不创建卡片，不移动牌组，不写入自定义队列计划，不接管 Anki 的取卡和作答。

## 写入流程

1. 查词及义项选择只读，按钮点击或命令行 `--promote` 才开始操作。
2. 使用 `cardsInfo` 重新读取卡片，核对 ID、牌组、词头和新卡状态；使用 `findCards(query="cid:<卡片ID> deck:filtered")` 检查筛选牌组状态。部分 AnkiConnect 版本的 `cardsInfo` 不返回 `odid`，因此仍需搜索确认。`is:filtered` 不是有效语法。
3. 若新卡暂停，必须明确授权，然后调用 `unsuspend(cards=[id])`。部分 AnkiConnect 版本成功执行后返回 `null`，不能要求返回值必须为 `true`。
4. 解除暂停后，再执行一次上述 `cardsInfo` 和 `findCards` 检查。只有卡片仍为匹配词头、匹配牌组的普通新卡，并且 `queue == 0`，才继续。卡片仍暂停或状态、词头、牌组发生变化时停止。
5. 调用 `setDueDate(cards=[id], days="0")`。只有返回 `true` 才显示设置成功。

不处理已学习、复习、埋藏和筛选牌组中的卡片，防止旧查询页覆盖已经变化的复习安排。词头按该卡实际匹配到的原词或词形还原结果验证，去 HTML、规范化空白及 Unicode，并遵循大小写配置。

解除暂停和设置到期日是两个独立 API 操作，不是事务；后一步失败时，前一步可能已经完成。请求超时或结果不确定时不自动重试，应重新查词并在 Anki 核对。

未暂停的新卡依次调用 `cardsInfo → findCards → setDueDate`；暂停的新卡依次调用 `cardsInfo → findCards → unsuspend → cardsInfo → findCards → setDueDate`。配置中的 `timeout` 作用于单次 AnkiConnect 请求，网页等待整个流程的上限为 `6 × timeout + 5` 秒。

“提队未确认”是通用提示，不表示每次错误都已经产生写入。例如最初的词头或筛选牌组检查失败时，尚未执行解除暂停或设置到期日。若已解除暂停但设置到期日失败，刷新后仍是新卡是正常的部分成功状态；核对后可以直接再次提队，无需重新勾选解除暂停。

## 调度边界

新卡转为复习卡会跳过首次新卡学习步骤，后续按 Anki 原生复习规则作答。可以绕过新卡额度，包括零新卡额度子牌组，但到期复习仍受所学牌组和子牌组的复习限额、埋藏规则等影响。设置今天到期不承诺今天一定展示，也不承诺出现在首位。

混排规则、普通新卡选择、学习步骤、统计、撤销和同步全部交由 Anki。修改到期日可能重建队列，所以不冻结原有逐张顺序。页面不模拟作答、不强制翻页，也不主动切换牌组。必要时返回概览再进入学习，刷新当前展示和数量。

## 本地按钮服务

`goldendict_anki/bridge.py` 处理 HTML 查询和 GoldenDict 改写 Origin 后的按钮通信。HTML 查询时按需启动，随机绑定 `127.0.0.1` 端口；同一配置和代码版本复用进程，空闲 30 分钟退出。词形库和模板在进程内复用，Anki 查询结果不缓存。服务信息位于系统临时目录 `goldendict-anki-bridge`，不进入发布包。

按钮发送随机令牌及所选卡信息；服务只提供健康检查、只读词头查询和提队入口，重新验证卡片后使用标准 AnkiConnect API。查询入口只接受词头与全量扫描开关，配置由服务端持有；HTML 查询的整体等待上限为配置中的 `timeout`，单次 AnkiConnect 请求仍使用该超时。它不允许网页指定任意 AnkiConnect action，不接管调度器。AnkiConnect API key 不放入 HTML，也不需要浏览器访问授权或 CORS 配置修改。

页面过期或本地服务退出时，重新查词会重新建立连接。服务复用标识包含项目路径、有效配置以及包内 Python、HTML、CSS 和 JavaScript 的内容摘要；这些文件或配置变化后，新查询会连接新服务，已打开的旧页面不会自动切换。无需为普通代码更新重启 Anki。不要分享带操作令牌的 HTML。纯命令行提队不依赖这个服务。


## 文件与验证

- `goldendict_anki/cli.py`：查询、词形还原结果匹配、执行前检查及标准 API 调用。
- `goldendict_anki/bridge.py`：按需运行的本地按钮通信服务。
- `goldendict_anki/templates` 与 `static`：义项选卡、暂停授权、绿卡反馈及重复提交保护。
- `tests/test_bridge.py`：查询与纯 AnkiConnect 写入流程。
- `tests/test_transport.py`：本地 HTTP、Origin 兼容、令牌、输入限制与错误处理。
- `tests/test_native_due_date.py`：在独立临时集合中使用真实 Anki 搜索和调度器，验证普通／筛选牌组检查、暂停新卡解除暂停后转为今天的绿卡，以及其他卡片不被改动。未配置 Anki 运行时时跳过。
- `tests/test_ui.js`：多词条隔离、默认选择、按钮状态和结果不确定时禁止重试。

单元测试和 HTTP 测试模拟 AnkiConnect；原生测试通过适配客户端调用实际 Anki 搜索和调度方法，不等同于完整 GoldenDict → AnkiConnect 界面链路测试。所有测试都不修改真实学习集合，具体运行方法见 [参与开发](../CONTRIBUTING.md)。打包脚本只生成源码发布包，并清除旧 `.ankiaddon` 构建产物。
