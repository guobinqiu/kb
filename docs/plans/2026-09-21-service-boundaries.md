# RAG Service Boundaries Implementation Plan

**Goal:** 明确 RAG Indexer 文档处理与 KB API 检索模块的职责、配置和部署边界。

**Architecture:** `rag_indexer` 负责文档清洗，在进程内调用 Parser 与文档向量适配器。`kb_api/rag_retriever` 在 KB API 进程内运行，负责查询向量、重排和向量检索；KB API 接收搜索请求并校验工作区授权。

**Tech Stack:** Python 3.11、FastAPI、httpx、Pydantic、PyYAML、Docker Compose、pytest

## Global Constraints

- App、org 树、用户、工作区授权和文件状态由 KB API 管理。
- Parser、Inference、Retriever 作为进程内模块运行。
- WebUI 与 Chat 通过 KB API 访问工作区文件和检索。

---

### Task 1: 固定最终目录与模块边界

**Files:**
- Move: `cleaning/indexer` -> `rag_indexer`
- Move: `cleaning/parser` -> `kb_api/rag_indexer/parser`
- Move: `cleaning/inference` -> `kb_api/rag_indexer/inference`
- Move: `rag_retriever` -> `kb_api/rag_retriever`
- Modify: 所有 Python 导入与配置路径
- Test: `kb_api/rag_indexer/tests`
- Test: `kb_api/rag_retriever/tests`

**Interfaces:**
- Consumes: 当前 ParserService、Inference provider、Retriever 搜索管线。
- Produces: `rag_indexer.parser.ParserService`、`rag_indexer.inference.InferenceComponents`、`kb_api.rag_retriever.Retriever`。

- [x] 移动目录并机械更新导入路径。
- [x] 模块共用应用服务入口、镜像和依赖清单。
- [x] 运行导入测试，确认新包路径可加载。

### Task 2: 改为进程内调用

**Files:**
- Modify: `kb_api/rag_indexer/app/main.py`
- Create: `kb_api/rag_indexer/parser/client.py`
- Create: `kb_api/rag_indexer/inference/service.py`
- Modify: `kb_api/rag_indexer/core/index/service.py`
- Modify: `kb_api/rag_indexer/core/api/services/search.py`
- Modify: `kb_api/rag_retriever/service.py`
- Test: `kb_api/rag_indexer/tests/unit/test_main_startup.py`
- Test: `kb_api/rag_indexer/tests/unit/test_search.py`

**Interfaces:**
- Consumes: `ParserService.parse_url()`、dense/sparse/rerank provider。
- Produces: Parser、Inference、Retriever 的进程内调用对象。

- [x] 启动测试覆盖进程内 Parser、Inference、Retriever 的初始化。
- [x] 实现本地 Parser 适配器与统一 Inference 组件装配。
- [x] 在应用生命周期中启动并关闭本地组件。
- [x] 将搜索路由改为直接调用 `kb_api.rag_retriever.Retriever`。
- [x] 运行 Indexer、Parser、Inference、Retriever 单元测试。

### Task 3: 收敛部署与配置

**Files:**
- Modify: `deploy/deploy.yaml`
- Modify: `deploy/nginx/nginx.conf`
- Modify: `kb_api/Dockerfile`
- Modify: `kb_api/pyproject.toml`
- Modify: `kb_api/config/rag.yaml`
- Modify: `chat/config/chat.yaml`
- Modify: `justfile`

**Interfaces:**
- Consumes: 单一 `rag_indexer:6000` 应用服务。
- Produces: 应用服务镜像及其进程内模块配置。

- [x] 合并 Python 依赖与镜像构建定义。
- [x] 删除独立服务 Compose 定义和服务内 URL 配置。
- [x] 更新 Nginx 与 Chat 的服务名为 `rag_indexer`。
- [x] 校验 `docker compose config` 并构建 `rag_indexer` 镜像。

### Task 4: 文档与回归验证

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/interaction-design.md`
- Modify: `docs/api.md`

**Interfaces:**
- Consumes: 最终目录和 Compose 服务清单。
- Produces: 与代码一致的服务边界说明。

- [x] 更新目录、服务边界和调用关系。
- [x] 运行不依赖外部基础设施的全部相关 pytest。
- [x] 运行 Compose 配置校验与 Python 导入检查。
- [x] 核对服务地址与包名。

### Task 5: 合并 RAG Indexer 模块配置

**Files:**
- Modify: `kb_api/config/rag.yaml`
- Modify: `kb_api/rag_indexer/parser/config_loader.py`
- Modify: `kb_api/rag_indexer/inference/config_loader.py`
- Delete: `kb_api/rag_indexer/parser/config/parser.yaml`
- Delete: `kb_api/rag_indexer/inference/config/inference.yaml`
- Test: `kb_api/rag_indexer/parser/tests/unit/test_config.py`
- Test: `kb_api/rag_indexer/inference/tests/unit/test_cloud_config.py`
- Test: `kb_api/rag_indexer/inference/tests/unit/test_tei_protocol.py`

**Interfaces:**
- Consumes: `KB_CONFIG_FILE` 指向的 RAG Indexer 服务配置。
- Produces: Parser 从 `parser` 节读取配置，Inference 从 `inference` 节读取配置。

- [x] 为统一配置入口增加失败测试。
- [x] 合并 YAML 并修改两个模块加载器。
- [x] 删除独立配置文件并同步文档和 E2E 夹具。
- [x] 运行不依赖外部凭据的回归测试和 Compose 启动验证。

### Task 6: 按知识库绑定 Embedding 规格

**Files:**
- Modify: `kb_api/config/rag.yaml`
- Modify: `kb_api/rag_indexer/inference/config_loader.py`
- Modify: `kb_api/rag_indexer/inference/service.py`
- Modify: `kb_api/rag_indexer/core/api/schemas.py`
- Modify: `kb_api/rag_indexer/core/api/services/apps.py`
- Modify: `kb_api/rag_indexer/core/api/services/files.py`
- Modify: `kb_api/rag_indexer/core/api/services/search.py`
- Modify: `kb_api/rag_indexer/clients/db/base.py`
- Modify: `kb_api/rag_indexer/clients/db/postgres.py`
- Modify: `scripts/db.sql`
- Test: `kb_api/rag_indexer/inference/tests/unit/test_model_routing.py`
- Test: `kb_api/rag_indexer/tests/unit/test_app_management.py`
- Test: `kb_api/rag_indexer/tests/unit/test_files_stateless.py`
- Test: `kb_api/rag_indexer/tests/unit/test_retriever_proxy.py`

**Interfaces:**
- Consumes: 请求中的 `embedding.provider`、`embedding.model`、`embedding.dimensions`。
- Produces: 知识库级不可变 Embedding 绑定，以及并发安全的请求级 dense client 路由。

- [x] 先增加模型目录、知识库绑定和查询复用的失败测试。
- [x] Inference 配置维护可用模型目录。
- [x] 使用 `ContextVar` 在单次请求内选择 dense client，不让并发请求互相覆盖。
- [x] 在 `apps` 表持久化知识库 Embedding 规格，首次绑定后拒绝变更。
- [x] 索引、重试、建库与查询统一读取并使用知识库绑定。
- [x] 更新 API、数据库脚本和架构文档，运行单元、集成与 Compose 验证。
