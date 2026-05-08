---
doc_type: requirement
slug: office-parsing
pitch: 把 Word、PPT、Excel 文件直接转成 Markdown，不用先导出 PDF
status: current
last_reviewed: 2026-05-07
implemented_by:
  - ARCHITECTURE
tags: [office, docx, pptx, xlsx, markdown]
---

# Office 文档直接转 Markdown

## 用户故事

- 作为一个写技术文档的人，我希望把 Word 文档直接转成 Markdown 发到博客，而不是先转 PDF 再解析一遍绕远路。
- 作为一个做数据分析的人，我希望 Excel 表格能变成 Markdown 表格或 CSV，而不是截图再 OCR。
- 作为一个做演示文稿的人，我希望 PPT 里的文字和图片能提取出来复用，而不是一页页截图。

## 为什么需要

Office 文件有自己的格式和结构（段落、标题层级、表格、文本框），走"导出 PDF → 再解析 PDF"这条路会丢掉文档原本的结构信息——标题层级变平了、表格变成散落文字、图片位置跑了。直接用格式库读 Office 原文件，拿到的结构更准、速度也更快。

## 怎么解决

识别文件后缀后走专门的 Office 转换路径，用文档格式库直接读取原始结构，提取文本、表格、图片，按原层级拼成 Markdown。表格特殊处理成 Markdown 表格格式，图片提取为独立文件后 Markdown 里用相对路径引用。

## 边界

- 只管 DOCX、PPTX、XLSX，不管旧格式（.doc / .ppt / .xls）。
- 不追求版式精确还原——Markdown 本身限制，复杂排版（多栏、嵌入图表、动画）会损失或丢失。
- XLSX 里公式不计算，只提取显示值。
- PPT 里的 SmartArt、嵌入视频、动画效果不在处理范围。
- 不保证高度定制模板的 Office 文件（如用宏生成的复杂表格）。
