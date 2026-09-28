# KB API 与 WebUI 实施计划

**Goal:** 按既定架构实现 KB API 对应用、组织节点、用户和文件的统一管理，并通过 RabbitMQ 驱动 RAG Indexer。

**Architecture:** Nginx 统一入口，KB API 持有身份、组织、文件和任务状态，文件写入 MinIO 后发布 RabbitMQ 索引任务。RAG Indexer 消费任务，在进程内调用 Parser 与 Inference 并写 Vector DB；WebUI 只调用 KB API 管理业务数据。

**Tech Stack:** FastAPI、PostgreSQL、MinIO、RabbitMQ、Vue 3、Element Plus、Docker Compose

## Global Constraints

- 数据模型包含 `apps`、`orgs`、`users`、`workspaces`、`workspace_user`、`workspace_org`、`files`。
- 每个 App 有一棵 org 树，组织通过 `parent_id` 表达层级。
- 用户登录名使用 `name`；平台 owner 的 `org_id` 为 null，其他用户通过 `org_id` 归属组织。工作区授权决定文件访问范围。
- `files.id` 直接作为 RAG `file_id`。
- Parser 和 Inference 保持为 RAG Indexer 进程内模块。
- Vector metadata 保留 `workspace_id`、`file_id`、`chunk_index`。

---

### Task 1: KB API 服务与数据模型

**Files:**
- Create: `kb_api/app/main.py`
- Create: `kb_api/config.py`
- Create: `kb_api/db.py`
- Create: `kb_api/auth.py`
- Create: `kb_api/schemas.py`
- Create: `kb_api/pyproject.toml`
- Create: `kb_api/Dockerfile`
- Test: `kb_api/tests/test_auth.py`
- Test: `kb_api/tests/test_schema.py`

**Interfaces:**
- Produces: `POST /api/v1/auth/login`、`GET /internal/auth/verify`、PostgreSQL 初始化及身份上下文。

- [ ] 先写登录、Token 校验、平台 owner 初始化和表约束的失败测试。
- [ ] 实现配置、数据库连接、密码哈希与签名 Token。
- [ ] 实现 FastAPI 生命周期、健康检查和错误响应。
- [ ] 运行 KB API 单元与数据库集成测试。

### Task 2: 应用、组织节点与用户 API

**Files:**
- Create: `kb_api/routes/apps.py`
- Create: `kb_api/api/routes/orgs.py`
- Create: `kb_api/routes/users.py`
- Test: `kb_api/tests/test_management_api.py`

**Interfaces:**
- Produces: 应用 CRUD、org 树 CRUD、用户 CRUD；组织查询加载当前 App 的完整树，用户管理按企业角色和组织范围授权。

- [ ] 先写平台 owner 和企业用户权限边界的失败测试。
- [ ] 实现 App 创建时同步创建根组织，响应包含 `app` 和 `org`。
- [ ] 实现节点树和用户管理接口。
- [ ] 运行管理 API 测试。

### Task 3: 文件、MinIO 与 RabbitMQ

**Files:**
- Create: `kb_api/storage.py`
- Create: `kb_api/queue.py`
- Create: `kb_api/routes/files.py`
- Test: `kb_api/tests/test_files_api.py`

**Interfaces:**
- Produces: 文件上传、更新、列表、删除接口；发布包含 `app_id`、`workspace_id`、`file_id`、`s3_url`、`filename`、`operation` 的任务。

- [ ] 先写上传、同 ID 更新、删除和状态变化失败测试。
- [ ] 实现 MinIO 写入与文件记录。
- [ ] 实现 RabbitMQ 任务发布。
- [ ] 实现文件权限过滤和状态 API。

### Task 4: RAG Indexer RabbitMQ 消费

**Files:**
- Create: `kb_api/rag_indexer/queue.py`
- Modify: `kb_api/rag_indexer/app/main.py`
- Modify: `kb_api/rag_indexer/core/index/service.py`
- Test: `kb_api/rag_indexer/tests/unit/test_queue_consumer.py`

**Interfaces:**
- Consumes: KB API 发布的索引和删除任务。
- Produces: Vector DB 写入/删除与 KB API 文件状态更新。

- [ ] 先写索引、删除、ack/nack 和状态回写失败测试。
- [ ] 实现后台消费者及优雅关闭。
- [ ] 复用现有 Parser、Inference 和 Vector client 执行任务。
- [ ] 运行 Indexer 回归测试。

### Task 5: Nginx 与 Compose

**Files:**
- Modify: `deploy/deploy.yaml`
- Modify: `deploy/infra.yaml`
- Modify: `deploy/nginx/nginx.conf`
- Modify: `deploy/env.example`

**Interfaces:**
- Produces: `kb_api` 应用服务、RabbitMQ 基础服务、Nginx 认证子请求和身份 Header。

- [ ] 加入 KB API 与 RabbitMQ 服务。
- [ ] 配置 `/api/v1/auth/` 公共路由和其余 API 的认证子请求。
- [ ] 注入 `X-App-Id`、`X-User-Id`、`X-Org-Id`、`X-Principal-Type`。
- [ ] 验证 Compose 配置和健康检查。

### Task 6: WebUI 应用、组织、用户与文件管理

**Files:**
- Modify: `webui/src/App.vue`
- Modify: `webui/src/router/index.js`
- Modify: `webui/src/stores/auth.js`
- Modify: `webui/src/stores/apps.js`
- Create: `webui/src/views/OrganizationsView.vue`
- Create: `webui/src/views/UsersView.vue`
- Create: `webui/src/views/FilesView.vue`
- Modify: `webui/src/views/AppsView.vue`
- Modify: `webui/src/views/LoginView.vue`
- Modify: `webui/src/i18n/locales/zh.json`
- Modify: `webui/src/i18n/locales/en.json`

**Interfaces:**
- Consumes: KB API 的认证、应用、节点、用户和文件接口。
- Produces: 分级组织管理、用户管理、文件上传/更新/删除和索引状态页面。

- [ ] 先更新路由和 API store 测试。
- [ ] 将登录和应用管理切换到 KB API。
- [ ] 实现组织树与用户页面。
- [ ] 实现工作区范围内的文件管理页面。
- [ ] 构建 WebUI 并进行桌面和移动端检查。

### Task 7: 联调与文档

**Files:**
- Modify: `README.md`
- Modify: `docs/api.md`
- Modify: `docs/architecture.md`
- Modify: `scripts/db.sql`

**Interfaces:**
- Produces: 可重复启动的本地环境和完整 API 文档。

- [ ] 更新数据库初始化脚本与 API 文档。
- [ ] 运行后端单元、集成测试和前端构建。
- [ ] 启动 PostgreSQL、MinIO、RabbitMQ、KB API、Indexer、Chat、Nginx。
- [ ] 完成登录、建应用、建子组织、建用户、工作区授权、上传文件、索引状态、删除文件的 E2E 验证。
