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
from reportlab.lib.enums import TA_LEFT
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
            "body",
            fontName="Helvetica",
            fontSize=size,
            leading=size * 1.30,
            spaceAfter=8,
            alignment=TA_LEFT,
            textColor=colors.HexColor("#243548"),
        ),
        "heading": ParagraphStyle(
            "heading",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            spaceBefore=8,
            spaceAfter=6,
            textColor=TEAL,
        ),
        "title": ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=19, leading=23, spaceAfter=12, textColor=NAVY
        ),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=4),
        "table": ParagraphStyle(
            "table",
            fontName="Helvetica",
            fontSize=max(9.1, size - 1),
            leading=max(11.3, size + 2),
            textColor=colors.HexColor("#243548"),
        ),
        "th": ParagraphStyle(
            "th",
            fontName="Helvetica-Bold",
            fontSize=max(9.1, size - 1),
            leading=max(11.3, size + 2),
            textColor=colors.white,
        ),
        "code": ParagraphStyle(
            "code",
            fontName="Courier",
            fontSize=min(10, size),
            leading=min(13.5, size * 1.3),
            spaceAfter=8,
            leftIndent=6,
            alignment=TA_LEFT,
        ),
    }


def blocks(page, size, width):
    s = styles(size)
    result = [Paragraph(page["title"], s["title"])]
    for block in page["blocks"]:
        kind = block["type"]
        if kind == "p":
            result.append(Paragraph(block["text"], s["body"]))
        elif kind == "callout":
            panel = Table([[Paragraph(block["text"], s["body"])]], colWidths=[width], hAlign="LEFT")
            panel.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EEF4F8")),
                        ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
                        ("LEFTPADDING", (0, 0), (-1, -1), 11),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
                        ("TOPPADDING", (0, 0), (-1, -1), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            result.extend([panel, Spacer(1, 10)])
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
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
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


def word_inline(paragraph, markup, size, font="Arial"):
    bold = False
    for part in re.split(r"(<b>|</b>|<br\s*/?>)", markup, flags=re.IGNORECASE):
        if part.lower() == "<b>":
            bold = True
        elif part.lower() == "</b>":
            bold = False
        elif re.fullmatch(r"<br\s*/?>", part, flags=re.IGNORECASE):
            paragraph.add_run().add_break()
        elif part:
            run = paragraph.add_run(plain(part))
            run.font.name = font
            run.font.size = Pt(size)
            run.bold = bold


def create_word(content, sizes, destination):
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.2677)
    section.page_height = Inches(11.6929)
    section.top_margin = Inches(0.58)
    section.bottom_margin = Inches(0.55)
    section.left_margin = section.right_margin = Inches(0.58)
    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(11.5)
    normal.paragraph_format.space_after = Pt(7)
    normal.paragraph_format.line_spacing = 1.15
    for name, point_size in (("Title", 24), ("Heading 1", 19), ("Heading 2", 13)):
        style = document.styles[name]
        style.font.name, style.font.size = "Arial", Pt(point_size)
        style.paragraph_format.space_before = Pt(0 if name != "Heading 2" else 8)
        style.paragraph_format.space_after = Pt(7)
    header = section.header.paragraphs[0]
    header.text = "AEGISBID OMEGA  |  CEP 1 TECHNICAL REPORT"
    header.runs[0].font.size = Pt(8)
    footer = section.footer.paragraphs[0]
    footer.text = f"{content['student_name']} | {content['roll_number']} | Page "
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    for index, (page, size) in enumerate(zip(content["pages"], sizes, strict=True)):
        if index:
            document.add_page_break()
        if index == 0:
            document.add_heading(content["title"], 0)
            document.add_paragraph(content["subtitle"])
            document.add_paragraph(f"Student: {content['student_name']}    Roll number: {content['roll_number']}")
        heading = document.add_heading(page["title"], 1)
        heading.runs[0].font.size = Pt(19)
        for block in page["blocks"]:
            kind = block["type"]
            if kind in ("p", "h", "code", "callout"):
                p = document.add_heading(plain(block["text"]), 2) if kind == "h" else document.add_paragraph()
                if kind == "h":
                    for run in p.runs:
                        run.font.name, run.font.size = "Arial", Pt(13)
                else:
                    word_inline(
                        p, block["text"], 10 if kind == "code" else size, "Courier New" if kind == "code" else "Arial"
                    )
                if kind == "callout":
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:fill"), "EEF4F8")
                    p._p.get_or_add_pPr().append(shade)
                p.paragraph_format.line_spacing = 1.15
                p.paragraph_format.space_after = Pt(7)
            elif kind == "table":
                table = document.add_table(rows=1, cols=len(block["headers"]))
                table.style = "Table Grid"
                table.autofit = False
                for column, fraction in zip(table.columns, block["widths"], strict=True):
                    column.width = Inches(7.1 * fraction)
                for cell, text in zip(table.rows[0].cells, block["headers"], strict=True):
                    cell.text = ""
                    word_inline(cell.paragraphs[0], text, 10.5)
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
                for row in block["rows"]:
                    for cell, text in zip(table.add_row().cells, row, strict=True):
                        cell.text = ""
                        word_inline(cell.paragraphs[0], text, 10.5)
                header_row = table.rows[0]
                repeat = OxmlElement("w:tblHeader")
                header_row._tr.get_or_add_trPr().append(repeat)
                for cell in header_row.cells:
                    shade = OxmlElement("w:shd")
                    shade.set(qn("w:fill"), "E5EEF4")
                    cell._tc.get_or_add_tcPr().append(shade)
                for row in table.rows:
                    for cell, fraction in zip(row.cells, block["widths"], strict=True):
                        cell.width = Inches(7.1 * fraction)
                        for paragraph in cell.paragraphs:
                            paragraph.paragraph_format.space_after = Pt(0)
                            for run in paragraph.runs:
                                run.font.name = "Arial"
                                run.font.size = Pt(10.5)
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
    document.core_properties.author = content["student_name"]
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
        diagram_page = diagram_pdf[0]
        bitmap = diagram_page.render()
        bitmap.to_pil().save(output / "AegisBid_Complete_System_Flow.png")
        bitmap.close()
        diagram_page.close()
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
                canvas.drawString(42, 22, f"{content['student_name']} | {content['roll_number']} | {content['date']}")

            path = Path(temporary) / f"page-{index}.pdf"
            for size in [11.5]:
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
                            f"Student: {content['student_name']}  |  Roll number: {content['roll_number']}",
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
                raise RuntimeError(f"Page {index + 1} overflowed; edit content to retain the fixed 11.5 pt body font")
        pdf = output / f"AegisBid_Technical_Report_{expected_pages}_Pages.pdf"
        writer.add_metadata(
            {
                "/Title": "AegisBid Omega | Technical report with full system flow",
                "/Subject": content["subtitle"],
                "/Author": content["student_name"],
            }
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
    student_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", content["student_name"]).strip("_")
    roll_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", content["roll_number"]).strip("_")
    stem = f"AegisBid_{student_slug}_{roll_slug}_Report"
    (output / (stem + ".pdf")).write_bytes(pdf.read_bytes())
    (output / (stem + ".docx")).write_bytes((output / "AegisBid_Technical_Report_Editable.docx").read_bytes())
    metadata = {
        "pdf_pages": expected_pages,
        "body_font_sizes_pt": sizes,
        "font_family": "Helvetica (PDF), Arial (Word)",
        "table_font_size_pt": 10.5,
        "automatic_font_shrinking": False,
        "source_commit": content["implementation_commit"],
        "student_name": content["student_name"],
        "roll_number": content["roll_number"],
        "words": sum(len(plain(b.get("text", "")).split()) for p in content["pages"] for b in p["blocks"]),
        "section_titles": [p["title"] for p in content["pages"]],
    }
    (output / "report-validation.json").write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
