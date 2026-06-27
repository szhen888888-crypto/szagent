你正在检查一张由多张商品图合并成的编号拼图。每张子图左上角有白色数字编号。

任务：
1. 判断是否存在可以通过人体参照判断产品尺寸、比例或佩戴效果的子图。
2. 返回一个最适合作为尺寸参考图的子图编号：优先选择模特佩戴、人体局部、手、脖子、耳朵、手腕等参照最清楚的图。
3. 返回一个与该尺寸参考图对应的产品主图编号：优先选择同一产品的纯产品图、PDP 封面图、干净背景、结构/材质/颜色清楚的图，不要选择人体佩戴图作为主图，除非没有纯产品图。
4. image_numbers 返回所有能用于尺寸/比例判断的子图编号。
5. 如果没有人体、手、脖子、耳朵、手腕、模特佩戴等参照，则 can_judge_size=false、image_numbers=[]、size_reference_image_number=null；仍然尽量返回 main_image_number。
6. 只输出 JSON，不要输出 Markdown。

JSON 格式：
{
  "can_judge_size": true,
  "image_numbers": [1, 3],
  "size_reference_image_number": 1,
  "main_image_number": 2,
  "reason": "简短中文原因"
}
