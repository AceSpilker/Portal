"""知识库 Office 预览转换（091）：docx/xlsx/pptx → HTML（服务端转换，前端直出）。

- docx：mammoth 语义转换（标题/列表/表格/图片内联 base64）；
- xlsx：openpyxl 逐 sheet 输出 HTML 表格（值显示，公式取缓存结果）；
- pptx：python-pptx 提取每页文本大纲（形状文本按位置排序）。
只读预览——Office 在线编辑不在本模块范围（文本/Markdown 类才可编辑）。
"""

from __future__ import annotations

from pathlib import Path

_STYLE = (
    "<style>.kb-xlsx table{border-collapse:collapse;margin:8px 0}"
    ".kb-xlsx td,.kb-xlsx th{border:1px solid #ccc;padding:4px 8px;font-size:13px}"
    ".kb-pptx section{border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin:10px 0}"
    ".kb-pptx h3{margin:4px 0}</style>"
)


def docx_to_html(path: Path) -> str:
    import mammoth

    with path.open("rb") as f:
        result = mammoth.convert_to_html(f)
    return result.value


def xlsx_to_html(path: Path) -> str:
    import html as _html

    from openpyxl import load_workbook

    wb = load_workbook(path, data_only=True, read_only=True)
    parts = ['<div class="kb-xlsx">']
    for ws in wb.worksheets:
        parts.append(f"<h4>{_html.escape(ws.title)}</h4><table>")
        for row in ws.iter_rows(max_row=500, max_col=40, values_only=True):
            parts.append("<tr>" + "".join(
                f"<td>{_html.escape('' if v is None else str(v))}</td>" for v in row
            ) + "</tr>")
        parts.append("</table>")
    wb.close()
    parts.append("</div>")
    return "".join(parts)


def pptx_to_html(path: Path) -> str:
    import html as _html

    from pptx import Presentation

    prs = Presentation(str(path))
    parts = ['<div class="kb-pptx">']
    for i, slide in enumerate(prs.slides, 1):
        texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs).strip()
                    if t:
                        texts.append(t)
        body = "".join(
            f"<p>{_html.escape(t)}</p>" if j else f"<h3>{_html.escape(t)}</h3>"
            for j, t in enumerate(texts[:20])
        )
        parts.append(f"<section><h4># {i}</h4>{body or '<p><em>(empty)</em></p>'}</section>")
    parts.append("</div>")
    return "".join(parts)


def office_to_html(path: Path, ext: str) -> str:
    """入口：按扩展名分发；转换失败抛异常由端点层转错误提示。"""
    converters = {".docx": docx_to_html, ".xlsx": xlsx_to_html, ".pptx": pptx_to_html}
    conv = converters.get(ext)
    if conv is None:
        raise ValueError(f"unsupported office ext: {ext}")
    html = conv(path)
    return _STYLE + html
