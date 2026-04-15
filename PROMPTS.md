# Project Prompts

本项目用于沉淀 OpenCLI、58 星河接口探查和系统操作接口 skill。后续让 AI/Codex 修改本项目时，默认遵守以下提示词约定。

## 通用提示词

```text
你在 /Users/cocoon97/Documents/AICode/openCli 项目中工作。

请遵守：
1. 优先复用现有 skill、脚本和目录结构，不要重复造轮子。
2. OpenCLI 安装、部署、Browser Bridge 诊断相关内容放到 skills/opencli-setup。
3. 58 星河页面探查、页面字段、页面接口发现记录放到 skills/dp58-task-list。
4. 58 星河系统操作接口脚本放到 skills/dp58-system-api。
5. 所有 Python 脚本命名不能重复；新增 .py 前必须全项目检查是否已有同名文件。
6. 如果多个 skill 需要复用同一个 Python helper，只保留一个正式 helper，其他脚本通过明确路径引用，不要复制多个同名 helper。
7. 一个接口尽量对应一个脚本；脚本名应表达接口语义。
8. 修改脚本后运行 python3 -m py_compile 做语法检查。
9. 不要把个人 cookie、token、密码、完整登录态写入仓库。
10. 查询机构相关任务时，必须区分“当前机构上下文”和返回字段里的 dept_id；需要跨机构查询时使用系统 skill 的机构切换能力。
11. 复合脚本可以放在项目根目录，脚本名必须表达组合动作，避免与 skill 内单接口脚本重名。
12. 所有脚本必须有中文注释；至少在文件顶部用中文说明脚本用途，复杂逻辑处也要用中文注释解释。
13. 编写或修改 SKILL.md 时，保持边界清晰、内容精简；不要写接口输入/输出示例，改为列举接口脚本及其调用方式。
```

## Python 脚本命名规则

新增 Python 脚本前先检查：

```bash
find . -name '*.py' -print
```

不得新增与现有脚本 basename 相同的文件。例如已有：

```text
skills/dp58-task-list/scripts/get_task_list_page.py
```

则其他目录下不能再新增：

```text
get_task_list_page.py
```

如确实需要兼容旧入口，优先使用以下方式之一：

- 删除旧入口，只保留正式脚本。
- 改成不同语义的文件名。
- 在文档中指向正式脚本，而不是复制一份同名脚本。

## 脚本注释规则

所有脚本必须有中文注释。

最低要求：

- 文件顶部必须有中文说明，解释脚本用途。
- 复杂逻辑、跨接口编排、状态恢复、临时切换上下文等位置必须有中文注释。
- 注释要解释“为什么这样做”，不要只复述代码。

示例：

```python
# 复用 Chrome 登录态，通过 OpenCLI 在页面主上下文中调用接口。

# 查询前临时切换机构，finally 中必须切回原机构，避免污染浏览器状态。
```

## Skill 边界

```text
opencli-setup:
  只放 OpenCLI 安装、部署、升级、Browser Bridge 扩展、doctor 诊断和常见故障。

dp58-task-list:
  只放 task-list 页面探查记录、页面接口发现、字段说明、页面筛选参数说明。

dp58-system-api:
  只放可执行的系统操作接口脚本，例如切换机构、获取任务列表、批量导出等。

项目根目录:
  可放跨接口复合脚本，例如切换机构后查询任务列表并自动切回。
```

## SKILL.md 编写规范

修改或新增 `SKILL.md` 时遵守：

- Frontmatter 的 `description` 必须准确描述触发场景，不能把不属于该 skill 的功能写进去。
- 每个 skill 只写自己的职责边界；跨边界能力用路径或 skill 名指向，不复制说明。
- 文档要短，优先写“怎么用”和“何时用”，不记录完整探索历史。
- 不写接口输入示例和输出示例；接口能力通过脚本路径、参数和调用命令体现。
- 可以列接口方法和路径，但必须配套对应脚本调用方式。
- 不写超长响应结构、完整字段清单、字段映射大全、Adapter 伪代码，除非用户明确要求。
- 脚本说明只列脚本路径、核心参数和 1-3 条常用命令。
- 如果功能已经迁移到其他 skill 或根目录脚本，只给引用，不保留旧功能的详细描述。
- 不写个人 Cookie、Token、密码、完整登录态、个人隐私数据。

推荐结构：

```text
---
name: ...
description: ...
---

# Skill Name

一句话说明用途。

## 前置条件

必要环境和依赖。

## 脚本

脚本路径、常用命令、核心参数。

## 接口

列接口方法、路径、对应脚本和脚本调用方式；不要放输入/输出 JSON 示例。

## 注意事项

只写会影响正确性或安全性的点。
```

## 验证提示词

```text
修改完成后请验证：
1. find . -name '*.py' -print | awk -F/ '{print $NF}' | sort | uniq -d
   结果必须为空，表示没有重复 Python 脚本名。
2. python3 -m py_compile $(find skills -name '*.py' -print)
   必须通过。
3. python3 - <<'PY'
   from pathlib import Path
   import re
   missing = []
   for path in Path('.').rglob('*.py'):
       text = path.read_text(encoding='utf-8')
       if not re.search(r'[\u4e00-\u9fff]', text):
           missing.append(str(path))
   print('\n'.join(missing))
   PY
   结果必须为空，表示所有 Python 脚本都包含中文注释。
4. 如果修改了 OpenCLI 调用脚本，至少运行一个 --compact 的最小查询验证。
```
