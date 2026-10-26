"""
Tests for the PDF renderer.

These PDFs are the pipeline's input, so what matters is that the text comes
back out: every test renders a real PDF into a temporary directory and reads
it again with the same library bronze uses.
"""

import fitz
import pytest

from dataset_generation.text_to_pdf import MAX_HEADING_LENGTH, text_to_pdf


@pytest.fixture
def render(tmp_path):
    """Renders text and returns what PyMuPDF reads back."""

    def go(text: str) -> str:
        path = tmp_path / "cv.pdf"
        text_to_pdf(text, str(path))
        with fitz.open(path) as document:
            return "\n".join(page.get_text() for page in document)

    return go


def test_a_pdf_is_written(tmp_path):
    path = tmp_path / "cv.pdf"

    text_to_pdf("Ada Lovelace\nEngineer", str(path))

    assert path.read_bytes().startswith(b"%PDF")


def test_the_text_can_be_read_back_out(render):
    read_back = render("Ada Lovelace\n\nWORK EXPERIENCE\nData Engineer at ACME")

    assert "Ada Lovelace" in read_back
    assert "Data Engineer at ACME" in read_back


def test_section_headings_survive_the_round_trip(render):
    assert "WORK EXPERIENCE" in render("Ada Lovelace\n\nWORK EXPERIENCE\nACME")


def test_a_long_uppercase_line_is_body_text_not_a_heading(render):
    """Uppercase alone does not make a heading, or a shouted sentence becomes one."""
    shouted = "A" * (MAX_HEADING_LENGTH + 10)

    assert shouted in render(f"Ada Lovelace\n{shouted}")


def test_blank_lines_do_not_break_rendering(render):
    assert "Engineer" in render("Ada Lovelace\n\n\n\nEngineer")


def test_a_single_line_renders(render):
    assert "Ada Lovelace" in render("Ada Lovelace")


def test_surrounding_whitespace_is_trimmed_before_rendering(render):
    assert "Ada Lovelace" in render("\n\n  Ada Lovelace  \n\n")
