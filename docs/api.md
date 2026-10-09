# API 文档

本文列出后端 HTTP 接口。外部系统集成通常只需要鉴权、workspace 文件上传和搜索接口；索引由 MQ 异步执行，Indexer 不提供 HTTP 接口。

检索路径为 `/api/v1/rag/search` 和 `/api/v1/rag/config`，对话路径为 `/api/v1/llm/*`，文件与分片管理使用 KB API 的 `/api/v1/workspaces/*`。旧 `/api/rag/*` 及其他 Indexer HTTP 路径已移除。

## 健康检查

KB API 和 Chat 各自提供仅供 Compose 内部使用的 `GET /health`。RAG Indexer 的运行状态通过容器进程、RabbitMQ 消费者数量和队列积压检查。

Parser、文档 Inference 和 Search 不提供独立 HTTP API。公开 `/api/v1/rag/search` 由 KB API 接收；KB API 根据工作区授权计算可检索的 `workspace_ids`，再传给进程内 Search。

## 鉴权

外部系统调用搜索和对话接口时使用 App API Key；WebUI 用户登录后使用签名 User Token。两种认证方式是二选一关系，不能在同一请求中同时发送。`X-App-Id` 是两种方式都必须提供的应用上下文，不是独立的认证方式。KB API 与 Chat 的认证中间件统一解析身份，路由再执行身份类型和业务权限校验。Chat 将当前身份凭证和 `X-App-Id` 转发给 KB API 搜索接口，最终工作区权限由 KB API 校验。Indexer 从 MQ 消费任务，使用任务消息携带的 `task_id` 和随机 `callback_token` 回写任务结果；数据库只保存令牌摘要。

请求头：

| Header | 说明 |
|---|---|
| `Authorization` | WebUI 用户发送 `Bearer <user_token>` |
| `X-App-Id` | 用户当前选择的 App，或外部系统要访问的 App |
| `X-API-Key` | 外部系统发送与 `X-App-Id` 匹配的 App API Key |

管理、组织、用户、工作区和文件接口只接受 User Token。搜索、对话和会话历史接口接受 User Token 或 App API Key。API Key 不代表具体用户，只能使用所属 App 的检索和对话能力。

WebUI 用户请求：

```http
Authorization: Bearer <user_token>
X-App-Id: <app_id>
```

外部系统请求：

```http
X-API-Key: <app_api_key>
X-App-Id: <app_id>
```

管理台接口使用签名 User Token：

```http
Authorization: Bearer <access_token>
```

### 管理台登录

```http
POST /api/v1/auth/login
Content-Type: application/json
```

请求：

```json
{
  "name": "admin",
  "password": "<password>"
}
```

响应：

```json
{
  "access_token": "...",
  "user": {
    "id": "<user-uuid>",
    "name": "admin",
    "role": "owner",
    "org_id": null
  }
}
```

登录响应还包含当前用户信息。平台 `owner` 的 `org_id` 为 null；其他用户的 `org_id` 指向所属 App 的组织。

## 应用与组织管理

应用管理接口只给管理台使用。外部系统不调用这些接口。

### 创建应用

```http
POST /api/v1/apps
Content-Type: application/json
```

请求：

```json
{
  "app_id": "tenant_a",
  "name": "Tenant A"
}
```

响应：

```json
{
  "app": {
    "id": "<app-uuid>",
    "app_id": "tenant_a",
    "name": "Tenant A",
    "api_key": "..."
  },
  "org": {
    "id": "<org-uuid>",
    "app_id": "<app-uuid>",
    "parent_id": null,
    "name": "Tenant A"
  }
}
```

`api_key` 保存在 PostgreSQL，外部业务系统用它调用 `/api/v1/rag/*` 和 `/api/v1/llm/*` 接口。创建 App 时建立该 App 唯一 org 树的根组织；平台 `owner` 不加入该组织。

`app_id` 是 2-40 个字符、唯一且不可变的业务标识，必须以字母开头，后续只能包含字母、数字或下划线。

### 查询应用列表

```http
GET /api/v1/apps
```

响应：

```json
{
  "apps": [
    {
      "id": "<app-uuid>",
      "app_id": "tenant_a",
      "name": "Tenant A",
      "api_key": "..."
    }
  ]
}
```

平台 `owner` 查询时响应包含 `api_key`；组织用户查询时不返回该字段。

### 删除应用

```http
DELETE /api/v1/apps/{app_id}
```

存在 org 或 workspace 时删除 App 返回 409。当前 App 创建时必建根组织，而根组织不能通过组织接口停用，因此正常创建的 App 暂不能通过该接口删除。路径中的 `app_id` 是创建 App 时提交的业务标识，不是数据库 UUID。

### 组织树

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/v1/orgs?app_id={app_id}` | 按业务 `app_id` 返回当前用户可见的 active org 树；平台 owner 可见完整树，其他用户从所属组织向下可见 |
| `POST` | `/api/v1/orgs` | 使用 `parent_id` 和 `name` 创建子组织 |
| `GET/PATCH/DELETE` | `/api/v1/orgs/{org_id}` | 查询、修改或停用组织 |

每个 App 只有一棵 org 树，组织不能移动到其他 App。`owner` 是平台角色，不挂组织；`admin` 和 `member` 属于一个 org。用户的登录名和响应字段使用 `name`，组织归属使用 `org_id`。

## 索引

文件索引由 workspace 文件接口异步触发。调用方先申请上传地址并将文件直传 MinIO，再调用索引接口；KB API 创建该 workspace 的文件记录并发布索引任务。任务包含 `operation`、`app_id`、`workspace_id`、`file_id`、`s3_url`、`filename`、`task_id` 和 `callback_token`。其中 `task_id` 与 `callback_token` 只用于当前任务的结果回写，数据库仅保存回调令牌摘要。

失败文件重试和文件删除也必须从 `/api/v1/workspaces/{workspace_id}/files/...` 进入，以便统一执行 workspace 授权。Indexer 的阶段错误写回该文件记录，由文件状态和 `error` 字段供管理界面展示。

Indexer 完成任务后调用 `POST /api/v1/index-results`，原样回传任务中的 `task_id`、`callback_token`、`operation` 和 `file_id`，并提交 `status`、`error`、`indexed_at` 等结果字段。接口只接受当前文件的当前任务凭证；旧任务和错误令牌返回 401，成功返回 204。

## 搜索

`GET /api/v1/rag/config` 返回检索默认值和可用的 sparse/rerank 能力，供搜索页面初始化控件。

`POST /api/v1/rag/search` 可在请求体中传多个 `workspace_ids`，不传时检索当前身份有权访问的全部工作区。

```http
POST /api/v1/rag/search
Content-Type: application/json
```

超过 `api.rate_limit` 时返回 429。

请求字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | string | 是 | - | 查询内容 |
| `mode` | string | 否 | `kb_api/config/rag.yaml` 的 `search.mode` | `dense`、`sparse` 或 `hybrid`；`hybrid` 在 sparse 不可用时自动降级为 `dense` |
| `top_k` | int | 否 | `kb_api/config/rag.yaml` 的 `search.top_k` | 最多返回条数，范围 `1..50` |
| `rerank` | bool | 否 | `kb_api/config/rag.yaml` 的 `search.rerank` | 是否启用 rerank |
| `fetch_k` | int | 否 | `kb_api/config/rag.yaml` 的 `search.fetch_k` | 每路检索召回数量，范围 `1..100`，必须大于等于 `top_k` |
| `rrf_k` | int | 否 | `kb_api/config/rag.yaml` 的 `search.hybrid.rrf_k` | hybrid 模式下 RRF 融合参数，范围 `1..1000` |
| `file_ids` | string[] | 否 | - | 在选定工作区内限定文件；不传表示不限文件；空数组会被拒绝；最多 1000 个 |
| `workspace_ids` | string[] | 否 | 当前用户在该 App 有权访问的全部工作区 | 限定一个或多个知识库；空数组会被拒绝；最多 1000 个；越权返回 403 |

请求示例：

```json
{
  "query": "有多少华为卡",
  "mode": "hybrid",
  "top_k": 5,
  "rerank": false,
  "fetch_k": 20,
  "rrf_k": 60,
  "workspace_ids": ["550e8400-e29b-41d4-a716-446655440001", "550e8400-e29b-41d4-a716-446655440002"],
  "file_ids": ["550e8400-e29b-41d4-a716-446655440000"]
}
```

响应字段：

| 字段 | 说明 |
|---|---|
| `results` | 搜索结果列表 |
| `mode` | 本次搜索模式 |
| `rerank` | 本次是否启用 rerank |
| `fetch_k` | 每路检索召回数量 |
| `elapsed_ms` | 后端搜索耗时，单位毫秒 |

`results` 元素字段：

| 字段 | 说明 |
|---|---|
| `id` | chunk ID |
| `content` | 命中的 chunk 文本 |
| `score` | 相关性分数 |

响应示例：

```json
{
  "results": [
    {
      "id": "chunk-text-1",
      "content": "合同约定项目验收周期为 30 天，逾期需要提交延期说明。",
      "score": 0.91
    },
    {
      "id": "chunk-table-1",
      "content": "| 项目 | 金额 | 备注 |\n|---|---:|---|\n| 设备费 | 120000 | 首期 |\n| 服务费 | 30000 | 年费 |",
      "score": 0.86
    },
    {
      "id": "chunk-text-2",
      "content": "付款条件为验收通过后 10 个工作日内支付尾款。",
      "score": 0.79
    }
  ],
  "mode": "dense",
  "rerank": false,
  "fetch_k": 20,
  "elapsed_ms": 271.7
}
```

## 对话

对话位于应用级入口，管理台发送前读取当前应用可访问的全部工作区，并传入这些工作区 ID。Chat 对每个工作区分别检索，按工作区分组将命中内容交给 LLM，不做跨工作区结果排序融合。任一工作区检索失败时，SSE 返回 `error` 事件，不使用不完整的检索结果生成答案。

```http
POST /api/v1/llm/chat/stream
Authorization: Bearer <access_token>
X-App-Id: <app_id>
Content-Type: application/json
```

```json
{
  "thread_id": "thread-1",
  "message": "差旅报销标准是什么？",
  "workspace_ids": ["<workspace-id-1>", "<workspace-id-2>"]
}
```

`workspace_ids` 为必填的非空数组。KB API 检索接口逐个校验工作区访问权限。JWT 会话按应用和用户隔离；App API Key 会话按应用隔离，同一 API Key 的调用方应避免复用彼此的 `thread_id`。响应为 SSE，正常返回 `token` 和 `done` 事件，失败返回包含 `message`、`service`、`trace_id` 的 `error` 事件。

## 知识库与授权

一个 App 可创建多个知识库。`POST /api/v1/apps/{app_id}/workspaces` 提交 `{"name":"知识库名称"}`，`GET` 同路径列出当前用户可访问的知识库。路径中的 `app_id` 是业务标识。`GET/PATCH/DELETE /api/v1/workspaces/{workspace_id}` 用于查询、重命名或删除空知识库。

`workspace_user` 保存个人角色，`workspace_org` 保存组织角色。`GET /api/v1/workspaces/{workspace_id}/members` 返回 user/org 两种授权来源；`POST` 同路径提交 `{"type":"user","id":"用户UUID","role":"editor"}` 或 `{"type":"org","id":"组织UUID","role":"viewer"}`。`PUT/DELETE /api/v1/workspaces/{workspace_id}/members/{member_id}?type=user或org` 修改角色或删除授权，PUT body 为 `{"role":"viewer"}`。组织授权仅覆盖直属用户，动态生效且不展开入库。个人角色优先。完整权限与目录接口见[工作区授权概要设计](workspace-authorization.md)。

会话历史接口为 `GET /api/v1/llm/threads`、`GET /api/v1/llm/threads/{thread_id}/messages` 和 `DELETE /api/v1/llm/threads/{thread_id}`。

## 文件上传

WebUI 使用三步直传流程。请求均使用签名 User Token 鉴权。

支持 `.pdf`、`.doc`、`.docx`、`.xls`、`.xlsx`、`.ppt`、`.pptx`、`.txt`、`.md`，后缀不区分大小写。申请上传地址和完成上传均会校验后缀；不支持的类型返回 HTTP 415，响应使用统一错误结构。该校验不验证文件内容是否与后缀一致。

### 申请 PUT 地址

```http
POST /api/v1/workspaces/{workspace_id}/files/upload-url
Content-Type: application/json
```

新增文件请求：

```json
{
  "filename": "guide.pdf",
  "content_type": "application/pdf"
}
```

替换文件时额外传 `file_id`。响应提供 `file_id`、`s3_url`、`content_type` 和 `upload_url`。`upload_url` 有效期为 15 分钟。

### 浏览器直传 MinIO

对 `upload_url` 发起 `PUT`，请求体为原始文件字节，`Content-Type` 使用申请响应里的 `content_type`。上传请求不经过 KB API。

### 提交索引

```http
POST /api/v1/workspaces/{workspace_id}/files/{file_id}/index
Content-Type: application/json
```

```json
{
  "s3_url": "s3://kb/uploads/app-id/workspace-id/file-id/version/guide.pdf",
  "filename": "guide.pdf",
  "content_type": "application/pdf"
}
```

KB API 会确认对象存在，分块读取对象计算 SHA-256，保存在文件记录的 `checksum` 字段，再登记文件并发布索引任务。替换时 `file_id` 保持不变；同一文件内容未变且已成功索引时，仅更新文件信息，不重复发布索引任务。索引失败后提交相同内容仍会重试索引，不同文件之间不做内容去重。浏览器必须能访问 `KB_MINIO_PUBLIC_URL` 指定的 MinIO 地址。

### 查询文档分片

管理台通过 `GET /api/v1/workspaces/{workspace_id}/chunks` 分页查看该知识库的分片。可选参数 `limit` 范围为 `1..200`，`cursor` 用于继续读取，`file_ids` 可重复传入以筛选文件。请求必须拥有该工作区的访问权限。

## 管理与诊断

### Workspace 文件列表

```http
GET /api/v1/workspaces/{workspace_id}/files
```

列出指定 workspace 的文件及索引状态。KB API 先校验 workspace 访问权限；文件记录不提供 org 归属字段。

分片分页使用上述 `GET /api/v1/workspaces/{workspace_id}/chunks`。旧 `/api/rag/chunks`、`/api/rag/presign` 和 `/api/v1/rag/presign` 已移除；当前 KB API 不提供 `dense-vector` 接口，分片列表不返回 embedding 数组。

### 删除 Workspace 文件

```http
DELETE /api/v1/workspaces/{workspace_id}/files/{file_id}
```

KB API 校验工作区删除权限及文件归属后，将文件状态改为 `deleting`，发布清理该文件 chunks 的异步任务并返回 202。Indexer 清理成功并完成回写后，KB API 才软删除文件记录和 MinIO 对象；回写前记录仍存在，失败时状态为 `delete_failed`。工作区 admin 可删除全部文件，editor 仅可删除自己上传的文件，viewer 无删除权限。

## Parser 模块

RAG Indexer 在进程内调用 Parser，输入 presigned URL 和文件名，返回按阅读顺序排列的 `blocks`；Parser 不生成检索分片。本地下载文件时同时返回 `file_size`（字节数），云端直接读取 URL 时省略该字段。

PDF 后端由 `kb_api/config/rag.yaml` 的 `parser` 节选择。`mineru_cloud` 提交 URL、轮询任务并转换结果 JSON；URL 必须能被云平台访问。`.doc/.docx/.xls/.xlsx/.ppt/.pptx` 固定调用 `parser.mineru.base_url` 指向的自建 MinerU API Server，并强制使用 Flash；`parser.mineru.tier` 只影响 PDF。TXT 和 Markdown 由 Indexer 内部的 Parser 模块下载到临时目录后处理，并在结束时清理。

`parser.download_timeout` 控制本地解析前的下载超时，单位秒。MinerU 云端通过 `MINERU_API_KEY` 读取 Token，`mineru_cloud.timeout` 控制提交、轮询及读取结果的总时间。启用 `mineru_cloud` 时关闭其他 PDF 后端的 enable。

`mineru` 调用自建 MinerU API Server，获取结构化内容后转换为 blocks；`tier` 支持 `flash/basic/standard/advanced`，`parse_method` 支持 `auto/ocr/txt`。部署见 `scripts/deploy_mineru_services.txt`，与云端后端只能启用一个，不需要云端 API Key。

TXT 按空行分段，Markdown 按语法元素读取；Office 的段落、页码和表格结构来自 MinerU Flash。所有格式的文本块统一带 `kind`，不为不存在的类别生成空块。

RAG 根据 `kind` 和 `chunk_size` 组合相邻文本：标题开启章节，连续标题跟随后正文，正文和列表项按顺序组合，超长文本再拆分，不跨章节、页码、表格或公式合并正文。TXT 保留空行段落边界。代码块不拆分，长度允许时与相邻说明组合；表格保留 caption 和完整 rows，同页紧邻且未跟随正文的 heading 与表格同片，相同 caption 不重复，不拼接普通前后文；单个代码块和表格可以超过普通文本的 chunk_size 限制

```json
{
  "blocks": [
    {"type": "text", "kind": "heading", "text": "向量数据库对比", "page": 1},
    {
      "type": "table",
      "rows": [["向量库", "稠密检索"], ["Milvus", "支持"], ["Qdrant", "支持"]],
      "caption": "检索能力对比",
      "page": 1
    },
    {"type": "formula", "text": "E = mc^2", "format": "latex", "page": 2},
    {"type": "text", "kind": "paragraph", "text": "没有页码的段落"}
  ]
}
```

| type | 必填字段 | 可选字段 |
| --- | --- | --- |
| `text` | `text`、`kind` | `page`、`level`（仅标题） |
| `table` | `rows`，每行一个数组，每个单元格一个字符串 | `caption`、`page` |
| `formula` | `text`、`format` | `page` |

页码从 1 开始，没有页码时省略 `page`；没有表格标题时省略 `caption`，不返回空字符串或 `null`

`kind` 为 `heading` 标题、`paragraph` 段落、`list_item` 列表项、`code` 代码块、`text` 无法明确分类的文本。TXT 段落使用 `paragraph`；PDF 使用解析后端的分类信息，无法识别时使用 `text`

标题可携带正整数 `level`，数值越小层级越高。MinerU 保留 `text_level`，Markdown 使用标题级别；没有明确级别时不推测。普通文本不携带级别。

`level` 目前仅保留在 Parser 响应中，RAG 不使用它组合章节，仍按上述 `kind` 和长度规则切片。TXT 仍按空行段落切片。

所有解析后端及文件类型使用同一响应结构，不返回 `role`、`header`、`footer`、`html` 或图片块。表格不返回 `text`，由 RAG 将紧邻 heading、`caption` 和完整 `rows` 按上述规则组合为一个 Markdown 分片

## Inference 模块

查询向量、文档向量和重排共用 `kb_api/config/rag.yaml` 的 `inference` 节，统一维护可用的 provider、模型、超时和重试。知识库实际使用的 dense provider、模型和维度由持久化绑定决定；配置中未启用的模型不能被请求选择。两者不提供 `/v1/models`、`/v1/embeddings`、`/v1/sparse_embeddings` 或 `/v1/rerank` 等独立 HTTP 接口。

| provider | dense 内部调用 | sparse 内部调用 | rerank 内部调用 |
| --- | --- | --- | --- |
| `tei` | `POST {dense.base_url}/v1/embeddings` | 无 | `POST {rerank.base_url}/rerank` |
| `siliconflow-cn` | `POST {base_url}/embeddings` | 无 | `POST {base_url}/rerank` |
| `siliconflow-intl` | `POST {base_url}/embeddings` | 无 | `POST {base_url}/rerank` |

文档列表调用 provider 的 `embed_documents`，查询文本调用 `embed_query`；两者使用一致的 dense 模型和维度。重排调用 provider 的 `rerank`，仅在启用时执行。

失败响应平铺返回 `error`、`service`、`retryable`、`traceId`。`error` 保存原始错误说明，没有时为 null；完整异常堆栈写入日志。例如计费异常返回 HTTP 502：

```json
{
  "error": "balance is insufficient",
  "service": "inference",
  "retryable": false,
  "traceId": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

达到配置的 `max_attempts` 后仍失败时，返回最后一次错误
- 网络异常、超时和 HTTP 5xx 按临时错误处理
- HTTP 4xx 按不可重试错误处理
- 无效响应为 false

依据：[SiliconFlow embeddings](https://docs.siliconflow.cn/docs/api/embeddings-post)、[rerank](https://docs.siliconflow.cn/docs/api/rerank-post)
