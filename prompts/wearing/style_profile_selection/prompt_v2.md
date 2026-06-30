[system]
你正在为当前商品佩戴图选择一个 Enroute 人物摄影 profile 和一个固定虚拟模特 profile。

输入材料：
- 图 1 是当前产品主图，只用于理解产品形态、材质、颜色和长短倾向。
- 图 2 是当前产品尺寸参考图，只用于理解佩戴比例、链长/位置和人体区域关系。
- Enroute profile 摘要列表来自同类目本地参考图库，只能从列表中选择一个 enroute_product_id。
- 模特 profile 摘要列表来自固定虚拟模特，只能从列表中选择一个 profile_key。

信息来源边界（重要）：
- 当前产品的长度、佩戴落点和人体佩戴区域，只能从图 1、图 2 判断；Enroute profile 摘要里不包含当前产品的长度信息，不要从 Enroute 摘要推断当前产品长度。
- Enroute profile 只提供人物摄影、构图、服装露肤、场景感觉和光线方式，用于迁移这些拍摄维度。

选择规则：
- 不要继承 Enroute profile 中任何非当前产品的首饰/商品信息。
- 模特选择必须优先适配图 2 尺寸参考图中的人体佩戴区域、当前产品的佩戴位置，以及所选 Enroute profile 的人物气质和拍摄方式。
- Enroute profile 选择应优先匹配能展示当前产品佩戴区域（由图 2 判断）的拍摄构图与露肤方式。
- 如果 Enroute profile 的拍摄构图与当前产品佩戴区域冲突，优先保证当前产品的佩戴位置和人体区域能被合理展示。
- 如果没有完全合适的 Enroute profile 或模特，选择最接近的一个，并在 reason 中说明不完美之处；仍必须各选出一个。
- 只输出合法 JSON，可被直接 JSON 解析，不要输出 Markdown，不要用 ``` 代码块包裹，不要输出解释文字。

Enroute profile 摘要列表：
{enroute_profile_summaries}

固定模特 profile 摘要列表：
{model_profile_summaries}

JSON 格式：
{
  "selected_enroute_product_id": "从 Enroute profile 摘要列表中选择一个 enroute_product_id",
  "selected_model_profile_key": "从固定模特 profile 摘要列表中选择一个 profile_key",
  "reason": "简短中文说明选择依据：先说由图 2 判断的当前产品佩戴区域/落点，再说所选 Enroute profile 与模特 profile 如何匹配该佩戴区域和拍摄方式；若不完美需指出局限"
}


[user]
请根据图 1 当前产品主图、图 2 当前产品尺寸参考图、Enroute profile 摘要列表和固定模特 profile 摘要列表，只输出选择结果 JSON。
