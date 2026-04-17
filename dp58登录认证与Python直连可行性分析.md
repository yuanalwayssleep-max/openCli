# dp58 登录认证与 Python 直连可行性分析

## 1. 目标

分析 `https://dp.58corp.com/data-develop/task-list` 的登录认证方式，判断是否可以稳定脱离浏览器，直接用 Python `requests` / `httpx` 调接口进行大批量抓取。

## 2. 接口与页面观察结论

- 页面首屏会调用多个接口，其中任务列表核心接口为：
  - `POST https://dp.58corp.com/v2/task-info/get-list-page`
- 在浏览器页面上下文中，使用：
  - `fetch('/v2/task-info/get-list-page', { credentials: 'include' })`
  可以稳定返回 `code=200` 的 JSON。
- 同一页面中，改为：
  - `credentials: 'omit'`
  会直接 `TypeError: Failed to fetch`。
- 给 `omit` 场景补 `localStorage.user_token`（`authorization` / `x-user-token`）也仍然失败。

说明：

- 该接口的可用性强依赖浏览器会话中的完整认证上下文。
- `user_token` 并不能替代浏览器 cookie 会话。

## 3. Python 直连实测

在终端内对同一接口做了两组 `requests` 实测：

1. 不带 cookie：
- HTTP 200，但 `content-type: text/html`
- 返回内容是登录页 HTML，而不是业务 JSON。

2. 仅带 `document.cookie` 可见 cookie（加了常见 UA/Origin/Referer）：
- 结果仍是登录页 HTML。

这说明：

- `document.cookie` 可见字段不足以复现浏览器完整认证态。
- 认证链路很可能依赖 HttpOnly 会话 cookie / SSO cookie（无法通过 JS 直接读取）。

## 4. 认证方式判断

当前可确定是 **Cookie 会话型认证（SSO 体系）**，并且依赖：

- 浏览器中已有登录态
- 完整 cookie jar（至少包含 JS 不可见的 HttpOnly 项）
- 可能还有浏览器上下文相关的站点策略（同站请求/跳转链路）

并未观察到“只靠一个 Bearer token 就可稳定直连”的模式。

## 5. 是否能稳定改为 Python `requests/httpx` 直连

结论：**在“完全不经过浏览器页面中转”的前提下，当前不可认为稳定可行。**

原因：

- 直连缺少关键认证 cookie，返回登录页。
- 从页面可见 token 无法替代会话 cookie。
- 即便一次性抓到 cookie，企业 SSO 会话通常有失效和刷新机制，长期稳定性弱。

## 6. 可行替代路径（按稳定性排序）

### 路径 A（推荐）：保留浏览器会话，仅做接口化分页抓取

- 继续使用浏览器登录态作为认证锚点。
- 在页面内触发分页 API（当前已可稳定分页导出）。
- 优点：稳定、改造成本低、与现网认证机制一致。

### 路径 B（中期）：Python 直连 + 定期注入完整 Cookie Jar

- 从浏览器开发者工具或受控流程导出完整 cookie（含 HttpOnly）。
- Python 侧维护 session 并定期刷新 cookie。
- 风险：cookie 失效频繁、维护成本高、流程易脆。

### 路径 C（长期）：申请官方服务端鉴权方式

- 争取内部 OpenAPI / 服务账号 / appkey 签名方式。
- 让 Python 走正式服务端鉴权，不依赖个人浏览器会话。
- 这是唯一真正“长期稳定去浏览器化”的方案。

## 7. 对当前需求的建议

若目标是“大批量稳定抓取”，建议当前阶段采用：

- 浏览器会话认证 + 分页接口批量抓取（已验证可跑）。
- 输出落盘后再由 Python 做离线清洗、去重、统计、入库。

这样可以先保证产出稳定，再推进后续认证去浏览器化。
