# Compose 启动单元

目标：infra、kb、indexer、chat、webui、tei、mineru 使用独立 Compose 项目，共享 kb-net。

1. 从应用 Compose 拆出四个文件，WebUI 不隐式启动 KB。
2. TEI、MinerU 独立按需运行，Infra 默认 Qdrant，Milvus/etcd 为可选 profile。
3. just 仅提供各单元 up/down，以及应用 build。配置更改执行 up 重新创建应用容器。
4. 校验全部 Compose 与 just dry-run，再迁移本地旧应用容器，检查健康与入口。
