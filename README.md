# 知识库

## 安装

单机部署使用 Docker Compose，本机构建并直接运行镜像。

部署需要 Docker Compose v2 和 Just。WebUI 在 Docker 构建阶段使用 Node.js 22；只有本地前端开发需要宿主机安装 Node.js 20.19+。

233 的完整安装步骤见 [233 安装指南](docs/install-233.md)，包含模型服务、环境变量、数据库初始化和运行验证。

```bash
cp deploy/env.example deploy/.env
# 先编辑 deploy/.env；JWT_SECRET 和 KB_ADMIN_PASSWORD 不能保留占位值
just infra up
until docker exec postgres pg_isready -U rag -d rag; do sleep 2; done
docker exec -i postgres psql -U rag -d postgres -v ON_ERROR_STOP=1 < scripts/db.sql
just kb up
just indexer up
just chat up
just webui up
```

打开管理台：<http://localhost:5175>。

各服务使用独立 Compose 文件与项目，共用外部 bridge 网络 `kb-net`。Compose 内部服务使用服务名通信；MinerU、TEI 等模型服务也可以按 `kb_api/config/rag.yaml` 配置为宿主机或远程地址。`deploy/infra.yaml` 使用 ParadeDB 镜像提供兼容 PostgreSQL 的关系数据库和默认向量后端，并启动 RabbitMQ、MinIO、OpenTelemetry Collector 和 Jaeger；Qdrant、Milvus 与 etcd 按 profile 启用，不默认启动。TEI 与 MinerU 按需执行 `just tei up`、`just mineru up`。

KB API 负责登录、应用、组织树、用户、工作区、文件、检索授权和索引任务状态；RAG Indexer 是纯 MQ 消费进程，从 RabbitMQ 消费索引与删除任务，通过 HTTP 向 KB API 回写结果，内含 Parser 与文档向量模块，不监听 HTTP 端口。公开搜索请求先进入 KB API，由 KB API 校验工作区授权，再调用 RAG 检索。Chat 使用一个 Uvicorn worker。

## 命令

在项目根目录执行以下命令：

| 命令 | 作用 |
| --- | --- |
| `just infra up/down` | 启动或移除基础服务容器 |
| `just kb up/down/build` | 管理 KB API 或构建其镜像 |
| `just indexer up/down/build` | 管理 RAG Indexer 或构建其镜像 |
| `just chat up/down/build` | 管理 Chat 或构建其镜像 |
| `just webui up/down/build` | 管理 WebUI 服务或构建其镜像 |
| `just tei up/down` | 管理 TEI 模型服务 |
| `just mineru up/down` | 管理 MinerU 模型服务 |
| `just --list` | 查看命令入口 |

表中的 `up/down/build` 表示可选动作，每次只传一个，例如 `just kb up`、`just kb build`、`just kb down`。没有 `restart/start/stop` 动作，也没有 `app`、`bundle` 或顶层 `build` 命令。

部署文件与独立项目：

| 文件 | Compose 项目 | 服务 |
| --- | --- | --- |
| `deploy/infra.yaml` | `kb-infra` | ParadeDB/PostgreSQL、RabbitMQ、MinIO、Collector、Jaeger；可选 Qdrant、Milvus、etcd |
| `deploy/kb.yaml` | `kb-api` | KB API |
| `deploy/indexer.yaml` | `kb-indexer` | RAG Indexer |
| `deploy/chat.yaml` | `kb-chat` | Chat |
| `deploy/webui.yaml` | `kb-webui` | WebUI |
| `deploy/tei.yaml` | `kb-tei` | TEI |
| `deploy/mineru.yaml` | `kb-mineru` | MinerU |

`kb/indexer/chat/webui up` 使用 `docker compose up -d --build --force-recreate`；`infra/tei/mineru up` 使用 `up -d`，不构建镜像。WebUI 镜像在构建阶段执行 Vite 构建，运行阶段使用镜像内的 Nginx 托管静态文件并透明代理 KB API 与 Chat；认证由后端服务处理。`kb/indexer/chat/webui build` 执行各自的 Compose 镜像构建。

所有 `down` 均执行对应项目的原生 `docker compose down`，停止并移除容器，不删除数据、镜像或共享外部网络 `kb-net`。

容器名与服务名一致。

`vector_db.postgres`、`vector_db.qdrant`、`vector_db.milvus` 及云端后端中必须且只能启用一个。默认启用 PostgreSQL 向量后端，数据写入同一个 ParadeDB 实例。使用 Qdrant 或 Milvus 时启用对应配置，并显式启动 profile：

各后端的 `bm25` 控制建库时是否创建 BM25 能力及是否参与 sparse/hybrid 检索。PostgreSQL 后端使用 `pg_search`，Qdrant 使用服务端的 `qdrant/bm25`，Milvus 使用内置 BM25 函数。关闭开关后现有集合仍可做 dense 检索；为已有 dense-only 集合开启 BM25 时，需要重新创建集合并重建文件索引。`query_timeout`、`write_timeout`、`init_timeout`、`drop_timeout` 分别限制查询、写入、初始化和删除操作，`retry` 控制可重试数据库错误的重试次数与间隔。

```bash
docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml --profile qdrant up -d --force-recreate
docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml --profile milvus up -d --force-recreate
```

MinerU Compose 沿用官方方式在本地构建好的 `mineru:4` 镜像，不从官方 registry 拉取该标签；运行前需确保本机已有该镜像。

应用镜像使用本地名称 `kb-<服务名>:${IMAGE_TAG}`。KB API 使用 `kb_api/Dockerfile`，RAG Indexer 使用 `kb_api/rag_indexer/Dockerfile`。两者各自维护 `pyproject.toml`、`uv.lock` 和依赖环境，共用 `kb_api/config/rag.yaml`。KB API 通过 Uvicorn 的 `kb_api.api.main:app` 启动，Indexer 通过 `python -m kb_api.rag_indexer.app.main` 启动。
`USE_CN_MIRROR` 作为构建参数传给 Docker。Indexer 通过 HTTP 调用 MinerU，不安装 MinerU Python 包。

两个服务均挂载 `kb_api/config`，不挂载整个源码目录。Indexer 的解析和向量推理通过远程服务执行，不挂载本地模型目录。修改代码、依赖或配置后执行 `just kb up` 或 `just indexer up`，重新构建并强制重新创建对应服务容器；修改共用配置后更新两个服务。

内网部署 Indexer 只需 Indexer 镜像、配置及运行环境变量，并能访问所配置的解析与推理服务，不需要 KB API 管理端源码或本地模型目录。源码目录只在构建镜像时使用。

Indexer 容器健康检查仅检查 PID 1 存活；消费情况通过 RabbitMQ 的消费者数量、队列积压和 Indexer 日志观察。

## 追踪运行

仅精确匹配 `POST /api/v1/rag/search` 的请求产生 OTel 根 span，并保留搜索流水线的 `rag.search.*` span，链路为 `KB API → OpenTelemetry Collector → Jaeger`。`just infra up` 默认启动[官方 Collector 0.161.0](https://opentelemetry.io/docs/collector/install/docker/) 和 [Jaeger v2.21.0](https://www.jaegertracing.io/docs/2.21/getting-started/)，无需 tracing profile。

其他请求保留用于响应与日志关联的请求 ID；这些 ID 不代表 OTel trace，不能据此预期在 Jaeger 中查到记录。登录、管理接口、文件索引和 Chat 不再产生新的 OTel trace。

KB API 使用 `http://otel-collector:4318`（`http/protobuf`）发送搜索追踪。Collector 在 `kb-net` 内监听 OTLP/HTTP 4318 和 OTLP/gRPC 4317，通过 `memory_limiter`、`batch` 后以 OTLP/HTTP 转发到 `http://jaeger:4318`；所有 OTLP 端口均不映射到宿主机。接收器、处理器和导出器集中在 `deploy/otel-collector/config.yaml`，后续可扩展处理流程或存储后端。

```bash
just infra up
just kb up
just indexer up
just chat up
just webui up
```

1. 发起一次 `POST /api/v1/rag/search` 请求，记录响应中的 `traceId` 或响应头 `X-Trace-Id`。
2. 打开 <http://localhost:16686>，在 UI 的 Trace ID 查询入口输入该 ID，查看 KB API 搜索阶段的 span、耗时和错误。Collector 和 Jaeger 负责接收、处理及存储这些 span。
3. 没有 trace ID 时，按 `kb_api` 及请求时间范围搜索。展开耗时较长或标记错误的 span，定位具体搜索阶段。

UI 仅绑定 `127.0.0.1`，用于本地管理，不经 Nginx 暴露。远程查看可用 `ssh -L 16686:127.0.0.1:16686 <部署主机>`，再打开本机地址。Collector 和 Jaeger 自身 tracing 已关闭，不影响搜索 trace 的接收和查询。

脚本查询使用 `GET /api/v3/services` 和 `GET /api/v3/traces/{traceId}`；2.21 的旧 `/api/services` 路径返回 404。

按[官方 Badger 配置](https://github.com/jaegertracing/jaeger/blob/v2.21.0/cmd/jaeger/config-badger.yaml)启用本地持久化，数据位于 `jaeger_data/`，保留 72 小时；重建容器不清空数据。已有 Indexer、Chat 等历史追踪继续保留至 72 小时 TTL 到期，收窄追踪范围不会清空历史数据。[Badger 适用于单节点](https://www.jaegertracing.io/docs/2.21/storage/badger/)，不支持横向扩展。Jaeger 以 UID/GID 10001 运行。

`deploy/env.example` 提供 OTel 设置，`deploy/kb.yaml` 仅对 KB API 设置服务名和 OTel 默认值：SDK 默认启用，`parentbased_traceidratio` 对新根追踪默认采样率为 `1.0`，子追踪沿用父级采样决定。可在 `deploy/.env` 设置 `OTEL_TRACES_SAMPLER_ARG=0.1` 降低采样，或 `OTEL_SDK_DISABLED=true` 关闭 SDK；修改后用 `just kb up` 重建/重新创建 KB API 容器使环境生效。

仅校验配置（不启动部署服务；最后两条使用临时容器运行配置校验，未缓存时需拉取镜像）：

```bash
docker compose --env-file deploy/env.example -p kb-infra -f deploy/infra.yaml config -q
docker compose --env-file deploy/env.example -p kb-api -f deploy/kb.yaml config --no-env-resolution -q
docker compose --env-file deploy/env.example -p kb-indexer -f deploy/indexer.yaml config --no-env-resolution -q
docker compose --env-file deploy/env.example -p kb-chat -f deploy/chat.yaml config --no-env-resolution -q
docker compose --env-file deploy/env.example -p kb-webui -f deploy/webui.yaml config --no-env-resolution -q
docker compose --env-file deploy/env.example -p kb-tei -f deploy/tei.yaml config --no-env-resolution -q
docker compose --env-file deploy/env.example -p kb-mineru -f deploy/mineru.yaml config --no-env-resolution -q
docker run --rm --network none -v "$PWD/deploy/otel-collector/config.yaml:/etc/otelcol/config.yaml:ro" ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector:0.161.0 validate --config /etc/otelcol/config.yaml
docker run --rm --network none -v "$PWD/deploy/jaeger/config.yaml:/etc/jaeger/config.yaml:ro" jaegertracing/jaeger:2.21.0 validate --config /etc/jaeger/config.yaml
```

## 测试

KB API 测试使用独立的 PostgreSQL 数据库 `rag_test`，每个用例会清空该库的 KB 业务表。默认连接为 `postgresql://rag:rag@127.0.0.1:5432/rag_test`，可通过 `KB_TEST_DATABASE_URL` 覆盖；数据库名必须以 `_test` 结尾。
正式库初始化执行 `scripts/db.sql`；测试库初始化执行 `scripts/test_db.sql`。

```bash
uv sync --project kb_api
kb_api/.venv/bin/python -m pytest kb_api/tests kb_api/rag_search/tests kb_api/rag_search/inference/tests/unit -q
uv sync --project kb_api/rag_indexer
kb_api/rag_indexer/.venv/bin/python -m pytest kb_api/rag_indexer/tests/unit kb_api/rag_indexer/parser/tests/unit kb_api/rag_indexer/inference/tests/unit -q
```

## MinerU 解析

PDF provider 在 `kb_api/config/rag.yaml` 中通过 `enable` 切换：

| 配置 | 解析方式 |
| --- | --- |
| `mineru` | 上传到文件解析 API，当前地址 `http://19.16.1.233:18002` |
| `mineru_cloud` | MinerU 云平台 |

当前启用 `mineru`，地址为 233 的 `http://19.16.1.233:18002`，请求超时读取 `timeout`，单位秒。API Server 内部调用 VLM Server，Indexer 不直接调用 VLM。API 返回 structured_content，云平台返回 content list；两者复用 blocks 转换和跨页表格合并逻辑，不在 Indexer 中调用 renderer。

`.doc/.docx/.xls/.xlsx/.ppt/.pptx` 固定使用自建 MinerU Flash，共用 `parser.mineru` 的服务地址、超时和重试配置。`parser.mineru.tier` 仅用于 PDF；PDF 仍按 `enable` 选择 provider。`.txt/.md` 保留本地解析。

Indexer 不运行本地 MinerU SDK 解析、不加载模型，也不需要 GPU。独立 MinerU 服务的官方模型下载与部署命令见 `scripts/deploy_mineru_services.txt`，其 Compose 配置为 `deploy/mineru.yaml`；模型目录由该服务使用并继续保留。

修改 provider 代码或配置后执行 `just indexer up`。

## API

Base URL 示例：

```
http://localhost:5175
```

### API 概况

| API 分组 | 主要路径 | 描述 | 认证方式 |
| --- | --- | --- | --- |
| 健康检查 | `GET /health` | KB API 和 Chat 各自提供，仅供容器内部检查 | 无 |
| 用户登录 | `POST /api/v1/auth/login` | 使用账户名和密码换取 JWT | 无 |
| 当前用户 | `/api/v1/auth/me`、`/api/v1/auth/password` | 查询当前用户、修改自己的密码 | JWT |
| App 管理 | `/api/v1/apps*` | 管理 App 及其工作区 | JWT |
| 组织和账户 | `/api/v1/orgs*`、`/api/v1/users*` | 管理组织树和企业账户 | JWT |
| 工作区和成员 | `/api/v1/workspaces*` | 管理知识库及个人、组织授权 | JWT |
| 文件和分片 | `/api/v1/workspaces/{workspace_id}/files*`、`/chunks` | 上传、查询和删除文件，查看索引分片 | JWT |
| RAG 检索 | `/api/v1/rag/search`、`/api/v1/rag/config` | 跨已授权工作区检索，查询检索配置 | JWT 或 App API Key |
| 对话 | `POST /api/v1/llm/chat/stream` | 检索知识库并流式生成回答 | JWT 或 App API Key |
| 索引结果回写 | `POST /api/v1/index-results` | Indexer 完成任务后更新文件状态 | 任务回调令牌 |

认证请求头：

| 认证方式 | 请求头 |
| --- | --- |
| JWT | `Authorization: Bearer <jwt>`；涉及 App 上下文时同时发送 `X-App-Id: <app_id>` |
| App API Key | `X-App-Id: <app_id>`、`X-API-Key: <app_api_key>` |

JWT 与 App API Key 不能在同一请求中同时发送。Indexer 结果回写使用每个任务独立生成的随机令牌。

### 接口明细

管理接口使用 JWT：

```http
Authorization: Bearer <user_token>
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/auth/login` | 用户登录 |
| `GET` | `/api/v1/auth/me` | 当前用户与平台管理员能力 |
| `PATCH` | `/api/v1/auth/password` | 当前用户验证旧密码后修改密码 |
| `GET/POST` | `/api/v1/apps` | 查询或创建应用；每个 App 维护一棵独立 org 树 |
| `GET/PATCH/DELETE` | `/api/v1/apps/{app_id}` | 按业务 `app_id` 查询、修改或删除应用 |
| `GET/POST` | `/api/v1/orgs` | 查询当前用户可见的组织树或创建组织 |
| `GET/PATCH/DELETE` | `/api/v1/orgs/{org_id}` | 查询、修改或停用组织 |
| `GET/POST` | `/api/v1/users` | 查询可见用户或创建用户 |
| `GET/PATCH/DELETE` | `/api/v1/users/{user_id}` | 查询、修改或停用用户 |
| `GET/POST` | `/api/v1/apps/{app_id}/workspaces` | 查询或创建知识库 |
| `GET/PATCH/DELETE` | `/api/v1/workspaces/{workspace_id}` | 查询、修改或删除知识库 |
| `GET/POST` | `/api/v1/workspaces/{workspace_id}/members` | 查询授权来源，或提交 `type/id/role` 新增个人或组织授权 |
| `GET` | `/api/v1/workspaces/{workspace_id}/orgs` | 查询可加入工作区的组织 |
| `GET` | `/api/v1/workspaces/{workspace_id}/users` | 分页查询可加入工作区的用户 |
| `PUT/DELETE` | `/api/v1/workspaces/{workspace_id}/members/{member_id}?type=user或org` | 按授权记录 ID 修改角色或移除授权 |
| `GET` | `/api/v1/workspaces/{workspace_id}/files` | 查询知识库文件 |
| `POST` | `/api/v1/workspaces/{workspace_id}/files/upload-url` | 校验权限并签发 MinIO PUT 上传地址 |
| `POST` | `/api/v1/workspaces/{workspace_id}/files/{file_id}/complete` | 校验对象已上传，登记文件并发布索引任务 |
| `GET/DELETE` | `/api/v1/workspaces/{workspace_id}/files/{file_id}` | 查询或删除文件 |
| `GET` | `/api/v1/workspaces/{workspace_id}/chunks` | 分页查询知识库分片 |
| `POST` | `/api/v1/rag/search` | 按已授权的 `workspace_ids` 检索，可跨知识库 |
| `GET` | `/api/v1/rag/config` | 查询检索默认值和 sparse、rerank 能力 |

创建应用需提交 `{"app_id":"imsdom","name":"应用名称"}`，响应包含 `app` 和根组织 `org`。`apps.id` 是数据库内部使用的 UUID 主键；`app_id` 是 2-40 个字符、唯一且不可变的业务标识，App 管理路径、`X-App-Id`、索引任务和检索统一使用它。每个 App 只有一棵以根组织开始的 org 树，组织使用 UUID 外键关联应用。平台 `owner` 不属于任何组织，`org_id` 为 null；`admin` 和 `member` 属于当前 App 的一个组织。用户登录和创建请求使用 `name` 表示登录名。

文件上传分三步：向 KB API 申请上传地址，浏览器直接 PUT 文件到 MinIO，再调用完成接口登记并创建索引任务。替换时申请地址需要传已有 `file_id`，完成接口会复用该 ID。浏览器访问的 MinIO 地址由 `KB_MINIO_PUBLIC_URL` 配置，需能从访问 WebUI 的浏览器连通。文件状态包括 `indexing`、`indexed`、`failed`、`deleting`、`delete_failed`。

KB API 将索引和删除任务发布到 `kb.index.tasks`，RAG Indexer 通过 HTTP 回写接口更新结果。一个 App 可有多个 workspace；`workspace_user` 保存个人角色，`workspace_org` 保存组织角色，组织授权动态覆盖直属用户，个人角色优先。操作和角色映射固定在代码，不建权限表。文件只归属 workspace，不归属 org；同一 App 的工作区共用向量 collection，分片保存 `workspace_id`、`file_id` 和 `chunk_index`。搜索可传多个 `workspace_ids` 和 `file_ids`，KB API 会校验工作区授权。详见[工作区授权概要设计](docs/workspace-authorization.md)。

### 文件索引

文件只归属 workspace。使用 `/api/v1/workspaces/{workspace_id}/files/upload-url` 申请地址，直传 MinIO 后调用 `/api/v1/workspaces/{workspace_id}/files/{file_id}/complete` 创建文件记录和异步索引任务。

### 搜索

```
POST /api/v1/rag/search
```

用于从当前应用的一个或多个工作区检索相关 chunk。外部系统必须同时发送 `X-App-Id` 和匹配的 `X-API-Key`；WebUI 发送用户 Token 和当前 `X-App-Id`。

请求字段：

| 字段           | 类型     | 必填 | 说明                                                          |
| -------------- | -------- | ---- | ------------------------------------------------------------- |
| query          | string   | 是   | 查询文本                                                      |
| mode           | string   | 否   | `dense`、`sparse`、`hybrid`；不传使用配置默认值               |
| top_k          | integer  | 否   | 返回数量，范围 1 到 50                                        |
| rerank         | boolean  | 否   | 是否启用重排；不传使用配置默认值                              |
| fetch_k        | integer  | 否   | 每路检索召回数量，范围 1 到 100；必须大于等于 `top_k` |
| rrf_k          | integer  | 否   | Hybrid RRF 参数，范围 1 到 1000                               |
| workspace_ids  | string[] | 否   | 限定检索工作区；不传时检索当前身份有权访问的全部工作区，最多 1000 个 |
| file_ids       | string[] | 否   | 限定检索文件，最多 1000 个                                    |

响应字段：

| 字段           | 类型            | 说明                                                      |
| -------------- | --------------- | --------------------------------------------------------- |
| results        | array           | 检索结果列表                                              |
| mode           | string          | 实际检索模式；`hybrid` 在 sparse 不可用时会降级为 `dense` |
| rerank         | boolean         | 本次是否启用重排                                          |
| fetch_k        | integer         | 每路检索召回数量                                         |
| elapsed_ms     | number          | 检索耗时，单位毫秒                                        |

`results[]` 字段：

| 字段    | 类型   | 说明           |
| ------- | ------ | -------------- |
| id      | string | chunk ID       |
| content | string | chunk 文本内容 |
| score   | number | 检索得分       |

状态码：

| 状态码 | 说明                             |
| ------ | -------------------------------- |
| 200    | 搜索成功                         |
| 400    | 参数错误、sparse/rerank 未配置等 |
| 401    | 未传或无效的用户 Token / App API Key |
| 403    | 指定的工作区不在当前身份授权范围内 |
| 422    | 请求体字段校验失败               |
| 429    | 触发限流                         |
| 500    | 服务内部错误                     |
| 503    | inference、向量库等依赖不可用    |

请求示例：

```bash
curl -X POST http://localhost:5175/api/v1/rag/search \
  -H 'X-App-Id: <app_id>' \
  -H 'X-API-Key: <app_api_key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "代位权",
    "workspace_ids": ["<workspace-id-1>", "<workspace-id-2>"],
    "mode": "hybrid",
    "top_k": 3,
    "rerank": true,
    "fetch_k": 20
  }'
```

成功示例：

```json
{
  "results": [
    {
      "id": "d65fc085-051f-5b90-b2ce-73ee00000001",
      "content": "如果债务人怠于行使自己已经到期的权利...",
      "score": 0.4209124445915222
    }
  ],
  "mode": "hybrid",
  "rerank": true,
  "fetch_k": 20,
  "elapsed_ms": 1134.2
}
```

失败示例：

```json
{
  "error": "sparse search is not configured",
  "service": "rag",
  "retryable": false,
  "traceId": "94f8f2dab8a2400587153d69912bea48"
}
```

删除文件使用 `DELETE /api/v1/workspaces/{workspace_id}/files/{file_id}`，由 KB API 校验 workspace 权限，将文件标记为 `deleting` 并返回 202。Indexer 异步清理索引并成功回写后，KB API 才软删除文件记录和 MinIO 对象；失败时状态为 `delete_failed`。

### 对话

```http
POST /api/v1/llm/chat/stream
```

使用 JWT 或 App API Key 认证，通过 SSE 流式返回回答。请求必须明确指定本次允许检索的工作区：

```json
{
  "thread_id": "conversation-1",
  "message": "报销期限是多少？",
  "workspace_ids": ["<workspace-id>"]
}
```

Chat 将当前身份凭证和 `X-App-Id` 转发给 KB API；KB API 再校验工作区权限，Chat 不信任客户端直接提交的用户或组织身份。

会话历史接口使用同一认证方式：

```text
GET    /api/v1/llm/threads
GET    /api/v1/llm/threads/{thread_id}/messages
DELETE /api/v1/llm/threads/{thread_id}
```

### 索引结果回写

```http
POST /api/v1/index-results
Content-Type: application/json

{
  "operation": "index",
  "file_id": "<file_id>",
  "task_id": "<task_id>",
  "callback_token": "<callback_token>",
  "status": "indexed"
}
```

该接口只供 RAG Indexer 使用。KB API 发布索引或删除任务时生成 `task_id` 和随机 `callback_token`，数据库只保存令牌摘要。Indexer 原样回传这两个字段以及 `operation`、`file_id`、`status`、`error` 和 `indexed_at`。回调只能更新当前任务，旧任务结果不能覆盖新任务状态；成功返回 204，凭证无效返回 401，Indexer 仅在回写成功后确认 MQ 消息。

更完整的请求、响应和权限说明见 [API 文档](docs/api.md)。
