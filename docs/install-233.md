# 233 安装指南

部署主机：`imsdom@19.16.1.233`。项目目录：`/home/imsdom/workspace/kb`。

本指南使用 Docker Compose、本机构建应用镜像。关系数据库使用兼容 PostgreSQL 的 ParadeDB 镜像，并同时作为默认向量后端。MinerU 和 TEI 复用 233 上已经运行的服务；Chat 当前使用 OpenRouter。

## 1. 检查环境

登录 233：

```bash
ssh imsdom@19.16.1.233
```

检查工具：

```bash
git --version
docker version
docker compose version
just --version
```

本次部署使用 Docker 29.1.2、Compose 5.0.0、Just 1.58.0。WebUI 在 Docker 镜像内使用 Node.js 22 构建，部署主机无需单独安装 Node.js 或 npm。当前用户需要有 Docker 操作权限。

检查已有模型服务：

```bash
curl -fsS http://127.0.0.1:18002/v1/health
curl -fsS http://127.0.0.1:8081/health
curl -fsS http://127.0.0.1:8082/health
```

| 服务 | 地址 | 要求 |
| --- | --- | --- |
| MinerU API Server | `http://19.16.1.233:18002` | 健康接口返回 `status: ok`；本次版本为 4.0.6 |
| TEI Embedding | `http://19.16.1.233:8081` | 健康接口 HTTP 200；模型 `BAAI/bge-m3` |
| TEI Rerank | `http://19.16.1.233:8082` | 健康接口 HTTP 200；模型 `BAAI/bge-reranker-v2-m3` |

TEI 健康接口可能没有响应正文，以 HTTP 状态为准。MinerU API Server 已连接现有 VLM Server，KB 不再启动额外的 VLM 引擎。

尚未安装 MinerU 或 TEI 时，先分别按照 [MinerU 部署步骤](../scripts/deploy_mineru_services.txt) 和 [TEI 部署步骤](../scripts/deploy_tei_services.txt) 准备服务。它们需要 NVIDIA GPU 与 Docker GPU 支持。上述三个地址可用后，再继续安装 KB。

## 2. 获取项目

首次安装：

```bash
mkdir -p ~/workspace
git clone git@github.com:guobinqiu/kb.git ~/workspace/kb
cd ~/workspace/kb
git remote -v
```

`origin` 应为 `git@github.com:guobinqiu/kb.git`，不是 `new_brain`。SSH 克隆需要该主机的 GitHub SSH Key 有仓库读取权限。

已有项目目录时，不重复克隆，改为：

```bash
cd ~/workspace/kb
git pull --ff-only
```

## 3. 复用模型目录

首次安装时建立链接：

```bash
cd ~/workspace/kb
ln -s ../brain/models models
readlink -f models
ls models/BAAI/bge-m3/config.json
ls models/BAAI/bge-reranker-v2-m3/config.json
```

`readlink` 应输出 `/home/imsdom/workspace/brain/models`，即：

```text
/home/imsdom/workspace/kb/models -> /home/imsdom/workspace/brain/models
```

已有正确链接时跳过 `ln -s`。KB API 和 Indexer 不加载本地模型；该链接供 TEI 等模型服务复用。MinerU 官方镜像使用自身准备的模型。

## 4. 配置环境变量

首次安装：

```bash
cd ~/workspace/kb
cp deploy/env.example deploy/.env
chmod 600 deploy/.env
nano deploy/.env
```

已有安装保留原 `.env`，不要重新覆盖。编辑下列值：

| 变量 | 233 配置 |
| --- | --- |
| `USE_CN_MIRROR` | `true` |
| `IMAGE_TAG` | `dev` |
| `KB_DATABASE_URL` | `postgresql://rag:rag@postgres:5432/rag` |
| `KB_ADMIN_NAME` | `admin` |
| `KB_ADMIN_PASSWORD` | 必填，至少 8 位；设置管理员初始登录密码，不能使用 `admin` 或 `change-me` |
| `JWT_SECRET` | 必填；KB API 与 Chat 共享的用户 JWT 签名密钥，不能使用 `change-me` |
| `RABBITMQ_USER` | `admin` |
| `RABBITMQ_PASSWORD` | `admin123` |
| `RABBITMQ_URL` | `amqp://admin:admin123@rabbitmq:5672/%2F` |
| `KB_MINIO_ENDPOINT` | `minio:9000` |
| `KB_MINIO_PUBLIC_URL` | `http://19.16.1.233:9000` |
| `KB_MINIO_BUCKET` | `kb-files` |
| `KB_MINIO_SECURE` | `false` |
| `S3_ACCESS_KEY`、`KB_MINIO_ACCESS_KEY` | 两项填相同的 MinIO 用户名 |
| `S3_SECRET_KEY`、`KB_MINIO_SECRET_KEY` | 两项填相同的 MinIO 密码，至少 8 个字符 |
| `OPENAI_API_KEY` | 填写 OpenRouter API Key，与 `chat/config/chat.yaml` 的 `openai_base_url` 对应 |

其他 OTel 设置保持 `env.example` 中的默认值。当前未启用云解析、云推理和云向量库，对应 API Key 可以留空。`.env` 不提交 Git。

`KB_MINIO_PUBLIC_URL` 用于浏览器直传文件，必须是浏览器能访问的主机地址，不能填 `localhost` 或 Docker 服务名。生成随机十六进制队列密码可避免连接串中的特殊字符转义问题。

## 5. 配置解析、推理和对话

编辑 `kb_api/config/rag.yaml`，核对以下已有配置项：

| 配置项 | 值 |
| --- | --- |
| `parser.mineru.enable` | `true` |
| `parser.mineru.base_url` | `http://19.16.1.233:18002` |
| `parser.mineru.tier` | `standard` |
| `parser.mineru_cloud.enable` | `false` |
| `inference.tei.enable` | `true` |
| `inference.tei.dense.bge_m3.enable` | `true` |
| `inference.tei.dense.bge_m3.base_url` | `http://19.16.1.233:8081` |
| `inference.tei.dense.bge_m3.model_name` | `BAAI/bge-m3` |
| `inference.tei.dense.bge_m3.dimensions` | `1024` |
| `inference.tei.rerank.bge_m3.enable` | `true` |
| `inference.tei.rerank.bge_m3.base_url` | `http://19.16.1.233:8082` |
| `inference.tei.rerank.bge_m3.model_name` | `BAAI/bge-reranker-v2-m3` |
| `inference.siliconflow-cn.enable`、`inference.siliconflow-intl.enable` | `false` |
| `vector_db.postgres.enable` | `true` |
| `vector_db.qdrant.enable` | `false` |
| `vector_db.qdrant.base_url` | `http://qdrant:6333` |
| `vector_db.milvus.enable`、`vector_db.qdrant_cloud.enable`、`vector_db.milvus_cloud.enable` | `false` |
| `storage.endpoint_url` | `http://minio:9000` |
| `storage.bucket` | `kb-files` |

KB API 和 Indexer 共用这个文件。所有 `vector_db` 后端中必须且只能启用一个。默认启用 PostgreSQL 向量后端，并使用 `database_url: postgresql://rag:rag@postgres:5432/rag`；其 `query_timeout`、`write_timeout`、`init_timeout`、`drop_timeout` 和 `retry` 分别控制数据库操作时限与重试。PDF 使用配置的 `standard`，Office 新旧格式固定使用 Flash，TXT 和 Markdown 使用现有文本解析。

编辑 `chat/config/chat.yaml`，核对：

```yaml
model_name: deepseek/deepseek-v4-flash-0731:nitro
openai_base_url: https://openrouter.ai/api/v1
llm_kwargs: '{"reasoning_effort":"high"}'
database_url: postgresql://rag:rag@postgres:5432/rag
request:
  timeout: 30
model:
  timeout: 10
rag:
  base_url: http://kb_api:6100
  timeout: 10
  top_k: 5
  rerank: false
  query_rewrite: true
```

保留该文件其余配置。

## 6. 检查容器和端口

```bash
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

新项目默认使用容器名 `postgres`、`minio`、`rabbitmq`、`jaeger`、`otel-collector`、`kb_api`、`rag_indexer`、`chat`、`webui`。其中 `postgres` 容器运行 ParadeDB，同时保存关系数据、向量和 BM25 索引。可选 Qdrant 使用 `qdrant`，可选 Milvus 使用 `etcd` 和 `milvus`。同名旧容器需先处理。

本次 233 有一个已停止的旧 `minio` 容器，实际处理命令为：

```bash
docker rename minio minio-legacy-stopped
```

仅在存在该旧容器时执行。此命令保留旧容器和数据，不应对正在使用的 KB MinIO 执行。

基础服务需要端口 `5432`、`5672`、`15672`、`9000`、`9001`，WebUI 使用 `5175`，Jaeger 在宿主机 `127.0.0.1:16686` 监听。选择 Qdrant 时还需要 `6333`、`6334`；选择 Milvus 时还需要 `2379`、`19530`、`9091`。已有 GPU 服务使用 `8081`、`8082`、`18002`。确保这些端口没有被其他服务占用；远程浏览器至少需要能访问 `5175` 和 `9000`。

## 7. 启动基础服务

```bash
cd ~/workspace/kb
sudo install -d -o 10001 -g 10001 jaeger_data jaeger_data/keys jaeger_data/values
just infra up
docker compose --env-file deploy/.env -p kb-infra -f deploy/infra.yaml ps -a
```

默认启动 ParadeDB/PostgreSQL、MinIO、RabbitMQ、Collector 和 Jaeger。

如果 RabbitMQ 拉取中断或长时间没有进展，本次 233 已验证以下方式可用：

```bash
docker pull docker.m.daocloud.io/library/rabbitmq:4-management
docker tag docker.m.daocloud.io/library/rabbitmq:4-management rabbitmq:4-management
just infra up
```

这是同一镜像的下载和本地标签设置，无需更改项目配置或 Docker 全局配置。

## 8. 初始化数据库

先等待 PostgreSQL 就绪：

```bash
until docker exec postgres pg_isready -U rag -d rag; do
  sleep 2
done
```

然后执行仓库中的 SQL：

```bash
docker exec -i postgres psql -U rag -d postgres -v ON_ERROR_STOP=1 < scripts/db.sql
docker exec postgres psql -U rag -d rag -c '\dt'
```

应看到 `apps`、`orgs`、`users`、`workspaces`、`workspace_user`、`workspace_org`、`files`。`db.sql` 同时准备 `rag_test` 数据库，正式运行不需要执行测试库建表脚本。

## 9. 构建并启动应用

```bash
cd ~/workspace/kb
just kb up
just indexer up
just chat up
just webui up
```

四条命令都自动构建并重新创建对应容器。`just webui up` 构建独立 WebUI 镜像；镜像内部使用 Nginx 托管静态文件并透明代理 KB API 与 Chat，认证由后端服务处理。

## 10. 检查运行状态

```bash
docker ps --filter network=kb-net --format 'table {{.Names}}\t{{.Status}}'
curl -f http://127.0.0.1:5175/
curl -f http://127.0.0.1:9000/minio/health/live
docker exec kb_api /app/.venv/bin/python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:6100/health').read().decode())"
docker exec rag_indexer /app/.venv/bin/python -c "import os; os.kill(1, 0)"
docker exec rabbitmq rabbitmqctl list_queues name consumers messages_ready messages_unacknowledged
```

`kb_api`、`rag_indexer`、`postgres`、`rabbitmq` 应为 `healthy`，其余长期服务应为 `Up`。Indexer 通过 `python -m kb_api.rag_indexer.app.main` 启动。队列 `kb.index.tasks` 的 `consumers` 应为 `1`；空闲时两项消息数量均为 `0`。

在浏览器打开：

```text
http://19.16.1.233:5175
```

使用 `.env` 的 `KB_ADMIN_NAME` 和 `KB_ADMIN_PASSWORD` 登录。首次启动会创建平台管理员；已有账号不会因修改环境变量自动改密码。

验收步骤：

1. 创建应用，并在其下创建工作区。
2. 在工作区上传 TXT 文件，写入一条明确的信息，例如酒店健身房的位置和开放时间。
3. 等待文件状态由“索引中”变为“已索引”，确认分片列表有内容。
4. 在应用搜索中查询该信息，确认能检索到文件分片。
5. 在应用对话中问相同问题，确认回答使用文件内容。
6. 上传 PDF 验证 MinerU 解析；Office 文件由 MinerU Flash 处理。
7. 删除测试文件，确认文件列表和索引同步删除。

本次 233 已完成 TXT 上传、索引状态回写、TEI 向量化和重排、检索、基于分片回答、文件与索引删除验证。

## 11. 查看日志和追踪

```bash
docker logs --tail 100 kb_api
docker logs --tail 100 rag_indexer
docker logs --tail 100 chat
```

从本机建立 Jaeger 隧道：

```bash
ssh -N -L 16686:127.0.0.1:16686 imsdom@19.16.1.233
```

本机打开 `http://localhost:16686`，搜索服务 `kb_api`。执行一次搜索后应能看到 `rag.search.*` 阶段。

233 上也可检查：

```bash
curl -fsS http://127.0.0.1:16686/api/v3/services
```

RabbitMQ 管理台为 `http://19.16.1.233:15672`，使用 `.env` 的 `RABBITMQ_USER` / `RABBITMQ_PASSWORD` 登录；MinIO 管理台为 `http://19.16.1.233:9001`，使用 `S3_ACCESS_KEY` / `S3_SECRET_KEY` 登录。

## 12. 后续更新

```bash
cd ~/workspace/kb
git pull --ff-only
just kb up
just indexer up
just chat up
just webui up
```

前端依赖发生变化时直接执行 `just webui up`，Docker 构建阶段会重新安装依赖并生成静态文件。首次安装的 `.env` 和数据库数据保留，不重复覆盖或删除。基础服务配置修改后执行 `just infra up`。

项目数据分别保存在 `pg_data`、`qdrant_data`、`minio_data`、`rabbitmq_data`、`jaeger_data` 下；模型通过 `models` 链接复用。`.dockerignore` 已排除这些数据目录和 `.env`，数据库启动后仍可正常构建应用镜像。
