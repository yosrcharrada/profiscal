"""
create_reports.py
Generate realistic Tunisian tax consultation reports grounded in Neo4j GraphRAG chunks.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional at runtime
    def load_dotenv() -> None:
        return None

try:
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover - optional at runtime
    GraphDatabase = None  # type: ignore

from config import get_config

try:
    from docx import Document  # type: ignore
except ImportError:  # pragma: no cover - optional at runtime
    Document = None


load_dotenv()


@dataclass(frozen=True)
class CaseType:
    key: str
    title: str
    client_kind: str
    topics: Tuple[str, ...]
    objective: str


@dataclass
class LegalSource:
    doc_name: str
    page_num: int
    article_ref: str
    section_title: str
    text: str
    score: float

    def short_ref(self) -> str:
        article = self.article_ref.strip() if self.article_ref else "n/r"
        return f"{self.doc_name} (p.{self.page_num}, {article})"


CASE_TYPES: Tuple[CaseType, ...] = (
    CaseType(
        key="non_resident_purchases",
        title="Achats auprès de non-résidents",
        client_kind="entreprise",
        topics=("tva", "retenue", "source", "non-résident", "importation", "cdpf", "ctva"),
        objective="Sécuriser le traitement TVA/IS et les obligations de retenue à la source sur achats étrangers.",
    ),
    CaseType(
        key="withholding_tax",
        title="Retenue à la source / mobilité internationale",
        client_kind="particulier",
        topics=("irpp", "retenue", "source", "résidence", "salaire", "sécurité sociale", "change"),
        objective="Déterminer la fiscalité des rémunérations multi-pays et les obligations locales associées.",
    ),
    CaseType(
        key="transfer_pricing",
        title="Prix de transfert et opérations intra-groupe",
        client_kind="entreprise",
        topics=("prix de transfert", "comparables", "documentation", "intra-groupe", "is"),
        objective="Cartographier les risques de déductibilité et de documentation des flux intra-groupe.",
    ),
    CaseType(
        key="corporate_individual_mix",
        title="Mix entreprise / personne physique",
        client_kind="mixte",
        topics=("irpp", "is", "tva", "rémunération", "gérance", "retenue", "honoraires"),
        objective="Arbitrer entre revenus personnels et structure sociétaire en limitant le risque fiscal global.",
    ),
)


COMPANY_NAMES = [
    "Maghreb Digital Services",
    "Carthage Industrial Components",
    "Tunimed Trading",
    "Sahara Consulting Partners",
    "Nord Afrique Distribution",
]

COUNTRIES = ["Tunisie", "France", "Maroc", "États-Unis", "Italie", "Allemagne", "Émirats Arabes Unis"]


class Neo4jContextService:
    def __init__(self) -> None:
        cfg = get_config()
        self.database = cfg["neo4j_database"]
        self.driver = None
        if GraphDatabase is not None:
            self.driver = GraphDatabase.driver(
                cfg["neo4j_uri"], auth=(cfg["neo4j_username"], cfg["neo4j_password"])
            )

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()

    def _run_chunk_query(self, topics: Sequence[str], limit: int) -> List[LegalSource]:
        query = """
        MATCH (c:Chunk)
        WHERE any(t IN $topics WHERE toLower(c.text) CONTAINS t OR toLower(coalesce(c.article_ref,'')) CONTAINS t)
        WITH c,
             reduce(s = 0.0, t IN $topics |
                 s + CASE WHEN toLower(c.text) CONTAINS t THEN 1.0 ELSE 0.0 END
             ) AS score
        RETURN c.doc_name AS doc_name,
               coalesce(c.page_num, 0) AS page_num,
               coalesce(c.article_ref, '') AS article_ref,
               coalesce(c.section_title, '') AS section_title,
               coalesce(c.text, '') AS text,
               score
        ORDER BY score DESC, c.doc_name ASC, c.page_num ASC
        LIMIT $limit
        """
        if self.driver is None:
            return []
        with self.driver.session(database=self.database) as session:
            rows = session.run(query, topics=[t.lower() for t in topics], limit=limit)
            return [LegalSource(**dict(row)) for row in rows]

    def select_relevant_regulations_for_case_type(self, case_type: CaseType, limit: int = 8) -> List[LegalSource]:
        return self._run_chunk_query(case_type.topics, limit)

    def find_articles_related_to_tax_topics(self, tax_topics: Sequence[str], limit: int = 8) -> List[LegalSource]:
        return self._run_chunk_query(tax_topics, limit)

    def retrieve_case_law_about_withholding_tax(self, limit: int = 6) -> List[LegalSource]:
        return self._run_chunk_query(("retenue", "source", "irpp", "convention", "résidence"), limit)

    def search_transfer_pricing_documentation(self, limit: int = 6) -> List[LegalSource]:
        return self._run_chunk_query(("prix de transfert", "intra-groupe", "comparables", "documentation"), limit)


def _pick_dates(rng: random.Random) -> Tuple[str, str]:
    start = date(2024, 1, 1) + timedelta(days=rng.randint(0, 550))
    meeting = start + timedelta(days=rng.randint(5, 45))
    return start.strftime("%d/%m/%Y"), meeting.strftime("%d/%m/%Y")


def build_case_profile(case_type: CaseType, idx: int, rng: random.Random) -> Dict[str, str]:
    start_date, meeting_date = _pick_dates(rng)
    reference_year = int(start_date[-4:])
    company = rng.choice(COMPANY_NAMES)
    country_a = rng.choice(COUNTRIES)
    country_b = rng.choice([c for c in COUNTRIES if c != country_a])
    materiality = f"{rng.randint(180, 950)} K TND"

    specific_context = {
        "non_resident_purchases": "Achats de licences/équipements auprès de fournisseurs non-résidents et question de territorialité TVA.",
        "withholding_tax": "Rémunération d'un dirigeant intervenant entre la Tunisie et l'étranger avec présence physique mixte.",
        "transfer_pricing": "Facturation intra-groupe (management fees, support IT, redevances) et justification des marges.",
        "corporate_individual_mix": "Expert exerçant via société tout en percevant des revenus personnels liés à la même activité.",
    }[case_type.key]

    return {
        "reference": f"CONS-{reference_year}-{idx:03d}",
        "client_name": company,
        "client_kind": case_type.client_kind,
        "case_title": case_type.title,
        "objective": case_type.objective,
        "context_focus": specific_context,
        "jurisdiction_1": country_a,
        "jurisdiction_2": country_b,
        "kickoff_date": start_date,
        "meeting_date": meeting_date,
        "materiality": materiality,
    }


def _unique_abbreviations(sources: Sequence[LegalSource]) -> List[str]:
    lexicon = {
        "TVA": "Taxe sur la Valeur Ajoutée",
        "IRPP": "Impôt sur le Revenu des Personnes Physiques",
        "IS": "Impôt sur les Sociétés",
        "CDPF": "Code des Droits et Procédures Fiscaux",
        "CTVA": "Code de la TVA",
    }
    corpus = " ".join([s.text for s in sources]) + " " + " ".join([s.article_ref for s in sources])
    found = [abbr for abbr in lexicon if re.search(rf"\b{abbr}\b", corpus, flags=re.IGNORECASE)]
    return [f"{abbr} : {lexicon[abbr]}" for abbr in sorted(found)] or [f"{k} : {v}" for k, v in lexicon.items()]


def _build_scope_lines(case_type: CaseType, sources: Sequence[LegalSource]) -> List[str]:
    article_lines = [s.article_ref.strip() for s in sources if s.article_ref.strip()]
    article_lines = list(dict.fromkeys(article_lines))[:6]
    scope_lines = [
        "Régime fiscal applicable (IRPP, IS, TVA, retenues à la source).",
        "Qualification des flux au regard de la territorialité et de la résidence fiscale.",
        "Conditions de déductibilité et exigences documentaires.",
        "Risques de redressement, pénalités et obligations déclaratives.",
    ]
    if case_type.key == "withholding_tax":
        scope_lines.extend(
            [
                "Régime social, change et transfert des rémunérations.",
                "Statut visa/carte de séjour et incidence sur la fiscalité personnelle.",
            ]
        )
    if article_lines:
        scope_lines.extend([f"Conformément à {article_ref}." for article_ref in article_lines[:3]])
        scope_lines.append("Références légales mobilisées : " + "; ".join(article_lines))
    return scope_lines


def _build_risk_rows(case_type: CaseType) -> List[Tuple[str, str, str, str]]:
    default = [
        ("Qualification fiscale des flux", "Moyenne", "Élevé", "Documenter la substance et la base légale."),
        ("Retenue à la source", "Élevée", "Élevé", "Mettre en place des contrôles de paiement et attestations."),
        ("TVA / territorialité", "Moyenne", "Moyen", "Cartographier la chaîne de facturation et lieu de consommation."),
    ]
    if case_type.key == "transfer_pricing":
        default.append(("Prix de transfert non justifiés", "Élevée", "Élevé", "Dossier local + benchmark comparables."))
    if case_type.key == "corporate_individual_mix":
        default.append(("Confusion flux perso/société", "Moyenne", "Élevé", "Conventionner et séparer les flux bancaires."))
    return default


def build_sections(case_type: CaseType, profile: Dict[str, str], sources: Sequence[LegalSource]) -> Dict[str, str]:
    legal_refs = [s.short_ref() for s in sources[:10]]
    scope_lines = _build_scope_lines(case_type, sources)
    abbreviations = _unique_abbreviations(sources)
    risk_rows = _build_risk_rows(case_type)
    primary_refs = "; ".join(legal_refs[:4]) if legal_refs else "Références Neo4j non disponibles"

    contexte = (
        f"1. CONTEXTE\n"
        f"1.1 Compréhension des faits\n"
        f"Nous comprenons que {profile['client_name']} ({profile['client_kind']}) sollicite notre avis pour: {profile['objective']}\n"
        f"- Contexte opérationnel: {profile['context_focus']}\n"
        f"- Juridictions concernées: {profile['jurisdiction_1']} / {profile['jurisdiction_2']}\n"
        f"- Dates clés: lancement {profile['kickoff_date']} ; réunion technique {profile['meeting_date']}\n"
        f"- Matérialité estimée: {profile['materiality']}\n\n"
        f"1.2 Étendue de nos travaux\n"
        + "\n".join([f"- {line}" for line in scope_lines])
    )

    executive_summary = (
        "3. SOMMAIRE EXÉCUTIF\n"
        f"Au regard des textes identifiés via Neo4j GraphRAG ({primary_refs}), "
        "les principaux enjeux portent sur la qualification des revenus/charges, "
        "la territorialité et les obligations de retenue à la source. "
        "Nos conclusions privilégient une documentation renforcée et un dispositif déclaratif traçable.\n\n"
        "Tableau de risques (probabilité / impact / action)\n"
        "| Risque | Probabilité | Impact | Mesure recommandée |\n"
        "|---|---|---|---|\n"
        + "\n".join([f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |" for r in risk_rows])
    )

    analysis_rows = [
        (
            "Le flux est-il imposable en Tunisie ?",
            "Résidence fiscale + territorialité (IRPP/IS/TVA) selon textes applicables.",
            "Vérifier lieu de réalisation, bénéficiaire effectif et présence d'établissement stable.",
        ),
        (
            "Une retenue à la source est-elle exigible ?",
            "Obligation de retenue selon nature du revenu et qualité du bénéficiaire.",
            "Analyser convention fiscale applicable et exigibilité documentaire au paiement.",
        ),
        (
            "Quelles pièces justificatives conserver ?",
            "CDPF/obligations de justification et documentation prix de transfert le cas échéant.",
            "Conserver contrats, factures, preuves d'exécution et benchmark économique.",
        ),
    ]

    analyses = (
        "4. ANALYSES\n"
        "| Question | Règle applicable | Analyse |\n"
        "|---|---|---|\n"
        + "\n".join([f"| {q} | {r} | {a} |" for q, r, a in analysis_rows])
    )

    documents = (
        "5. DOCUMENTS ET RÉFÉRENCES\n"
        + "\n".join([f"- {ref}" for ref in legal_refs])
        + "\n\nAbréviations utilisées\n"
        + "\n".join([f"- {abbr}" for abbr in abbreviations])
    )

    return {
        "REFERENCE": profile["reference"],
        "TYPE_CAS": case_type.title,
        "CONTEXTE": contexte,
        "SOMMAIRE_EXECUTIF": executive_summary,
        "ANALYSES": analyses,
        "DOCUMENTS_REFERENCES": documents,
    }


def replace_tokens_in_docx(template_path: Path, output_path: Path, tokens: Dict[str, str]) -> None:
    if Document is None:
        raise RuntimeError("python-docx is not installed. Install it with: pip install python-docx")
    doc = Document(str(template_path))
    token_map = {f"{{{{{k}}}}}": v for k, v in tokens.items()}

    def replace_in_runs(runs, token: str, value: str) -> bool:
        replaced = False
        for run in runs:
            if token in run.text:
                run.text = run.text.replace(token, value)
                replaced = True
        return replaced

    for paragraph in doc.paragraphs:
        for token, value in token_map.items():
            if token in paragraph.text and not replace_in_runs(paragraph.runs, token, value):
                paragraph.text = paragraph.text.replace(token, value)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for token, value in token_map.items():
                    if token in cell.text:
                        for paragraph in cell.paragraphs:
                            if token in paragraph.text and not replace_in_runs(paragraph.runs, token, value):
                                paragraph.text = paragraph.text.replace(token, value)

    doc.save(str(output_path))


def write_text_fallback(output_path: Path, tokens: Dict[str, str]) -> None:
    ordered = ["REFERENCE", "TYPE_CAS", "CONTEXTE", "SOMMAIRE_EXECUTIF", "ANALYSES", "DOCUMENTS_REFERENCES"]
    payload = [f"{k}\n{tokens[k]}" for k in ordered]
    output_path.write_text("\n\n".join(payload), encoding="utf-8")


def slugify_filename(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", normalized).strip("_")


def generate_reports(
    count: int,
    output_dir: Path,
    template_path: Optional[Path],
    seed: int,
    case_type: Optional[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    neo4j = Neo4jContextService()

    try:
        for idx in range(1, count + 1):
            selected = None
            if case_type:
                selected = next((c for c in CASE_TYPES if c.key == case_type), None)
                if selected is None:
                    raise ValueError(f"case_type inconnu: {case_type}")
            else:
                selected = rng.choice(CASE_TYPES)

            profile = build_case_profile(selected, idx, rng)
            try:
                sources = neo4j.select_relevant_regulations_for_case_type(selected, limit=10)
                if selected.key == "withholding_tax":
                    sources += neo4j.retrieve_case_law_about_withholding_tax(limit=4)
                if selected.key == "transfer_pricing":
                    sources += neo4j.search_transfer_pricing_documentation(limit=4)
            except Exception as exc:
                print(f"⚠️ Neo4j context unavailable for report {idx}: {exc}")
                sources = []
            sources = list(
                {
                    (
                        s.doc_name,
                        s.page_num,
                        s.article_ref,
                        hashlib.sha256(s.text.strip().encode("utf-8")).hexdigest()[:12],
                    ): s
                    for s in sources
                }.values()
            )[:10]

            tokens = build_sections(selected, profile, sources)
            file_stem = slugify_filename(f"{profile['client_name']}_{selected.key}_{idx:02d}")
            if template_path and template_path.exists():
                output_path = output_dir / f"Consultation_{file_stem}.docx"
                replace_tokens_in_docx(template_path, output_path, tokens)
            else:
                output_path = output_dir / f"Consultation_{file_stem}.txt"
                write_text_fallback(output_path, tokens)
            print(f"✅ Generated: {output_path}")
    finally:
        neo4j.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Neo4j-grounded tax consultation reports")
    parser.add_argument("--count", type=int, default=10, help="Nombre de consultations à générer (défaut: 10)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("generated_consultations"),
        help="Dossier de sortie",
    )
    parser.add_argument(
        "--template-path",
        type=Path,
        default=Path("template_fr.docx"),
        help="Path to the Word template file (default: template_fr.docx)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible generation (default: 42)")
    parser.add_argument(
        "--case-type",
        type=str,
        choices=[c.key for c in CASE_TYPES],
        default=None,
        help="Forcer un type de cas précis",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_reports(
        count=args.count,
        output_dir=args.output_dir,
        template_path=args.template_path,
        seed=args.seed,
        case_type=args.case_type,
    )
