# product_listing 工作流规则与算法说明

本文档总结当前 `product_listing` LangGraph 工作流的真实执行路径、核心规则和关键算法。它面向后续维护与调试，优先描述代码已经实现并被测试覆盖的行为，不把尚未接入的上架草稿生成能力写成当前完成标准。

主要代码入口：

- 工作流编排：`src/productv2/graph.py`
- 选品：`src/productv2/selection.py`
- SQLite 数据与锁：`src/productv2/db.py`
- 进程内商品状态：`src/productv2/state.py`
- 主图聚合：`src/productv2/images.py`
- 产品合格性检测：`src/productv2/vision.py`
- Enroute 参考选择：`src/productv2/enroute.py`
- Enroute profile 学习与风格/模特选择：`src/productv2/reference_analysis_service.py`
- 生图 prompt 编排与佩戴图生成：`src/productv2/wearing.py`
- 人工审核 payload：`src/productv2/manual_review.py`
- AI checkpoint：`src/productv2/workflow_checkpoints.py`
- 外部 AI 调用持久化锁：`src/productv2/ai_locks.py`

## 1. 当前主流程定位

当前主流程聚焦“商品图片处理”，尤其是从候选商品中选出可处理产品，聚合商品主图，执行产品合格性检测，学习同类目 Enroute 人物摄影 profile，从 Enroute profile 和固定模特 profile 中做选择，编排最终生图 prompt，生成 inyourday 风格佩戴图，并进入人工审核。

旧的 `ListingDraft` 仍然存在，工作流末尾也会构造 `drafts` 和 `review_queue`，但这不是当前主流程的核心完成标准。当前真正会落库的核心结果是：

- 商品进入处理时写入 `status=processing` 和锁字段。
- 人工审核通过后写入 `status=done`、`wearing_image=<generated_image_path>`，并释放锁。
- 人工拒绝或重生成超过上限后写入 `status=failed`，并释放锁。

中间产物如主图拼图、产品合格性检测结果、尺寸参考选择、Enroute 学习计划、风格/模特选择结果、佩戴图 prompt 和未审核的生成图，默认写入 LangGraph state、进程内 extras、文件目录或缓存表，不直接写入 `products` 的图片字段。Enroute 单图学习状态属于全局学习库，写入 SQLite `enroute_learning_references`，不作为单个 workflow 的业务 state。

## 2. 状态机总览

工作流节点顺序：

```text
START
  -> load_candidates
  -> merge_main_images
  -> detect_size_reference
  -> [条件]
       ok      -> select_enroute_reference
       failed  -> load_candidates
       skipped -> build_listing_drafts
  -> learn_enroute_profiles
  -> select_wearing_style_profile
  -> compile_wearing_generation_prompt
  -> generate_wearing_image
  -> wait_manual_review
  -> [条件]
       approve               -> build_listing_drafts
       regenerate 且未超上限 -> generate_wearing_image
       reject/未知/超上限     -> mark_failed_and_reload_candidates
  -> prepare_review_queue
  -> END
```

人工审核失败分支：

```text
mark_failed_and_reload_candidates
  -> load_candidates
```

这意味着被拒绝或重生成超限的商品会被标记失败并释放锁，随后同一工作流继续尝试选择下一个商品。

## 3. 全局数据规则

### 3.1 商品数据库是主状态源

默认数据库路径是 `data/productv2.db`。`products` 表使用 `(product_id, platform)` 唯一约束。工作流默认只从 SQLite 选择待处理商品，不直接读取历史候选 JSON 文件。

默认可处理商品条件：

```json
{
  "status": "LOWER(status) NOT IN ['done', 'completed', 'published', 'failed']",
  "locked_at": null
}
```

`failed` 已被归入完成状态集合，因此失败商品不会再次被默认选中。`reset-db` 可以把商品恢复为 `all_pendding` 并清空锁和图片字段。

### 3.2 原始数据导入规则

工作流每次进入 `load_candidates` 时都会先扫描 `data/raw/*.json`：

1. 按文件名排序逐个读取 JSON。
2. 文件内候选商品通过 Pydantic 模型校验。
3. 每个商品 upsert 到 `products` 表，默认状态为 `all_pendding`。
4. 单个 JSON 文件完整导入成功后删除该文件。
5. 如果某个文件解析或导入失败，该文件保留在 `data/raw/`，错误写入导入 summary，其他文件继续处理。

导入输入示例：

```json
[
  {
    "product_id": "raw-1",
    "platform": "1688",
    "rawdata": {
      "title": "Raw Product 1",
      "detail": {
        "image_urls": ["https://..."]
      }
    }
  }
]
```

导入输出 summary 示例：

```json
{
  "raw_data_dir": "data/raw",
  "files_scanned": 1,
  "files_imported": 1,
  "products_imported": 2,
  "failed_files": []
}
```

### 3.3 临时流程数据不硬塞数据库字段

`CandidateProduct` 和 `products` 表只保存核心商品字段与图片字段。临时流程数据必须保存在：

- LangGraph state：跨节点、可 checkpoint/resume 的流程数据。
- `state.set_extra()`：当前进程内临时状态，例如选中的主图路径、尺寸参考图路径、Enroute 参考图路径。
- 文件系统：`data/products/<platform>/<product_id>/...`。
- 专用缓存表：例如 `enroute_image_analyses`、`ai_call_locks`。

不要为了某个节点临时需要，把字段塞进 `products` 表或 `CandidateProduct`。

## 4. 节点详解

### 4.1 load_candidates：导入、同步模特、随机选品并加锁

阶段目标：

- 把 `data/raw/` 新投递的候选商品导入 SQLite。
- 把固定虚拟模特 profile 同步到 `model_profiles` 表。
- 从未完成且未加锁商品中选择一个可处理商品。
- 选中后立即锁定商品并初始化进程内状态。

输入：

```json
{
  "database_path": "data/productv2.db",
  "raw_data_dir": "data/raw",
  "model_profiles_dir": "data/model_profiles",
  "data_path": null,
  "limit": null
}
```

核心算法：

```python
import_raw_data_directory(database_path, raw_data_dir)
sync_default_model_profiles(database_path, model_profiles_dir)

if state.data_path:
    candidates = load_candidate_products(data_path)
    source = "json"
else:
    products = load_unfinished_products_from_database(database_path)
    shuffled = random.shuffle(products)
    for product in shuffled:
        if not has_platform_adapter(product.platform):
            skip(product)
            continue
        adapter = get_platform_adapter(product.platform)
        if hasattr(adapter, "can_handle") and not adapter.can_handle(product):
            skip(product)
            continue
        locked_product = lock_product(product_id, platform, status="processing")
        if locked_product is None:
            skip(product)
            continue
        candidate = locked_product
        break
```

选品规则：

- 默认从 SQLite 选；只有显式传入 `data_path` 才从单个 JSON 文件读调试数据。
- 先一次性读取所有未完成商品，再在内存中随机打乱。
- 只选择存在平台适配器的商品。
- 如果适配器实现了 `can_handle()`，还必须通过适配器自己的判断。
- 加锁使用数据库条件更新：只有 `locked_at IS NULL` 时才成功。
- 锁成功后同时把商品状态写为 `processing`。

输出：

```json
{
  "candidates": [
    {
      "id": 1,
      "product_id": "...",
      "platform": "1688",
      "rawdata": {},
      "status": "processing",
      "locked_at": "2026-...",
      "locked_by": "productv2-..."
    }
  ],
  "selected_product": {
    "id": 1,
    "product_id": "...",
    "platform": "1688",
    "status": "processing"
  },
  "metrics": {
    "candidate_count": 1,
    "candidate_source": "database_adapter_selection",
    "raw_import": {},
    "unfinished_count": 12,
    "selected_adapter": "1688",
    "skipped_without_adapter_count": 0
  }
}
```

验收标准：

- 选中商品必须已经写入 `status=processing`。
- 选中商品必须有 `locked_at` 和 `locked_by`。
- 进程内 `productv2.state` 已初始化为选中的数据库行。
- 如果没有候选商品，`candidates=[]`，后续节点应进入 skipped 或空输出。

### 4.2 merge_main_images：提取主图、下载并编号合图

阶段目标：

- 从平台原始数据中提取可用 PDP/主图 URL。
- 下载最多 6 张图片。
- 保存每张来源图和一张带编号的拼图，供 LLM 做产品合格性检测。

输入：

```json
{
  "candidates": [
    {
      "id": 1,
      "platform": "1688",
      "product_id": "...",
      "rawdata": {
        "detail": {
          "image_urls": ["https://...alicdn.com/...jpg"]
        }
      }
    }
  ],
  "product_assets_dir": "data/products"
}
```

1688 主图提取规则：

- 从 `rawdata.detail.image_urls`、`rawdata.image_urls`、`rawdata.images` 中递归提取 URL。
- 只保留 `http://` 或 `https://` 开头的 URL。
- 只保留包含 `alicdn.com` 的图片。
- 排除 `.svg`。
- 按首次出现顺序去重。

合图算法：

```python
image_urls = adapter.get_main_images(candidate)
for url in image_urls[:6]:
    image = download(url, timeout=20s)
    if download_ok:
        keep(image)

if not images:
    raise ValueError("No downloadable images available for collage.")

save sources:
  data/products/<platform>/<product_id>/main_image_sources/1.jpg
  data/products/<platform>/<product_id>/main_image_sources/2.jpg

build collage:
  tile_size = 512
  columns = min(3, image_count)
  rows = ceil(image_count / columns)
  each tile = white square + contained RGB image
  top-left black label = 1, 2, ...

save:
  data/products/<platform>/<product_id>/main_image_collage.jpg
```

输出：

```json
{
  "main_image_result": {
    "status": "ok",
    "path": "data/products/1688/<product_id>/main_image_collage.jpg",
    "temporary": true,
    "source_image_count": 6,
    "numbered_sources": [
      {
        "index": 1,
        "url": "https://...",
        "path": "data/products/1688/<product_id>/main_image_sources/1.jpg"
      }
    ]
  }
}
```

写库规则：

- `main_image_collage.jpg` 是 LLM 检测用临时产物。
- 不写入 `products.main_image`。
- 成功结果写入进程内 extra：`main_image_collage`。

失败规则：

- 如果候选商品不是来自数据库，即 `candidate.id is None`，该节点返回 skipped。
- 如果图片全部下载失败，节点抛出异常，工作流停止；不会自动把商品标记为 failed。

### 4.3 detect_size_reference：产品合格性检测

阶段目标：

- 让视觉 LLM 检查编号拼图，判断当前商品素材是否合格进入后续 Enroute profile 匹配和 AI 佩戴图生成。
- 当前已实现的硬规则是：必须存在真实人体、手、脖子、耳朵、手腕或模特佩戴等参照，能判断产品尺寸、比例或佩戴效果。
- 找出能判断产品尺寸、比例或佩戴效果的子图编号，并选择一张尺寸参考图和一张产品主图。
- 为后续更多质检项预留 `qualification_checks` 和 `failed_checks`，后续新增规则应进入同一个节点，而不是再把不合格素材直接送去生图。

输入：

```json
{
  "main_image_result": {
    "status": "ok",
    "path": "data/products/1688/<product_id>/main_image_collage.jpg",
    "source_image_count": 6,
    "numbered_sources": [
      {"index": 1, "path": ".../1.jpg", "url": "..."},
      {"index": 2, "path": ".../2.jpg", "url": "..."}
    ]
  }
}
```

LLM 请求规则：

- 使用 OpenAI-compatible Responses API。
- `stream=true`。
- 图片以 `data:image/...;base64,...` 形式传入。
- prompt 来自 `prompts/vision/size_reference/prompt_v1.md`。
- 要求只输出 JSON。

LLM 输出契约：

```json
{
  "is_product_qualified": true,
  "qualification_checks": {
    "size_reference": {
      "passed": true,
      "reason": "有清楚的人体佩戴参照"
    }
  },
  "failed_checks": [],
  "can_judge_size": true,
  "image_numbers": [1, 3],
  "size_reference_image_number": 1,
  "main_image_number": 2,
  "reason": "简短中文原因"
}
```

解析与归一化算法：

```python
detection = parse_json(text)
detection.image_numbers = sorted(unique(n for n in image_numbers if n > 0))

if size_reference_image_number is not positive int:
    size_reference_image_number = image_numbers[0] if image_numbers else None

if main_image_number is not positive int:
    main_image_number = None

detection.can_judge_size = bool(image_numbers) and detection.can_judge_size

if not detection.can_judge_size:
    size_reference_image_number = None

qualification_checks.size_reference = {
    "passed": detection.can_judge_size,
    "image_numbers": image_numbers,
    "size_reference_image_number": size_reference_image_number,
    "reason": reason
}

if not detection.can_judge_size:
    failed_checks.append("size_reference")

is_product_qualified = is_product_qualified and not failed_checks
```

选图映射算法：

```python
numbered_sources = {source.index: source for source in main_image_result.numbered_sources}
size_source = numbered_sources[size_reference_image_number]
main_source = numbered_sources[main_image_number]

selected_images = {
  "size_reference_image": {
    "number": size_source.index,
    "path": size_source.path,
    "url": size_source.url
  },
  "main_image": {
    "number": main_source.index,
    "path": main_source.path,
    "url": main_source.url
  }
}
```

输出：

```json
{
  "size_reference_result": {
    "status": "ok",
    "is_product_qualified": true,
    "qualification_checks": {
      "size_reference": {
        "passed": true,
        "reason": "有清楚的人体佩戴参照"
      }
    },
    "failed_checks": [],
    "can_judge_size": true,
    "image_numbers": [1, 3],
    "size_reference_image_number": 1,
    "main_image_number": 2,
    "reason": "有佩戴图",
    "selected_images": {
      "size_reference_image": {
        "number": 1,
        "path": ".../main_image_sources/1.jpg",
        "url": "https://..."
      },
      "main_image": {
        "number": 2,
        "path": ".../main_image_sources/2.jpg",
        "url": "https://..."
      }
    }
  }
}
```

分支规则：

```python
if size_reference_result.status == "failed":
    branch = "mark_failed_and_reload_candidates"
elif size_reference_result.status == "ok":
    branch = "select_enroute_reference"
else:
    branch = "build_listing_drafts"
```

当前实现会先把 LLM 解析出的产品合格性结果包装成 `status=ok`，再做必需参照校验。只有同时满足以下条件才继续 Enroute 流程：

- `is_product_qualified=true`
- `failed_checks=[]`
- `can_judge_size=true`
- `size_reference_image_number` 存在
- `selected_images.main_image.path` 存在
- `selected_images.size_reference_image.path` 存在

如果任一质检项失败，或检测结果说明无法判断尺寸比例、没有真实人体/手部/佩戴参照图，节点会改写为：

```json
{
  "status": "failed",
  "is_product_qualified": false,
  "failed_checks": ["size_reference"],
  "failure_type": "product_unqualified",
  "failure_detail": "size_reference_unusable",
  "reason": "仅看到文字宣传图，无人体、手部或佩戴参照，无法判断尺寸比例"
}
```

随后进入 `mark_failed_and_reload_candidates`：当前商品写入 `failed`，清空锁，并回到 `load_candidates` 选择下一个商品。这个分支不是重试同一商品，也不是继续把不合格材料交给 AI 生图。后续新增的产品质检规则也应该沿用这一分支语义。

如果 LLM 无法调用、输出为空或输出不可解析，异常会向外抛出，工作流停止；不会自动写 `failed_product`。

checkpoint 规则：

- key：`detect_size_reference`
- input 包含商品身份、拼图路径、来源图片数量、编号来源列表和运行时指纹。
- 运行时指纹包含当前 prompt manifest、模型名和 provider 指纹。
- 如果 input hash 一致且历史结果不是 failed/error，重入时直接复用。
- 复用时输出会带 `checkpoint="hit"`。

### 4.4 select_enroute_reference：按商品类目规划 Enroute 学习任务

阶段目标：

- 根据当前商品推断 Enroute 类目。
- 根据当前商品类目查询 SQLite `enroute_learning_references` 学习表。
- 根据同类目有效缓存数量决定本轮要新学习多少个 Enroute 参考图。

输入：

```json
{
  "candidates": [
    {
      "product_id": "...",
      "platform": "1688",
      "rawdata": {
        "title": "Pearl cross necklace",
        "motif_id": "...",
        "detail": {
          "category": "..."
        }
      }
    }
  ],
  "database_path": "data/productv2.db"
}
```

类目推断算法：

把以下字段合并成小写文本，并把 `_`、`-`、`/` 替换为空格：

- `candidate.product_id`
- `candidate.platform`
- `rawdata.title`
- `rawdata.candidate_id`
- `rawdata.motif_id`
- `rawdata.query`
- `rawdata.keyword`
- `rawdata.detail.title`
- `rawdata.detail.category`
- `rawdata.detail.product_type`

按关键词计分：

```json
{
  "necklaces": ["necklace", "pendant", "chain", "choker", "lariat", "项链", "吊坠"],
  "earrings": ["earring", "earrings", "ear cuff", "hoop", "stud", "耳环", "耳饰", "耳钉"],
  "bracelets": ["bracelet", "bangle", "watch bracelet", "手链", "手镯"],
  "rings": ["ring", "戒指", "指环"]
}
```

选择得分最高且得分大于 0 的类目；否则返回 `None`。

学习表数据来源：

- 下载、删除、同步 Enroute 图片库属于图片管理动作，可以读取或修改 `enroute-bestsellers/` 目录。
- 上述动作结束后，把当前规范 `02.jpg` 参考集同步到 SQLite `enroute_learning_references`。
- 普通 workflow、控制台统计和 UI 不扫描目录；所有参考图数量、未学习数量、学习中、已学习、失败数量都只从 SQLite 查询。
- 图片库中删除或不再属于当前规范 `02.jpg` 参考集的记录，会在同步动作中从学习表删除，不使用长期 `missing` 状态参与统计。

严格规则：

- 只允许同类目参考。
- 如果无法推断类目，跳过。
- 如果数据库学习表中没有同类目参考记录，跳过。
- 不跨类目兜底。

缓存有效性规则：

有效缓存不再要求包含模特选择字段。模特选择已经从学习层拆出，放到后续 `select_wearing_style_profile` 节点。

当前有效缓存判断：

```python
def is_valid_profile(analysis_json):
    if not isinstance(analysis_json, dict) or not analysis_json:
        return False
    if analysis_json.get("is_valid_human_reference") is False:
        return False
    if analysis_json.get("is_valid_wearing_reference") is False:
        return False
    return True
```

含义：

- 空 JSON 无效。
- 明确标记 `is_valid_human_reference=false` 的缓存无效。
- 明确标记 `is_valid_wearing_reference=false` 的旧格式缓存无效。
- 不再检查 `selected_model_profile.profile_key`。

学习数量算法：

```python
cached = valid_cache_by_category(category)
references = learning_reference_rows_by_category(category)
unlearned = [row for row in references if row.enroute_product_id not in cached_ids]
learning_batch_size = 5 if len(cached) < 5 else 1
learning_limit = min(learning_batch_size, len(unlearned))
learning_references = unlearned[:learning_limit]
```

含义：

- 同类目有效缓存少于 5 条时，本轮最多学习 5 张。
- 同类目有效缓存达到 5 条后，本轮学习 1 张。
- 如果没有未学习参考图，`learning_references=[]`，后续选择节点仍会从已有有效缓存中选择。
- 具体选哪几条由学习表查询顺序和未学习列表顺序决定，不随机。

输出：

```json
{
  "enroute_reference_result": {
    "status": "ok",
    "category": "necklaces",
    "reference_source": "database",
    "reference_count": 60,
    "cached_analysis_count": 3,
    "unlearned_count": 57,
    "learning_count": 5,
    "learning_references": [
      {
        "enroute_product_id": "necklaces:example",
        "category": "necklaces",
        "image_path": "enroute-bestsellers/necklaces/example/02.jpg",
        "product_dir": "enroute-bestsellers/necklaces/example",
        "metadata": {
          "title": "...",
          "handle": "...",
          "product_type": "...",
          "source_url": "..."
        }
      }
    ]
  }
}
```

### 4.5 learn_enroute_profiles：只负责学习 Enroute profile

阶段目标：

- 执行 `select_enroute_reference` 规划出的学习任务。
- 按学习规则串行学习：同类目有效缓存少于 5 条时最多学习 5 张，达到 5 条后学习 1 张。
- 把 Enroute 人物参考图逆向成结构化摄影 profile 和 summary，并写入 `enroute_image_analyses` 缓存表。
- 不做固定模特选择。
- 不生成最终生图 prompt。

输入：

```json
{
  "enroute_reference_result": {
    "status": "ok",
    "category": "necklaces",
    "learning_count": 5,
    "learning_references": [
      {
        "enroute_product_id": "necklaces:example",
        "category": "necklaces",
        "image_path": "enroute-bestsellers/necklaces/example/02.jpg",
        "product_dir": "enroute-bestsellers/necklaces/example",
        "metadata": {
          "title": "...",
          "handle": "..."
        }
      }
    ]
  }
}
```

单张学习输入：

```json
{
  "reference_image_path": "enroute-bestsellers/necklaces/example/02.jpg",
  "enroute_product_id": "necklaces:example",
  "category": "necklaces"
}
```

学习层不载入 `model_profiles`，也不会把固定模特信息传给 Enroute 逆向 prompt。固定模特只在下一节点 `select_wearing_style_profile` 中参与选择。

执行规则：

- 串行学习，不使用并行学习锁。
- 每张图开始前把 `enroute_learning_references.status` 更新为 `learning`。
- 学习成功后写入 `enroute_image_analyses`，并把学习表状态更新为 `learned`。
- 学习失败后把学习表状态更新为 `failed`，记录 `last_error` 和尝试次数。

学习前复用顺序：

```python
if database has valid cache for enroute_product_id:
    return database cache

analysis = analyze_enroute_reference_image(reference.image_path)
summary = summarize_enroute_profile(analysis)
upsert_enroute_image_analysis(...)
return analysis
```

逆向分析 LLM 请求规则：

- prompt 来自 `prompts/reference_analysis/enroute_reference/prompt_v2.md`。
- 使用 Responses streaming。
- 图片以 high detail 传入。
- `temperature` 和 `top_p` 来自配置，默认用于 Enroute 分析的创意采样参数。
- 不传 `top_k`。
- 不注入固定模特 profile。

当前逆向 JSON 契约核心字段：

```json
{
  "is_valid_human_reference": true,
  "invalid_reason": "",
  "analysis_scope": {
    "task": "photographic_reverse_profile_only",
    "not_prompt_generation": true,
    "exif_status": "visual_estimate_only_not_real_exif"
  },
  "observed_facts": {
    "human_visible_area": {},
    "composition_observation": {},
    "camera_observation": {},
    "lighting_observation": {},
    "pose_observation": {},
    "hair_observation": {},
    "clothing_observation": {},
    "background_observation": {},
    "observed_makeup_facts": {}
  },
  "estimated_shooting_profile": {
    "camera_estimate": {},
    "lighting_estimate": {},
    "pose_estimate": {}
  },
  "confidence_and_limits": {},
  "transfer_notes": {
    "stable_reference_features": [],
    "unstable_or_low_confidence_features": [],
    "do_not_transfer_from_reference": []
  },
  "summary": ""
}
```

重要约束：

- 逆向分析只提炼人物摄影、构图、镜头、光线、姿势、可见人体区域、背景、发型、妆容、服装和画面处理方式。
- 禁止把 Enroute 图里的具体产品、首饰、装饰物、道具或背景具体物件写进可迁移信息。
- 禁止输出最终生图 prompt。
- 如果 LLM 没有输出 `summary`，程序会用 `summarize_enroute_profile()` 从结构化 profile 中压缩生成缓存 summary。

缓存写入：

```json
{
  "table": "enroute_image_analyses",
  "unique_key": "enroute_product_id",
  "fields": {
    "enroute_category": "necklaces",
    "enroute_title": "...",
    "enroute_handle": "...",
    "image_path": ".../02.jpg",
    "image_position": 2,
    "analysis_json": {},
    "summary": "..."
  }
}
```

节点输出：

```json
{
  "enroute_learning_result": {
    "status": "ok",
    "category": "necklaces",
    "learning_count": 1,
    "cached_analysis_count_after_learning": 4
  }
}
```

跳过规则：

- 上游没有同类目 Enroute 参考：`status=skipped, reason=no_matching_enroute_reference`。
- 上游缺少类目：`status=skipped, reason=enroute_category_missing`。

### 4.6 select_wearing_style_profile：选择 Enroute profile 与固定模特 profile

阶段目标：

- 载入同类目所有有效 Enroute profile summary。
- 载入所有固定虚拟模特 profile summary。
- 结合当前产品主图与尺寸参考图，选择一个 Enroute profile 和一个固定模特 profile。
- 输出选择结果和实际完整 profile，供下一节点编排 prompt。

选择层前置条件：

- `enroute_reference_result.status == "ok"`。
- 类目有效缓存非空。
- SQLite `model_profiles` 表中存在固定模特 profile。
- `size_reference_result.selected_images.main_image.path` 存在。
- `size_reference_result.selected_images.size_reference_image.path` 存在。

输入：

```json
{
  "main_image_path": "data/products/1688/<product_id>/main_image_sources/2.jpg",
  "size_reference_image_path": "data/products/1688/<product_id>/main_image_sources/1.jpg",
  "enroute_profile_summaries": [
    {
      "enroute_product_id": "necklaces:short",
      "summary": "适合短链，锁骨区域构图明确。"
    },
    {
      "enroute_product_id": "necklaces:long",
      "summary": "适合长链，需要更宽松的胸前范围。"
    }
  ],
  "model_profile_summaries": [
    {
      "profile_key": "romantic_rebel_european",
      "name": "Romantic Rebel",
      "summary": "冷静松弛，适合锁骨链。",
      "image_path": "data/model_profiles/romantic_rebel_european/model.jpg"
    }
  ]
}
```

选择规则：

- prompt 来自 `prompts/wearing/style_profile_selection/prompt_v1.md`。
- LLM 只允许从 `enroute_profile_summaries` 中选择一个 `enroute_product_id`。
- LLM 只允许从 `model_profile_summaries` 中选择一个 `profile_key`。
- Enroute profile 只用于迁移人物摄影、构图、服装露肤、场景感觉和光线方式。
- 不继承 Enroute profile 中任何非当前产品的首饰/商品信息。
- 如果 Enroute profile 与尺寸参考冲突，优先保证当前产品尺寸和佩戴位置合理。
- 只输出 JSON。

输出契约：

```json
{
  "selected_enroute_product_id": "necklaces:short",
  "selected_model_profile_key": "romantic_rebel_european",
  "reason": "当前尺寸参考更接近短链构图，固定模特气质和构图适配。"
}
```

校验规则：

```python
selected = next(row for row in cached if row.enroute_product_id == selected_id)
if selected is None:
    raise ValueError("Selected Enroute analysis is not in cache")

selected_model = find(model_profiles, profile_key=selection.selected_model_profile_key)
if selected_model is None:
    raise ValueError("Selected model profile is not in model_profiles")
```

最终输出：

```json
{
  "wearing_style_selection_result": {
    "status": "ok",
    "cache": "selected",
    "reference_image_path": "enroute-bestsellers/necklaces/short/02.jpg",
    "enroute_reference_image_path": "enroute-bestsellers/necklaces/short/02.jpg",
    "enroute_product_id": "necklaces:short",
    "category": "necklaces",
    "summary": "适合短链，锁骨区域构图明确。",
    "analysis": {},
    "selected_model_profile": {
      "profile_key": "romantic_rebel_european",
      "name": "Romantic Rebel",
      "summary": "冷静松弛，适合锁骨链。",
      "image_path": "data/model_profiles/romantic_rebel_european/model.jpg",
      "metadata_path": "data/model_profiles/romantic_rebel_european/metadata.json"
    },
    "selection": {
      "selected_enroute_product_id": "necklaces:short",
      "selected_model_profile_key": "romantic_rebel_european",
      "reason": "当前尺寸参考更接近短链构图，固定模特气质和构图适配。"
    }
  }
}
```

兼容输出：

- 同一结果也会写入 `enroute_analysis_result`，供旧的人工审核 payload 和控制台读取路径继续工作。

checkpoint 规则：

- key：`select_wearing_style_profile`
- input 包含当前商品主图路径、尺寸参考图路径、Enroute summary 列表、模特 summary 列表和运行时指纹。
- 若 input hash 一致，重入时复用选择结果。

跳过规则：

- 没有同类目 Enroute 参考：`status=skipped, reason=no_matching_enroute_reference`。
- 学习后仍无有效缓存：`status=skipped, reason=no_cached_enroute_analysis`。
- 缺少当前商品主图或尺寸参考图路径：`status=skipped, reason=selected_product_images_missing`。

异常规则：

- LLM 选择了缓存中不存在的 `selected_enroute_product_id` 时抛出 `ValueError`。
- LLM 选择了不存在的 `selected_model_profile_key` 时抛出 `ValueError`。
- 这些系统异常不会自动把商品标记为 failed。

### 4.7 compile_wearing_generation_prompt：材料优化编排并生成生图 prompt

阶段目标：

- 加载实际 Enroute profile、固定模特 profile、产品主图和尺寸参考图。
- 把输入图片整理成图片生成模型能稳定理解的材料包。
- 调用 LLM 编排最终中文生图 prompt。
- 只产出 prompt 与输入图片列表，不调用图片生成接口。

输入：

```json
{
  "candidates": [
    {
      "product_id": "...",
      "platform": "1688"
    }
  ],
  "size_reference_result": {
    "selected_images": {
      "main_image": {
        "path": "data/products/1688/<product_id>/main_image_sources/2.jpg"
      },
      "size_reference_image": {
        "path": "data/products/1688/<product_id>/main_image_sources/1.jpg"
      }
    }
  },
  "wearing_style_selection_result": {
    "status": "ok",
    "summary": "适合短链，锁骨区域构图明确。",
    "reference_image_path": "enroute-bestsellers/necklaces/short/02.jpg",
    "analysis": {},
    "selected_model_profile": {
      "profile_key": "romantic_rebel_european",
      "name": "Romantic Rebel",
      "summary": "冷静松弛，适合锁骨链。",
      "image_path": "data/model_profiles/romantic_rebel_european/model.jpg"
    },
    "selection": {
      "reason": "当前尺寸参考更接近短链构图，固定模特气质和构图适配。"
    }
  }
}
```

输入图片准备算法：

```python
marked_dir = product_asset_dir / "wearing_generation_inputs"

01 = create_labeled_reference_image(
    source=selected_main_image,
    output=marked_dir / "01_main_image.jpg",
    label="01 主图"
)

02 = create_labeled_reference_image(
    source=selected_size_reference_image,
    output=marked_dir / "02_size_reference.jpg",
    label="02 尺寸参考图"
)

input_images = [01, 02]
if selected_model_profile.image_path:
    input_images.append(selected_model_profile.image_path)
```

标记图规则：

- 原图转换为 RGB。
- 底部增加白条。
- 白条中间写入 `01 主图` 或 `02 尺寸参考图`。
- 输出 JPEG，质量 92。

prompt 编排 LLM 规则：

- prompt 来自 `prompts/wearing/compile_generation_prompt/prompt_v1.md`。
- LLM 输入包含 `01 主图`、`02 尺寸参考图` 和固定模特三视图。
- LLM 同时读取 Enroute profile JSON、固定模特 profile JSON 和选择理由。
- LLM 只输出最终图片生成 prompt 正文，不输出 JSON、Markdown 或解释。

编排硬规则：

- 必须生成 inyourday 风格首饰佩戴图。
- 图 `01` 是当前商品唯一产品来源。
- 图 `02` 是真实佩戴比例和佩戴位置参考。
- 固定模特三视图只用于锁定模特身份、五官、肤色、体型和三维比例。
- Enroute profile 只用于迁移人物摄影、构图、服装露肤、场景感觉和光线方式。
- 禁止复制 Enroute profile 对应参考图中的产品、首饰、装饰物、道具或背景具体物件。

checkpoint 规则：

- key：`compile_wearing_generation_prompt`
- input 包含商品身份、尺寸参考结果、风格/模特选择结果、产品产物目录和运行时指纹。
- 命中 checkpoint 时会确认 `input_images` 文件仍存在；如果文件缺失，会重新编排。

输出：

```json
{
  "wearing_generation_prompt_result": {
    "status": "ok",
    "reason": "wearing_generation_prompt_compiled",
    "product_id": "...",
    "platform": "1688",
    "size_reference_image_numbers": [1],
    "marked_main_image_path": ".../wearing_generation_inputs/01_main_image.jpg",
    "marked_size_reference_image_path": ".../wearing_generation_inputs/02_size_reference.jpg",
    "enroute_reference_image_path": "enroute-bestsellers/necklaces/short/02.jpg",
    "selected_model_profile": {
      "profile_key": "romantic_rebel_european",
      "name": "Romantic Rebel",
      "image_path": "data/model_profiles/romantic_rebel_european/model.jpg"
    },
    "input_images": [
      ".../01_main_image.jpg",
      ".../02_size_reference.jpg",
      "data/model_profiles/romantic_rebel_european/model.jpg"
    ],
    "prompt": "最终中文生图 prompt",
    "selection_reason": "当前尺寸参考更接近短链构图，固定模特气质和构图适配。"
  }
}
```

跳过/异常规则：

- 缺少商品候选：`status=skipped, reason=no_candidate`。
- 上游风格/模特选择未完成：`status=skipped, reason=style_profile_not_ready`。
- 缺少实际 Enroute 或模特 profile：`status=skipped, reason=selected_enroute_or_model_profile_missing`。
- 缺少主图或尺寸参考图：`status=skipped, reason=selected_main_or_size_reference_missing`。
- 输入图片文件缺失时抛出 `FileNotFoundError`。

### 4.8 generate_wearing_image：使用编排后的 prompt 调用图片生成

阶段目标：

- 读取 `compile_wearing_generation_prompt` 输出的 prompt 和输入图片列表。
- 调用 Grsai 图片生成接口。
- 保存本次 attempt 的结果。

输入：

```json
{
  "wearing_generation_prompt_result": {
    "status": "ok",
    "prompt": "最终中文生图 prompt",
    "input_images": [
      ".../01_main_image.jpg",
      ".../02_size_reference.jpg",
      "data/model_profiles/romantic_rebel_european/model.jpg"
    ],
    "marked_main_image_path": ".../01_main_image.jpg",
    "marked_size_reference_image_path": ".../02_size_reference.jpg",
    "enroute_reference_image_path": ".../02.jpg",
    "selected_model_profile": {}
  },
  "wearing_generation_attempt": 0,
  "manual_review_decision": {}
}
```

attempt 算法：

```python
should_regenerate = manual_review_decision.action == "regenerate"
next_attempt = int(state.wearing_generation_attempt or 0) + 1
checkpoint_key = f"generate_wearing_image_attempt_{next_attempt}"
```

复用规则：

- 如果不是人工 regenerate，且 state 中已有 `wearing_image_result.status=ok`，并且 `generated_image_path` 文件仍存在，直接复用。
- 如果不是人工 regenerate，且对应 attempt checkpoint input hash 一致，也可复用 checkpoint。
- 人工 regenerate 会跳过旧 checkpoint，进入新的 attempt。

图片生成调用：

```python
generator.generate(
    prompt=wearing_generation_prompt_result.prompt,
    images=[data_url(path) for path in wearing_generation_prompt_result.input_images],
    wait=True,
    database_path=database_path
)
```

生成成功状态必须是以下之一：

```json
["succeeded", "success", "completed", "done"]
```

保存规则：

```text
data/products/<platform>/<product_id>/wearing_image_attempt_<n>.<suffix>
```

如果同一 attempt stem 已存在旧文件，会先删除旧文件再写新结果。

输出：

```json
{
  "wearing_image_result": {
    "status": "ok",
    "reason": "wearing_image_generated",
    "product_id": "...",
    "platform": "1688",
    "marked_main_image_path": ".../wearing_generation_inputs/01_main_image.jpg",
    "marked_size_reference_image_path": ".../wearing_generation_inputs/02_size_reference.jpg",
    "enroute_reference_image_path": "enroute-bestsellers/necklaces/short/02.jpg",
    "selected_model_profile": {
      "profile_key": "romantic_rebel_european",
      "name": "Romantic Rebel",
      "image_path": "data/model_profiles/romantic_rebel_european/model.jpg",
      "reason": "..."
    },
    "input_images": [
      ".../01_main_image.jpg",
      ".../02_size_reference.jpg",
      "data/model_profiles/romantic_rebel_european/model.jpg"
    ],
    "prompt": "...",
    "generated_image_path": "data/products/1688/<product_id>/wearing_image_attempt_1.png",
    "generated_image_url": "https://...",
    "image_generation": {
      "id": "task-id",
      "status": "succeeded",
      "progress": 100,
      "urls": ["https://..."],
      "error": ""
    },
    "attempt": 1
  },
  "wearing_generation_attempt": 1,
  "manual_review_decision": {}
}
```

写库规则：

- 生成成功后只写文件和 LangGraph state。
- 不立刻写入 `products.wearing_image`。
- 只有人工 approve 后才把 `generated_image_path` 写入数据库。

失败规则：

- 缺少已编排 prompt 或输入图片时返回 skipped。
- 输入图片文件缺失时抛出 `FileNotFoundError`。
- 图片生成接口异常或返回失败状态时抛出异常。
- 这些异常不会自动把商品标记为 failed。

### 4.9 wait_manual_review：人工审核 interrupt

阶段目标：

- 把生成图、输入图、Enroute 参考、模特 profile 和 prompt 提交给人工审核。
- 通过 LangGraph `interrupt()` 暂停工作流。
- 根据 resume payload 归一化审核动作。

输入：

```json
{
  "selected_product": {},
  "wearing_image_result": {
    "status": "ok",
    "generated_image_path": "...",
    "generated_image_url": "...",
    "marked_main_image_path": "...",
    "marked_size_reference_image_path": "...",
    "enroute_reference_image_path": "...",
    "selected_model_profile": {},
    "prompt": "..."
  },
  "wearing_generation_attempt": 1
}
```

interrupt payload：

```json
{
  "type": "wearing_image_review",
  "product": {},
  "generated_image_path": "data/products/1688/<product_id>/wearing_image_attempt_1.png",
  "generated_image_url": "https://...",
  "marked_main_image_path": ".../01_main_image.jpg",
  "marked_size_reference_image_path": ".../02_size_reference.jpg",
  "enroute_reference_image_path": "enroute-bestsellers/necklaces/short/02.jpg",
  "selected_model_profile": {},
  "prompt": "...",
  "attempt": 1,
  "options": ["approve", "regenerate", "reject"]
}
```

resume 输入：

```json
{"action": "approve", "reason": ""}
```

也支持传字符串或空值，最终都会归一化成：

```json
{
  "action": "approve",
  "reason": ""
}
```

如果 `wearing_image_result.status != "ok"`，节点不会 interrupt，而是返回：

```json
{
  "manual_review_request": {
    "status": "skipped",
    "reason": "wearing_image_not_ready"
  },
  "manual_review_decision": {
    "action": "reject",
    "reason": "wearing_image_not_ready"
  }
}
```

### 4.10 人工审核路由与最终写库

路由算法：

```python
action = manual_review_decision.action.lower()

if action == "approve":
    branch = "build_listing_drafts"
elif action == "regenerate":
    if wearing_generation_attempt < MAX_WEARING_REGENERATE_ATTEMPTS:
        branch = "generate_wearing_image"
    else:
        branch = "mark_failed_and_reload_candidates"
elif action == "reject":
    branch = "mark_failed_and_reload_candidates"
else:
    branch = "mark_failed_and_reload_candidates"
```

当前最大重生成次数：

```python
MAX_WEARING_REGENERATE_ATTEMPTS = 3
```

approve 写库规则：

```python
if manual_review_decision.action == "approve":
    require wearing_image_result.generated_image_path
    update products set:
      status = "done"
      wearing_image = generated_image_path
      locked_at = NULL
      locked_by = NULL
```

approve 输出：

```json
{
  "approved_product": {
    "product_id": "...",
    "platform": "1688",
    "status": "done",
    "wearing_image": "data/products/1688/<product_id>/wearing_image_attempt_1.png"
  }
}
```

reject 或重生成超限写库规则：

```python
update products set:
  status = "failed"
  locked_at = NULL
  locked_by = NULL
```

失败输出：

```json
{
  "failed_product": {
    "product_id": "...",
    "platform": "1688",
    "status": "failed",
    "reason": "人工拒绝"
  },
  "candidates": [],
  "selected_product": {},
  "manual_review_request": {},
  "manual_review_decision": {},
  "wearing_image_result": {},
  "wearing_generation_attempt": 0
}
```

然后回到 `load_candidates`，继续处理下一个商品。

## 5. AI checkpoint 与持久化锁

当前系统有两层避免重复调用外部 AI 的机制。

### 5.1 LangGraph state 级 checkpoint

位置：`state["ai_checkpoints"]`

用途：

- 在同一 thread / checkpoint resume 场景下复用已经完成的 LLM 或图片 AI 结果。
- 避免节点重入时重复调用外部服务。

checkpoint 结构：

```json
{
  "key": "detect_size_reference",
  "type": "llm",
  "source": "llm",
  "input": {
    "product": {},
    "collage_path": "...",
    "_runtime": {
      "prompts": {},
      "model": "gpt-5.5",
      "providers": {}
    }
  },
  "input_hash": "sha256...",
  "status": "ok",
  "result": {},
  "attempt_count": 1
}
```

复用条件：

- checkpoint key 相同。
- 当前 input 的 stable hash 与历史 `input_hash` 相同。
- checkpoint 自身 `status` 不是 `failed` 或 `error`。
- checkpoint result 的 `status` 也不是 `failed` 或 `error`。

input hash 包含运行时指纹：

- 当前 prompt manifest。
- 当前模型名。
- 当前 LLM provider 指纹。

因此 prompt、模型或 provider 变更会自动让旧 checkpoint 失效。

当前关键 checkpoint keys：

- `detect_size_reference`
- `select_wearing_style_profile`
- `compile_wearing_generation_prompt`
- `generate_wearing_image_attempt_<n>`

### 5.2 SQLite `ai_call_locks` 持久化锁

位置：SQLite `ai_call_locks` 表。

用途：

- 跨进程或跨请求避免同一个外部 AI 调用重复执行。
- 等待其他 worker 已经在跑的同请求。
- 复用已成功结果。
- 接管失败或陈旧的 in-progress 锁。

稳定 key：

```python
call_key = f"{call_type}:{sha256(json.dumps(request, sort_keys=True))}"
```

状态机：

```text
missing -> acquire -> in_progress
in_progress -> succeeded
in_progress -> failed
failed -> reclaim -> in_progress
stale in_progress -> reclaim -> in_progress
succeeded -> direct reuse
```

等待规则：

- 如果已有 `succeeded`，直接把 `result_json` 转回业务结果。
- 如果已有 `in_progress`，按配置轮询等待。
- 如果等待超时仍未完成，抛出 `AICallInProgressError`。
- 如果锁已经失败，按 acquire 规则可被下一次调用接管重试。

当前使用位置：

- Responses streaming LLM 解析调用。
- 图片生成组件也可通过 `database_path` 使用持久化锁。

## 6. 日志规则

每次工作流运行会创建中文可读日志，默认目录：

```text
workflow-logs/
```

日志路径初始是临时运行日志；选中商品后重命名为：

```text
workflow-logs/<product_name>__<platform>__<product_id>.log
```

日志应记录：

- `workflow_start`
- 每个节点的 `node_start` / `node_end`
- interrupt 的 `node_interrupt`
- 异常的 `node_error`
- 条件边的 `branch_decision`
- LLM 请求、原始响应、解析输出和错误
- 图片 AI 请求参数、输入图片和原始响应
- 关键判断字段，如 `status`、`reason`、`cache`、`is_product_qualified`、`failed_checks`、`can_judge_size`、图片编号、选中模特、Enroute 参考路径

日志是调试产物，不写入数据库，不纳入 Git。

候选商品日志摘要规则：

- 记录候选数量、产品 ID、平台、标题、状态、锁信息和 rawdata 字段名。
- 不记录完整 rawdata。

## 7. 失败边界与业务数据保护

工作流区分“业务决策失败”和“系统异常”。

会写业务失败的情况：

- 人工审核 `reject`。
- 人工 `regenerate` 已达到最大 attempt 上限。
- `wait_manual_review` 发现佩戴图没准备好，并归一化为 reject 分支。

不会自动写业务失败的情况：

- 主图全部下载失败。
- 产品合格性检测 LLM 调用失败。
- 产品合格性检测 LLM 输出不可解析。
- Enroute 选择返回了缓存中不存在的 product_id。
- 图片生成接口异常。
- 图片生成返回失败状态。
- 输入图片文件缺失。

这些系统异常会让节点抛错并停止当前执行，保留现场用于排查。不要为了“跑通”而手动 approve/reject/regenerate 真实 review thread，除非明确收到针对该数据操作的指令。

## 8. 关键算法伪代码汇总

### 8.1 默认选品算法

```python
def select_product():
    products = load_unfinished_products(
        status_not_in=["done", "completed", "published", "failed"],
        locked_at_is_null=True,
    )
    random.shuffle(products)
    for product in products:
        if not has_platform_adapter(product.platform):
            continue
        adapter = get_platform_adapter(product.platform)
        if hasattr(adapter, "can_handle") and not adapter.can_handle(product):
            continue
        locked = lock_product(product, status="processing")
        if locked:
            return locked
    return None
```

### 8.2 Enroute 类目推断算法

```python
def infer_category(candidate):
    text = normalize(candidate.product_id, candidate.platform, rawdata fields)
    scores = {
        category: count(term in text for term in terms)
        for category, terms in category_terms.items()
    }
    category, score = max(scores.items(), key=lambda x: x[1])
    return category if score > 0 else None
```

### 8.3 Enroute 学习规划算法

```python
def plan_enroute_learning(category):
    references = learning_reference_rows_by_category(category)
    cached = valid_cache_rows(category)
    unlearned = [row for row in references if row.enroute_product_id not in cached.ids]
    batch_size = 5 if len(cached) < 5 else 1
    return unlearned[:batch_size]
```

### 8.4 风格 profile 与模特 profile 选择算法

```python
def select_wearing_style_profile(main_image, size_reference_image, category):
    cached = valid_cache_rows(category)
    enroute_summaries = [
        {"enroute_product_id": row.id, "summary": row.summary}
        for row in cached
    ]
    model_profiles = load_model_profiles(database_path)
    model_summaries = [
        {"profile_key": row.profile_key, "summary": row.summary}
        for row in model_profiles
    ]
    selection = llm_select(
        main_image=main_image,
        size_reference_image=size_reference_image,
        enroute_summaries=enroute_summaries,
        model_summaries=model_summaries,
        rule="choose one enroute_product_id and one model profile_key",
    )
    selected = find(cached, id=selection.selected_enroute_product_id)
    selected_model = find(model_profiles, key=selection.selected_model_profile_key)
    if not selected or not selected_model:
        raise ValueError
    return selected, selected_model
```

### 8.5 生图 prompt 编排算法

```python
def compile_generation_prompt(size_reference_result, selected_enroute, selected_model):
    input_images = [
        mark_image(size_reference_result.main_image, "01 主图"),
        mark_image(size_reference_result.size_reference_image, "02 尺寸参考图"),
        selected_model.image_path,
    ]
    prompt = llm_compile_prompt(
        input_images=input_images,
        enroute_profile=selected_enroute.analysis_json,
        model_profile=selected_model,
        selection_reason=selection.reason,
    )
    return {"prompt": prompt, "input_images": input_images}
```

### 8.6 佩戴图 attempt 与审核路由算法

```python
def route_review(action, attempt):
    if action == "approve":
        persist_done_and_wearing_image()
        return END

    if action == "regenerate" and attempt < 3:
        return generate_wearing_image(attempt + 1)

    mark_failed_and_unlock()
    return load_next_candidate()
```

## 9. 修改工作流时的维护规则

1. 修改节点输入输出时，同步更新本文档的对应 JSON 示例。
2. 修改 prompt、模型或 provider 相关逻辑时，确认 checkpoint input 是否已经包含足够的运行时指纹。
3. 修改 Enroute 逆向 JSON schema 时，区分 prompt 期望字段、Pydantic 解析字段和工作流实际消费字段。
4. 新增真实商品字段前，先判断它是不是临时流程数据；临时数据优先放 state、extra 或专用缓存表。
5. 新增外部 AI 调用时，必须记录原始输入/输出，并考虑是否需要 state checkpoint 和 SQLite `ai_call_locks`。
6. 修改人工审核动作时，必须同步更新 `manual_review.py` payload、路由逻辑、控制台 UI 和测试。
7. 不要让系统异常自动改写业务状态；只有明确业务决策才写 `done` 或 `failed`。
