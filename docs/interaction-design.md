# 知识库平台架构

## 服务交互

```mermaid
flowchart LR
    User["用户"] --> WebUI["WebUI"]

    subgraph Platform["知识库平台"]
        KBAPI["KB API"]
        Chat["Chat"]
        WebUI --> KBAPI
        WebUI --> Chat
        Chat --> KBAPI
    end

    subgraph MgrGroup["后台管理"]
        Mgr["Backend Management"]
    end

    subgraph RetrieverGroup["检索服务"]
        Retriever["RAG Retriever"]
        QueryInference["Inference (使用云服务)"]
        Retriever --> QueryInference
    end

    subgraph Intranet["清洗服务"]
        Indexer["RAG Indexer"]
        Parser["Parser"]
        DocumentInference["Inference (使用本地服务)"]
        Indexer --> Parser
        Indexer --> DocumentInference
    end

    subgraph Infrastructure["基础服务"]
        RDB[(RDB)]
        MinIO[(MinIO)]
        MQ[(MQ)]
        VDB[(VDB)]
    end

    KBAPI --> Mgr
    KBAPI --> RDB
    KBAPI --> MinIO
    KBAPI --> MQ
    KBAPI --> Retriever
    Retriever --> VDB
    MQ --> Indexer
    Indexer --> KBAPI
    Indexer --> MinIO
    Indexer --> VDB
```

Indexer 是纯 MQ 消费进程，不提供 HTTP API：从 `kb.index.tasks` 消费索引与删除任务，通过 HTTP 向 KB API 回写结果。

## 身份与数据范围

每个 App 对应一棵独立 org 树，界面从当前 App 根组织向下加载完整树。平台 `owner` 不挂组织；`admin` 和 `member` 通过 `org_id` 归属组织。用户登录名使用 `name`。Nginx 完成认证后向内部服务传递 `X-Org-Id`。

一个 App 可以有多个 workspace。`workspace_user` 保存个人授权与角色，`workspace_org` 保存组织授权与角色。界面选择 org 时只保存组织授权，不展开用户；该组织的直属用户动态获得访问权，不包含子组织。个人角色优先于组织角色。文件只归 workspace，上传、列表、替换、删除和检索都以 `workspace_id` 为范围。角色与操作映射详见[工作区授权概要设计](workspace-authorization.md)。

## 业务时序

### 文件上传与索引

```mermaid
sequenceDiagram
    actor User as 用户
    participant WebUI
    participant KBAPI as KB API
    participant RDB
    participant MinIO
    participant MQ
    participant Indexer as RAG Indexer
    participant Parser
    participant Inference
    participant VDB

    User->>WebUI: 上传文件
    WebUI->>KBAPI: 为 workspace 申请上传地址
    KBAPI-->>WebUI: 返回 file_id 与 MinIO PUT URL
    WebUI->>MinIO: 直接上传文件
    WebUI->>KBAPI: 完成 workspace 文件上传
    KBAPI->>RDB: 创建 workspace 文件记录
    KBAPI->>MQ: 发布含 workspace_id 的索引任务

    MQ->>Indexer: 下发索引任务
    Indexer->>MinIO: 读取原文件
    MinIO-->>Indexer: 返回文件内容
    Indexer->>Parser: 解析、分片
    Parser-->>Indexer: 返回 chunks
    Indexer->>Inference: 文档向量化
    Inference-->>Indexer: 返回向量
    Indexer->>VDB: 写入索引
    VDB-->>Indexer: 写入结果
    Indexer->>KBAPI: HTTP 回写索引结果
    KBAPI->>RDB: 更新文件状态
    Indexer-->>MQ: basic.ack
```

### 聊天与检索

```mermaid
sequenceDiagram
    actor User as 用户
    participant WebUI
    participant Chat
    participant LLM
    participant KBAPI as KB API
    participant Retriever as RAG Retriever
    participant Inference
    participant VDB

    User->>WebUI: 发起聊天
    WebUI->>Chat: 发送问题
    Chat->>KBAPI: 请求知识检索
    KBAPI->>Retriever: 执行 RAG 检索
    Retriever->>Inference: 查询向量化
    Inference-->>Retriever: 返回查询向量
    Retriever->>VDB: 向量召回
    VDB-->>Retriever: 返回候选文档片段
    Retriever-->>KBAPI: 返回检索结果
    KBAPI-->>Chat: 返回知识上下文
    Chat->>LLM: 携带上下文生成回答
    LLM-->>Chat: 返回回答
    Chat-->>WebUI: 返回回答
    WebUI-->>User: 展示回答
```
