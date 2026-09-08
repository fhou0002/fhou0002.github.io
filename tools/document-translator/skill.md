# document_translator

## 基本信息
- **版本**: 2.0.0
- **描述**: 本地网页版英译中文档对照翻译工具。上传 TXT / Word / PDF 文档后自动翻译为中文，以左右对照视图展示，鼠标悬停逐句高亮联动
- **作者**: Skill Lab
- **标签**: translation, document, pdf, word, web-ui

## 功能概述
- 支持上传 `.txt`、`.md`、`.docx`、`.pdf` 格式的英文文档
- 自动识别 PDF 是单栏还是双栏排版（也可手动指定），双栏文档会先读完左栏、再读右栏，避免两栏文字交叉错行
- 点击"开始翻译"后，后端按句子切分原文并调用翻译引擎生成中文译文
- 结果以左右对照的形式展示：左侧原文（English），右侧译文（中文）
- 鼠标悬停在左侧任意一句英文上时，右侧对应译文自动高亮（反之亦然），并在目标句不在可见区域时自动滚动过去

## 使用方法
1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 启动本地服务：
   ```bash
   python translator.py
   ```
3. 浏览器打开 `http://127.0.0.1:5001`
4. 上传文档 → 选择原文版式（自动检测 / 单栏 / 双栏）→ 点击"开始翻译"

## 参数配置
### layout
- **类型**: string
- **可选值**: auto, one_column, two_columns
- **默认值**: auto
- **描述**: 原始文档的版式。`auto` 基于 PDF 每页文字的横向分布自动判断；两栏文档会先按左栏、后按右栏的顺序提取文字

### target_language
- **类型**: string
- **默认值**: zh-CN
- **描述**: 目标翻译语言代码，传给翻译引擎

## 接口说明
- `POST /api/upload`：以 `multipart/form-data` 上传文件（字段名 `file`），返回 `{ doc_id, filename }`
- `POST /api/translate`：传入 `{ doc_id, layout, target_language }`，返回按段落、句子对齐的原文/译文 JSON：
  ```json
  {
    "paragraphs": [
      { "sentences": [ { "id": 0, "en": "...", "zh": "..." } ] }
    ],
    "sentence_count": 42,
    "filename": "paper.pdf"
  }
  ```

## 执行配置
- **入口文件**: translator.py
- **启动方式**: 本地 Web 服务（Flask），默认端口 5001，可用环境变量 `PORT` 修改
- **超时时间**: 300
- **最大文件大小**: 50MB
- **依赖**: Flask, python-docx, pdfplumber, deep-translator（翻译需要联网调用 Google 翻译；无网络时会退化为离线占位翻译并给出提示）

## 触发条件（供智能体/技能框架识别）
### 关键词
翻译, translate, translation, 英文文档, english document, 中文, 对照, 双栏, 单栏

### 文件类型
.pdf, .docx, .txt, .md

### 匹配模式
翻译.*(文档|文件|pdf|word)
translate.*(document|file|pdf|word)
.*英文.*(翻译|中文)
