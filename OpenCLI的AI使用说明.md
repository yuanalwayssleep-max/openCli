# OpenCLI AI 使用说明

这份文档面向 AI Agent，目标是让 AI 在需要操作网站、桌面应用或外部 CLI 时，能正确选择并使用 OpenCLI 相关 skill。

## 1. OpenCLI 是什么

OpenCLI 可以把网站、Electron 应用和部分外部 CLI 包装成统一命令行接口，供 AI 调用。

它主要覆盖三类能力：

1. 网站适配器
   例如 Bilibili、Twitter、Reddit、Xiaohongshu、YouTube、知乎、Google、arXiv。
2. 桌面应用适配器
   例如 Cursor、Codex、ChatGPT、Notion。
3. 外部 CLI 透传
   例如 `gh`、`docker`、`vercel`、`lark-cli`。

对 AI 来说，OpenCLI 的核心价值是：

- 复用已有登录态，不必重复处理账号密码
- 用统一命令替代脆弱的手工浏览器操作
- 输出结构化，便于继续推理、总结、写入或自动化

## 2. AI 何时应该使用 OpenCLI Skill

当用户的请求符合以下情况时，AI 应优先考虑 OpenCLI：

- 需要读取某个网站上的内容，而且该网站已有 OpenCLI 适配器
- 需要在网页中执行登录态相关操作，例如获取通知、收藏、私信、个人主页、已保存内容
- 需要和桌面应用交互，例如读取 Codex、Cursor、ChatGPT、Notion 当前内容
- 需要通过统一接口调用 `gh`、`docker` 等 CLI
- 需要把网页内容转成 Markdown 或结构化输出

典型例子：

- “帮我查一下 Reddit 热门帖子”
- “读取我的 Twitter 通知”
- “抓取这个网页正文并转成 Markdown”
- “列出当前 Codex 会话内容”
- “用 `gh` 看一下这个仓库的 PR”

## 3. 何时使用哪个 Skill

OpenCLI 相关 skill 不止一个，AI 需要按任务选择：

### `opencli-usage`

用于“使用已有 OpenCLI 命令”。

适合：

- 用户要查询、抓取、读取、发送、导出
- 目标站点或应用已经有现成命令
- AI 只需要调用，不需要开发新适配器

### `opencli-browser`

用于“浏览器自动化操作”。

适合：

- 需要点击、输入、等待页面变化
- 需要使用浏览器会话和页面交互
- 站点流程更偏 UI 操作，不只是读取数据

### `opencli-explorer`

用于“从零探索并创建新站点适配器”。

适合：

- 用户要支持一个 OpenCLI 目前还没有的网站
- 需要分析页面 API、认证方式、响应结构
- 需要新增 TypeScript adapter

### `opencli-oneshot`

用于“基于一个具体 URL 和目标，快速生成一次性适配能力”。

适合：

- 用户只关心一个页面或一个具体目标
- 需要快速验证 API 可用性
- 不需要完整站点级适配

## 4. AI 的推荐决策流程

收到用户请求后，按下面顺序判断：

1. 目标是不是网站、桌面应用或外部 CLI
2. OpenCLI 是否已经支持该目标
3. 这是“调用现有能力”，还是“新增能力”
4. 是否需要登录态
5. 输出应该是表格、JSON、Markdown，还是供后续总结的文本

推荐策略：

- 已支持站点 + 只是调用：使用 `opencli-usage`
- 需要页面点击输入：使用 `opencli-browser`
- 未支持站点 + 需要长期复用：使用 `opencli-explorer`
- 未支持站点 + 只是一次性目标：使用 `opencli-oneshot`

## 5. OpenCLI 基本命令格式

最常见的命令格式是：

```bash
opencli <site> <command> [args] [--limit N] [-f json|yaml|md|csv|table]
```

例如：

```bash
opencli reddit hot --limit 10 -f json
opencli twitter notifications -f md
opencli web read --url https://example.com -f md
opencli codex read -f json
opencli gh pr list --limit 5
```

AI 在调用时建议遵循这些原则：

- 优先使用 `-f json`，便于后续解析和总结
- 给列表类命令显式加 `--limit`
- 面向用户直接展示内容时，可考虑 `-f md` 或 `-f table`
- 如果只是为了下游处理，尽量不要选择难解析的自由文本输出

## 6. 常见使用模式

### 读取网站内容

```bash
opencli reddit hot --limit 10 -f json
opencli bilibili hot --limit 20 -f json
opencli zhihu hot -f json
```

适合：

- 热榜
- 搜索结果
- feed、timeline、通知、收藏

### 读取网页正文

```bash
opencli web read --url https://example.com/article -f md
```

适合：

- 文章提取
- 网页转 Markdown
- 供 AI 总结后再输出

### 读取桌面应用上下文

```bash
opencli codex status -f json
opencli codex read -f json
opencli cursor read -f json
opencli notion read -f md
```

适合：

- 获取当前会话
- 导出内容
- 辅助总结或继续操作

### 调用外部 CLI

```bash
opencli gh pr list --limit 10
opencli docker ps
opencli vercel projects ls
```

适合：

- 统一通过 OpenCLI 暴露常见 CLI
- 让 AI 在一个命令体系内工作

## 7. 浏览器类命令的前提条件

许多网站命令依赖浏览器和登录态。AI 需要知道这些前提：

1. Chrome 正在运行
2. 用户已经在 Chrome 中登录目标网站
3. 已安装 opencli Browser Bridge 扩展
4. 首次浏览器命令时，daemon 会自动启动

如果这些条件不满足，浏览器类命令可能失败。

因此，AI 在处理需要登录态的网站任务时，应优先假设：

- 登录态来自用户现有 Chrome 会话
- OpenCLI 不是替代账号登录，而是复用登录状态

## 8. 输出格式建议

AI 选择输出格式时可参考：

- `json`
  最适合继续分析、筛选、总结、拼装结果
- `md`
  最适合展示文章、正文、长文本
- `table`
  最适合终端快速查看
- `yaml`
  适合人类阅读的结构化结果
- `csv`
  适合导出列表数据

默认建议：

- 给 AI 自己消费：`json`
- 给用户直接看：`md` 或 `table`
- 给网页正文提取：优先 `md`

## 9. AI 调用 OpenCLI 的操作准则

### 准则 1：先用现成命令，不要一开始就造适配器

如果站点已经支持，优先直接调用已有命令。

### 准则 2：优先最小可行命令

先跑最小范围命令确认可用，例如：

```bash
opencli reddit hot --limit 3 -f json
```

确认成功后再扩大范围。

### 准则 3：优先结构化输出

除非用户明确要可读文本，否则优先 `json`。

### 准则 4：列表命令显式限制数量

避免一次拉太多数据：

```bash
--limit 5
--limit 10
--limit 20
```

### 准则 5：读网页正文时优先 `web read`

对于任意 URL 的正文提取，优先：

```bash
opencli web read --url <url> -f md
```

### 准则 6：失败时先诊断，再决定是否修复

如果命令失败，不要立刻放弃，先尝试诊断。

## 10. 失败排查与自修复

OpenCLI 支持诊断和适配器修复思路。

### 常见失败原因

- Chrome 未启动
- 用户未登录目标网站
- Browser Bridge 扩展未安装或未连接
- 页面结构变化
- 站点 API、选择器或响应 schema 改变
- 命令名或参数用错

### 首选排查命令

```bash
opencli doctor
opencli list -f json
opencli validate
```

### 打开诊断模式

```bash
OPENCLI_DIAGNOSTIC=1 opencli <site> <command> ...
```

适合在命令失败后拿到更结构化的上下文。

### AI 的失败处理策略

1. 先确认是不是环境问题
2. 再确认是不是登录态问题
3. 再确认是不是命令本身参数错误
4. 如果怀疑适配器失效，再考虑修复 adapter

如果是站点变更导致的失效，OpenCLI 推荐：

- 开启 `OPENCLI_DIAGNOSTIC=1`
- 根据诊断信息定位 adapter
- 修复后重试
- 最多进行 3 轮修复

## 11. AI 回复用户时的最佳实践

当 AI 使用 OpenCLI 完成任务后，建议不要只贴原始输出，而要做二次加工。

推荐做法：

1. 先调用 OpenCLI 获取结构化结果
2. 再提炼出用户真正关心的信息
3. 必要时附上数据来源、数量和筛选条件
4. 如果结果不完整，说明原因，例如登录态不足或页面限制

不推荐做法：

- 把超长 JSON 原样丢给用户
- 在没验证命令可用前就承诺一定能拿到结果
- 明明是登录态问题，却误报为“站点不支持”

## 12. AI 可直接复用的命令模板

### 热门内容

```bash
opencli <site> hot --limit 10 -f json
```

### 搜索

```bash
opencli <site> search "<keyword>" --limit 10 -f json
```

### 用户信息

```bash
opencli <site> user <id-or-name> -f json
```

### 通知或 feed

```bash
opencli <site> notifications -f json
opencli <site> feed --limit 20 -f json
```

### 网页正文提取

```bash
opencli web read --url <url> -f md
```

### 桌面应用读取

```bash
opencli codex read -f json
opencli cursor read -f json
opencli notion read -f md
```

### 外部 CLI 透传

```bash
opencli gh pr list --limit 5
opencli docker ps
```

## 13. AI 的简版行动模板

如果你是一个 AI agent，可以按下面方式执行：

1. 判断目标平台是否已被 OpenCLI 支持
2. 若已支持，优先使用 `opencli-usage`
3. 选择最小命令验证能力
4. 优先 `-f json`
5. 对列表加 `--limit`
6. 若失败，先运行 `opencli doctor` 或开启 `OPENCLI_DIAGNOSTIC=1`
7. 若只是网页正文提取，优先 `opencli web read`
8. 若需要页面点击、输入、等待，改用 `opencli-browser`
9. 若平台未支持，改用 `opencli-oneshot` 或 `opencli-explorer`

## 14. 推荐给 AI 的一句话原则

能直接调用现成 OpenCLI 命令时，不要先做浏览器脚本；能输出结构化结果时，不要先输出大段自然语言；命令失败时，先诊断环境和登录态，再判断是否需要修复适配器。

