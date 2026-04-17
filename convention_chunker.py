"""
Semantic chunker for French Convention documents
Splits by: Chapter and Article boundaries
Entity extraction: Regex-based (no LLM)
"""

import re
from typing import List, Dict

class ConventionDocumentChunker:
    """
    Chunks French Convention/Treaty documents
    Structure: Chapitres → Articles
    Entity extraction: Pure regex patterns (no LLM)
    """

    def __init__(self, max_chunk_size: int = 2000, chunk_overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        
        # French regex patterns for conventions
        self.chapter_pattern = re.compile(
            r'^(?:CHAPITRE|CH\.?)\s+(?:I{1,3}V?|VI{0,3}|\d+)\s*[\-:—–]',
            re.IGNORECASE | re.MULTILINE
        )
        
        self.article_pattern = re.compile(
            r'^(?:ARTICLE|ART\.?)\s+(\d+(?:\s+bis)?)\s*[\-:—–]',
            re.IGNORECASE | re.MULTILINE
        )
        
        # Cross-reference patterns
        self.article_ref_pattern = re.compile(
            r'(?:article|art\.?)\s+(\d+(?:\s+bis)?)',
            re.IGNORECASE
        )
        
        self.chapter_ref_pattern = re.compile(
            r'(?:chapitre|chap\.?)\s+(?:I{1,3}V?|VI{0,3}|\d+)',
            re.IGNORECASE
        )
        
        # Tax/fiscal concepts
        self.tax_concepts = [
            r'\bimpos(?:ition|able)\b', r'\brev(?:enu|enus)\b', r'\bsoci[ée]t[ée]s?\b',
            r'\bd[ée]duction\b', r'\bexon[ée]ration\b', r'\btaux\b', r'\bassiette\b',
            r'\bresidents?\b', r'\bnationaux\b', r'\b(?:personne|entreprise) physique\b',
            r'\b(?:personne|entreprise) morale\b', r'\bdroits? de douane\b',
            r'\b(?:retenue|rétention)\b', r'\bdividendes?\b', r'\bint[ée]r[êe]ts?\b',
            r'\bredevances?\b', r'\bpension\b', r'\bsalaire\b'
        ]
        
        # Percentages and thresholds
        self.threshold_pattern = re.compile(
            r'(\d+(?:[.,]\d+)?)\s*(?:%|pour-?cent)',
            re.IGNORECASE
        )
        
        # Dates
        self.date_pattern = re.compile(
            r'(?:le|d[eu])\s+(\d{1,2})\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})',
            re.IGNORECASE
        )

    def chunk_document(self, raw_chunks: List[Dict]) -> List[Dict]:
        """
        Main entry point. Takes raw chunks from pdf_table_extractor,
        returns refined context-aware chunks for Convention documents.
        """
        
        # Filter text chunks only
        text_chunks = [c for c in raw_chunks if c['chunk_type'] == 'text']
        
        if not text_chunks:
            return []
        
        # Sort by page
        text_chunks.sort(key=lambda c: c.get('page_num', 0))
        doc_name = text_chunks[0]['doc_name']
        
        # Concatenate all text
        full_text = "\n\n".join(c['text'] for c in text_chunks)
        
        # Split by chapters first
        chapters = self._split_by_chapters(full_text)
        
        final_chunks = []
        
        for chapter_title, chapter_text in chapters:
            # Split each chapter by articles
            articles = self._split_by_articles(chapter_text)
            
            for article_title, article_text in articles:
                if not article_text.strip():
                    continue
                
                # Extract metadata and entities
                article_ref = self._extract_article_ref(article_title)
                chapter_ref = chapter_title.strip() if chapter_title else ''
                
                # Extract entities (regex-based)
                entities = self._extract_entities(article_text)
                thresholds = self._extract_thresholds(article_text)
                cross_refs = self._extract_cross_references(article_text)
                
                # Determine page
                page_num = self._find_page_for_text(article_text, text_chunks)
                
                # If article is too large, split by paragraphs
                if len(article_text) > self.max_chunk_size:
                    sub_chunks = self._split_large_article(article_text)
                    for sub_idx, sub_text in enumerate(sub_chunks):
                        final_chunks.append({
                            'text': f"[{chapter_ref}]\n{article_title}\n{sub_text}",
                            'doc_name': doc_name,
                            'page_num': page_num,
                            'chunk_type': 'text',
                            'article_ref': article_ref,
                            'chapter_ref': chapter_ref,
                            'section_ref': '',
                            'sub_index': sub_idx,
                            'entities': entities,
                            'thresholds': thresholds,
                            'cross_references': cross_refs,
                            'doc_type': 'convention'
                        })
                else:
                    final_chunks.append({
                        'text': f"[{chapter_ref}]\n{article_title}\n{article_text}",
                        'doc_name': doc_name,
                        'page_num': page_num,
                        'chunk_type': 'text',
                        'article_ref': article_ref,
                        'chapter_ref': chapter_ref,
                        'section_ref': '',
                        'sub_index': 0,
                        'entities': entities,
                        'thresholds': thresholds,
                        'cross_references': cross_refs,
                        'doc_type': 'convention'
                    })
        
        return final_chunks

    def _split_by_chapters(self, text: str) -> List[tuple]:
        """Split text by CHAPITRE boundaries."""
        matches = list(self.chapter_pattern.finditer(text))
        
        if not matches:
            return [("", text)]
        
        chapters = []
        
        # Preamble
        preamble = text[:matches[0].start()].strip()
        if preamble and len(preamble) > 50:
            chapters.append(("Préambule", preamble))
        
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            
            chapter_title = match.group().strip().rstrip('-:—– ')
            chapter_text = text[start:end].strip()
            
            chapters.append((chapter_title, chapter_text))
        
        return chapters

    def _split_by_articles(self, text: str) -> List[tuple]:
        """Split text by ARTICLE boundaries."""
        matches = list(self.article_pattern.finditer(text))
        
        if not matches:
            return [("", text)]
        
        articles = []
        
        # Text before first article
        preamble = text[:matches[0].start()].strip()
        if preamble and len(preamble) > 20:
            articles.append(("", preamble))
        
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            
            article_title = match.group().strip().rstrip('-:—– ')
            article_text = text[start:end].strip()
            
            articles.append((article_title, article_text))
        
        return articles

    def _split_large_article(self, text: str) -> List[str]:
        """Split oversized article by numbered paragraphs or sentences."""
        # Try splitting by numbered paragraphs
        para_pattern = re.compile(r'(?=\n\s*\d{1,2}\))')
        parts = para_pattern.split(text)
        
        if len(parts) > 1:
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
                        result.append(current_group)
                    current_group = part
            
            if current_group:
                result.append(current_group)
            
            return result if result else [text]
        
        # Fallback: split by sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        result = []
        current = ""
        
        for sent in sentences:
            if len(current) + len(sent) + 1 <= self.max_chunk_size:
                current = (current + " " + sent).strip()
            else:
                if current:
                    result.append(current)
                current = sent
        
        if current:
            result.append(current)
        
        return result if result else [text]

    def _extract_article_ref(self, article_title: str) -> str:
        """Extract clean article reference."""
        match = re.search(r'ARTICLE\s+(\d+(?:\s+bis)?)', article_title, re.IGNORECASE)
        if match:
            return f"Art. {match.group(1)}"
        return ""

    def _extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract tax concepts and legal terms (regex-based)."""
        entities = {
            'tax_concepts': [],
            'legal_terms': [],
            'article_references': [],
            'chapter_references': []
        }
        
        # Tax concepts
        for pattern_str in self.tax_concepts:
            matches = re.finditer(pattern_str, text)
            for match in matches:
                concept = match.group()
                if concept not in entities['tax_concepts']:
                    entities['tax_concepts'].append(concept)
        
        # Article references
        article_refs = self.article_ref_pattern.findall(text)
        entities['article_references'] = list(set(article_refs))[:10]
        
        # Chapter references
        chapter_refs = self.chapter_ref_pattern.findall(text)
        entities['chapter_references'] = list(set(chapter_refs))[:5]
        
        # Legal term definitions
        legal_terms = re.findall(r'(?:Au sens|au sens|means?)\s+[«"]?([^«»\n.]{3,100})[»"]?', text, re.IGNORECASE)
        entities['legal_terms'] = list(set(legal_terms))[:10]
        
        return entities

    def _extract_thresholds(self, text: str) -> List[Dict]:
        """Extract percentages and thresholds."""
        thresholds = []
        
        matches = self.threshold_pattern.finditer(text)
        for match in matches:
            value = match.group(1)
            unit = match.group(0)
            
            start_pos = max(0, match.start() - 50)
            end_pos = min(len(text), match.end() + 50)
            context = text[start_pos:end_pos].strip()
            
            thresholds.append({
                'value': value,
                'full_text': unit,
                'context': context
            })
        
        return thresholds[:20]

    def _extract_cross_references(self, text: str) -> List[str]:
        """Extract cross-references to other articles/chapters."""
        refs = []
        
        cross_ref_pattern = re.compile(
            r'(?:article|art\.?)\s+(\d+(?:\s+bis)?)\s+(?:du|de|la)\s+([^.]+?)(?:\.|,|;)',
            re.IGNORECASE
        )
        
        matches = cross_ref_pattern.finditer(text)
        for match in matches:
            ref_text = f"Art. {match.group(1)} {match.group(2)}"
            if ref_text not in refs:
                refs.append(ref_text)
        
        return refs[:15]

    @staticmethod
    def _find_page_for_text(text: str, text_chunks: List[Dict]) -> int:
        """Find which page this text is from."""
        for chunk in text_chunks:
            if text[:50] in chunk['text']:
                return chunk.get('page_num', 0)
        return 0