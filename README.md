productv2
=========

基于 LangChain/LangGraph 的商品上架系统骨架，使用仓库内候选商品数据生成上架草稿。

## 环境初始化

```bash
uv sync
```

## 运行工作流

```bash
uv run productv2 --limit 3
```

处理全部候选商品：

```bash
uv run productv2 --all
```

也可以使用显式子命令：

```bash
uv run productv2 run --limit 3
```

## 初始化 SQLite 数据库

```bash
uv run productv2 init-db
```

初始化并导入候选商品数据：

```bash
uv run productv2 init-db --seed-candidates --all
```

默认数据库路径为 `data/productv2.db`，可通过 `PRODUCTV2_DATABASE_PATH` 或 `--database-path` 覆盖。

## 原始数据目录

程序启动时会先扫描 `data/raw` 下的 `*.json` 文件。扫描到数据后会导入 `products` 表：

- `status` 写入 `all_pendding`
- 五个图片字段保持默认空字符串
- 每个 JSON 文件完整导入成功后会删除该 JSON 文件
- 导入失败的 JSON 文件会保留在原目录，方便修复后重试

原始数据目录可通过 `PRODUCTV2_RAW_DATA_DIR` 或 `--raw-data-dir` 覆盖。

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

当前 OpenAI-compatible Responses 接口已探测支持 `temperature` 和 `top_p`；`top_k` 会触发网关失败或不稳定，因此 Enroute 逆向分析只使用 `temperature/top_p` 做创意采样，尺寸检测仍保持稳定默认参数。

## 图片生成配置

全局图片生成组件位于 `src/productv2/image_generation.py`，默认使用 Grsai 图片生成接口：

```bash
IMAGE_GENERATION_API_BASE=https://grsaiapi.com
IMAGE_GENERATION_MODEL=gpt-image-2
IMAGE_GENERATION_ASPECT_RATIO=1024x1024
IMAGE_GENERATION_REPLY_TYPE=json
IMAGE_GENERATION_TIMEOUT=600
IMAGE_GENERATION_POLL_TIMEOUT=600
```

本地密钥写入 `.env` 的 `IMAGE_GENERATION_API_KEY`。组件会调用：

- `POST /v1/api/generate`
- `GET /v1/api/result?id=<task_id>`

## 虚拟模特风格

佩戴图生成会使用固定虚拟模特 profile，定义在 `src/productv2/model_profiles.py`。当前 5 个 profile：

- `Romantic Rebel`：欧洲女性，黑发/深棕发，冷淡叛逆，适合十字架、锁头、金币、蛇链。
- `Soft Romantic`：欧洲女性，浅棕/深金发，柔和但不甜，适合珍珠、蝴蝶结、花、细链。
- `Vintage Muse`：欧洲女性，复古脸型和旧墙/暖灰氛围，适合爱心、金币、宝石、宫廷感款。
- `Cool Romantic`：黑人女性，松弛冷静，适合银链、珍珠、宝石、锁头、叠戴项链。
- `Playful Muse`：亚洲女性，轻快但不网红可爱，适合海星、彩色、趣味吊坠。

共同原则：不是“漂亮模特戴首饰”，而是“这个女孩的风格里自然有这件首饰”。

固定模特图片保存在：

```text
data/model_profiles/<profile_key>/model.jpg
```

当前图片是白/浅灰背景的三视图技术参考图，用于让 AI 识别模特五官、肤色、体型和三维比例。工作流启动时会把这些图片路径和模特摘要同步到 SQLite `model_profiles` 表。

Enroute 佩戴图逆向分析会把 `model_profiles.summary` 注入 LLM system prompt，并要求逆向 JSON 输出 `selected_model_profile`。佩戴图生成预留节点会把选中的固定模特三视图图片加入输入图片列表。

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

每个类目按 `sort_by=best-selling` 拉取产品，并下载产品图片。默认每个类目目标采集约 60 张图片，最低目标 50 张，最多 70 张。输出目录：

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
  --target-images-per-category 60 \
  --max-images-per-category 70
```

## 测试

```bash
uv run pytest
```
