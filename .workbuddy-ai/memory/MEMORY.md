# 项目长期约定（bytecode2code）

## 仓库
- 远端：https://github.com/llll35/bytecode2code （main）
- 提交信息用英文，正文说明「现象 / 根因 / 修法」，与 CHANGELOG.md 风格一致。

## 什么入库、什么不入库
- 不入库：`embed_python/`（313MB 解释器）、`.venv/`、`.workbuddy-ai/`、`*.bak`、
  `opencode_session.bat`、`_scratch/*.txt|out|err`。
- 例外：`tests/samples/*.pyc` **必须入库**——是测试夹具，没有对应解释器无法重建。
- `_scratch/*.py` 保留，bugs.md 的验证命令直接引用它们。

## 测试与基线（改动前后都要对）
- `python -m tests.run`：61/66（3.9 组 34/34；3.12 组 27/32）
- `python main.py selftest`：373 项 / 3 失败（`3.10 with try`、`3.11 nested try`、`3.12 nested try`）
- `python -B _scratch/probe_controlflow.py 3.9 3.10 3.11 3.12`：约 30 失败
- 失败项多为 bugs.md 里标注的已知缺陷；修一个就跑这三条确认无回归。

## 网络（Windows 本机）
- 推 GitHub 走 **SSH**（22 端口稳定）；HTTPS 到 github.com 间歇被阻断。
- `~/.ssh/config` 有 Host github.com 块把 HostName 固定到 20.205.243.166，
  key 为 `~/.ssh/id_ed25519_bytecode2code`。若 IP 失效，换一个可用 IP 或删掉该块。
- git 命令若走 HTTPS，需 `-c http.proxy=` 绕开沙箱代理。
