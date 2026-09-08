# 参与开发

使用 uv 管理 Python 依赖和 `.venv`，Python 3.10+。

```powershell
uv sync --frozen
uv run --frozen python -m unittest discover -v
npm ci --prefix .test-tools
uv run --frozen node tests/test_ui.js
uv run --frozen python scripts/build_release.py
```

Anki 端仅使用 AnkiConnect 标准 API，不再开发或发布自定义 Anki 队列插件。GoldenDict 按钮的本地 Python 服务仅负责通信、参数验证和调用标准 API；命令行提队直接调用相同业务逻辑。

## 测试范围

- `tests/test_bridge.py`：查询、词形匹配和提队业务逻辑，使用模拟 API 返回值。
- `tests/test_transport.py`：真实本地 HTTP 服务与模拟 AnkiConnect 客户端，覆盖令牌、Origin 兼容、操作范围和失败处理。
- `tests/test_ui.js`：使用 jsdom 和模拟 HTTP，覆盖多词条隔离、默认选中、暂停授权、绿卡反馈与重复提交保护。Node.js 会调用 Python 生成测试 HTML，因此应通过 `uv run` 执行。
- `tests/test_native_due_date.py`：可选的真实 Anki 搜索与调度测试，在项目内创建并清理独立临时集合，不读取或修改用户的学习集合。

默认 `unittest discover` 会跳过未配置 Anki 运行时的原生测试。变更搜索语法或调度 API 调用时，还应运行原生测试；仅通过模拟测试不能证明 Anki 接受这些参数。

## 真实 Anki 运行时测试

以下命令对应已验证的 Anki 26.8.1 / Python 3.13 环境。将 `ANKI_APP_PACKAGES` 改为本机路径，并选择与 Anki 包匹配的 Python 版本：

```powershell
$env:ANKI_APP_PACKAGES = 'C:\Program Files\Anki\app_packages'
uv run --frozen --python 3.13 python -m unittest tests.test_native_due_date -v
Remove-Item Env:ANKI_APP_PACKAGES
```

该测试通过适配客户端将生产提队逻辑的 `findCards`、`unsuspend` 和 `setDueDate` 调用交给真实 Anki 引擎，验证搜索语法、解除暂停和转为今天的复习卡。它没有启动真实 AnkiConnect HTTP 服务，也不覆盖完整 GoldenDict 界面链路；报告验证结果时应区分这些范围。

## 修改时的检查

- 筛选牌组检查使用 `cid:<id> deck:filtered`，不要使用无效的 `is:filtered`。
- `unsuspend` 在部分 AnkiConnect 版本中成功后返回 `null`。模拟测试应覆盖返回 `null`、`true`、`false` 的情况，并以重新读取的卡片状态确认是否可以继续；不要只模拟理想的布尔成功值。
- 解除暂停后重新核对词头、牌组、类型和筛选牌组状态，确认 `queue == 0` 才调用 `setDueDate(cards=[id], days="0")`。
- 覆盖卡片未解除暂停、检查期间卡片状态变化、API 报错和部分成功；这些调用不是事务，不能自动重试写操作。
- 修改网页交互时，验证多词条隔离、默认选中、状态提示及重复提交保护。本地服务只提供受令牌保护的健康检查和提队入口，不能扩展为网页可任意调用的 Anki API 代理。

修改 `cli.py`、`bridge.py` 或配置后，重新查词会按新版本建立或复用服务。旧页面仍绑定原服务；手动验证时必须生成新页面。模板或脚本修改同样需要重新查词，一般无需重启 Anki。

## 打包

`scripts/build_release.py` 生成 `dist/goldendict-anki-recaller-source.zip`，并删除旧的 `dist/goldendict-anki-recaller.ankiaddon` 构建产物。文档更新后重新打包，确保发布包与工作区一致。升级说明应保留“删除或禁用旧队列插件后重启 Anki”的要求，避免旧补丁继续影响原生调度。

不要提交 `config.json`、`.venv`、运行令牌、临时数据库或本机学习数据。发布包仅包含源码、文档和测试。
