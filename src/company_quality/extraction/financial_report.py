"""Page- and coordinate-preserving extraction for verified financial PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
from importlib import import_module
from pathlib import Path
from typing import Literal, Protocol, Sequence


Coordinate = tuple[Decimal, Decimal, Decimal, Decimal]
ExtractionMethod = Literal["text_layer", "rapidocr", "unreadable"]


class PdfExtractionError(RuntimeError):
    """Raised when an official PDF cannot be safely admitted for extraction."""


class AuditPdfInventory(Protocol):
    pdf_path: Path | None
    pdf_sha256: str | None
    evidence_ids: tuple[str, ...]
    available_at: str


@dataclass(frozen=True, slots=True)
class OcrObservation:
    text: str
    confidence: float
    polygon: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]


class OcrEngine(Protocol):
    def recognize(self, image: object) -> Sequence[OcrObservation]: ...


class RapidOcrEngine:
    def __init__(self) -> None:
        try:
            RapidOCR = getattr(import_module("rapidocr_onnxruntime"), "RapidOCR")
        except ImportError as exc:
            raise PdfExtractionError("RapidOCR dependency is unavailable") from exc
        self._engine = RapidOCR()

    def recognize(self, image: object) -> tuple[OcrObservation, ...]:
        result, _ = self._engine(image)
        if result is None:
            return ()
        observations: list[OcrObservation] = []
        for item in result:
            text = str(item[1]).strip()
            points = tuple((float(point[0]), float(point[1])) for point in item[0])
            if not text or len(points) != 4:
                continue
            observations.append(OcrObservation(
                text=text,
                confidence=float(item[2]),
                polygon=(points[0], points[1], points[2], points[3]),
            ))
        return tuple(observations)


@dataclass(frozen=True, slots=True)
class PdfTextBlock:
    evidence_id: str
    page: int
    coordinate: Coordinate
    text: str
    confidence: float | None
    method: Literal["text_layer", "rapidocr"]
    available_at: str


@dataclass(frozen=True, slots=True)
class PdfPageEvidence:
    page: int
    method: ExtractionMethod
    text: str
    blocks: tuple[PdfTextBlock, ...]


@dataclass(frozen=True, slots=True)
class PdfTextEvidence:
    status: Literal["available", "partial"]
    pdf_sha256: str
    source_path: Path
    page_count: int
    selected_pages: tuple[int, ...]
    pages: tuple[PdfPageEvidence, ...]
    page_coverage: Decimal
    parser_version: Literal["pymupdf-text-rapidocr-fallback.v1"] = (
        "pymupdf-text-rapidocr-fallback.v1"
    )
    schema_version: Literal["PdfTextEvidence.v1"] = "PdfTextEvidence.v1"


def _ratio(value: float, total: float) -> Decimal:
    return Decimal(str(value)) / Decimal(str(total))


def _coordinate(
    x0: float, y0: float, x1: float, y1: float, width: float, height: float
) -> Coordinate:
    if width <= 0 or height <= 0:
        raise PdfExtractionError("PDF page has invalid dimensions")
    values = (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, y0 / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
    )
    if values[0] >= values[2] or values[1] >= values[3]:
        raise PdfExtractionError("extracted block has invalid coordinates")
    return (
        Decimal(str(values[0])),
        Decimal(str(values[1])),
        Decimal(str(values[2])),
        Decimal(str(values[3])),
    )


def _block(
    *,
    digest: str,
    page: int,
    index: int,
    coordinate: Coordinate,
    text: str,
    confidence: float | None,
    method: Literal["text_layer", "rapidocr"],
    available_at: str,
) -> PdfTextBlock:
    return PdfTextBlock(
        evidence_id=f"pdf:{digest}:page:{page}:block:{index}",
        page=page,
        coordinate=coordinate,
        text=text,
        confidence=confidence,
        method=method,
        available_at=available_at,
    )


def extract_pdf_pages(
    inventory: AuditPdfInventory,
    *,
    page_numbers: Sequence[int] | None = None,
    ocr: OcrEngine | None = None,
    render_scale: float = 2.0,
) -> PdfTextEvidence:
    """Extract selected pages, invoking OCR only when a page has no text layer."""

    path = inventory.pdf_path
    digest = inventory.pdf_sha256
    if path is None or digest is None or not Path(path).is_file():
        raise PdfExtractionError("verified audit PDF is required")
    raw = Path(path).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != digest:
        raise PdfExtractionError("audit PDF hash mismatch")
    if f"pdf:{digest}" not in inventory.evidence_ids:
        raise PdfExtractionError("audit PDF evidence ID is not admitted")
    if render_scale <= 0:
        raise PdfExtractionError("render_scale must be positive")
    try:
        fitz = import_module("fitz")
    except ImportError as exc:
        raise PdfExtractionError("PyMuPDF dependency is unavailable") from exc

    document = fitz.open(path)
    try:
        page_count = len(document)
        selected = (
            tuple(page_numbers)
            if page_numbers is not None
            else tuple(range(1, page_count + 1))
        )
        if (
            not selected
            or len(set(selected)) != len(selected)
            or any(page < 1 or page > page_count for page in selected)
        ):
            raise PdfExtractionError("selected PDF pages are invalid")
        pages: list[PdfPageEvidence] = []
        readable = 0
        ocr_engine = ocr
        for page_number in selected:
            page = document[page_number - 1]
            text_blocks: list[PdfTextBlock] = []
            for raw_block in page.get_text("blocks", sort=True):
                text = " ".join(str(raw_block[4]).split())
                if not text:
                    continue
                text_blocks.append(
                    _block(
                        digest=digest,
                        page=page_number,
                        index=len(text_blocks) + 1,
                        coordinate=_coordinate(
                            float(raw_block[0]),
                            float(raw_block[1]),
                            float(raw_block[2]),
                            float(raw_block[3]),
                            float(page.rect.width),
                            float(page.rect.height),
                        ),
                        text=text,
                        confidence=None,
                        method="text_layer",
                        available_at=inventory.available_at,
                    )
                )
            method: ExtractionMethod = "text_layer"
            if not text_blocks:
                if ocr_engine is None:
                    ocr_engine = RapidOcrEngine()
                try:
                    np = import_module("numpy")
                except ImportError as exc:
                    raise PdfExtractionError("NumPy dependency is unavailable") from exc
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(render_scale, render_scale), alpha=False
                )
                image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                    pixmap.height, pixmap.width, pixmap.n
                )
                observations = ocr_engine.recognize(image)
                for observation in observations:
                    xs = [point[0] for point in observation.polygon]
                    ys = [point[1] for point in observation.polygon]
                    text_blocks.append(
                        _block(
                            digest=digest,
                            page=page_number,
                            index=len(text_blocks) + 1,
                            coordinate=_coordinate(
                                min(xs),
                                min(ys),
                                max(xs),
                                max(ys),
                                float(pixmap.width),
                                float(pixmap.height),
                            ),
                            text=observation.text,
                            confidence=observation.confidence,
                            method="rapidocr",
                            available_at=inventory.available_at,
                        )
                    )
                method = "rapidocr" if text_blocks else "unreadable"
            if text_blocks:
                readable += 1
            pages.append(
                PdfPageEvidence(
                    page=page_number,
                    method=method,
                    text="\n".join(block.text for block in text_blocks),
                    blocks=tuple(text_blocks),
                )
            )
        coverage = _ratio(readable, len(selected))
        return PdfTextEvidence(
            status="available" if coverage == 1 else "partial",
            pdf_sha256=digest,
            source_path=Path(path),
            page_count=page_count,
            selected_pages=selected,
            pages=tuple(pages),
            page_coverage=coverage,
        )
    finally:
        document.close()


__all__ = [
    "OcrObservation",
    "PdfExtractionError",
    "PdfPageEvidence",
    "PdfTextBlock",
    "PdfTextEvidence",
    "RapidOcrEngine",
    "extract_pdf_pages",
]
