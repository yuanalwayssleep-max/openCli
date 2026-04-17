# TODO清单

## 1. 当前目标

- 以 `dp.58corp.com` 为目标站点，沉淀一套可复用的自动化能力。
- 优先覆盖高频、稳定、可重复使用的查询与导出场景。
- 区分三类产物：
  - `skill`：给 AI 用的探索与排障流程
  - `adapter`：给 OpenCLI 用的稳定命令
  - `Python 脚本`：给批量导出、跨机构合并、定时任务使用

## 2. 当前状态

- 已完成：`项目说明.md`
- 已完成：`OpenCLI的AI使用说明.md`
- 已完成：`dp58登录认证与Python直连可行性分析.md`
- 已完成：`scripts/dp58_download_zhuangyuan_tasks.py`
- 已完成：庄园名下任务跨机构合并导出
  - 当前结果文件：
    - `outputs/dp58_zhuangyuan_tasks_all_orgs.json`
    - `outputs/dp58_zhuangyuan_tasks_all_orgs.csv`
    - `outputs/dp58_zhuangyuan_tasks_all_orgs_summary.json`
- 已确认：Python 直连时不能并行切机构，必须使用单会话串行切换并校验当前机构

## 3. 第一优先级

- 补齐 `dp58` 的探索型 skill
  - 目标：让 AI 能按固定流程探索新页面、抓包、定位接口、判断认证方式
  - 范围：
    - 页面打开与抓包
    - 当前用户校验
    - 机构切换校验
    - CookieJar 直连判断
    - 失败时的排障路径

- 固化任务列表导出经验
  - 把“跨机构串行切换 + 强校验”的经验写入文档或 skill
  - 明确哪些接口依赖“当前机构上下文”
  - 明确哪些场景不要用 `--limit`

- 整理现有 Python 直连脚本的使用说明
  - 目标脚本：`scripts/dp58_download_zhuangyuan_tasks.py`
  - 补充内容：
    - 输入 cookie 文件要求
    - 输出文件说明
    - 常见失败原因
    - 切机构失败时如何排查

## 4. 第二优先级

- 实现 `current-user` adapter
  - 目标：稳定输出当前登录人、当前机构、登录态是否可用
  - 原因：这是所有后续命令的最小探活能力

- 实现 `task-list` adapter
  - 目标：支持当前机构下的任务列表读取
  - 最小参数：
    - `--limit`
    - `--page`
    - 可选 `--name`
  - 输出字段：
    - `id`
    - `title`
    - `owner`
    - `status`
    - `updated_at`
    - `url`

- 实现 `search` adapter
  - 目标：按关键词搜索任务
  - 原则：尽量复用 `task-list` 的字段与解析逻辑

## 5. 第三优先级

- 探索 `table-list` 页面
  - 目标页面：`https://dp.58corp.com/data-manage/table-list`
  - 当前已知：
    - 页面首屏核心接口是 `POST /api/table-manage/tables`
    - 页面上已默认筛到 `庄园(zz_zhuangyuan01)`
  - 待确认：
    - 请求体完整字段
    - 是否支持分页
    - 是否依赖当前机构
    - 能否稳定复现“庄园名下所有表”

- 评估 `table-list` 最终应做成什么
  - 如果接口稳定且高频：做成 adapter
  - 如果仍在摸索：先写 skill
  - 如果涉及跨机构批量导出：优先 Python 脚本

## 6. Python 脚本线

- 保持“批量导出”和“跨机构合并”优先走 Python
- 后续优先补的脚本能力：
  - `庄园名下所有表` 跨机构导出
  - 任务结果增量导出
  - 输出摘要统计
  - 失败重试与更清晰的错误提示

- Python 脚本设计原则：
  - 默认全量，不默认限条
  - 需要跨机构时，串行切换并校验当前机构
  - 输出至少包含：
    - 原始 JSON
    - 扁平 CSV
    - summary JSON

## 7. Skill 线

- 新建或恢复 `dp58` 探索型 skill
  - 建议内容：
    - 如何用 OpenCLI 打开页面
    - 如何读取 `network`
    - 如何定位核心接口
    - 如何判断 Cookie / Header / Intercept
    - 如何切换到 Python 直连路径

- 后续可拆分的子 skill：
  - `dp58-task-list`
  - `dp58-table-list`
  - `dp58-system-api`

## 8. Adapter 线

- 仅固化“高频、稳定、单点可复用”的命令
- 当前建议顺序：
  1. `current-user`
  2. `task-list`
  3. `search`
  4. `table-list`（待接口稳定后）

- Adapter 原则：
  - 输入参数尽量少
  - 默认输出结构化 JSON
  - 列表类支持 `--limit`
  - 尽量避免把复杂跨机构状态管理塞进 adapter

## 9. 文档待补

- 新增或补充一份总览文档
  - 说明 `skill / adapter / Python 脚本` 的职责边界
- 补充 `dp58_download_zhuangyuan_tasks.py` 的运行说明
- 如果恢复更多历史文件，需要统一整理目录结构说明

## 10. 下一步建议

- 先做：整理 `dp58` 探索型 skill
- 再做：补 `current-user` adapter
- 然后：继续推进 `table-list` 的接口确认
