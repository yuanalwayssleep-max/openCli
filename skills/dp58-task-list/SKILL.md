---
name: dp58-task-list
description: Use when exploring or reusing 58 星河 dp.58corp.com 的「数据开发 / 所有任务」页面接口, including task-list page scripts, page filter APIs, and simple request/response examples.
---

# DP58 Task List

用于 `https://dp.58corp.com/data-develop/task-list` 页面接口探查和页面辅助接口复用。

使用前先完成 `opencli-setup`，并确认：

```bash
source ~/.nvm/nvm.sh
nvm use 22
opencli doctor
```

`Daemon`、`Extension`、`Connectivity` 都应为 OK。

## 页面探查

打开页面：

```bash
opencli browser open https://dp.58corp.com/data-develop/task-list
opencli browser wait time 5
opencli browser state
```

查看首屏接口：

```bash
opencli browser network
```

如果 `network --detail` 返回空，重新触发页面按钮或刷新后再抓：

```bash
opencli browser click <刷新按钮索引>
opencli browser wait time 2
opencli browser network
```

注意：元素索引会变，点击前必须重新运行 `opencli browser state`。

## 脚本

脚本目录：

```text
skills/dp58-task-list/scripts/
```

通用参数：

```text
--no-open    复用当前页面，不重新打开 task-list
--compact    输出紧凑 JSON
```

脚本清单：

| 脚本 | 接口 | 用途 |
| --- | --- | --- |
| `get_current_user.py` | `GET /v2/user-info/get-current-user` | 当前用户 |
| `get_user_org_list.py` | `GET /api/org-manage/org/get-user-org-list` | 当前用户机构列表 |
| `list_task_types.py` | `GET /v2/task-info/list-types` | 任务类型下拉 |
| `list_users.py` | `GET /v2/user-info/list?size=<size>` | 负责人候选，可用 `--keyword` 本地过滤 |
| `fetch_hot_label_list.py` | `GET /v2/task-info/fetch-hot-label-list?orgId=<org_id>` | 热门标签 |
| `fetch_label_list.py` | `GET /v2/task-info/fetch-label-list?orgId=<org_id>` | 标签候选 |
| `fetch_business_group_list.py` | `GET /v2/user-info/fetch-business-group-list` | 业务组候选 |
| `get_product_list.py` | `GET /api/component-claim/get-product-list?org_id=<org_id>` | 产品/核算单元候选 |
| `get_page_column_cfg.py` | `GET /v3/page-column-cfg?page=0` | 列表列配置 |
| `get_user_diagnosis.py` | `GET /api/asset-govern/task/user-diagnosis` | 任务治理诊断 |
| `get_perm.py` | `GET /api/auth-manage/authority/get-perm` | 当前用户权限 |
| `get_notice.py` | `GET /v3/notice` | 页面通知状态 |
| `get_reminder_all_count.py` | `GET /api/msg/reminder-all-count` | 消息提醒计数 |
| `get_user_feedback_platforms.py` | `GET /api/user-feedback/platforms` | 用户反馈平台选项 |
| `get_task_list_page.py` | `POST /v2/task-info/get-list-page` | 当前机构下任务列表 |

需要跨机构查询任务时，不使用本 skill，改用项目根目录复合脚本：

```bash
python3 dp58_task_list_composite.py --org-id 1095 --size 500
```

## 常用脚本

当前用户：

```bash
python3 skills/dp58-task-list/scripts/get_current_user.py
```

当前用户机构列表：

```bash
python3 skills/dp58-task-list/scripts/get_user_org_list.py --no-open
```

当前机构下任务列表：

```bash
python3 skills/dp58-task-list/scripts/get_task_list_page.py --size 10
```

按任务名搜索：

```bash
python3 skills/dp58-task-list/scripts/get_task_list_page.py --name bili --size 5
```

任务类型：

```bash
python3 skills/dp58-task-list/scripts/list_task_types.py --no-open
```

查负责人：

```bash
python3 skills/dp58-task-list/scripts/list_users.py --size 5000 --keyword 陈家喆 --compact
```

标签候选：

```bash
python3 skills/dp58-task-list/scripts/fetch_label_list.py --org-id 33 --no-open
```

## 核心接口

### 当前用户

接口：

```http
GET /v2/user-info/get-current-user
```

输出示例：

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "id": 49926,
    "oa_name": "zz_zhuangyuan01",
    "chinese_name": "庄园",
    "current_org_id": 33,
    "current_org_name": "转转技术部"
  }
}
```

### 机构列表

接口：

```http
GET /api/org-manage/org/get-user-org-list
```

输出示例：

```json
{
  "status": "success",
  "code": 200,
  "data": [
    {
      "org_id": 33,
      "org_name": "转转技术部",
      "is_current": 1
    },
    {
      "org_id": 1095,
      "org_name": "转转大数据研发部",
      "is_current": 2
    }
  ]
}
```

### 当前机构任务列表

接口：

```http
POST /v2/task-info/get-list-page
```

输入示例：

```json
{
  "page": {
    "current": 1,
    "size": 10,
    "orders": []
  },
  "req": {
    "owner_id": 49926,
    "name": "bili",
    "has_sub_product": false
  }
}
```

输出示例：

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "records": [
      {
        "scheduler_id": 627319,
        "name": "bili-撞库合并",
        "owner_chinese_name": "庄园",
        "job_type_name": "SparkSql",
        "job_state": 400,
        "status": 2,
        "update_time": "2025-12-04 17:56:29"
      }
    ],
    "total": 2,
    "current": 1,
    "size": 10,
    "pages": 1
  }
}
```

注意：本接口只查当前机构上下文。需要切换机构时使用 `dp58_task_list_composite.py` 或 `dp58-system-api` 的机构切换接口。

## 辅助接口示例

任务类型：

```http
GET /v2/task-info/list-types
```

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "types": [
      {
        "id": 16,
        "name": "SparkSql"
      }
    ],
    "total": 33
  }
}
```

标签候选：

```http
GET /v2/task-info/fetch-label-list?orgId=33
```

```json
{
  "status": "success",
  "code": 200,
  "data": [
    {
      "label_id": 16611,
      "name": "data-p1",
      "task_num": 12
    }
  ]
}
```

产品/核算单元：

```http
GET /api/component-claim/get-product-list?org_id=33
```

```json
{
  "status": "success",
  "code": 200,
  "data": {
    "opcc_list": [
      {
        "opcc_name": "转转",
        "opcc_code": 29
      }
    ]
  }
}
```

## 筛选参数

已确认：

```text
req.owner_id          负责人用户 ID
req.name              任务名关键词
req.has_sub_product   是否包含子核算单元
```

继续探查其他筛选项时，先清空捕获，再执行页面交互：

```bash
opencli browser eval "window.__ocCaptured=[]; JSON.stringify({cleared:true})"
opencli browser click <筛选控件索引>
opencli browser click <选项索引>
opencli browser wait time 2
opencli browser network
```

## 注意事项

- 不要在脚本或文档中写入 Cookie、Token、密码或完整登录态。
- `dept_id` 是任务返回字段，不等于当前机构上下文。
- 页面脚本复用 `dp58-system-api/scripts/_dp58_opencli.py`，不要再复制新的同名 helper。
- 本文记录的是 `2026-04-15` 对 task-list 页面的探查结果，接口可能随前端版本变化。
