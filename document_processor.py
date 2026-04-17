"""
================================================================================
DOCUMENT PROCESSOR — Tunisian Legal Documents
================================================================================
Extracts text + tables from PDFs and splits them into semantic chunks.

CHECKPOINT SYSTEM:
  Each PDF is saved to its own JSON file immediately when done.
  On restart, already-processed PDFs are skipped automatically.
  If a PDF crashed mid-way, only that PDF is re-processed.

  Progress file: processed_documents/_progress.json
  Tracks: filename → status (done | failed | in_progress) + timestamp + chunks

Supports:
  - Loi documents           → chunked by Article
  - Note Commune documents  → chunked by hierarchical section (I. / A. / ■)
  - Text-layer tables       → detected by column alignment heuristics
  - Image-embedded tables   → extracted via Tesseract OCR on cropped regions
  - Scanned pages           → full-page OCR fallback

Run:
    python document_processor.py
    python document_processor.py --force   # reprocess everything
================================================================================
"""

import os
import re
import json
import time
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass, asdict


import pymupdf as fitz

import pytesseract
from pdf2image import convert_from_path
from dotenv import load_dotenv

load_dotenv()

TESSERACT_CMD = os.getenv("TESSERACT_CMD")
POPPLER_PATH  = os.getenv("POPPLER_PATH")
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

MIN_TEXT_CHARS    = 80
MAX_ARTICLE_CHARS = 2000
TABLE_MIN_ROWS    = 3
OCR_CONF_MIN      = 30
PROGRESS_FILE     = "_progress.json"


# ═════════════════════════════════════════════════════════════════════════════
# DATA CLASS
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Chunk:
    chunk_id:          str
    document_id:       str
    filename:          str
    document_type:     str
    chunk_type:        str
    content:           str
    article_number:    Optional[str] = None
    section_number:    Optional[str] = None
    section_title:     Optional[str] = None
    subsection_letter: Optional[str] = None
    subsection_title:  Optional[str] = None
    page_number:       Optional[int] = None
    part:              Optional[int] = None


# ═════════════════════════════════════════════════════════════════════════════
# PROGRESS TRACKER  ← the checkpoint brain
# ═════════════════════════════════════════════════════════════════════════════

class ProgressTracker:
    """
    Reads and writes _progress.json inside the output directory.

    Structure:
    {
      "Loi2024_48.pdf": {
        "status":    "done",           -- "done" | "failed" | "in_progress"
        "chunks":    170,
        "timestamp": "2025-01-17 14:32",
        "output":    "Loi2024_48_processed.json"
      }
    }

    Rules:
      "done"        → JSON exists and is complete → SKIP on next run
      "failed"      → processing raised an exception → RETRY on next run
      "in_progress" → script was killed mid-way → RETRY on next run
                      (partial JSON is deleted before retry)
    """

    def __init__(self, output_dir: str):
        self.path = Path(output_dir) / PROGRESS_FILE
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def is_done(self, filename: str) -> bool:
        return self.data.get(filename, {}).get("status") == "done"

    def mark_in_progress(self, filename: str):
        self.data[filename] = {
            "status":    "in_progress",
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._save()

    def mark_done(self, filename: str, chunk_count: int, output_file: str):
        self.data[filename] = {
            "status":    "done",
            "chunks":    chunk_count,
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
            "output":    output_file,
        }
        self._save()

    def mark_failed(self, filename: str, error: str):
        self.data[filename] = {
            "status":    "failed",
            "error":     str(error)[:300],
            "timestamp": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._save()

    def summary(self):
        done   = sum(1 for v in self.data.values() if v["status"] == "done")
        failed = sum(1 for v in self.data.values() if v["status"] == "failed")
        chunks = sum(v.get("chunks", 0) for v in self.data.values()
                     if v["status"] == "done")
        return {"done": done, "failed": failed, "total_chunks": chunks}

    def print_status(self):
        icon_map = {"done": "✓", "failed": "✗", "in_progress": "⏸"}
        print("\n── Previous run status (checkpoint) ──────────────────")
        for fn, info in self.data.items():
            icon   = icon_map.get(info["status"], "?")
            extra  = (f"  ({info['chunks']} chunks)"
                      if info["status"] == "done" else
                      f"  ERROR: {info.get('error','')[:60]}"
                      if info["status"] == "failed" else "  (interrupted)")
            print(f"  {icon} {fn}{extra}  [{info.get('timestamp','')}]")
        print("──────────────────────────────────────────────────────\n")


# ═════════════════════════════════════════════════════════════════════════════
# SEMANTIC CHUNKER
# ═════════════════════════════════════════════════════════════════════════════

class SemanticChunker:

    RE_ARTICLE = re.compile(
        r'^(Art(?:icle)?\.?)\s*(\d+\s*(?:bis|ter)?|premier)\b',
        re.MULTILINE | re.IGNORECASE
    )
    RE_SUBSECTION = re.compile(
        r'^\s*(\d+\)|[A-Za-z]\)|[IVX]+\.)\s+',
        re.MULTILINE
    )
    RE_NC_MAJOR = re.compile(r'^([IVX]+)\.\s+(.+)$', re.MULTILINE)
    RE_NC_SUB   = re.compile(r'^\s{0,4}([A-Z])\.\s+(.+)$', re.MULTILINE)
    RE_RESUME   = re.compile(
        r'RESUM[EÉ]\s*\n(.*?)(?=\n\s*[IVX]+\.|\Z)',
        re.DOTALL | re.IGNORECASE
    )

    def detect_type(self, filename: str, text: str) -> str:
        fn = filename.lower()
        if 'loi' in fn:                          return 'loi'
        if 'note' in fn or 'commune' in fn or 'مذكرة' in fn:
                                                 return 'note_commune'
        s = text[:600].lower()
        if 'loi de finances' in s or 'article premier' in s: return 'loi'
        if 'note commune' in s or 'objet :' in s:            return 'note_commune'
        if 'مذكرة' in s or 'قانون' in s:                    return 'note_commune'
        return 'loi'

    def chunk(self, text, filename, doc_id, doc_type):
        if doc_type == 'loi':
            return self._chunk_loi(text, filename, doc_id, doc_type)
        return self._chunk_note(text, filename, doc_id, doc_type)

    # ── Loi ──────────────────────────────────────────────────────────────────

    def _chunk_loi(self, text, filename, doc_id, doc_type):
        chunks  = []
        matches = list(self.RE_ARTICLE.finditer(text))

        if not matches:
            return [Chunk(chunk_id=f"{doc_id}_full", document_id=doc_id,
                          filename=filename, document_type=doc_type,
                          chunk_type='full_document', content=text.strip())]

        preamble = text[:matches[0].start()].strip()
        if len(preamble) > 50:
            chunks.append(Chunk(chunk_id=f"{doc_id}_preamble",
                                document_id=doc_id, filename=filename,
                                document_type=doc_type, chunk_type='preamble',
                                content=preamble))

        for i, m in enumerate(matches):
            art_num  = m.group(2).strip()
            start    = m.start()
            end      = matches[i+1].start() if i+1 < len(matches) else len(text)
            art_text = text[start:end].strip()

            if len(art_text) <= MAX_ARTICLE_CHARS:
                chunks.append(Chunk(chunk_id=f"{doc_id}_art_{art_num}",
                                    document_id=doc_id, filename=filename,
                                    document_type=doc_type, chunk_type='article',
                                    content=art_text, article_number=art_num))
            else:
                for j, part in enumerate(self._split(art_text), 1):
                    chunks.append(Chunk(chunk_id=f"{doc_id}_art_{art_num}_p{j}",
                                        document_id=doc_id, filename=filename,
                                        document_type=doc_type,
                                        chunk_type='article_part',
                                        content=part, article_number=art_num, part=j))
        return chunks

    def _split(self, text):
        header = text.split('\n')[0]
        subs   = list(self.RE_SUBSECTION.finditer(text))
        if subs:
            return [f"{header}\n\n{text[m.start(): subs[i+1].start() if i+1<len(subs) else len(text)].strip()}"
                    for i, m in enumerate(subs)]
        paras = text.split('\n\n')
        parts, buf = [], header + '\n\n'
        for p in paras[1:]:
            if len(buf) + len(p) > 1800:
                if buf.strip() != header:
                    parts.append(buf.strip())
                buf = header + '\n\n' + p + '\n\n'
            else:
                buf += p + '\n\n'
        if buf.strip() != header:
            parts.append(buf.strip())
        return parts or [text]

    # ── Note Commune ──────────────────────────────────────────────────────────

    def _chunk_note(self, text, filename, doc_id, doc_type):
        chunks = []

        resume_m = self.RE_RESUME.search(text)
        if resume_m:
            chunks.append(Chunk(chunk_id=f"{doc_id}_resume",
                                document_id=doc_id, filename=filename,
                                document_type=doc_type, chunk_type='resume',
                                content=resume_m.group(0).strip(),
                                section_number='RESUME', section_title='Résumé'))

        major = list(self.RE_NC_MAJOR.finditer(text))
        for i, m in enumerate(major):
            sec_num   = m.group(1)
            sec_title = m.group(2).strip()
            start     = m.start()
            end       = major[i+1].start() if i+1 < len(major) else len(text)
            sec_text  = text[start:end]
            subs      = list(self.RE_NC_SUB.finditer(sec_text))

            if not subs:
                chunks.append(Chunk(chunk_id=f"{doc_id}_sec_{sec_num}",
                                    document_id=doc_id, filename=filename,
                                    document_type=doc_type, chunk_type='section',
                                    content=sec_text.strip(),
                                    section_number=sec_num,
                                    section_title=sec_title))
            else:
                for j, sub_m in enumerate(subs):
                    sub_letter = sub_m.group(1)
                    sub_title  = sub_m.group(2).strip()
                    s_start    = sub_m.start()
                    s_end      = subs[j+1].start() if j+1 < len(subs) else len(sec_text)
                    chunks.append(Chunk(
                        chunk_id=f"{doc_id}_sec_{sec_num}_{sub_letter}",
                        document_id=doc_id, filename=filename,
                        document_type=doc_type, chunk_type='subsection',
                        content=f"{sec_num}. {sec_title}\n\n{sec_text[s_start:s_end].strip()}",
                        section_number=sec_num, section_title=sec_title,
                        subsection_letter=sub_letter, subsection_title=sub_title))

        if not chunks:
            chunks.append(Chunk(chunk_id=f"{doc_id}_full",
                                document_id=doc_id, filename=filename,
                                document_type=doc_type, chunk_type='full_document',
                                content=text.strip()))
        return chunks


# ═════════════════════════════════════════════════════════════════════════════
# TABLE EXTRACTOR
# ═════════════════════════════════════════════════════════════════════════════

class TableExtractor:

    def extract_from_page(self, page, pdf_path, page_num,
                          doc_id, filename, doc_type):
        chunks = []
        for idx, tbl in enumerate(self._text_tables(page.get_text())):
            chunks.append(Chunk(chunk_id=f"{doc_id}_p{page_num+1}_tt{idx}",
                                document_id=doc_id, filename=filename,
                                document_type=doc_type, chunk_type='text_table',
                                content=tbl, page_number=page_num+1))
<<<<<<< HEAD
        # SKIP IMAGE TABLE OCR — it's causing hangs
        #if page.get_images(full=True):
            #for c in self._image_tables(pdf_path, page_num, doc_id, filename, doc_type):
        #        chunks.append(c)
        return chunks

    def _text_tables(self, text):
        if not text:  # Handle None or empty text
            return []
=======

        if page.get_images(full=True):
            for c in self._image_tables(pdf_path, page_num, doc_id, filename, doc_type):
                chunks.append(c)
        return chunks

    def _text_tables(self, text):
>>>>>>> 9b23e8fa926e8ec82f72f25f9402af3169405eff
        lines, tables, buf = text.split('\n'), [], []
        for line in lines:
            n = line.count('|') + line.count('\t') + len(re.findall(r' {3,}', line))
            if n >= 2:
                buf.append(line)
            else:
                if len(buf) >= TABLE_MIN_ROWS:
                    tables.append('\n'.join(buf))
                buf = []
        if len(buf) >= TABLE_MIN_ROWS:
            tables.append('\n'.join(buf))
        return tables

    def _image_tables(self, pdf_path, page_num, doc_id, filename, doc_type):
        chunks = []
        try:
            imgs = convert_from_path(pdf_path, first_page=page_num+1,
                                     last_page=page_num+1,
                                     poppler_path=POPPLER_PATH, dpi=200)
            if not imgs:
                return chunks
            img = imgs[0]
            ocr = pytesseract.image_to_data(img,
                                             output_type=pytesseract.Output.DICT,
                                             lang='fra')
            for idx, (x, y, w, h) in enumerate(self._regions(ocr, img.size)):
                text = pytesseract.image_to_string(
                    img.crop((x, y, x+w, y+h)), lang='fra', config='--psm 6'
                ).strip()
                if text:
                    chunks.append(Chunk(
                        chunk_id=f"{doc_id}_p{page_num+1}_it{idx}",
                        document_id=doc_id, filename=filename,
                        document_type=doc_type, chunk_type='image_table',
                        content=f"[TABLE IMAGE — page {page_num+1}]\n{text}",
                        page_number=page_num+1))
        except Exception as e:
            print(f"    ⚠ Image table OCR p{page_num+1}: {e}")
        return chunks

    def _regions(self, ocr, img_size):
        n     = len(ocr['text'])
        words = [{'left': ocr['left'][i], 'top': ocr['top'][i],
                  'right': ocr['left'][i]+ocr['width'][i],
                  'bottom': ocr['top'][i]+ocr['height'][i]}
                 for i in range(n)
                 if int(ocr['conf'][i]) >= OCR_CONF_MIN
                 and ocr['text'][i].strip()]
        if not words:
            return []
        words.sort(key=lambda w: (w['top'], w['left']))

        rows, cur = [], [words[0]]
        for w in words[1:]:
            if abs(w['top'] - cur[0]['top']) <= 12:
                cur.append(w)
            else:
                rows.append(cur); cur = [w]
        rows.append(cur)

        def cols(row):
            xs = sorted(w['left'] for w in row)
            c  = 1
            for a, b in zip(xs, xs[1:]):
                if b - a > 20: c += 1
            return c

        groups, buf = [], []
        for row in rows:
            if cols(row) >= 2:
                buf.append(row)
            else:
                if len(buf) >= TABLE_MIN_ROWS: groups.append(buf)
                buf = []
        if len(buf) >= TABLE_MIN_ROWS: groups.append(buf)

        bboxes = []
        for grp in groups:
            ws = [w for row in grp for w in row]
            bboxes.append((
                max(0, min(w['left']   for w in ws) - 5),
                max(0, min(w['top']    for w in ws) - 5),
                min(img_size[0], max(w['right']  for w in ws) + 5) - max(0, min(w['left'] for w in ws) - 5),
                min(img_size[1], max(w['bottom'] for w in ws) + 5) - max(0, min(w['top']  for w in ws) - 5),
            ))
        return bboxes


# ═════════════════════════════════════════════════════════════════════════════
# PDF PROCESSOR
# ═════════════════════════════════════════════════════════════════════════════

class PDFProcessor:
    def __init__(self):
        self.chunker   = SemanticChunker()
        self.extractor = TableExtractor()

    def process(self, pdf_path: str) -> List[Chunk]:
        path     = Path(pdf_path)
        filename = path.name
        doc_id   = re.sub(r'[^\w]', '_', path.stem)
        doc      = fitz.open(pdf_path)

        print(f"  Pages: {len(doc)}")

        full_text = ""
        for page_num, page in enumerate(doc):
            raw = page.get_text()
            if len(raw.strip()) >= MIN_TEXT_CHARS:
                full_text += raw + "\n\n"
            else:
                print(f"    Page {page_num+1}: scanned → OCR")
                full_text += self._ocr(pdf_path, page_num) + "\n\n"

        doc_type = self.chunker.detect_type(filename, full_text)
        print(f"  Type: {doc_type}")

        text_chunks = self.chunker.chunk(full_text, filename, doc_id, doc_type)
        print(f"  Text chunks: {len(text_chunks)}")

        table_chunks = []
        for page_num, page in enumerate(doc):
            table_chunks.extend(
                self.extractor.extract_from_page(
                    page, pdf_path, page_num, doc_id, filename, doc_type)
            )
        print(f"  Table chunks: {len(table_chunks)}")

        doc.close()
        return text_chunks + table_chunks

    def _ocr(self, pdf_path, page_num):
        try:
            imgs = convert_from_path(pdf_path, first_page=page_num+1,
                                     last_page=page_num+1,
                                     poppler_path=POPPLER_PATH, dpi=300)
            return pytesseract.image_to_string(imgs[0], lang='fra') if imgs else ""
        except Exception as e:
            print(f"    OCR error p{page_num+1}: {e}")
            return ""


# ═════════════════════════════════════════════════════════════════════════════
# BATCH PROCESSING WITH CHECKPOINTS
# ═════════════════════════════════════════════════════════════════════════════

def _collect_pdfs(root: Path) -> List[Path]:
    """
    Collect all PDF files under root recursively.
    Skips only truly empty files (0 bytes).
    All non-empty PDFs are included regardless of size.
    """
    all_pdfs   = sorted(root.rglob("*.pdf"))
    safe_pdfs  = []
    skipped_dl = []

    for p in all_pdfs:
        size = p.stat().st_size
        if size == 0:
            skipped_dl.append(p)
        else:
            safe_pdfs.append(p)

    if skipped_dl:
        print(f"\n  Skipped {len(skipped_dl)} empty file(s).")

    print(f"  Found {len(safe_pdfs)} ready PDF(s) under \'{root}\'")
    return safe_pdfs


def process_all(input_dir=None, output_dir=None, force=False):
    """
    Process every PDF found recursively under input_dir.
    Skips already-done files (checkpoint). Safe to run while scraper downloads.

    Folder structure supported:
        documents/
          notes_communes/NC_01.pdf, NC_02.pdf …
          lois_finances/Loi2024_48.pdf …
          SomeFile.pdf          ← also picked up

    Args:
        input_dir  : root folder to scan recursively for PDFs
        output_dir : folder to write JSON chunks + _progress.json
        force      : if True, ignore checkpoints and reprocess everything

    Checkpoint key = relative path from input_dir, e.g.
        "notes_communes/NC_02.pdf"
    This avoids collisions when two subfolders have files with the same name.
    """
    input_dir  = Path(input_dir  or os.getenv("DOCUMENTS_DIR",  "./documents"))
    output_dir = Path(output_dir or os.getenv("PROCESSED_DIR", "./processed_documents"))

    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Collect PDFs recursively, skip files still downloading ───────────────
    pdf_files = _collect_pdfs(input_dir)

    if not pdf_files:
        print(f"ERROR: No ready PDFs found under '{input_dir}'")
        print("  (files < 5 KB are treated as still-downloading and skipped)")
        return {}

    # Show discovered structure
    subfolders = sorted({p.parent for p in pdf_files})
    print(f"\n{'='*60}")
    print(f"  FOUND {len(pdf_files)} PDF(s) in {len(subfolders)} folder(s)")
    for sf in subfolders:
        count = sum(1 for p in pdf_files if p.parent == sf)
        print(f"    {sf.relative_to(input_dir) if sf != input_dir else '(root)'}:"
              f"  {count} file(s)")
    print(f"  Output dir: {output_dir}")
    print(f"{'='*60}")

    tracker   = ProgressTracker(str(output_dir))
    processor = PDFProcessor()

    if tracker.data:
        tracker.print_status()

    skipped = processed = failed = 0

    for i, pdf_path in enumerate(pdf_files, 1):
        # Use relative path as checkpoint key → unique even across subfolders
        rel_path = str(pdf_path.relative_to(input_dir))   # e.g. "notes_communes/NC_02.pdf"
        filename = pdf_path.name

        # Unique doc_id from relative path (avoids collisions across subfolders)
        doc_stem = re.sub(r'[^\w]', '_', str(pdf_path.relative_to(input_dir).with_suffix('')))
        out_json = output_dir / f"{doc_stem}_processed.json"

        # ── Checkpoint ────────────────────────────────────────────────────────
        if not force and tracker.is_done(rel_path):
            if out_json.exists():
                info = tracker.data[rel_path]
                print(f"\n[{i}/{len(pdf_files)}] ⏭  SKIP  {rel_path}"
                      f"  ({info.get('chunks','?')} chunks, {info.get('timestamp','')})")
                skipped += 1
                continue
            print(f"\n[{i}/{len(pdf_files)}] ⚠  JSON missing, reprocessing: {rel_path}")

        print(f"\n[{i}/{len(pdf_files)}] ▶  {rel_path}")
        print("-" * 50)

        # Delete partial JSON from any interrupted previous run
        if out_json.exists():
            out_json.unlink()

        tracker.mark_in_progress(rel_path)

        try:
            t0      = time.time()
            chunks  = processor.process(str(pdf_path))
            elapsed = time.time() - t0

            with open(out_json, 'w', encoding='utf-8') as f:
                json.dump([asdict(c) for c in chunks], f, ensure_ascii=False, indent=2)

            tracker.mark_done(rel_path, len(chunks), out_json.name)
            processed += 1
            print(f"  ✓ {len(chunks)} chunks → {out_json.name}  ({elapsed:.1f}s)")

        except Exception as e:
            tracker.mark_failed(rel_path, str(e))
            failed += 1
            print(f"  ✗ FAILED: {e}")
            print(f"    Will retry automatically on next run.")

    # ── Summary ───────────────────────────────────────────────────────────────
    s = tracker.summary()
    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"  This run  : {processed} processed,  {skipped} skipped,  {failed} failed")
    print(f"  All time  : {s['done']} / {len(pdf_files)} PDFs done,"
          f"  {s['total_chunks']} chunks")
    if failed:
        print(f"  ⚠ Run again to retry the {failed} failed PDF(s).")
    if skipped_downloading := len(pdf_files) - processed - skipped - failed:
        pass  # already reported above
    print(f"{'='*60}\n")
    return s


if __name__ == "__main__":
    import sys
    process_all(force="--force" in sys.argv)