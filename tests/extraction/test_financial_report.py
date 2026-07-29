import hashlib
from types import SimpleNamespace

import pytest

fitz = pytest.importorskip("fitz")

from company_quality.extraction.financial_report import (
    OcrObservation,
    PdfExtractionError,
    extract_pdf_pages,
)


class FakeOcr:
    def recognize(self, image):
        height, width = image.shape[:2]
        return (
            OcrObservation(
                text="關鍵查核事項：收入認列",
                confidence=0.95,
                polygon=((10, 20), (width - 10, 20), (width - 10, 60), (10, 60)),
            ),
        )


def _inventory(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return SimpleNamespace(
        pdf_path=path,
        pdf_sha256=digest,
        evidence_ids=(f"pdf:{digest}",),
        available_at="2026-02-26T17:23:30+08:00",
    )


def test_extracts_text_layer_with_page_and_normalized_coordinates(tmp_path) -> None:
    path = tmp_path / "report.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((72, 100), "Revenue recognition KAM")
    document.save(path)
    document.close()

    result = extract_pdf_pages(_inventory(path), page_numbers=(1,))

    assert result.status == "available"
    assert result.page_count == 1
    assert result.pages[0].page == 1
    assert result.pages[0].method == "text_layer"
    assert "Revenue recognition KAM" in result.pages[0].text
    block = result.pages[0].blocks[0]
    assert block.evidence_id.startswith(f"pdf:{result.pdf_sha256}:page:1:block:")
    assert all(0 <= value <= 1 for value in block.coordinate)
    assert block.available_at == "2026-02-26T17:23:30+08:00"


def test_uses_ocr_only_when_page_has_no_text_layer(tmp_path) -> None:
    path = tmp_path / "scanned.pdf"
    document = fitz.open()
    document.new_page(width=600, height=800)
    document.save(path)
    document.close()

    result = extract_pdf_pages(_inventory(path), page_numbers=(1,), ocr=FakeOcr())

    assert result.pages[0].method == "rapidocr"
    assert result.pages[0].text == "關鍵查核事項：收入認列"
    assert result.pages[0].blocks[0].confidence == pytest.approx(0.95)


def test_hash_mismatch_blocks_extraction(tmp_path) -> None:
    path = tmp_path / "report.pdf"
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()
    inventory = _inventory(path)
    inventory.pdf_sha256 = "0" * 64

    with pytest.raises(PdfExtractionError, match="hash mismatch"):
        extract_pdf_pages(inventory, page_numbers=(1,))
