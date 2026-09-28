# 工作区授权概要设计

## 边界

App 是企业及数据隔离边界，下有一套组织树、多个工作区。组织负责人员归属，工作区负责文件协作。组织上下级关系不自动授予文件访问权。

企业角色与工作区角色分开：`users.role` 的 owner/admin/member 管平台和企业；工作区的 admin/editor/viewer 管该工作区。名称相同的 admin 不代表同一份权限。

平台 owner 和企业 admin 可创建工作区，创建者在同一事务中获得个人 admin 授权。企业角色不隐式取得其他工作区的内容权限。

## 数据模型

| 表 | 主要字段 | 用途 |
| --- | --- | --- |
| users | id, name, org_id, role | 账号、登录名、组织归属、企业角色 |
| orgs | id, app_id, parent_id, name | 企业组织树 |
| workspaces | id, app_id, name | 知识工作区 |
| workspace_user | id, workspace_id, user_id, role | 个人授权，role 为 admin/editor/viewer |
| workspace_org | id, workspace_id, org_id, role | 组织授权，role 为 editor/viewer |

两张授权表分别对 `(workspace_id, user_id)`、`(workspace_id, org_id)` 唯一。组织授权不展开写入 workspace_user。用户调岗、部门停用、取消部门授权后，访问权限随原始关系实时变化。

选部门仅授权该部门的直属用户，不包含子部门。需要子部门时单独选择。个人授权优先于组织授权，包括个人 viewer 覆盖部门 editor。未授权、跨企业、账号停用或所属组织链停用均不可访问。

平台 owner 不隶属于组织；只有显式个人授权才可进入相应工作区。

## 固定角色与操作

操作常量和 `WORKSPACE_ROLE_PERMISSIONS` 固定在 `kb_api/permissions.py`，接口使用 `has_workspace_permission` 检查具体操作；数据库保存授权对象和 role 字符串。

| 操作 | admin | editor | viewer |
| --- | --- | --- | --- |
| workspace.update | 是 | 否 | 否 |
| workspace.delete | 是 | 否 | 否 |
| workspace.members.manage | 是 | 否 | 否 |
| workspace.files.read | 是 | 是 | 是 |
| workspace.files.upload | 新增、替换全部文件 | 新增、替换自己上传的文件 | 否 |
| workspace.files.delete | 全部文件 | 自己上传的文件 | 否 |
| workspace.search | 是 | 是 | 是 |

搜索权限同时适用于对话引用资料。`workspace.create` 由平台或企业角色决定。前端使用后端返回的 permissions 控制按钮；后端校验操作权限，替换和删除文件时同时核对 `created_by`。

以上角色针对用户身份。企业 API Key 按 App 范围访问检索。

成员编辑、移除及 upsert 覆盖必须保留至少一个有效个人 admin，并发操作遵循同一约束。账号停用与组织治理由企业管理负责。

## 接口

| 接口 | 含义 |
| --- | --- |
| GET /api/v1/apps/{app_id}/workspaces | 可访问工作区列表及创建权限；每个工作区带 role、permissions |
| GET /api/v1/workspaces/{id} | 当前工作区、有效 role、permissions |
| GET /api/v1/workspaces/{id}/members | 授权来源列表，区分 user/org |
| POST /api/v1/workspaces/{id}/members | 新增或覆盖授权，body 为 type/id/role |
| PUT /api/v1/workspaces/{id}/members/{member_id}?type=user或org | 修改角色，body 为 role |
| DELETE /api/v1/workspaces/{id}/members/{member_id}?type=user或org | 移除对应授权 |
| GET /api/v1/workspaces/{id}/orgs | 工作区管理员可选的本企业有效组织树 |
| GET /api/v1/workspaces/{id}/users | 分页查询本企业有效用户，添加成员与部门人员预览共用 |

用户查询参数：`org_id` 可选，指定时仅查该部门直属用户；不传时查询全企业。`query` 按用户 `name` 做不区分大小写的包含搜索，默认空。`page` 默认 1，`page_size` 默认 20、最大 100。返回 `users`、`total`、`page`、`page_size`。两个接口都要求 `workspace.members.manage`，用户结果不含密码等账号敏感字段。

示例：`{"type":"org","id":"部门UUID","role":"editor"}` 只写 workspace_org；`{"type":"user","id":"用户UUID","role":"admin"}` 只写 workspace_user。

无权限返回 403，不可访问的工作区或不存在的授权返回 404，最后管理员冲突返回 409，组织授 admin 等非法输入返回 422。错误响应包含 `error`、`service`、`traceId`。

## 界面

同一个添加成员弹窗左右分栏：左侧只展示组织树，右侧展示所选部门直属用户，支持分页和用户名搜索；不限定部门时搜索全企业用户。组织与人员复选框独立，不因勾选部门自动勾选员工。已选区保留跨部门、跨页选择，选中组织时不能选择 admin。

成员表展示授权来源，不展开成每个员工一行。可编辑角色、移除授权、预览部门直属人员；同时存在个人与部门授权时说明个人角色优先。

文件在工作区内上传；搜索、对话可跨当前企业内有权访问的工作区。

## 初始化与验证

正式库结构在 `scripts/db.sql`，测试库结构在 `scripts/test_db.sql`。应用与测试不自动创建或迁移表，先手动准备相应数据库。两者不可混用。

验证覆盖角色矩阵、个人覆盖组织、调岗与停用、跨企业拒绝、成员目录、最后管理员、文件归属及搜索权限；前端通过构建与人工联调验证。
