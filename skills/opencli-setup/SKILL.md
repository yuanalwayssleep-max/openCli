---
name: opencli-setup
description: Use when installing, deploying, upgrading, or diagnosing OpenCLI on this machine, especially setting up Node 22, installing @jackwener/opencli, configuring the Chrome Browser Bridge extension, and verifying opencli doctor before other OpenCLI-based skills run.
---

# OpenCLI Setup

用于在本机安装、部署、升级和诊断 OpenCLI。其他依赖 `opencli browser` 的 skill，应先确认本 skill 的检查通过。

## 安装 OpenCLI

本机推荐使用 Node 22：

```bash
source ~/.nvm/nvm.sh
nvm install 22
nvm use 22
npm install -g @jackwener/opencli
```

验证版本：

```bash
source ~/.nvm/nvm.sh
nvm use 22
opencli --version
```

## 安装 Browser Bridge 扩展

浏览器类命令需要 Chrome 扩展：

```text
OpenCLI Browser Bridge
```

安装步骤：

1. 打开 OpenCLI releases：

```text
https://github.com/jackwener/opencli/releases/latest
```

2. 下载扩展 zip，文件名通常类似：

```text
opencli-extension-v*.zip
```

3. 解压 zip。
4. 打开 Chrome：

```text
chrome://extensions
```

5. 打开「开发者模式」。
6. 点击「加载已解压的扩展程序」。
7. 选择刚才解压出的扩展目录。

## 诊断

安装后运行：

```bash
source ~/.nvm/nvm.sh
nvm use 22
opencli doctor
```

成功输出应包含：

```text
[OK] Daemon
[OK] Extension
[OK] Connectivity
```

## 常用命令前缀

在本机脚本中调用 OpenCLI 时，优先使用这个前缀，避免 shell 没加载 nvm 导致 `opencli: command not found`：

```bash
source ~/.nvm/nvm.sh && nvm use 22 >/dev/null && opencli ...
```

Python 脚本中可用：

```python
import subprocess

cmd = "source ~/.nvm/nvm.sh && nvm use 22 >/dev/null && opencli doctor"
subprocess.run(["zsh", "-lc", cmd], check=True)
```

## Browser 验证

确认扩展连上后，用一个公开页面做最小验证：

```bash
source ~/.nvm/nvm.sh
nvm use 22
opencli browser open https://example.com
opencli browser state
```

如果能看到页面 title 和 DOM 结构，说明 `opencli browser` 可用。

## 常见问题

### opencli: command not found

当前 shell 没加载 Node 22 环境。先运行：

```bash
source ~/.nvm/nvm.sh
nvm use 22
command -v opencli
```

如果仍然不存在，重新安装：

```bash
npm install -g @jackwener/opencli
```

### Extension not connected

`opencli doctor` 出现：

```text
[MISSING] Extension: not connected
[FAIL] Connectivity
```

处理：

1. 确认 Chrome 已打开。
2. 确认 `chrome://extensions` 中 OpenCLI Browser Bridge 已启用。
3. 重新运行：

```bash
opencli doctor
```

如果 daemon 状态异常，可重启：

```bash
opencli daemon stop
opencli doctor
```

### 写入 ~/.opencli 失败

OpenCLI 首次运行会初始化：

```text
~/.opencli/package.json
~/.opencli/adapter-manifest.json
~/.opencli/clis/
```

如果受沙箱或权限限制导致写入失败，需要在允许写用户目录的环境中重新运行：

```bash
source ~/.nvm/nvm.sh
nvm use 22
opencli doctor
```

## 完成标准

在继续使用其他 OpenCLI skill 前，必须满足：

- `opencli --version` 能输出版本。
- `opencli doctor` 的 Daemon、Extension、Connectivity 都是 OK。
- `opencli browser open <url>` 和 `opencli browser state` 能正常返回页面结构。
