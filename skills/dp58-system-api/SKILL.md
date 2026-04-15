---
name: dp58-system-api
description: Use when operating 58 星河 dp.58corp.com system APIs through OpenCLI, especially switching current org context with /api/user/auth/change-current-org.
---

# DP58 System API

通过 OpenCLI Browser Bridge 复用 Chrome 登录态，在 `dp.58corp.com` 页面主上下文里调用星河系统接口。

使用前先确认：

```bash
source ~/.nvm/nvm.sh
nvm use 22
opencli doctor
```

`Daemon`、`Extension`、`Connectivity` 都应为 OK。

## 脚本

```text
skills/dp58-system-api/scripts/change_current_org.py
```

常用机构：

```text
33    转转技术部
1095  转转大数据研发部
```

## 切换机构

脚本：

```bash
python3 skills/dp58-system-api/scripts/change_current_org.py --org-id 1095
```

接口：

```http
POST /api/user/auth/change-current-org
```

输入示例：

```json
{
  "org_id": 1095
}
```

输出示例：

```json
{
  "status": "success",
  "code": 200,
  "data": null
}
```

注意：这个脚本会修改当前浏览器会话的机构上下文。

## 示例

```bash
python3 skills/dp58-system-api/scripts/change_current_org.py --org-id 33
python3 skills/dp58-system-api/scripts/change_current_org.py --org-id 1095
```

## 注意事项

- 机构切换会影响当前浏览器会话，操作完成后按需要切回原机构。
- 不要在脚本或文档中写入 Cookie、Token、密码或完整登录态。
