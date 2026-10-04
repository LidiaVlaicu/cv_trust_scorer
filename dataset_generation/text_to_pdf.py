"""
Renders generated CV text as a PDF.

The layout matters more than it looks: these PDFs are the pipeline's input, so
how text is laid out here decides what PyMuPDF can read back out. Section
headings are detected by being short and uppercase, which is also how the
generated text marks them.
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

# A line is treated as a section heading if it is uppercase and shorter than
# this, which distinguishes "WORK EXPERIENCE" from an uppercase sentence.
MAX_HEADING_LENGTH = 40

_NAME_STYLE = ParagraphStyle(
    "Name", fontSize=16, fontName="Helvetica-Bold",
    spaceAfter=4, textColor=colors.HexColor("#1a1a1a"),
)
_BODY_STYLE = ParagraphStyle(
    "Body", fontSize=9.5, fontName="Helvetica",
    spaceAfter=4, leading=14, textColor=colors.HexColor("#333333"),
)
_SECTION_STYLE = ParagraphStyle(
    "Section", fontSize=10, fontName="Helvetica-Bold",
    spaceBefore=6, spaceAfter=2, textColor=colors.HexColor("#1a1a1a"),
)


def text_to_pdf(text: str, output_path: str) -> None:
    """Writes `text` to `output_path` as an A4 PDF, first line as the name."""
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        rightMargin=1.8 * cm, leftMargin=1.8 * cm,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )
    story = []
    for index, raw_line in enumerate(text.strip().split("\n")):
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 4))
        elif index == 0:
            story.append(Paragraph(line, _NAME_STYLE))
            story.append(HRFlowable(width="100%", thickness=0.5,
                                    color=colors.HexColor("#cccccc")))
        elif line.isupper() and len(line) < MAX_HEADING_LENGTH:
            story.append(Spacer(1, 4))
            story.append(Paragraph(line, _SECTION_STYLE))
            story.append(HRFlowable(width="100%", thickness=0.3,
                                    color=colors.HexColor("#dddddd")))
        else:
            story.append(Paragraph(line, _BODY_STYLE))
    doc.build(story)
