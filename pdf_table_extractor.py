"""
PDF Table Extractor + OCR Handler for Tunisian Fiscal GraphRAG
==============================================================
UPDATED v2 — All fixes applied:
  ✅ Pages rendered ONE AT A TIME (fixes MemoryError on 122-page PDFs)
  ✅ DPI lowered to 200 (half the RAM of 300, still accurate for printed docs)
  ✅ OCR only runs on lois_finances/ PDFs (tables are there)
  ✅ notes_communes/ and Arabic file → text-only, no OCR (faster, no false positives)
  ✅ Poppler path set programmatically (no system PATH needed)
  ✅ numpy<2.0 compatible

Dependencies (install in order):
    pip install "numpy<2.0"
    pip install pymupdf pdfplumber pytesseract pdf2image opencv-python
    Tesseract: https://github.com/UB-Mannheim/tesseract/wiki  (with French pack)
    Poppler:   https://github.com/oschwartz10612/poppler-windows/releases
==============================================================
UPDATED v3:
  ✅ Reads Tesseract and Poppler paths from .env (no hardcoded paths)
  ✅ All other logic unchanged from v2
"""

import os
import re
import cv2
import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# ── PDF reading ───────────────────────────────────────────────────────────────
import fitz          # PyMuPDF
import pdfplumber

# ── OCR ──────────────────────────────────���────────────────────────────────────
import pytesseract
from pytesseract import Output
from pdf2image import convert_from_path

# ── Image processing ──────────────────────────────────────────────────────────
from PIL import Image, ImageEnhance, ImageFilter

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — now reads from .env via config.py
# ─────────────────────────────────────────────────────────────────────────────
from config import get_config
_cfg = get_config()

pytesseract.pytesseract.tesseract_cmd = _cfg["tesseract_cmd"]
os.environ["PATH"] += f";{_cfg['poppler_path']}"

TESSERACT_LANG    = 'fra'
OCR_DPI           = 200
IMAGE_REGION_AREA = 5000
TEXT_DENSITY_MIN  = 0.002
TABLES_FOLDER     = "lois_finances"


# ============================================================================
# DATA STRUCTURES  (unchanged from your original)
# ============================================================================

@dataclass
class ExtractedTable:
    """One table extracted from a PDF page."""
    page_num:       int
    table_index:    int
    doc_name:       str
    raw_data:       List[List[str]]
    headers:        List[str]
    method:         str
    markdown:       str = ""
    prose:          str = ""
    context_before: str = ""
    context_after:  str = ""

    def __post_init__(self):
        self.markdown = self._to_markdown()
        self.prose    = self._to_prose()

    def _to_markdown(self) -> str:
        if not self.raw_data:
            return ""
        rows   = self.raw_data
        header = self.headers if self.headers else rows[0]
        body   = rows[1:] if not self.headers else rows
        ncols  = max(len(r) for r in [header] + body) if body else len(header)
        header = self._pad(header, ncols)
        body   = [self._pad(r, ncols) for r in body]
        sep    = "| " + " | ".join(["---"] * ncols) + " |"
        head   = "| " + " | ".join(self._clean(c) for c in header) + " |"
        rows_md = [
            "| " + " | ".join(self._clean(c) for c in row) + " |"
            for row in body
        ]
        return "\n".join([head, sep] + rows_md)

    def _to_prose(self) -> str:
        if not self.raw_data:
            return ""
        header = self.headers if self.headers else self.raw_data[0]
        body   = self.raw_data[1:] if not self.headers else self.raw_data
        header = [self._clean(h) for h in header]
        lines  = []
        for row in body:
            parts = []
            for i, cell in enumerate(row):
                cell_clean = self._clean(cell)
                if not cell_clean:
                    continue
                key = header[i] if i < len(header) else f"Colonne {i+1}"
                parts.append(f"{key}: {cell_clean}")
            if parts:
                lines.append(". ".join(parts) + ".")
        return "\n".join(lines)

    @staticmethod
    def _pad(row: list, n: int) -> list:
        return row + [""] * (n - len(row))

    @staticmethod
    def _clean(cell) -> str:
        if cell is None:
            return ""
        return re.sub(r'\s+', ' ', str(cell)).strip()


@dataclass
class ExtractedPage:
    page_num:      int
    text:          str
    tables:        List[ExtractedTable] = field(default_factory=list)
    is_image_page: bool = False


@dataclass
class ExtractedDocument:
    file_path: str
    doc_name:  str
    pages:     List[ExtractedPage] = field(default_factory=list)

    def to_chunks(self) -> List[Dict]:
        chunks = []
        for page in self.pages:
            if page.text.strip():
                chunks.append({
                    'text':       page.text.strip(),
                    'doc_name':   self.doc_name,
                    'page_num':   page.page_num,
                    'chunk_type': 'text'
                })
            for tbl in page.tables:
                base = {
                    'doc_name':    self.doc_name,
                    'page_num':    page.page_num,
                    'table_index': tbl.table_index,
                }
                if tbl.markdown:
                    chunks.append({
                        **base,
                        'text': (
                            f"[TABLE – page {page.page_num}, "
                            f"extracted via {tbl.method}]\n"
                            f"Context avant: {tbl.context_before[:200]}\n\n"
                            f"{tbl.markdown}"
                        ),
                        'chunk_type': 'table_markdown',
                    })
                if tbl.prose:
                    chunks.append({
                        **base,
                        'text': (
                            f"[TABLE NARRATIVE – page {page.page_num}]\n"
                            f"{tbl.prose}"
                        ),
                        'chunk_type': 'table_prose',
                    })
        return chunks

# ============================================================================
# CORE EXTRACTOR
# ============================================================================

class FiscalPDFExtractor:
    """
    Per-page extractor. Decision logic per page:
      → native tables found?       use them (fastest, most accurate)
      → image regions + OCR on?    run OCR table extraction
      → otherwise                  text-only

    Memory fix: renders ONE page at a time instead of entire PDF at once.
    This keeps RAM usage flat regardless of document length.
    """

    def __init__(self, ocr_lang: str = TESSERACT_LANG, dpi: int = OCR_DPI):
        self.ocr_lang = ocr_lang
        self.dpi      = dpi

    def extract(self, pdf_path: str, enable_ocr: bool = True) -> ExtractedDocument:
        path        = Path(pdf_path)
        doc_name    = path.name
        mode_label  = "OCR enabled" if enable_ocr else "text-only"
        print(f"\n📄 Extracting: {doc_name}  [{mode_label}]")

        doc         = ExtractedDocument(file_path=str(path), doc_name=doc_name)
        mupdf_doc   = fitz.open(pdf_path)
        plumber_doc = pdfplumber.open(pdf_path)
        total_pages = len(mupdf_doc)

        for page_idx in range(total_pages):
            print(f"   Page {page_idx + 1}/{total_pages}: ", end="", flush=True)

            mupdf_page   = mupdf_doc[page_idx]
            plumber_page = plumber_doc.pages[page_idx]

            # ── Render ONLY this page to PIL image (memory fix) ───────────────
            # Old code: convert_from_path(pdf_path) → loads ALL pages → MemoryError
            # New code: first_page=N, last_page=N   → one page at a time → safe
            pil_image = None
            if enable_ocr:
                pil_pages = convert_from_path(
                    pdf_path,
                    dpi        = self.dpi,
                    first_page = page_idx + 1,   # 1-based
                    last_page  = page_idx + 1
                )
                pil_image = pil_pages[0]

            ep = self._process_page(
                page_num     = page_idx + 1,
                mupdf_page   = mupdf_page,
                plumber_page = plumber_page,
                pil_image    = pil_image,
                doc_name     = doc_name,
                enable_ocr   = enable_ocr
            )
            doc.pages.append(ep)

            # Free page image from memory immediately
            if pil_image is not None:
                del pil_image
            if enable_ocr:
                del pil_pages

        mupdf_doc.close()
        plumber_doc.close()

        total_tables = sum(len(p.tables) for p in doc.pages)
        print(f"\n   ✅ Done: {total_pages} pages, {total_tables} tables extracted")
        return doc

    def _process_page(
        self,
        page_num:     int,
        mupdf_page:   fitz.Page,
        plumber_page,
        pil_image:    Optional[Image.Image],
        doc_name:     str,
        enable_ocr:   bool
    ) -> ExtractedPage:

        raw_text     = mupdf_page.get_text("text")
        text_density = len(raw_text) / max(
            mupdf_page.rect.width * mupdf_page.rect.height, 1
        )
        image_list       = mupdf_page.get_images(full=True)
        has_large_images = any(
            self._image_area(img, mupdf_page) > IMAGE_REGION_AREA
            for img in image_list
        )
        is_image_page = text_density < TEXT_DENSITY_MIN

        ep = ExtractedPage(page_num=page_num, text=raw_text, is_image_page=is_image_page)

        # ── 1. Native table extraction (always attempted first) ───────────────
        native_tables = self._extract_native_tables(plumber_page, page_num, doc_name)

        if native_tables:
            print(f"native tables({len(native_tables)})", end=" ", flush=True)
            ep.tables = native_tables

        # ── 2. OCR table extraction (only if enabled and needed) ─────────────
        elif enable_ocr and pil_image is not None and (has_large_images or is_image_page):
            label = "full" if is_image_page else "regions"
            print(f"OCR({label})", end=" ", flush=True)
            ocr_tables = self._extract_ocr_tables(
                mupdf_page, pil_image, page_num, doc_name, is_image_page
            )
            ep.tables = ocr_tables
            if is_image_page:
                ep.text = self._full_page_ocr_text(pil_image)

        else:
            print("text-only", end=" ", flush=True)

        print(f"→ {len(ep.tables)} tables, {len(ep.text)} chars")
        return ep

    # ── Native table extraction ───────────────────────────────────────────────

    def _extract_native_tables(
        self, plumber_page, page_num: int, doc_name: str
    ) -> List[ExtractedTable]:
        tables = []
        try:
            raw_tables = plumber_page.extract_tables({
                "vertical_strategy":   "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance":      5,
                "join_tolerance":      3,
                "edge_min_length":     20,
            })
            for t_idx, raw in enumerate(raw_tables):
                if not raw or len(raw) < 2:
                    continue
                headers = [str(c).strip() if c else "" for c in raw[0]]
                tbl = ExtractedTable(
                    page_num    = page_num,
                    table_index = t_idx,
                    doc_name    = doc_name,
                    raw_data    = [[str(c) if c else "" for c in row] for row in raw],
                    headers     = headers,
                    method      = 'native'
                )
                tables.append(tbl)
        except Exception as e:
            print(f"[native err: {e}]", end=" ", flush=True)
        return tables

    # ── OCR table extraction ──────────────────────────────────────────────────

    def _extract_ocr_tables(
        self, mupdf_page: fitz.Page, pil_image: Image.Image,
        page_num: int, doc_name: str, full_page: bool
    ) -> List[ExtractedTable]:
        tables       = []
        cv_image     = self._pil_to_cv(pil_image)
        preprocessed = self._preprocess_for_ocr(cv_image)
        regions      = self._detect_table_regions(preprocessed)

        if not regions and full_page:
            regions = [(0, 0, pil_image.width, pil_image.height)]

        for t_idx, (x, y, w, h) in enumerate(regions):
            try:
                region_img = pil_image.crop((x, y, x + w, y + h))
                table_data = self._ocr_table_region(region_img)
                if not table_data or len(table_data) < 2:
                    continue
                headers = [str(c).strip() for c in table_data[0]]
                tbl = ExtractedTable(
                    page_num    = page_num,
                    table_index = t_idx,
                    doc_name    = doc_name,
                    raw_data    = table_data,
                    headers     = headers,
                    method      = 'ocr'
                )
                tables.append(tbl)
            except Exception as e:
                print(f"[ocr err p{page_num} t{t_idx}: {e}]", end=" ", flush=True)
        return tables

    def _ocr_table_region(self, region_img: Image.Image) -> List[List[str]]:
        """
        Tesseract TSV → word bounding boxes → spatial clustering.
        Cluster by Y-overlap for rows, by X-gap for columns.
        Works for any table structure (no fixed grid assumed).
        """
        enhanced = self._enhance_image(region_img)
        tsv_data = pytesseract.image_to_data(
            enhanced, lang=self.ocr_lang,
            config='--psm 6', output_type=Output.DICT
        )
        words = [
            {
                'text':   tsv_data['text'][i].strip(),
                'left':   tsv_data['left'][i],
                'top':    tsv_data['top'][i],
                'width':  tsv_data['width'][i],
                'height': tsv_data['height'][i],
            }
            for i in range(len(tsv_data['text']))
            if tsv_data['text'][i].strip() and int(tsv_data['conf'][i]) > 40
        ]
        if not words:
            return []

        words.sort(key=lambda w: w['top'])
        rows: List[List[dict]] = []
        current_row = [words[0]]
        for word in words[1:]:
            prev_center = current_row[-1]['top'] + current_row[-1]['height'] / 2
            if word['top'] <= prev_center <= word['top'] + word['height']:
                current_row.append(word)
            else:
                rows.append(sorted(current_row, key=lambda w: w['left']))
                current_row = [word]
        rows.append(sorted(current_row, key=lambda w: w['left']))

        col_boundaries = self._detect_col_boundaries(rows[0], region_img.width)
        table_data = []
        for row in rows:
            row_cells = [""] * len(col_boundaries)
            for word in row:
                idx = self._assign_to_column(word['left'], col_boundaries)
                row_cells[idx] = (row_cells[idx] + " " + word['text']).strip()
            table_data.append(row_cells)
        return table_data

    @staticmethod
    def _detect_col_boundaries(
        header_words: List[dict], img_width: int
    ) -> List[Tuple[int, int]]:
        if not header_words:
            return [(0, img_width)]
        words_sorted = sorted(header_words, key=lambda w: w['left'])
        boundaries, col_start = [], 0
        for i in range(1, len(words_sorted)):
            prev_right = words_sorted[i-1]['left'] + words_sorted[i-1]['width']
            gap        = words_sorted[i]['left'] - prev_right
            if gap > 20:
                boundaries.append((col_start, prev_right + gap // 2))
                col_start = prev_right + gap // 2
        boundaries.append((col_start, img_width))
        return boundaries

    @staticmethod
    def _assign_to_column(x: int, boundaries: List[Tuple[int, int]]) -> int:
        for i, (start, end) in enumerate(boundaries):
            if start <= x < end:
                return i
        return len(boundaries) - 1

    def _detect_table_regions(
        self, cv_img: np.ndarray
    ) -> List[Tuple[int, int, int, int]]:
        """
        Morphological line detection:
          horiz kernel → horizontal lines
          vert kernel  → vertical lines
          combine      → grid intersections only
          dilate       → merge cells into table bounding box
          contours     → one bounding box per table
        """
        h, w = cv_img.shape[:2]
        horiz = cv2.morphologyEx(
            cv_img, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (w // 40, 1)), iterations=2
        )
        vert = cv2.morphologyEx(
            cv_img, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, h // 40)), iterations=2
        )
        grid = cv2.addWeighted(horiz, 0.5, vert, 0.5, 0)
        _, binary = cv2.threshold(grid, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        dilated = cv2.dilate(
            binary,
            cv2.getStructuringElement(cv2.MORPH_RECT, (40, 40)),
            iterations=3
        )
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if cw * ch > IMAGE_REGION_AREA * 4 and cw > 100 and ch > 50:
                pad = 5
                regions.append((
                    max(0, x - pad), max(0, y - pad),
                    min(w, cw + pad * 2), min(h, ch + pad * 2)
                ))
        return regions

    def _full_page_ocr_text(self, pil_image: Image.Image) -> str:
        enhanced = self._enhance_image(pil_image)
        return pytesseract.image_to_string(
            enhanced, lang=self.ocr_lang, config='--psm 3'
        )

    @staticmethod
    def _pil_to_cv(pil_img: Image.Image) -> np.ndarray:
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    @staticmethod
    def _preprocess_for_ocr(cv_img: np.ndarray) -> np.ndarray:
        gray = (
            cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
            if len(cv_img.shape) == 3 else cv_img
        )
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, blockSize=15, C=4
        )
        return cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    @staticmethod
    def _enhance_image(pil_img: Image.Image) -> Image.Image:
        img = pil_img.convert('L')
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        return img.filter(ImageFilter.MedianFilter(size=1))

    @staticmethod
    def _image_area(img_ref, mupdf_page: fitz.Page) -> float:
        try:
            rects = mupdf_page.get_image_rects(img_ref[0])
            if rects:
                r = rects[0]
                return (r.x1 - r.x0) * (r.y1 - r.y0)
        except Exception:
            pass
        return 0.0


# ============================================================================
# DOCUMENT LOADER
# ============================================================================

class FiscalDocumentLoader:
    """
    Smart loader with per-folder routing:
      lois_finances/   → text + OCR table extraction
      notes_communes/  → text only (no tables, saves time)
      Arabic PDF       → text only (no tables)
    """

    def __init__(self, docs_path: str, ocr_lang: str = TESSERACT_LANG):
        self.docs_path = Path(docs_path)
        self.extractor = FiscalPDFExtractor(ocr_lang=ocr_lang)

    def load_all_chunks(self) -> List[Dict]:
        pdf_files = list(self.docs_path.rglob("*.pdf"))
        if not pdf_files:
            raise FileNotFoundError(f"No PDFs found in {self.docs_path}")

        print(f"Found {len(pdf_files)} PDF(s)")
        # Process lois_finances first
        pdf_files.sort(key=lambda p: (0 if TABLES_FOLDER in str(p) else 1, p.name))

        all_chunks = []
        for pdf_path in pdf_files:
            try:
                enable_ocr = TABLES_FOLDER in str(pdf_path)
                doc        = self.extractor.extract(str(pdf_path), enable_ocr=enable_ocr)
                chunks     = doc.to_chunks()
                all_chunks.extend(chunks)

                t  = sum(1 for c in chunks if c['chunk_type'] == 'text')
                md = sum(1 for c in chunks if c['chunk_type'] == 'table_markdown')
                pr = sum(1 for c in chunks if c['chunk_type'] == 'table_prose')
                print(f"   → {len(chunks)} chunks | text:{t}  table_md:{md}  table_prose:{pr}")

            except Exception as e:
                print(f"❌ Error processing {pdf_path.name}: {e}")
                import traceback; traceback.print_exc()

        return all_chunks

    def save_extraction_report(
        self, chunks: List[Dict], output_path: str = "extraction_report.json"
    ):
        report = {
            "total_chunks": len(chunks),
            "by_type": {
                "text":           sum(1 for c in chunks if c['chunk_type'] == 'text'),
                "table_markdown": sum(1 for c in chunks if c['chunk_type'] == 'table_markdown'),
                "table_prose":    sum(1 for c in chunks if c['chunk_type'] == 'table_prose'),
            },
            "by_document": {}
        }
        for chunk in chunks:
            doc = chunk['doc_name']
            if doc not in report['by_document']:
                report['by_document'][doc] = {"text": 0, "table_markdown": 0, "table_prose": 0}
            ct = chunk['chunk_type']
            if ct in report['by_document'][doc]:
                report['by_document'][doc][ct] += 1
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n📊 Extraction report saved: {output_path}")


# ============================================================================
# STANDALONE TEST
# ============================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python pdf_table_extractor.py <path_to_pdf_or_folder>")
        sys.exit(1)
    target = sys.argv[1]
    if os.path.isfile(target):
        doc    = FiscalPDFExtractor().extract(target, enable_ocr=True)
        chunks = doc.to_chunks()
    else:
        loader = FiscalDocumentLoader(target)
        chunks = loader.load_all_chunks()
        loader.save_extraction_report(chunks)
    print(f"\nTotal chunks: {len(chunks)}")
    for i, c in enumerate(chunks[:3], 1):
        print(f"\n── Chunk {i} ({c['chunk_type']}, page {c['page_num']}) ──")
        print(c['text'][:400])