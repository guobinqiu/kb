# MinerU 远程解析

目标：保留原生文档及云平台解析，通过 HTTP 接入 233 的文件 API Server，由 API Server 调用 VLM Server；Indexer 不运行本地 MinerU SDK 解析或加载模型。

1. 核对运行中 4.0.6 的 OpenAPI 和本地 4.0.3 SDK 契约。
2. 增加文件 API 的 enable 配置，地址为 18002，timeout 使用秒。
3. 文件 API 使用上传、解析任务、轮询和 structured_content 下载；VLM 仅供 API Server 在容器网络内调用。
4. structured_content 直接转换为 blocks，复用云平台 content list 的表格合并逻辑；Indexer 不安装 MinerU Python 包。验证标题、页码、表格以及错误和超时。
5. 离线回归，实际请求远端，再构建启动 Indexer 验证。
6. 移除 Indexer 的 CPU/GPU extras、SERVICE_EXTRA 构建参数及 models 挂载；inference 通过 SiliconFlow/TEI HTTP 客户端调用模型，不读取本地模型目录。

原生解析保留 .txt/.md；Office 新旧格式统一使用自建 MinerU Flash。官方独立服务的模型下载和部署保留在 scripts/deploy_mineru_services.txt 与 deploy/mineru.yaml，不删除实际模型目录。
