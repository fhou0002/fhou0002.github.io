#!/usr/bin/env python3
"""
文档翻译对照工具 - 本地 Web UI

上传英文 TXT / Word / PDF 文档，自动翻译为中文，并以左右对照的
形式展示；鼠标悬停在任意一句原文上时，右侧对应的译文会高亮联动。

运行方式:
    pip install -r requirements.txt
    python translator.py
    浏览器打开 http://127.0.0.1:5001
"""

import os
import re
import uuid
import traceback
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request

import docx
import pdfplumber

try:
    from deep_translator import GoogleTranslator
    _HAS_TRANSLATOR = True
except ImportError:
    _HAS_TRANSLATOR = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf"}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# doc_id -> {"path", "ext", "name"}; process runs single-user/local so an
# in-memory dict is enough (no database needed for a local tool).
_DOCS: Dict[str, Dict[str, str]] = {}


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "e.g", "i.e",
    "fig", "eq", "no", "vol", "pp", "st", "u.s", "u.k", "inc", "ltd", "co",
}

# Split after a sentence terminator followed by whitespace and what looks
# like the start of a new sentence (capital letter, digit, or a quote).
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9"\'(])')


def split_sentences(paragraph: str) -> List[str]:
    """Split an English paragraph into sentences.

    There's no NLP dependency available, so this uses a regex heuristic and
    re-joins splits that landed right after a known abbreviation (e.g. "Dr.").
    """
    paragraph = paragraph.strip()
    if not paragraph:
        return []

    raw_parts = _SENTENCE_SPLIT_RE.split(paragraph)
    sentences: List[str] = []
    for part in raw_parts:
        if sentences:
            prev = sentences[-1]
            trailing = re.findall(r'([A-Za-z][A-Za-z.]*)\.$', prev)
            if trailing and trailing[0].lower().rstrip('.') in _ABBREVIATIONS:
                sentences[-1] = prev + " " + part
                continue
        sentences.append(part)
    return [s.strip() for s in sentences if s.strip()]


# ---------------------------------------------------------------------------
# Document readers
# ---------------------------------------------------------------------------

def read_txt(file_path: str) -> List[str]:
    """Read a plain text file, split into paragraphs on blank lines."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in raw.splitlines() if line.strip()]
    return paragraphs


def read_docx(file_path: str) -> List[str]:
    """Read a Word document's paragraphs in document order."""
    document = docx.Document(file_path)
    return [p.text.strip() for p in document.paragraphs if p.text.strip()]


def read_pdf(file_path: str, layout: str = "auto") -> List[str]:
    """Extract paragraphs from a PDF, column-layout aware.

    Naively concatenating PyPDF2-style extraction on a two-column PDF
    interleaves lines from both columns. Here words are read with their
    positions (pdfplumber), clustered into a left/right column by
    x-position when the page looks two-column, and each column is read
    top-to-bottom, left column first, before the next column.
    """
    paragraphs: List[str] = []

    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if not words:
                continue

            page_layout = layout
            if page_layout == "auto":
                page_layout = _detect_columns(words, page.width)

            if page_layout == "two_columns":
                mid = page.width / 2
                left = [w for w in words if (w["x0"] + w["x1"]) / 2 < mid]
                right = [w for w in words if (w["x0"] + w["x1"]) / 2 >= mid]
                paragraphs.extend(_words_to_paragraphs(left))
                paragraphs.extend(_words_to_paragraphs(right))
            else:
                paragraphs.extend(_words_to_paragraphs(words))

    return paragraphs


def _detect_columns(words: List[Dict[str, Any]], page_width: float) -> str:
    """Heuristic: treat the page as two columns if there's a mostly-empty
    vertical band around the horizontal middle that text rarely crosses."""
    if len(words) < 20:
        return "one_column"

    mid = page_width / 2
    band = page_width * 0.04
    straddling = [w for w in words if w["x0"] < mid + band and w["x1"] > mid - band]
    left_count = sum(1 for w in words if (w["x0"] + w["x1"]) / 2 < mid)
    right_count = sum(1 for w in words if (w["x0"] + w["x1"]) / 2 >= mid)

    if left_count > 5 and right_count > 5 and len(straddling) < 0.05 * len(words):
        return "two_columns"
    return "one_column"


def _words_to_paragraphs(words: List[Dict[str, Any]]) -> List[str]:
    """Group words (already restricted to one column) into lines by
    vertical position, then lines into paragraphs by vertical gap size."""
    if not words:
        return []

    words = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))

    lines: List[Dict[str, Any]] = []
    current_line: List[Dict[str, Any]] = []
    current_top: Optional[float] = None

    for w in words:
        if current_top is None or abs(w["top"] - current_top) <= 3:
            current_line.append(w)
            current_top = current_top if current_top is not None else w["top"]
        else:
            lines.append({"top": current_top, "words": current_line})
            current_line = [w]
            current_top = w["top"]
    if current_line:
        lines.append({"top": current_top, "words": current_line})

    for line in lines:
        line["words"].sort(key=lambda w: w["x0"])
        line["text"] = " ".join(w["text"] for w in line["words"])

    if len(lines) < 2:
        return [l["text"] for l in lines]

    gaps = [lines[i + 1]["top"] - lines[i]["top"] for i in range(len(lines) - 1)]
    median_gap = sorted(gaps)[len(gaps) // 2] or 1.0

    paragraphs: List[str] = []
    buffer = [lines[0]["text"]]
    for i in range(1, len(lines)):
        if gaps[i - 1] > median_gap * 1.6:
            paragraphs.append(" ".join(buffer))
            buffer = [lines[i]["text"]]
        else:
            buffer.append(lines[i]["text"])
    if buffer:
        paragraphs.append(" ".join(buffer))

    return [p.strip() for p in paragraphs if p.strip()]


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

# Tiny offline fallback so the tool still produces *something* when there's
# no network access (deep-translator needs to reach Google Translate).
_FALLBACK_DICT = {
    "the": "这", "is": "是", "a": "一个", "an": "一个", "and": "和", "or": "或",
    "for": "为了", "with": "与", "this": "这个", "that": "那个",
    "document": "文档", "translation": "翻译", "example": "示例", "test": "测试",
    "system": "系统", "data": "数据", "processing": "处理", "analysis": "分析",
    "report": "报告", "summary": "摘要", "introduction": "介绍",
    "conclusion": "结论", "method": "方法", "result": "结果",
    "discussion": "讨论", "reference": "参考", "appendix": "附录",
    "table": "表格", "figure": "图表", "section": "章节", "chapter": "章",
}


def _fallback_translate(text: str) -> str:
    words = text.split()
    out = []
    for w in words:
        clean = w.strip('.,;:!?()[]{}"\'').lower()
        out.append(_FALLBACK_DICT.get(clean, w))
    return " ".join(out) + "（离线占位翻译，未检测到网络翻译服务）"


def translate_batch(sentences: List[str], target_lang: str = "zh-CN") -> List[str]:
    if not sentences:
        return []

    if _HAS_TRANSLATOR:
        try:
            translator = GoogleTranslator(source="en", target=target_lang)
            results = []
            # deep-translator's batch endpoint has an input-size limit, so
            # sentences are sent in modest chunks rather than all at once.
            chunk_size = 50
            for i in range(0, len(sentences), chunk_size):
                chunk = sentences[i:i + chunk_size]
                results.extend(translator.translate_batch(chunk))
            return results
        except Exception as e:
            print(f"在线翻译失败，使用离线占位翻译: {e}")

    return [_fallback_translate(s) for s in sentences]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def process_document(file_path: str, ext: str, layout: str = "auto",
                      target_lang: str = "zh-CN") -> Dict[str, Any]:
    if ext == ".pdf":
        paragraphs = read_pdf(file_path, layout)
    elif ext == ".docx":
        paragraphs = read_docx(file_path)
    elif ext in (".txt", ".md"):
        paragraphs = read_txt(file_path)
    else:
        raise ValueError(f"不支持的文件类型: {ext}")

    if not paragraphs:
        raise ValueError("文档内容为空或无法解析")

    all_sentences: List[str] = []
    para_sentence_counts: List[int] = []
    for para in paragraphs:
        sentences = split_sentences(para)
        if not sentences:
            continue
        all_sentences.extend(sentences)
        para_sentence_counts.append(len(sentences))

    translations = translate_batch(all_sentences, target_lang)

    result_paragraphs = []
    idx = 0
    sent_id = 0
    for count in para_sentence_counts:
        sentences = []
        for _ in range(count):
            sentences.append({
                "id": sent_id,
                "en": all_sentences[idx],
                "zh": translations[idx] if idx < len(translations) else "",
            })
            idx += 1
            sent_id += 1
        result_paragraphs.append({"sentences": sentences})

    return {"paragraphs": result_paragraphs, "sentence_count": sent_id}


# ---------------------------------------------------------------------------
# Web app
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "未收到文件"}), 400

    f = request.files["file"]
    if f.filename == "":
        return jsonify({"error": "文件名为空"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"不支持的文件类型: {ext}"}), 400

    doc_id = uuid.uuid4().hex
    saved_path = os.path.join(UPLOAD_DIR, f"{doc_id}{ext}")
    f.save(saved_path)

    _DOCS[doc_id] = {"path": saved_path, "ext": ext, "name": f.filename}
    return jsonify({"doc_id": doc_id, "filename": f.filename})


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(force=True, silent=True) or {}
    doc_id = data.get("doc_id")
    layout = data.get("layout", "auto")
    target_lang = data.get("target_language", "zh-CN")

    doc = _DOCS.get(doc_id)
    if not doc:
        return jsonify({"error": "未找到已上传的文档，请重新上传"}), 404

    try:
        result = process_document(doc["path"], doc["ext"], layout, target_lang)
        result["filename"] = doc["name"]
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


def main():
    port = int(os.environ.get("PORT", 5001))
    print(f"文档翻译工具已启动: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)


if __name__ == "__main__":
    main()
