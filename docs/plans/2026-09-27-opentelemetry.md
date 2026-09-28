# OpenTelemetry Implementation Plan

**Goal:** 在 Jaeger 查看检索、对话与异步索引的完整调用链。

**Architecture:** KB API、RAG Indexer、Chat 使用 OpenTelemetry SDK，以 OTLP HTTP 上报 Jaeger。HTTP 和 RabbitMQ headers 传递 W3C trace context；内部模块使用子 span。

**Tech Stack:** OpenTelemetry Python、FastAPI、HTTPX、Pika、Jaeger、Docker Compose。

## 实施顺序

1. `kb_api/telemetry.py` 负责 SDK、HTTP 自动采集和上下文；现有 tracing 模块委托该实现。测试请求响应 ID 与导出 trace 一致。
2. `kb_api/queue.py` 发布时注入上下文，消费时提取并创建处理 span；`index_tasks.py` 标记任务结果，HTTP 回写沿用上下文。测试连续任务隔离及 ACK/NACK 行为。
3. Retriever、Indexer 为解析、切片、向量化、检索、重排、写入创建 span。用内存 exporter 验证父子关系与失败状态。
4. Chat 接入独立 SDK 初始化，贯通检索与模型调用，记录首 token 和流完成；验证流式错误和结束时间。
5. Compose 加入 Jaeger 和持久化配置，应用配置 OTLP 地址与采样率；更新依赖锁文件并运行后端测试。
6. 启动本地服务，用实际请求检查 Jaeger trace、错误 ID 和消息上下文，提供查看地址。

## 数据

记录服务、阶段、模型、耗时、状态、数量及 app/workspace/file ID。正文、密码和签名 URL 不作为 span 属性。用户与文件的现有授权和状态规则保持不变。

## 验证

- 后端测试使用 `rag_test`；遥测单测使用内存 exporter。
- 自动上报不可用时不阻断业务；关闭上报后请求仍可执行。
- Jaeger UI 绑定本机端口，OTLP 端口仅容器网络开放。
