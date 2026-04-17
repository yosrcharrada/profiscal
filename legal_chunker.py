"""
Context-Aware Legal Document Chunker for Tunisian Fiscal Laws
=============================================================
Replaces blind SentenceSplitter with structure-aware chunking:
  - Loi de finances: splits by article boundaries (Art. N)
  - Note commune: splits by section boundaries (I., II., III.)
  - Tables: never split (kept atomic)
  - Oversized articles: split by sub-paragraphs, then fallback to SentenceSplitter
"""

import re
from typing import List, Dict, Optional
from llama_index.core.node_parser import SentenceSplitter


# ── Regex patterns for Tunisian fiscal document structure ─────────────────────

# Matches: "Art. 2 -", "Art. 22 -", "Article premier :", "Article 7 bis :"
ARTICLE_PATTERN = re.compile(
    r'^(?:Art(?:icle)?\.?\s*'
    r'(?:premier|première|\d+(?:\s*(?:bis|ter|quater|quinquies|sexies|septies|octies|novies|decies))?)'
    r')\s*[-:—–(]',
    re.IGNORECASE | re.MULTILINE
)

# Note commune sections: "I.", "II.", "III.", "1.", "2)"
NOTE_SECTION_PATTERN = re.compile(
    r'^(?:'
    r'(?:I{1,3}V?|VI{0,3})\s*[.)\-–—]'
    r'|'
    r'\d{1,2}\s*[.)\-–—]'
    r')\s+',
    re.MULTILINE
)

# Document type indicators
LOI_INDICATORS = ['loi de finances', 'décret-loi', 'Art.', 'Article premier',
                  'Journal Officiel', 'Dispositions']
NOTE_INDICATORS = ['Note commune', 'NOTE COMMUNE', 'OBJET :', 'RESUME',
                   'Direction Générale des Impôts']


class LegalDocumentChunker:
    """
    Structure-aware chunker for Tunisian fiscal documents.
    
    1. Detect document type (Loi vs Note commune)
    2. Split text by article/section boundaries
    3. Attach section headers as metadata
    4. Use SentenceSplitter only as fallback for oversized units
    5. Never split table chunks
    """

    def __init__(self, max_chunk_size: int = 1500,
                 fallback_chunk_size: int = 1024, chunk_overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.fallback_splitter = SentenceSplitter(
            chunk_size=fallback_chunk_size, chunk_overlap=chunk_overlap
        )

    def chunk_document(self, raw_chunks: List[Dict]) -> List[Dict]:
        """
        Main entry point. Takes raw chunks from pdf_table_extractor,
        returns refined context-aware chunks.
        """
        table_chunks = [c for c in raw_chunks if c['chunk_type'] != 'text']
        text_chunks  = [c for c in raw_chunks if c['chunk_type'] == 'text']

        # Group text by document
        docs = {}
        for chunk in text_chunks:
            doc_name = chunk['doc_name']
            if doc_name not in docs:
                docs[doc_name] = []
            docs[doc_name].append(chunk)

        final_chunks = []

        for doc_name, chunks in docs.items():
            chunks.sort(key=lambda c: c.get('page_num', 0))
            full_text = "\n\n".join(c['text'] for c in chunks)
            doc_type = self._detect_doc_type(full_text)

            if doc_type == 'loi':
                refined = self._chunk_loi(chunks, doc_name)
            elif doc_type == 'note':
                refined = self._chunk_note(chunks, doc_name)
            else:
                refined = self._chunk_generic(chunks, doc_name)

            final_chunks.extend(refined)

        # Table chunks: keep atomic, just add article_ref metadata
        for tc in table_chunks:
            tc['article_ref'] = self._find_nearest_article_ref(
                tc.get('page_num', 0), text_chunks, tc['doc_name']
            )
            tc['section_title'] = ''
            tc['sub_index'] = 0
            final_chunks.append(tc)

        return final_chunks

    def _detect_doc_type(self, text: str) -> str:
        text_lower = text.lower()
        loi_score  = sum(1 for ind in LOI_INDICATORS if ind.lower() in text_lower)
        note_score = sum(1 for ind in NOTE_INDICATORS if ind.lower() in text_lower)
        if loi_score >= 2:
            return 'loi'
        elif note_score >= 2:
            return 'note'
        return 'generic'

    def _chunk_loi(self, text_chunks: List[Dict], doc_name: str) -> List[Dict]:
        """Split a Loi de finances by article boundaries."""
        page_segments = [{'text': c['text'], 'page_num': c.get('page_num', 0)}
                         for c in text_chunks]
        full_text = "\n\n".join(seg['text'] for seg in page_segments)

        article_matches = list(ARTICLE_PATTERN.finditer(full_text))
        if not article_matches:
            return self._chunk_generic(text_chunks, doc_name)

        result = []
        current_section_title = None

        # Preamble (before first article)
        preamble = full_text[:article_matches[0].start()].strip()
        if preamble and len(preamble) > 50:
            result.append({
                'text': preamble, 'doc_name': doc_name,
                'page_num': self._find_page_for_offset(0, page_segments),
                'chunk_type': 'text', 'article_ref': 'Préambule',
                'section_title': '', 'sub_index': 0,
            })

        for i, match in enumerate(article_matches):
            start = match.start()
            end = article_matches[i+1].start() if i+1 < len(article_matches) else len(full_text)
            article_text = full_text[start:end].strip()
            article_ref = match.group().strip().rstrip('-:—–( ')
            page_num = self._find_page_for_offset(start, page_segments)

            # Check for section header before this article
            preceding = full_text[max(0, start - 300):start].strip()
            header = self._extract_section_header(preceding)
            if header:
                current_section_title = header

            if len(article_text) <= self.max_chunk_size:
                chunk_text = article_text
                if current_section_title:
                    chunk_text = f"[{current_section_title}]\n{article_text}"
                result.append({
                    'text': chunk_text, 'doc_name': doc_name,
                    'page_num': page_num, 'chunk_type': 'text',
                    'article_ref': article_ref,
                    'section_title': current_section_title or '',
                    'sub_index': 0,
                })
            else:
                sub_chunks = self._split_large_article(
                    article_text, article_ref, current_section_title
                )
                for si, sub_text in enumerate(sub_chunks):
                    result.append({
                        'text': sub_text, 'doc_name': doc_name,
                        'page_num': page_num, 'chunk_type': 'text',
                        'article_ref': article_ref,
                        'section_title': current_section_title or '',
                        'sub_index': si,
                    })

        return result

    def _chunk_note(self, text_chunks: List[Dict], doc_name: str) -> List[Dict]:
        """Split a Note commune by section boundaries."""
        page_segments = [{'text': c['text'], 'page_num': c.get('page_num', 0)}
                         for c in text_chunks]
        full_text = "\n\n".join(seg['text'] for seg in page_segments)

        section_matches = list(NOTE_SECTION_PATTERN.finditer(full_text))
        if not section_matches:
            return self._chunk_generic(text_chunks, doc_name)

        result = []

        # Header/OBJET before first section
        header_text = full_text[:section_matches[0].start()].strip()
        if header_text and len(header_text) > 30:
            objet = ''
            objet_match = re.search(r'OBJET\s*:\s*(.+?)(?:\n|$)', header_text, re.IGNORECASE)
            if objet_match:
                objet = objet_match.group(1).strip()[:200]
            result.append({
                'text': header_text, 'doc_name': doc_name,
                'page_num': self._find_page_for_offset(0, page_segments),
                'chunk_type': 'text', 'article_ref': 'En-tête / Résumé',
                'section_title': objet, 'sub_index': 0,
            })

        for i, match in enumerate(section_matches):
            start = match.start()
            end = section_matches[i+1].start() if i+1 < len(section_matches) else len(full_text)
            section_text = full_text[start:end].strip()
            section_ref = match.group().strip().rstrip('.-–—) ')
            page_num = self._find_page_for_offset(start, page_segments)

            if len(section_text) <= self.max_chunk_size:
                result.append({
                    'text': section_text, 'doc_name': doc_name,
                    'page_num': page_num, 'chunk_type': 'text',
                    'article_ref': f'Section {section_ref}',
                    'section_title': '', 'sub_index': 0,
                })
            else:
                sub_texts = self.fallback_splitter.split_text(section_text)
                for si, sub in enumerate(sub_texts):
                    result.append({
                        'text': sub, 'doc_name': doc_name,
                        'page_num': page_num, 'chunk_type': 'text',
                        'article_ref': f'Section {section_ref}',
                        'section_title': '', 'sub_index': si,
                    })

        return result

    def _chunk_generic(self, text_chunks: List[Dict], doc_name: str) -> List[Dict]:
        """Fallback: sentence-split each page's text."""
        result = []
        for chunk in text_chunks:
            sub_texts = self.fallback_splitter.split_text(chunk['text'])
            for si, sub in enumerate(sub_texts):
                result.append({
                    **chunk, 'text': sub, 'article_ref': '',
                    'section_title': '', 'sub_index': si,
                })
        return result

    def _split_large_article(self, article_text, article_ref, section_title):
        """Split oversized article by numbered sub-paragraphs first."""
        sub_para_pattern = re.compile(r'(?=\n\s*\d{1,2}\)\s)')
        parts = sub_para_pattern.split(article_text)

        prefix = f"[{article_ref}]"
        if section_title:
            prefix = f"[{section_title} — {article_ref}]"

        if len(parts) <= 1:
            sub_texts = self.fallback_splitter.split_text(article_text)
            return [f"{prefix}\n{t}" for t in sub_texts]

        result = []
        current_group = ""
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(current_group) + len(part) + 2 <= self.max_chunk_size:
                current_group = (current_group + "\n" + part).strip()
            else:
                if current_group:
                    result.append(f"{prefix}\n{current_group}")
                current_group = part
        if current_group:
            result.append(f"{prefix}\n{current_group}")

        # Safety: split any remaining oversized groups
        final = []
        for chunk in result:
            if len(chunk) <= self.max_chunk_size:
                final.append(chunk)
            else:
                final.extend(self.fallback_splitter.split_text(chunk))
        return final

    @staticmethod
    def _extract_section_header(preceding_text: str) -> Optional[str]:
        lines = preceding_text.strip().split('\n')
        for line in reversed(lines[-5:]):
            line = line.strip()
            if not line or len(line) < 15:
                continue
            if line.startswith('Art') or line.startswith('Page '):
                continue
            if 20 < len(line) < 250 and line[0].isupper() and not line[0].isdigit():
                return line
        return None

    @staticmethod
    def _find_page_for_offset(char_offset, page_segments):
        cumulative = 0
        for seg in page_segments:
            cumulative += len(seg['text']) + 2
            if char_offset < cumulative:
                return seg['page_num']
        return page_segments[-1]['page_num'] if page_segments else 0

    @staticmethod
    def _find_nearest_article_ref(page_num, text_chunks, doc_name):
        doc_chunks = [c for c in text_chunks if c['doc_name'] == doc_name]
        for offset in range(0, 10):
            for c in reversed(doc_chunks):
                if c.get('page_num', 0) == page_num - offset:
                    match = ARTICLE_PATTERN.search(c['text'])
                    if match:
                        return match.group().strip().rstrip('-:—–( ')
        return ''