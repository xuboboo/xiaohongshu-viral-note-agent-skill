from __future__ import annotations

import math
from pathlib import Path

from pydantic import BaseModel, Field

from xhs_skill.intelligence.text_similarity import ngram_jaccard


class ImageSimilarityReport(BaseModel):
    candidate: str
    reference: str
    phash_distance: int | None = None
    ocr_similarity: float | None = None
    visual_similarity: float | None = None
    blocked: bool = False
    warnings: list[str] = Field(default_factory=list)


def _dct_2d(values: list[list[float]], size: int = 8) -> list[list[float]]:
    n = len(values)
    result = [[0.0] * size for _ in range(size)]
    for u in range(size):
        for v in range(size):
            total = 0.0
            for x in range(n):
                for y in range(n):
                    total += (
                        values[x][y]
                        * math.cos((2 * x + 1) * u * math.pi / (2 * n))
                        * math.cos((2 * y + 1) * v * math.pi / (2 * n))
                    )
            cu = math.sqrt(1 / n) if u == 0 else math.sqrt(2 / n)
            cv = math.sqrt(1 / n) if v == 0 else math.sqrt(2 / n)
            result[u][v] = cu * cv * total
    return result


def perceptual_hash(path: str | Path, hash_size: int = 8) -> int:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Install the vision optional dependency to use image pHash") from exc
    image = Image.open(path).convert("L").resize((32, 32))
    flattened = getattr(image, "get_flattened_data", None)
    pixels = list(flattened() if callable(flattened) else image.getdata())
    matrix = [list(map(float, pixels[index * 32 : (index + 1) * 32])) for index in range(32)]
    dct = _dct_2d(matrix, hash_size)
    coefficients = [dct[x][y] for x in range(hash_size) for y in range(hash_size) if not (x == 0 and y == 0)]
    median = sorted(coefficients)[len(coefficients) // 2]
    value = 0
    for index, coefficient in enumerate(coefficients):
        if coefficient >= median:
            value |= 1 << index
    return value


def phash_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def extract_ocr_text(path: str | Path) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Install the vision optional dependency and Tesseract OCR") from exc
    return str(pytesseract.image_to_string(Image.open(path), lang="chi_sim+eng")).strip()


def compare_images(
    candidate: str | Path,
    reference: str | Path,
    *,
    phash_block_distance: int = 6,
    enable_ocr: bool = False,
) -> ImageSimilarityReport:
    report = ImageSimilarityReport(candidate=str(candidate), reference=str(reference))
    try:
        distance = phash_distance(perceptual_hash(candidate), perceptual_hash(reference))
        report.phash_distance = distance
        report.visual_similarity = round(1 - min(distance, 63) / 63, 6)
        report.blocked = distance <= phash_block_distance
    except Exception as exc:
        report.warnings.append(f"pHash unavailable: {type(exc).__name__}")
    if enable_ocr:
        try:
            report.ocr_similarity = round(
                ngram_jaccard(extract_ocr_text(candidate), extract_ocr_text(reference), width=3),
                6,
            )
            report.blocked = report.blocked or report.ocr_similarity >= 0.88
        except Exception as exc:
            report.warnings.append(f"OCR unavailable: {type(exc).__name__}")
    return report
