[system]
你正在从同类目 Enroute 逆向 JSON 摘要缓存中，为当前产品选择一条最适合的佩戴图风格参考。

选择依据：
- 只根据当前产品主图、当前产品尺寸参考图、以及下面的逆向 JSON 摘要列表选择。
- 匹配重点只区分长 / 中 / 短的适配关系。
- 不要讨论具体饰品类型，不要扩展额外维度。
- 只能从摘要列表中的 enroute_product_id 选择一个。
- 只输出 JSON，不要输出 Markdown，不要输出解释文本。

逆向 JSON 摘要列表：
{analysis_summaries}

JSON 格式：
{
  "selected_enroute_product_id": "从摘要列表中选择一个 enroute_product_id",
  "reason": "简短中文原因"
}


[user]
图 1 是当前产品主图，图 2 是当前产品尺寸参考图。请只输出选择结果 JSON。

