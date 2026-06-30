productv2
=========

基于 LangChain/LangGraph 的商品上架系统骨架，启动时扫描原始 JSON 目录入库，并从 SQLite 中选择待处理商品。

## 环境初始化

```bash
uv sync
```

## 运行工作流

```bash
uv run langgraph dev --allow-blocking --no-reload
```

主流程已迁移到 `langgraph dev`。服务启动后，优先使用安全恢复命令启动 workflow：

```bash
uv run productv2 restart-workflow
```

该命令会先检查 LangGraph API 中是否存在未完成 thread：正在运行的 thread 会直接返回状态；等待人工审核的 interrupted thread 会返回待审核信息，不会新建 workflow。确认审核结果后再显式 resume：

```bash
uv run productv2 restart-workflow --resume-json '{"action":"approve"}'
```

没有未完成 thread 时，该命令才会创建新 thread 并启动 `product_listing` graph。执行到佩戴图审核节点时会暂停，resume payload 示例：

```json
{"action": "approve"}
```

可选动作：`approve` 继续后续流程，`regenerate` 重新生成佩戴图，`reject` 标记当前商品失败并重新选品。

图入口配置在 `langgraph.json`，导出对象为 `src/productv2/dev_graph.py:product_listing`。`langgraph dev` 的本地 in-memory runtime 会接管持久化并支持 `interrupt()` / resume；不要在导出图里手动传入自定义 checkpointer。

## 控制台

本地控制台用于操作 LangGraph dev 服务和 thread，不直接编辑商品内容；清理或删除 flow 时会恢复对应商品的处理状态和锁，避免商品卡在处理中：

```bash
tools/control-console.sh start
```

该脚本会同时启动 `langgraph dev`、控制 API 和 Web 控制台。

默认地址：

- 控制 API：`http://127.0.0.1:8765`
- Web 控制台：`http://127.0.0.1:5173`
- LangGraph API：`http://127.0.0.1:2024`

控制台脚本支持统一启停：

```bash
tools/control-console.sh status
tools/control-console.sh stop
tools/control-console.sh restart
tools/control-console.sh start --api-port 8766 --ui-port 5174
tools/control-console.sh start --langgraph-port 2025
```

也可以分别启动：

```bash
uv run langgraph dev --allow-blocking --no-reload
uv run productv2 control-api
uv run productv2 control-ui
```

控制台支持查看服务在线状态、由控制台启动/停止/重启本机 `langgraph dev`、查看 thread 列表与 state、启动 workflow、安全恢复 workflow、停止单个 flow 的活跃 run、删除单个 flow、清理全部 flow，以及对 interrupted thread 发送 resume JSON。

工作流运行时会持续写入 `workflow-logs/` 和 `data/products/` 产物。手动启动 `langgraph dev` 时应使用 `--no-reload`，避免日志或图片产物写入触发热重载，打断长时间 LLM / 图片 AI 节点。

## 初始化 SQLite 数据库

```bash
uv run productv2 init-db
```

初始化并导入候选商品数据：

```bash
uv run productv2 init-db --seed-candidates --all
```

默认数据库路径为 `data/productv2.db`，可通过 `PRODUCTV2_DATABASE_PATH` 或 `--database-path` 覆盖。

重置现有产品数据到初始待处理状态：

```bash
uv run productv2 reset-db
```

该命令只重置 `products` 表：`status` 写回 `all_pendding`、清空五个图片字段、清空 `locked_at` / `locked_by`。它不会扫描或导入 `data/raw`，也不会清空 Enroute 逆向分析缓存和模特 profile 表。

## 原始数据目录

使用 CLI 工具扫描 `data/raw` 下的 `*.json` 文件：

```bash
uv run productv2 import-raw
```

扫描到数据后会导入 `products` 表：

- `status` 写入 `all_pendding`
- 五个图片字段保持默认空字符串
- 文件夹中的所有 JSON 都会逐个纳入导入处理
- 每个 JSON 文件完整导入成功后会删除该 JSON 文件
- 导入失败的 JSON 文件会保留在原目录，方便修复后重试

原始数据目录可通过 `PRODUCTV2_RAW_DATA_DIR` 或 `--raw-data-dir` 覆盖。

默认主流程不读取固定候选 JSON 文件；它只从 SQLite 选择待处理产品。`--data-path` 仅用于 `init-db --seed-candidates` 手动导入。

`products` 表以 `product_id + platform` 作为组合唯一键，图片字段默认空字符串：

- `main_image`：产品主图 / PDP 封面图
- `wearing_image`：佩戴图
- `detail_image`：细节图
- `size_ratio_image`：尺寸 / 比例图
- `multi_angle_image`：多角度图

## 平台适配器

平台适配器放在 `src/productv2/adapters/`。程序从数据库读取所有未完成状态的产品到内存，随机打乱后逐条检查是否存在对应平台适配器；没有适配器的平台会跳过，直到选中一条可处理产品。

当前已内置 `1688` 适配器。新增平台时创建对应模块：

```text
src/productv2/adapters/<platform>.py
```

`1688` 适配器提供：

- `get_main_images(candidate)`：从原始数据中提取产品主图 URL。
- `get_specification_images(candidate)`：从原始数据中提取规格图 URL；当前原始数据没有规格图字段时返回空列表。

选中产品后，工作流会调用适配器获取主图 URL，将可下载的主图编号后合并为一张 JPEG，并保存到：

```text
data/products/<platform>/<product_id>/main_image_collage.jpg
```

合并图是临时流程产物，不写入 `products.main_image`。随后 LLM 会检查编号合并图，判断哪些编号的子图包含人体参照，能用于判断产品尺寸、比例或佩戴效果。

已完成状态默认为 `done`、`completed`、`published`；其他状态，如 `all_pendding`，都视为未完成。

产品选择还会过滤正在处理中的产品：`locked_at` 不为空的记录不会进入内存候选集。锁归属可记录在 `locked_by`。

选中产品后会立刻写入锁并把 `status` 更新为 `processing`，随后用数据库整行数据初始化进程内全局 state。后续通过 `productv2.state.set_status()` 或 `productv2.state.set_image()` 修改真实状态和图片字段时，会同步更新 SQLite；临时流程数据放入 state extras。

## 工作流日志

每次运行工作流都会创建独立中文可读日志文件：

```text
workflow-logs/<product_name>__<platform>__<product_id>.log
```

工作流启动时会先创建临时运行日志；一旦选中产品，会使用产品名称、平台和产品 ID 重命名日志文件，避免同名产品覆盖。日志路径会写入返回结果的 `metrics.workflow_log_path`。日志记录 `workflow_start`、每个节点的 `node_start` / `node_end`、interrupt 时的 `node_interrupt`、异常时的 `node_error`，以及条件边的 `branch_decision`。每个逻辑单元都会带中文说明，解释该节点在流程中的作用。

在 `langgraph dev` 中，日志路径也会写入 workflow state 的 `workflow_log_path`。人工审核节点触发 `interrupt()` 时会记录 `node_interrupt`，这属于正常暂停，不是错误。

节点日志以中文文本记录输入数据、输出数据、状态记忆摘要、状态写回逻辑，以及 `status`、`reason`、`cache`、`is_product_qualified`、`failed_checks`、`can_judge_size`、图片编号、选中模特、Enroute 参考图路径等关键判断字段。候选产品 `candidates` 只记录数量、产品 ID、平台、标题、状态、锁信息和 rawdata 字段名，不记录完整 rawdata。LLM 和图片 AI 调用会额外记录原始输入与原始输出，包括 prompt、请求参数、图片输入路径/URL、模型原始响应文本或接口原始响应 JSON。日志目录可通过 `PRODUCTV2_WORKFLOW_LOGS_DIR` 覆盖，默认不纳入 Git。

## AI Checkpoint

商品级 LLM 和图片 AI 调用结果会写入 LangGraph state 的 `ai_checkpoints`。当前保存范围：

- `detect_size_reference`：主图拼图产品合格性检测 LLM 结果；当前首个硬规则是必须有可判断尺寸、比例或佩戴效果的真人/人体参照图。
- `select_wearing_style_profile`：从已学习 Enroute profile 和固定模特摘要中选择风格与模特。
- `compile_wearing_generation_prompt`：把产品素材、Enroute profile 和模特 profile 编排为最终生图提示词。
- `generate_wearing_image_attempt_<n>`：第 `n` 次佩戴图生成图片 AI 结果。

每个 checkpoint 包含 `type`、`source`、`input`、`input_hash`、`status`、`result` 和 `attempt_count`。节点重入时如果 `input_hash` 一致，会优先复用 state checkpoint，不重复调用外部 LLM 或图片生成接口；人工要求 `regenerate` 时会进入新的 attempt checkpoint。Enroute 单图学习是全局学习库行为，不写入单个 workflow state checkpoint，学习状态和复用分别以 `enroute_learning_references` / `enroute_image_analyses` 为准。

## LLM 配置

全局 LLM 由 `src/productv2/config.py` 的 `build_chat_model()` 创建，默认使用 OpenAI-compatible Responses API streaming 配置：

```bash
OPENAI_MODEL=gpt-5.5
OPENAI_API_BASE=https://www.lynxhub.top
OPENAI_USE_RESPONSES_API=true
OPENAI_STREAMING=true
OPENAI_OUTPUT_VERSION=responses/v1
ENROUTE_ANALYSIS_TEMPERATURE=0.9
ENROUTE_ANALYSIS_TOP_P=0.9
```

本地密钥放在 `.env`，模板见 `.env.example`。

当前 OpenAI-compatible Responses 接口已探测支持 `temperature` 和 `top_p`；`top_k` 会触发网关失败或不稳定，因此 Enroute 逆向分析只使用 `temperature/top_p` 做创意采样，产品合格性检测仍保持稳定默认参数。

## 图片生成配置

全局图片生成组件位于 `src/productv2/image_generation.py`，默认使用 Grsai 图片生成接口：

```bash
IMAGE_GENERATION_API_BASE=https://grsaiapi.com
IMAGE_GENERATION_MODEL=gpt-image-2
IMAGE_GENERATION_ASPECT_RATIO=4/5
IMAGE_GENERATION_REPLY_TYPE=json
IMAGE_GENERATION_TIMEOUT=600
IMAGE_GENERATION_POLL_TIMEOUT=600
```

本地密钥写入 `.env` 的 `IMAGE_GENERATION_API_KEY`。组件会调用：

- `POST /v1/api/generate`
- `GET /v1/api/result?id=<task_id>`

佩戴图生成节点会调用该组件，把带标记的产品主图、尺寸参考图和固定模特图作为输入，生成结果按 attempt 保存到：

```text
data/products/<platform>/<product_id>/wearing_image_attempt_<n>.*
```

该路径只写入本次 workflow 的 `wearing_image_result.generated_image_path`，不会写入 `products.wearing_image`。

## 虚拟模特风格

佩戴图生成会使用固定虚拟模特 profile，定义在 `src/productv2/model_profiles.py`。当前 5 个 profile：

- `Romantic Rebel`：欧洲女性，黑发/深棕发，冷淡叛逆，适合十字架、锁头、金币、蛇链。
- `Sharp Romantic`：欧洲女性，浅棕/深金发，冷感、警觉、有杂志感，适合珍珠、蝴蝶结、花、细链、水晶。
- `Vintage Muse`：欧洲女性，复古脸型和旧墙/暖灰氛围，适合爱心、金币、宝石、宫廷感款。
- `Cool Romantic`：黑人女性，松弛冷静，适合银链、珍珠、宝石、锁头、叠戴项链。
- `Playful Muse`：亚洲女性，轻快但不网红可爱，适合海星、彩色、趣味吊坠。

共同原则：不是“漂亮模特戴首饰”，而是“这个女孩的风格里自然有这件首饰”。

固定模特图片保存在：

```text
data/model_profiles/<profile_key>/model.jpg
```

当前图片是白/浅灰背景的三视图技术参考图，用于让 AI 识别模特五官、肤色、体型和三维比例。工作流启动时会把这些图片路径和模特摘要同步到 SQLite `model_profiles` 表。

Enroute 佩戴图逆向分析会把 `model_profiles.summary` 注入 LLM system prompt，并要求逆向 JSON 输出 `selected_model_profile`。佩戴图生成节点会把选中的固定模特三视图图片加入输入图片列表。

## Enroute 参考图库

离线采集 Enroute best-selling 参考图片：

```bash
uv run python tools/enroute-bestsellers/download.py
```

脚本会访问：

```text
https://enroutejewelry.com/collections/<category>/products.json
```

默认类目：

- `earrings`
- `bracelets`
- `necklaces`
- `rings`

每个类目按 `sort_by=best-selling` 拉取产品，并下载产品图片。普通 workflow 和控制台统计不扫描该目录；下载、删除或同步图片库这类明确图片管理动作结束后，会把可学习的 `02.jpg` 参考记录同步到 SQLite `enroute_learning_references` 表。之后所有学习数量、未学习数量和 UI 状态都只从数据库查询。

默认下载完整产品图片；如果只需要学习参考图，使用 `--reference-only`，只抽取每个产品的第 2 张图并保存为 `02.jpg`。产品数模式默认目标约 80 个产品，范围约 70-100 个产品。输出目录：

```text
enroute-bestsellers/
  necklaces/
    01-product-name/
      01.jpg
      02.jpg
      metadata.json
```

可用参数：

```bash
uv run python tools/enroute-bestsellers/download.py \
  --reference-only \
  --target-products-per-category 80 \
  --max-products-per-category 100
```

## 测试

```bash
uv run pytest
```
