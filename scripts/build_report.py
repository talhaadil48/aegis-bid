"""Build the verified report with a complete system design page and Word companion."""

import json
import re
import tempfile
from html import unescape
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from pypdf import PdfReader, PdfWriter
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from scripts.system_diagram import system_design

ROOT = Path(__file__).resolve().parents[1]
NAVY = colors.HexColor("#16334D")
TEAL = colors.HexColor("#126C78")


def plain(text):
    return unescape(re.sub("<[^>]+>", "", text))


def flow(labels, width):
    drawing = Drawing(width, 47)
    gap = 10
    box = (width - gap * (len(labels) - 1)) / len(labels)
    for index, label in enumerate(labels):
        x = index * (box + gap)
        drawing.add(
            Rect(x, 7, box, 32, rx=4, ry=4, fillColor=colors.HexColor("#EAF3F5"), strokeColor=TEAL, strokeWidth=0.6)
        )
        words = label.split(" ")
        cut = max(1, len(words) // 2)
        for offset, line in enumerate([" ".join(words[:cut]), " ".join(words[cut:])]):
            drawing.add(
                String(
                    x + box / 2,
                    27 - offset * 10,
                    line,
                    textAnchor="middle",
                    fontName="Helvetica",
                    fontSize=8,
                    fillColor=NAVY,
                )
            )
        if index < len(labels) - 1:
            drawing.add(Line(x + box, 23, x + box + gap, 23, strokeColor=TEAL))
    return drawing


def styles(size):
    return {
        "body": ParagraphStyle(
            "body", fontName="Times-Roman", fontSize=size, leading=size * 1.18, spaceAfter=5, alignment=TA_JUSTIFY
        ),
        "heading": ParagraphStyle(
            "heading", fontName="Helvetica-Bold", fontSize=11.1, leading=13, spaceBefore=5, spaceAfter=5, textColor=TEAL
        ),
        "title": ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=17, leading=20, spaceAfter=10, textColor=NAVY
        ),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8.6, leading=10.2, spaceAfter=3),
        "table": ParagraphStyle(
            "table", fontName="Helvetica", fontSize=max(8.3, size - 0.9), leading=max(9.9, size + 0.1), wordWrap="CJK"
        ),
        "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=8.7, leading=10.1, textColor=colors.white),
        "code": ParagraphStyle(
            "code", fontName="Courier", fontSize=8.7, leading=10.4, spaceAfter=5, leftIndent=6, alignment=TA_LEFT
        ),
    }


def blocks(page, size, width):
    s = styles(size)
    result = [Paragraph(page["title"], s["title"])]
    for block in page["blocks"]:
        kind = block["type"]
        if kind == "p":
            result.append(Paragraph(block["text"], s["body"]))
        elif kind == "h":
            result.append(Paragraph(block["text"], s["heading"]))
        elif kind == "code":
            text = (
                block["text"]
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br/>")
                .replace("  ", "&#160;&#160;")
            )
            result.append(Paragraph(text, s["code"]))
        elif kind == "table":
            rows = [[Paragraph(value, s["th"]) for value in block["headers"]]]
            rows.extend([[Paragraph(value, s["table"]) for value in row] for row in block["rows"]])
            table = Table(rows, colWidths=[width * w for w in block["widths"]], hAlign="LEFT", repeatRows=1)
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F7")]),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD6DD")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            result.extend([table, Spacer(1, 7)])
        elif kind == "flow":
            result.append(flow(block["labels"], width))
        elif kind == "system_design":
            result.append(system_design(width))
        elif kind == "refs":
            for number, title, url in block["items"]:
                result.append(Paragraph(f'[{number}] <link href="{url}" color="#126C78">{title}</link>', s["small"]))
    return result


def create_word(content, sizes, destination):
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.2677)
    section.page_height = Inches(11.6929)
    section.top_margin = Inches(0.58)
    section.bottom_margin = Inches(0.55)
    section.left_margin = section.right_margin = Inches(0.58)
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(4)
    header = section.header.paragraphs[0]
    header.text = "AEGISBID OMEGA  |  CEP 1 TECHNICAL REPORT"
    header.runs[0].font.size = Pt(8)
    footer = section.footer.paragraphs[0]
    footer.text = "23 November 2026  |  Implementation + measured evidence  |  Page "
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    for index, (page, size) in enumerate(zip(content["pages"], sizes, strict=True)):
        if index:
            document.add_page_break()
        if index == 0:
            document.add_heading(content["title"], 0)
            document.add_paragraph(content["subtitle"])
            document.add_paragraph("Student: __________________________    Roll number: __________________")
        heading = document.add_heading(page["title"], 1)
        heading.runs[0].font.size = Pt(15)
        for block in page["blocks"]:
            kind = block["type"]
            if kind in ("p", "h", "code"):
                p = (
                    document.add_heading(plain(block["text"]), 2)
                    if kind == "h"
                    else document.add_paragraph(plain(block["text"]))
                )
                for run in p.runs:
                    run.font.name = "Courier New" if kind == "code" else ("Arial" if kind == "h" else "Times New Roman")
                    run.font.size = Pt(10.5 if kind == "h" else (8.5 if kind == "code" else size))
                p.paragraph_format.line_spacing = 1.0
                p.paragraph_format.space_after = Pt(4)
            elif kind == "table":
                table = document.add_table(rows=1, cols=len(block["headers"]))
                table.style = "Table Grid"
                for cell, text in zip(table.rows[0].cells, block["headers"], strict=True):
                    cell.text = text
                for row in block["rows"]:
                    for cell, text in zip(table.add_row().cells, row, strict=True):
                        cell.text = plain(text)
                for row in table.rows:
                    for cell, fraction in zip(row.cells, block["widths"], strict=True):
                        cell.width = Inches(7.1 * fraction)
                        for paragraph in cell.paragraphs:
                            paragraph.paragraph_format.space_after = Pt(0)
                            for run in paragraph.runs:
                                run.font.name = "Arial"
                                run.font.size = Pt(8.2)
            elif kind == "flow":
                document.add_paragraph("  >  ".join(block["labels"]))
            elif kind == "system_design":
                document.add_picture(str(destination.parent / "AegisBid_Complete_System_Flow.png"), width=Inches(7.0))
            elif kind == "refs":
                for number, title, url in block["items"]:
                    p = document.add_paragraph(f"[{number}] {title}: {url}")
                    for run in p.runs:
                        run.font.size = Pt(8)
    document.core_properties.title = content["title"] + " Technical Report"
    document.core_properties.subject = content["subtitle"]
    document.save(destination)


def main():
    content = json.loads((ROOT / "docs/report/report-content.json").read_text(encoding="utf-8"))
    output = ROOT / "docs/submission"
    output.mkdir(exist_ok=True)
    expected_pages = content["expected_pages"]
    if len(content["pages"]) != expected_pages:
        raise RuntimeError("Source page count does not match the declared report length")
    import pypdfium2
    from reportlab.graphics import renderPDF, renderSVG

    diagram = system_design(1058)
    renderSVG.drawToFile(diagram, str(output / "AegisBid_Complete_System_Flow.svg"))
    with pypdfium2.PdfDocument(renderPDF.drawToString(diagram)) as diagram_pdf:
        diagram_pdf[0].render().to_pil().save(output / "AegisBid_Complete_System_Flow.png")
    sizes = []
    writer = PdfWriter()
    with tempfile.TemporaryDirectory() as temporary:
        for index, page in enumerate(content["pages"]):

            def decorate(canvas, doc, page_index=index):
                canvas.setStrokeColor(TEAL)
                canvas.line(42, A4[1] - 28, A4[0] - 42, A4[1] - 28)
                canvas.setFont("Helvetica", 8)
                canvas.setFillColor(NAVY)
                canvas.drawString(42, A4[1] - 20, "AEGISBID OMEGA  |  CEP 1 TECHNICAL REPORT")
                canvas.drawRightString(A4[0] - 42, 22, f"{page_index + 1} / {expected_pages}")
                canvas.drawString(42, 22, "23 November 2026  |  Source baseline " + content["implementation_commit"])

            path = Path(temporary) / f"page-{index}.pdf"
            for attempt in range(9):
                size = 10.2 - attempt * 0.15
                story = blocks(page, size, A4[0] - 84)
                if index == 0:
                    top = [
                        Paragraph(
                            content["title"],
                            ParagraphStyle(
                                "cover",
                                fontName="Helvetica-Bold",
                                fontSize=23,
                                leading=25,
                                textColor=NAVY,
                                spaceAfter=4,
                            ),
                        ),
                        Paragraph(content["subtitle"], styles(size)["small"]),
                        Paragraph(
                            "Student: __________________________  |  Roll number: __________________",
                            styles(size)["small"],
                        ),
                        Spacer(1, 6),
                    ]
                    story = top + story
                document = SimpleDocTemplate(
                    str(path),
                    pagesize=A4,
                    leftMargin=42,
                    rightMargin=42,
                    topMargin=42,
                    bottomMargin=38,
                    title=content["title"],
                )
                document.build(story, onFirstPage=decorate, onLaterPages=decorate)
                pages = PdfReader(path)
                if len(pages.pages) == 1:
                    sizes.append(size)
                    writer.add_page(pages.pages[0])
                    break
            else:
                raise RuntimeError(f"Page {index + 1} overflowed; edit content rather than shrinking below 9 pt")
        pdf = output / f"AegisBid_Technical_Report_{expected_pages}_Pages.pdf"
        writer.add_metadata(
            {"/Title": "AegisBid Omega | Technical report with full system flow", "/Subject": content["subtitle"]}
        )
        with pdf.open("wb") as stream:
            writer.write(stream)
    checked = PdfReader(pdf)
    if len(checked.pages) != expected_pages:
        raise RuntimeError(f"Report must contain exactly {expected_pages} pages")
    for index, page in enumerate(content["pages"]):
        if page["title"] not in checked.pages[index].extract_text():
            raise RuntimeError("Report section is on the wrong page")
    create_word(content, sizes, output / "AegisBid_Technical_Report_Editable.docx")
    metadata = {
        "pdf_pages": expected_pages,
        "body_font_sizes_pt": sizes,
        "source_commit": content["implementation_commit"],
        "words": sum(len(plain(b.get("text", "")).split()) for p in content["pages"] for b in p["blocks"]),
        "section_titles": [p["title"] for p in content["pages"]],
    }
    (output / "report-validation.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
