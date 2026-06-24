# Agent 指令

项目目标：基于 LangChain/LangGraph 和本仓库中的候选商品数据，开发商品上架系统。

## 技术栈

- Python 3.11+
- uv：项目初始化、依赖管理、虚拟环境和锁文件管理
- LangChain：后续 LLM 能力接入层
- LangGraph：商品上架流程编排
- Pydantic / pydantic-settings：领域模型与运行配置

## 仓库目录与作用

- `AGENTS.md`：面向编码 Agent 的项目目标、技术栈、目录说明与协作约定。
- `README.md`：面向开发者的项目启动、运行和测试说明。
- `pyproject.toml`：uv/Python 项目元数据、依赖声明和命令行入口配置。
- `uv.lock`：uv 生成的依赖锁文件，保证环境可复现。
- `.python-version`：uv 选定的项目 Python 版本。
- `.env.example`：本地环境变量示例，包含候选商品数据路径和 LLM 配置占位。
- `.gitignore`：本地虚拟环境、缓存、密钥文件和构建产物忽略规则。
- `data/productv2.db`：本地 SQLite 数据库文件，由 `uv run productv2 init-db` 生成，默认不纳入版本管理。
- `data/raw/`：原始 JSON 数据投递目录。程序启动时先扫描该目录，成功导入数据库后删除已导入 JSON 文件。
- `data/products/`：产品处理产物目录，例如主图合并图，默认不纳入版本管理。
- `data/model_profiles/`：固定虚拟模特三视图图片目录，默认不纳入版本管理；启动工作流时同步写入 SQLite `model_profiles` 表。
- `workflow-logs/`：每次工作流运行的独立中文 `.log` 日志目录，记录节点输入、输出、状态记忆、判断结果、分支选择以及 AI 原始输入输出，默认不纳入版本管理。
- `enroute-bestsellers/`：离线采集的 Enroute best-selling 参考图片库，默认不纳入版本管理。
- `inyourday-candidate-products-site-raw-20260622.json`：候选商品原始数据，是商品上架流程的当前输入数据源。
- `src/productv2/__init__.py`：Python 包入口，导出 CLI `main`。
- `src/productv2/adapters/`：平台适配器目录，按平台名放置适配器模块；当前内置 `1688.py`。
- `src/productv2/cli.py`：命令行入口，支持运行工作流、初始化 SQLite 数据库、导入候选商品数据。
- `src/productv2/config.py`：项目根目录、默认数据路径、环境变量配置，以及 LangChain ChatModel 构造入口。
- `src/productv2/data.py`：候选商品 JSON 数据读取与模型校验。
- `src/productv2/db.py`：SQLite 连接、建表和候选商品导入逻辑。
- `src/productv2/image_generation.py`：全局图片生成组件，封装 Grsai `POST /v1/api/generate` 和 `GET /v1/api/result`。
- `src/productv2/enroute.py`：从本地 Enroute best-selling 参考图库按处理商品类目严格选择 `02.jpg` 佩戴参考图。
- `src/productv2/reference_analysis.py`：使用 OpenAI Responses streaming 逆向分析 Enroute 佩戴参考图，按模特风格、衣服风格、场景风格和拍摄风格多维输出；LLM 禁止描述参考图产品细节。
- `src/productv2/model_profiles.py`：inyourday 风格固定虚拟模特 profile，用于后续佩戴图生成 prompt。
- `src/productv2/models.py`：候选商品与上架草稿的 Pydantic 领域模型。
- `src/productv2/selection.py`：从数据库读取未完成商品，在内存中随机选择有平台适配器的商品。
- `src/productv2/state.py`：进程内全局产品 state。核心 product 字段与数据库 `products` 表保持一致；临时流程数据放入 state extras，不硬塞入数据库字段。更新真实图片和状态字段时同步写回 SQLite。
- `src/productv2/graph.py`：LangGraph 商品上架草稿工作流，当前包含加载候选商品、生成草稿、准备人工复核队列。
- `src/productv2/workflow_logging.py`：每次工作流运行的中文可读日志组件，负责记录节点输入/输出、状态记忆、异常、关键判断字段、条件分支，以及 LLM / 图片 AI 原始输入输出。
- `tools/enroute-bestsellers/download.py`：离线下载 Enroute best-selling 参考图库。访问 `collections/<category>/products.json`，默认四类 `earrings`、`bracelets`、`necklaces`、`rings`，按 `sort_by=best-selling` 下载产品图，每类目标约 60 张、最多 70 张。
- `tests/test_adapters.py`：平台适配器发现和随机选择逻辑测试。
- `tests/test_db.py`：SQLite 表结构、唯一键、图片默认值和候选商品导入测试。
- `tests/test_workflow.py`：工作流基础测试，验证候选商品可生成上架草稿。

## SQLite 数据库

默认数据库路径：`data/productv2.db`。

默认原始数据目录：`data/raw/`。程序启动时先扫描 `*.json`，成功导入的文件会被删除；导入状态写入 `all_pendding`，图片字段初始为空字符串。

使用 `uv run productv2 reset-db` 可将 `products` 表恢复到初始待处理状态：所有产品 `status` 写回 `all_pendding`，五个图片字段写回空字符串，`locked_at` / `locked_by` 清空。该命令不扫描或导入 `data/raw/`，也不清空 Enroute 逆向分析缓存和模特 profile 表。

`products` 表字段：

- `id`：自增主键。
- `product_id`：产品 ID，非空。
- `platform`：平台，非空。
- `rawdata`：候选商品原始 JSON 数据，文本存储，默认 `{}`。
- `status`：商品处理状态，默认 `candidate`。
- `main_image`：产品主图 / PDP 封面图，默认空字符串。
- `wearing_image`：佩戴图，默认空字符串。
- `detail_image`：细节图，默认空字符串。
- `size_ratio_image`：尺寸 / 比例图，默认空字符串。
- `multi_angle_image`：多角度图，默认空字符串。
- `created_at`：创建时间。
- `updated_at`：更新时间。
- `locked_at`：处理锁时间；不为空表示正在处理中，产品选择时会过滤。
- `locked_by`：处理锁归属。

唯一约束：`UNIQUE(product_id, platform)`。

`enroute_image_analyses` 表用于缓存 Enroute 参考图逆向拆解 JSON：

- `enroute_product_id`：Enroute 产品唯一 ID，唯一约束。
- `enroute_category`：Enroute 产品类目，例如 `necklaces`、`earrings`。
- `enroute_title`：Enroute 产品标题。
- `enroute_handle`：Enroute 产品 handle。
- `image_path`：被逆向分析的本地参考图路径，当前为产品 `02.jpg`。
- `image_position`：图片序号，当前默认为 `2`。
- `analysis_json`：图片拆解 JSON，包含模特风格、衣服风格、场景风格、拍摄风格。
- `summary`：LLM 输出的中文摘要，重点说明该风格适合哪类饰品；项链需说明短链、锁骨链、中长链、长链等适配关系。
- `created_at` / `updated_at`：缓存创建与更新时间。

`model_profiles` 表用于登记固定虚拟模特：

- `id`：自增主键。
- `profile_key`：固定模特唯一 key，例如 `romantic_rebel_european`。
- `name`：固定模特名。
- `summary`：模特信息摘要，会注入 Enroute 逆向 LLM 的 system prompt，供 LLM 选择模特。
- `image_path`：固定模特三视图图片本地路径。
- `metadata_path`：固定模特生成 metadata 本地路径。
- `created_at` / `updated_at`：记录创建与更新时间。

## 当前工作流

当前主流程聚焦商品图片处理，不把上架草稿生成视为核心目标。旧的 `ListingDraft` 代码仍存在，但不是当前图片处理主流程的完成标准。

每次调用 `run_listing_workflow()` 都会创建一个独立日志文件，默认位于 `workflow-logs/<product_name>__<platform>__<product_id>.log`。工作流启动时先创建临时运行日志；一旦选中产品，会使用产品名称、平台和产品 ID 重命名日志文件，避免同名产品覆盖，最终路径会写入 `metrics.workflow_log_path`。日志事件包括 `workflow_start`、每个节点的 `node_start` / `node_end`、异常时的 `node_error` / `workflow_error`、以及尺寸检测后的 `branch_decision`。节点日志以中文可读文本记录输入 state、输出 state、状态记忆摘要、状态写回逻辑，并抽取 `status`、`reason`、`cache`、`can_judge_size`、图片编号、选中模特、Enroute 参考图路径等关键判断字段。LLM 和图片 AI 调用必须记录原始输入与原始输出，包括 prompt、请求参数、图片输入路径/URL、模型原始响应文本或接口原始响应 JSON。日志是排查用运行产物，不写入数据库，不纳入 Git。

当候选商品 JSON 不存在时，`load_candidates` 会从 SQLite 读取所有未完成且未加锁商品到内存，随机打乱后逐条检查 `src/productv2/adapters/` 是否存在平台适配器；没有适配器则跳过，直到选中一条商品。默认完成状态：`done`、`completed`、`published`；`locked_at` 不为空表示正在处理中，会被过滤。

选中商品后，系统会立刻写入 `locked_at` / `locked_by` 并将 `status` 更新为 `processing`，然后使用数据库整行数据初始化进程内全局 state。后续流程通过 `productv2.state.get_current_product()` 读取当前商品；通过 `set_status()` 和 `set_image()` 更新真实状态或图片字段时，必须同步写回 SQLite。临时流程数据使用 `set_extra()` / `get_extra()`，不要硬加入数据库字段或 `CandidateProduct` 字段。

主图聚合检测：选中商品后调用平台适配器 `get_main_images()` 获取主图 URL，下载可用图片、给子图编号并临时合并保存为 `data/products/<platform>/<product_id>/main_image_collage.jpg`。该合并图只是 LLM 检测用临时产物，不写入 `products.main_image`。合图完成后调用全局 LLM 判断哪些编号子图包含人体参照，可用于判断产品尺寸、比例或佩戴效果。

LLM 检测成功后会在 state extras 中写入尺寸参考图和产品主图的本地文件路径。随后系统会根据当前处理商品类目，从 `enroute-bestsellers/<category>/` 中严格选择同类目商品的 `02.jpg` 佩戴参考图；如果无法推断类目或同类目没有参考图，则跳过该逆向分析节点，不跨类目兜底。

Enroute 参考图选中后，系统先同步 `data/model_profiles/` 到 SQLite `model_profiles` 表，再按 `enroute_product_id` 查询 `enroute_image_analyses` 缓存。缓存命中且 `analysis_json.selected_model_profile.profile_key` 存在时直接读取；旧缓存缺少模特选择字段时会重新调用逆向 LLM。未命中时调用全局 LLM 对该佩戴图做逆向分析，system prompt 会注入所有固定模特摘要和图片路径，要求 LLM 在 JSON 中输出 `selected_model_profile`。逆向 JSON 按 `summary`、`selected_model_profile`、`model_style`、`clothing_style`、`scene_style` 和 `shooting_style` 多维输出，并写入缓存表。`summary` 由 LLM 自己写，程序不再拼接摘要。逆向分析只提炼模特、衣物、场景和拍摄规则，prompt 禁止输出参考图产品细节。

进入佩戴图生成预留节点时，系统会把已选产品主图和尺寸参考图复制到 `wearing_generation_inputs/`，分别添加底部白条标记 `01 主图` 和 `02 尺寸参考图`，并把 LLM 选中的固定模特三视图图片加入输入图片列表，再根据 Enroute 逆向 JSON 组装图片生成 prompt。prompt 会要求将 `01` 的同一件产品戴在模特脖子上，以 `02` 的佩戴比例为尺寸参考，使用选定固定模特的身份、五官、肤色、体型和三维比例，并强调产品一致性、尺寸一致性和佩戴位置合理。当前仍不实际调用慢速图片生成接口，也不会写入 `products.wearing_image`。

Grsai 图片生成组件是工具能力，不是主流程本身。

## 协作约定

- 使用 `uv add` / `uv remove` 管理依赖，不手写锁文件。
- 使用 `uv run productv2 --limit N` 验证工作流入口。
- 使用 `uv run productv2 init-db --seed-candidates --all` 初始化 SQLite 并导入当前候选商品数据。
- 使用 `uv run productv2 reset-db` 将现有产品数据恢复为待处理初始状态。
- 将待导入原始 JSON 放入 `data/raw/` 后，任意 `uv run productv2 ...` 启动都会先导入该目录数据。
- 使用 `uv run python tools/enroute-bestsellers/download.py` 离线采集 Enroute 参考图库。
- 使用 `uv run pytest` 验证测试。
- 全局 LLM 通过 `src/productv2/config.py` 的 `build_chat_model()` 创建，默认使用 OpenAI-compatible `base_url`、Responses API、streaming、`responses/v1` 输出格式和 `gpt-5.5` 模型。
- Enroute 逆向 LLM 的 Responses payload 单独使用创意采样参数 `ENROUTE_ANALYSIS_TEMPERATURE=0.9` 和 `ENROUTE_ANALYSIS_TOP_P=0.9`。当前接口已探测支持 `temperature`、`top_p`，不支持或无法稳定处理 `top_k`，因此不要传 `top_k`。
- 真实 `OPENAI_API_KEY` 和 `IMAGE_GENERATION_API_KEY` 只放本地 `.env`，不要写入 README、AGENTS 或测试夹具。
- 全局图片生成通过 `src/productv2/image_generation.py` 的 `get_image_generator()` 创建，默认使用 `IMAGE_GENERATION_API_BASE=https://grsaiapi.com`、`IMAGE_GENERATION_MODEL=gpt-image-2`。
- LLM 节点接入前，应保持当前非 LLM 工作流可离线运行。
