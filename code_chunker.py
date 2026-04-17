"""
Semantic chunker for French Tunisian Fiscal Code documents
Splits by: Chapter, Section, Article boundaries
Entity extraction: Regex-based (no LLM)
"""

import re
from typing import List, Dict, Optional

class CodeDocumentChunker:
    """
    Chunks French legal code documents (Code de la Fiscalité Locale, etc.)
    Structure: Chapitres → Sections → Articles
    Entity extraction: Pure regex patterns (fast, no LLM)
    """

    def __init__(self, max_chunk_size: int = 2000, chunk_overlap: int = 100):
        self.max_chunk_size = max_chunk_size
        self.chunk_overlap = chunk_overlap
        
        # French regex patterns
        self.chapter_pattern = re.compile(
            r'^(?:CHAPITRE|CH\.?)\s+(?:PREMIER|I{1,3}V?|VI{0,3}|\d+)\s*[\-:—–]',
            re.IGNORECASE | re.MULTILINE
        )
        
        self.section_pattern = re.compile(
            r'^(?:SECTION|SEC\.?)\s+(?:\d+|I{1,3}V?|VI{0,3})\s*[\-:—–]',
            re.IGNORECASE | re.MULTILINE
        )
        
        self.article_pattern = re.compile(
            r'^(?:ARTICLE|ART\.?)\s+(?:PREMIER|PREMIER BIS|[\d\w]+(?:\s+bis|\s+ter|\s+quater)?)\s*[\-:—–]',
            re.IGNORECASE | re.MULTILINE
        )
        
        # Entity extraction patterns (French)
        self.article_ref_pattern = re.compile(
            r'(?:l[\'´])?(?:article|art\.?)\s+(?:PREMIER|[\d\w]+(?:\s+bis|\s+ter|\s+quater)?)',
            re.IGNORECASE
        )
        
        self.chapter_ref_pattern = re.compile(
            r'(?:chapitre|chap\.?)\s+(?:PREMIER|I{1,3}V?|VI{0,3}|\d+)',
            re.IGNORECASE
        )
        
        self.section_ref_pattern = re.compile(
            r'(?:section|sec\.?)\s+(?:\d+|I{1,3}V?|VI{0,3})',
            re.IGNORECASE
        )
        
        # Tax concepts and thresholds
        self.tax_concepts = [
            r'\bTVA\b', r'\bIRPP\b', r'\bIS\b', r'\bTFP\b', r'\bCNSS\b',
            r'\bexon[ée]ration\b', r'\bsuspension\b', r'\bd[ée]grev[ement|ement]\b',
            r'\bamortissement\b', r'\bplus-value\b', r'\bassiette\b', r'\btaux\b',
            r'\bbase\b', r'\bretenue\b', r'\bversement\b', r'\bd[ée]duction\b',
            r'\bcontribution\b', r'\bimposition\b', r'\bpénalité\b'
        ]
        
        # Percentages and thresholds
        self.threshold_pattern = re.compile(
            r'(\d+(?:[.,]\d+)?)\s*(?:%|pour-?cent|dinars?|DT|d\.?\s?t\.?)',
            re.IGNORECASE
        )
        
        # Dates
        self.date_pattern = re.compile(
            r'(?:du|de|au)\s+(\d{1,2})\s+(?:janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+(\d{4})',
            re.IGNORECASE
        )

    def chunk_document(self, raw_chunks: List[Dict]) -> List[Dict]:
        """
        Main entry point. Takes raw chunks from pdf_table_extractor,
        returns refined context-aware chunks for Code documents.
        
        Args:
            raw_chunks: List of dicts with 'text', 'page_num', 'doc_name', 'chunk_type'
        
        Returns:
            List of chunks with added metadata: article_ref, chapter_ref, section_ref, entities, thresholds
        """
        
        # Filter text chunks only (skip tables for now)
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
        
        for chapter_idx, (chapter_title, chapter_text) in enumerate(chapters):
            # Split each chapter by sections
            sections = self._split_by_sections(chapter_text)
            
            for section_idx, (section_title, section_text) in enumerate(sections):
                # Split each section by articles
                articles = self._split_by_articles(section_text)
                
                for article_idx, (article_title, article_text) in enumerate(articles):
                    if not article_text.strip():
                        continue
                    
                    # Extract metadata and entities
                    article_ref = self._extract_article_ref(article_title)
                    chapter_ref = chapter_title.strip() if chapter_title else ''
                    section_ref = section_title.strip() if section_title else ''
                    
                    # Extract entities (regex-based, fast)
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
                                'text': f"[{chapter_ref}]\n[{section_ref}]\n{article_title}\n{sub_text}",
                                'doc_name': doc_name,
                                'page_num': page_num,
                                'chunk_type': 'text',
                                'article_ref': article_ref,
                                'chapter_ref': chapter_ref,
                                'section_ref': section_ref,
                                'sub_index': sub_idx,
                                'entities': entities,
                                'thresholds': thresholds,
                                'cross_references': cross_refs,
                                'doc_type': 'code'
                            })
                    else:
                        final_chunks.append({
                            'text': f"[{chapter_ref}]\n[{section_ref}]\n{article_title}\n{article_text}",
                            'doc_name': doc_name,
                            'page_num': page_num,
                            'chunk_type': 'text',
                            'article_ref': article_ref,
                            'chapter_ref': chapter_ref,
                            'section_ref': section_ref,
                            'sub_index': 0,
                            'entities': entities,
                            'thresholds': thresholds,
                            'cross_references': cross_refs,
                            'doc_type': 'code'
                        })
        
        return final_chunks

    def _split_by_chapters(self, text: str) -> List[tuple]:
        """Split text by CHAPITRE boundaries."""
        matches = list(self.chapter_pattern.finditer(text))
        
        if not matches:
            return [("", text)]
        
        chapters = []
        
        # Preamble before first chapter
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

    def _split_by_sections(self, text: str) -> List[tuple]:
        """Split text by SECTION boundaries."""
        matches = list(self.section_pattern.finditer(text))
        
        if not matches:
            return [("", text)]
        
        sections = []
        
        # Text before first section
        preamble = text[:matches[0].start()].strip()
        if preamble and len(preamble) > 30:
            sections.append(("", preamble))
        
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            
            section_title = match.group().strip().rstrip('-:—– ')
            section_text = text[start:end].strip()
            
            sections.append((section_title, section_text))
        
        return sections

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

    def _split_large_article(self, text: str, max_size: int = None) -> List[str]:
        """Split oversized article by numbered paragraphs, then fallback to sentences."""
        if max_size is None:
            max_size = self.max_chunk_size
        
        # Try splitting by numbered paragraphs: "1)", "2)", etc.
        para_pattern = re.compile(r'(?=\n\s*\d{1,2}\))')
        parts = para_pattern.split(text)
        
        if len(parts) > 1:
            result = []
            current_group = ""
            
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                
                if len(current_group) + len(part) + 2 <= max_size:
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
            if len(current) + len(sent) + 1 <= max_size:
                current = (current + " " + sent).strip()
            else:
                if current:
                    result.append(current)
                current = sent
        
        if current:
            result.append(current)
        
        return result if result else [text]

    def _extract_article_ref(self, article_title: str) -> str:
        """Extract clean article reference like 'Art. 52'."""
        match = re.search(r'(?:ARTICLE|ART\.?)\s+([\w\s]+?)(?:\s*[-:—–]|$)', article_title, re.IGNORECASE)
        if match:
            return f"Art. {match.group(1).strip()}"
        return ""

    def _extract_entities(self, text: str) -> Dict[str, List[str]]:
        """Extract tax concepts, legal terms, etc. from text (regex-based)."""
        entities = {
            'tax_concepts': [],
            'legal_terms': [],
            'article_references': [],
            'section_references': [],
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
        entities['article_references'] = list(set(article_refs))[:10]  # Limit to 10
        
        # Chapter references
        chapter_refs = self.chapter_ref_pattern.findall(text)
        entities['chapter_references'] = list(set(chapter_refs))[:5]
        
        # Section references
        section_refs = self.section_ref_pattern.findall(text)
        entities['section_references'] = list(set(section_refs))[:5]
        
        # Legal terms (look for definitions)
        legal_terms = re.findall(r'(?:Au sens|au sens|means?|d[ée]nomm[ée]|appel[ée])\s+[«"]?([^«»\n.]{3,100})[»"]?', text, re.IGNORECASE)
        entities['legal_terms'] = list(set(legal_terms))[:10]
        
        return entities

    def _extract_thresholds(self, text: str) -> List[Dict]:
        """Extract percentages, amounts, and thresholds."""
        thresholds = []
        
        matches = self.threshold_pattern.finditer(text)
        for match in matches:
            value = match.group(1)
            unit = match.group(0)
            
            # Get surrounding context (previous 30 chars)
            start_pos = max(0, match.start() - 30)
            context = text[start_pos:match.end() + 30].strip()
            
            thresholds.append({
                'value': value,
                'full_text': unit,
                'context': context
            })
        
        return thresholds[:20]  # Limit to 20

    def _extract_cross_references(self, text: str) -> List[str]:
        """Extract cross-references to other articles, chapters, sections."""
        refs = []
        
        # "Article X du présent code", "Article X de la loi n°..."
        cross_ref_pattern = re.compile(
            r'(?:article|art\.?)\s+(\w+)\s+(?:du|de|la|l[\'´])\s+([^.]+?)(?:\.|,|;)',
            re.IGNORECASE
        )
        
        matches = cross_ref_pattern.finditer(text)
        for match in matches:
            ref_text = f"Art. {match.group(1)} {match.group(2)}"
            if ref_text not in refs:
                refs.append(ref_text)
        
        return refs[:15]

    def _extract_thresholds(self, text: str) -> List[Dict]:
        """Extract percentages, amounts, and thresholds with context."""
        thresholds = []
        
        matches = self.threshold_pattern.finditer(text)
        for match in matches:
            value = match.group(1)
            unit = match.group(0)
            
            # Get surrounding context
            start_pos = max(0, match.start() - 50)
            end_pos = min(len(text), match.end() + 50)
            context = text[start_pos:end_pos].strip()
            
            thresholds.append({
                'value': value,
                'full_text': unit,
                'context': context
            })
        
        return thresholds[:20]

    @staticmethod
    def _find_page_for_text(text: str, text_chunks: List[Dict]) -> int:
        """Find which page this text fragment is from."""
        # Simple heuristic: find matching text chunk
        for chunk in text_chunks:
            if text[:50] in chunk['text']:
                return chunk.get('page_num', 0)
        return 0