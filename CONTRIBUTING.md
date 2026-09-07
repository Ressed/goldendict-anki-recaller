# 参与开发

建议使用独立虚拟环境。项目采用 Python 3.10+，真实 Anki 引擎测试需匹配所安装 Anki 使用的 Python 版本。

```sh
python -m pip install -r requirements.txt
python -m unittest tests.test_bridge -v
npm ci --prefix .test-tools
node tests/test_ui.js
python scripts/build_release.py
```

`tests/test_priority_queue.py` 使用独立临时集合，覆盖随机收集、零额度子牌组、总额度、插队、作答及撤销。先安装兼容的 Anki Python 包，或通过 `ANKI_APP_PACKAGES` 指向本机 Anki 的 `app_packages`，再用与其匹配的 Python 运行：

```powershell
$env:ANKI_APP_PACKAGES = 'C:\Program Files\Anki\app_packages'
python -m unittest tests.test_priority_queue -v
```

本项目曾在 Anki 26.8.1 / Python 3.13 上验证该集成测试。普通查词与模板测试使用 Python 3.14。请勿用真实学习集合运行测试。

修改队列逻辑时，请覆盖原生作答、撤销和不同每日限额；修改网页交互时，验证多词条隔离、默认选中、暂停授权和重复提交保护。不要提交 `config.json`、`vendor`、生成的预览、学习计划或集合数据库。

提交问题时请附上 Python、Anki、AnkiConnect 和 GoldenDict-ng 版本、复现步骤及去除密钥的错误信息。截图中的词典内容仅用于演示，不作为测试数据来源。
