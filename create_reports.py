"""
create_reports.py
Generate realistic Tunisian tax consultation reports grounded in Neo4j GraphRAG.

Key improvements:
1. [NOM_CLIENT] and [MM/AA] replaced in textboxes (header/footer)
2. [ABREVIATIONS] extracted from LLM response
3. Neo4j chunks used in ANALYSES (where logic/answers go)
4. Realistic 1.2 Étendue with article citations
5. 3. Sommaire Exécutif with conclusions
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> None:
        return None

try:
    from neo4j import GraphDatabase
except ImportError:
    GraphDatabase = None

from config import get_config

try:
    from openai import AzureOpenAI
except ImportError:
    AzureOpenAI = None

load_dotenv()

# ============================================================================
# CONFIGURATION
# ============================================================================

_MAX_CHUNK_TEXT_CHARS = 600
_DEDUP_HASH_LENGTH = 16
_LLM_TIMEOUT_SECONDS = 120.0


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class LegalSource:
    """Represents one chunk of legal text from Neo4j."""
    doc_name: str
    page_num: int
    article_ref: str
    section_title: str
    text: str
    score: float
    year: int = 0

    def short_ref(self) -> str:
        """Return a short reference string (e.g., 'CTVA 2024 — p.42 — Art. 3')."""
        article = self.article_ref.strip() if self.article_ref else ""
        parts = [self.doc_name]
        if self.year:
            parts.append(str(self.year))
        parts.append(f"p.{self.page_num}")
        if article:
            parts.append(article)
        return " — ".join(parts)


@dataclass
class ConsultationScenario:
    """All facts needed to generate one consultation report."""
    idx: int
    reference: str
    case_label: str
    client_type: str
    client_name: str
    client_description: str
    situation: str
    objective: str
    topics: Tuple[str, ...]
    extra_topics: Tuple[str, ...] = field(default_factory=tuple)


# ============================================================================
# 10 DISTINCT SCENARIOS
# ============================================================================

SCENARIOS: Tuple[ConsultationScenario, ...] = (
    ConsultationScenario(
        idx=1,
        reference="CONS-2024-001",
        case_label="saas_usa",
        client_type="entreprise",
        client_name="TechPark Innovations SARL",
        client_description=(
            "TechPark Innovations SARL est une société tunisienne spécialisée dans le "
            "développement de solutions ERP pour PME, immatriculée à Tunis, soumise à "
            "l'impôt sur les sociétés au taux normal."
        ),
        situation=(
            "La société souhaite acquérir un abonnement annuel à un logiciel SaaS "
            "(Microsoft Azure & Salesforce) auprès de fournisseurs résidant aux États-Unis, "
            "pour un montant estimé à 480 000 TND/an. Aucun établissement stable de ces "
            "fournisseurs n'existe en Tunisie."
        ),
        objective=(
            "Déterminer le traitement TVA applicable (territorialité, auto-liquidation), "
            "l'obligation de retenue à la source sur les paiements à l'étranger, et les "
            "obligations déclaratives associées (CDPF, formulaires douaniers)."
        ),
        topics=("tva", "retenue", "source", "non-résident", "prestation", "service"),
        extra_topics=("importation", "cdpf", "ctva", "territoire"),
    ),
    ConsultationScenario(
        idx=2,
        reference="CONS-2024-002",
        case_label="equipment_germany",
        client_type="entreprise",
        client_name="Carthage Industries SA",
        client_description=(
            "Carthage Industries SA est un groupe industriel tunisien fabriquant des "
            "composants mécaniques pour l'automobile, coté à la Bourse des Valeurs "
            "Mobilières de Tunis, réalisant un chiffre d'affaires annuel de 45 M TND."
        ),
        situation=(
            "La société prévoit l'acquisition de machines-outils CNC auprès d'un "
            "fabricant allemand (Trumpf GmbH) pour 2,1 M EUR. Le contrat prévoit en outre "
            "une prestation de mise en service et de formation réalisée par des techniciens "
            "allemands sur site tunisien pendant 6 semaines."
        ),
        objective=(
            "Analyser le régime TVA à l'importation, la retenue à la source sur la "
            "prestation de services, les droits de douane, et l'incidence éventuelle de "
            "la convention fiscale franco-allemande/tunisienne."
        ),
        topics=("tva", "importation", "retenue", "source", "douane", "prestation"),
        extra_topics=("convention", "établissement stable", "cdpf"),
    ),
    ConsultationScenario(
        idx=3,
        reference="CONS-2024-003",
        case_label="dg_francais",
        client_type="particulier",
        client_name="M. Laurent Dupont",
        client_description=(
            "M. Laurent Dupont est un ressortissant français, résidant à Paris, "
            "nommé Directeur Général d'une filiale tunisienne d'un groupe pharmaceutique "
            "français (Pharma Med Tunisie SARL). Il intervient en Tunisie 3 jours par "
            "semaine et perçoit sa rémunération exclusivement de la maison mère en France."
        ),
        situation=(
            "M. Dupont perçoit un salaire mensuel de 18 000 EUR versé par la maison mère "
            "française. La filiale tunisienne lui rembourse uniquement ses frais de déplacement. "
            "Il n'a pas de visa de travail tunisien ni de carte de séjour."
        ),
        objective=(
            "Déterminer son statut fiscal en Tunisie (résident / non-résident), "
            "l'imposition de sa rémunération au titre de l'IRPP tunisien, "
            "le régime des retenues à la source de la filiale, "
            "son statut au regard de la sécurité sociale, du change, "
            "et la nécessité d'un visa de travail."
        ),
        topics=("irpp", "résidence", "retenue", "source", "convention", "france"),
        extra_topics=("directeur", "non-résident", "change", "visa", "travail"),
    ),
    ConsultationScenario(
        idx=4,
        reference="CONS-2024-004",
        case_label="remote_worker_uae",
        client_type="particulier",
        client_name="Mme Sana Mejri",
        client_description=(
            "Mme Sana Mejri est une développeuse tunisienne résidant à Tunis, "
            "travaillant en tant que consultante indépendante pour une entreprise "
            "tech basée à Dubaï (UAE). Elle facture directement en USD depuis la Tunisie."
        ),
        situation=(
            "Mme Mejri réside en Tunisie plus de 183 jours par an. Elle perçoit 5 000 USD "
            "par mois d'une société émiratie sans présence en Tunisie. Les fonds sont "
            "rapatriés via virement bancaire international sur un compte tunisien. "
            "Elle n'a ni statut d'entreprise, ni inscription à la patente."
        ),
        objective=(
            "Établir son obligation déclarative IRPP en Tunisie, le régime de change "
            "applicable (obligation de rapatriement), la TVA sur prestations exportées, "
            "et l'opportunité de créer une structure juridique (SARL, entreprise individuelle)."
        ),
        topics=("irpp", "résidence", "change", "tva", "exportation", "prestation"),
        extra_topics=("convention", "rapatriement", "devises", "indépendant"),
    ),
    ConsultationScenario(
        idx=5,
        reference="CONS-2024-005",
        case_label="management_fees",
        client_type="entreprise",
        client_name="Groupe Méditerranée Holding (filiale tunisienne : Med Services SARL)",
        client_description=(
            "Med Services SARL est la filiale tunisienne d'un groupe français coté. "
            "La société mère française facture des « management fees » (services de "
            "direction générale, IT, finance) à la filiale tunisienne depuis 3 ans."
        ),
        situation=(
            "La maison mère française (Méditerranée Holding SA) facture annuellement "
            "1,2 M TND de management fees à Med Services SARL, soit 8 % du chiffre "
            "d'affaires de la filiale. Aucune documentation de prix de transfert n'a "
            "été établie à ce jour. L'administration fiscale a ouvert un contrôle."
        ),
        objective=(
            "Analyser la déductibilité des management fees au titre de l'IS, "
            "les exigences documentaires prix de transfert (art. CDPF), "
            "le risque de redressement, la retenue à la source applicable, "
            "et les mesures correctives à mettre en place."
        ),
        topics=("prix de transfert", "management fees", "déductibilité", "is"),
        extra_topics=("intra-groupe", "comparables", "retenue", "cdpf", "contrôle"),
    ),
    ConsultationScenario(
        idx=6,
        reference="CONS-2024-006",
        case_label="ip_royalties",
        client_type="entreprise",
        client_name="TunisTech SARL",
        client_description=(
            "TunisTech SARL est une PME tunisienne éditrice de logiciels, filiale à 70 % "
            "d'une holding néerlandaise (NLTech BV). La holding détient la propriété "
            "intellectuelle (marque, logiciels) et autorise la filiale à les exploiter."
        ),
        situation=(
            "TunisTech SARL verse chaque année 15 % de son chiffre d'affaires à NLTech BV "
            "au titre de redevances de licence de marque et de logiciels. Le taux a été "
            "fixé par contrat sans étude de comparables. NLTech BV n'a pas d'établissement "
            "stable en Tunisie."
        ),
        objective=(
            "Apprécier la déductibilité des redevances (IS), la retenue à la source "
            "sur les paiements (convention Tunisie-Pays-Bas), le risque prix de transfert "
            "sur le taux de 15 %, la TVA applicable, et les obligations documentaires."
        ),
        topics=("redevance", "propriété intellectuelle", "retenue", "source", "convention"),
        extra_topics=("prix de transfert", "is", "tva", "déductibilité"),
    ),
    ConsultationScenario(
        idx=7,
        reference="CONS-2024-007",
        case_label="doctor_sarl",
        client_type="mixte",
        client_name="Dr. Hedi Ben Salah / Clinique Lumière SARL",
        client_description=(
            "Dr. Hedi Ben Salah est médecin spécialiste (cardiologue) exerçant à la fois "
            "en cabinet libéral à titre personnel et en tant que gérant associé unique "
            "de Clinique Lumière SARL, clinique privée qu'il a créée en 2018."
        ),
        situation=(
            "Dr. Ben Salah perçoit des honoraires personnels pour consultations en cabinet "
            "(200 K TND/an) et une rémunération de gérance de la clinique (150 K TND/an). "
            "La clinique est soumise à la TVA au taux réduit pour les actes médicaux. "
            "Il envisage d'apporter son cabinet à la SARL et de se salarier."
        ),
        objective=(
            "Comparer le régime IRPP (revenus libéraux vs rémunération gérance), "
            "la déductibilité des rémunérations du gérant en matière d'IS, "
            "le régime TVA des honoraires médicaux, et l'intérêt de la restructuration envisagée."
        ),
        topics=("irpp", "is", "gérance", "rémunération", "tva", "médecin", "honoraires"),
        extra_topics=("retenue", "source", "dividendes", "libéral"),
    ),
    ConsultationScenario(
        idx=8,
        reference="CONS-2024-008",
        case_label="hr_consultant_mix",
        client_type="mixte",
        client_name="Mme Fatma Chaabane / RH Partners SARL",
        client_description=(
            "Mme Fatma Chaabane est consultante RH indépendante. Elle a créé RH Partners SARL "
            "en 2022. Elle facture ses missions via la société mais perçoit également des "
            "honoraires à titre personnel d'entreprises qui préfèrent contractualiser "
            "directement avec elle."
        ),
        situation=(
            "En 2024, RH Partners SARL a réalisé 320 K TND de CA (IS) et Mme Chaabane "
            "a perçu 90 K TND d'honoraires personnels (IRPP BNC). Elle est aussi "
            "administratrice d'une SA cotée et perçoit des jetons de présence. "
            "Les retenus à la source effectuées varient selon les clients payeurs."
        ),
        objective=(
            "Analyser la qualification fiscale des honoraires personnels vs revenus SARL, "
            "le régime des jetons de présence (retenue, IS, IRPP), "
            "les risques d'abus de droit pour double flux, "
            "et l'optimisation de la structure de rémunération."
        ),
        topics=("irpp", "is", "honoraires", "retenue", "jetons de présence", "bnc"),
        extra_topics=("abus de droit", "tva", "rémunération", "gérance"),
    ),
    ConsultationScenario(
        idx=9,
        reference="CONS-2024-009",
        case_label="digital_services_vat",
        client_type="entreprise",
        client_name="StreamTN (filiale tunisienne de StreamGlobal BV)",
        client_description=(
            "StreamGlobal BV est une plateforme néerlandaise de streaming vidéo. "
            "Elle a créé StreamTN, filiale tunisienne, pour facturer ses abonnements "
            "aux clients résidents en Tunisie depuis janvier 2024."
        ),
        situation=(
            "StreamTN facture des abonnements mensuels (15 TND/mois) à 45 000 abonnés "
            "tunisiens. Les services sont entièrement dématérialisés. La maison mère "
            "percevait auparavant ces abonnements directement depuis les Pays-Bas sans "
            "TVA tunisienne. La filiale s'interroge sur ses obligations TVA, IS et retenue."
        ),
        objective=(
            "Déterminer l'assujettissement TVA des services numériques (territorialité, "
            "taux applicable), le régime IS de la filiale, les obligations déclaratives "
            "et de facturation électronique, et la situation avant création de la filiale."
        ),
        topics=("tva", "services numériques", "territoire", "abonnement", "électronique"),
        extra_topics=("is", "retenue", "facturation", "non-résident", "prestation"),
    ),
    ConsultationScenario(
        idx=10,
        reference="CONS-2024-010",
        case_label="btp_etablissement_stable",
        client_type="entreprise",
        client_name="BuildCon Belgium SA (chantier Tunisie)",
        client_description=(
            "BuildCon Belgium SA est une société de BTP belge spécialisée dans la "
            "construction de centrales solaires. Elle a remporté un appel d'offres "
            "pour la construction d'une centrale photovoltaïque en Tunisie."
        ),
        situation=(
            "Les travaux ont débuté en mars 2024 et dureront 14 mois. BuildCon Belgium "
            "importe du matériel et fait intervenir 40 techniciens belges sur le chantier. "
            "Elle sous-traite 30 % des travaux à des entreprises tunisiennes locales. "
            "Elle n'a pas de structure juridique en Tunisie mais dispose d'une direction "
            "locale permanente sur le chantier."
        ),
        objective=(
            "Établir l'existence ou non d'un établissement stable en Tunisie "
            "(convention Belgique-Tunisie), le régime IS applicable, les retenues à la "
            "source sur paiements aux sous-traitants, les obligations TVA, douanières "
            "et les formalités administratives requises."
        ),
        topics=("établissement stable", "chantier", "convention", "belgique", "is", "retenue"),
        extra_topics=("tva", "importation", "sous-traitant", "btp", "travaux"),
    ),
)


# ============================================================================
# NEO4J SERVICE
# ============================================================================

class Neo4jContextService:
    """Retrieves legal chunks from Neo4j."""

    _CHUNK_QUERY = """
    MATCH (c:Chunk)
    WHERE any(t IN $topics
              WHERE toLower(c.text) CONTAINS toLower(t)
                 OR toLower(coalesce(c.article_ref,'')) CONTAINS toLower(t)
                 OR toLower(coalesce(c.section_title,'')) CONTAINS toLower(t)
                 OR toLower(coalesce(c.doc_name,'')) CONTAINS toLower(t))
    WITH c,
         reduce(s = 0.0, t IN $topics |
             s + CASE 
                WHEN toLower(c.text) CONTAINS toLower(t) THEN 2.0
                WHEN toLower(c.article_ref) CONTAINS toLower(t) THEN 1.5
                WHEN toLower(c.section_title) CONTAINS toLower(t) THEN 1.0
                WHEN toLower(c.doc_name) CONTAINS toLower(t) THEN 0.5
                ELSE 0.0 
             END
        ) AS score
    WHERE score > 0
    RETURN c.doc_name     AS doc_name,
           coalesce(c.page_num, 0)        AS page_num,
           coalesce(c.article_ref, '')    AS article_ref,
           coalesce(c.section_title, '')  AS section_title,
           coalesce(c.text, '')           AS text,
           0                              AS year,
           score
    ORDER BY score DESC, c.doc_name ASC, c.page_num ASC
    LIMIT $limit
    """

    def __init__(self) -> None:
        cfg = get_config()
        self.database = cfg["neo4j_database"]
        self.driver = None
        
        if GraphDatabase is not None:
            try:
                self.driver = GraphDatabase.driver(
                    cfg["neo4j_uri"], 
                    auth=(cfg["neo4j_username"], cfg["neo4j_password"])
                )
                with self.driver.session(database=self.database) as session:
                    session.run("RETURN 1")
                print(f"✅ Neo4j connected to database '{self.database}'")
            except Exception as e:
                print(f"⚠️  Neo4j connection failed: {e}")
                self.driver = None

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()

    def _run_chunk_query(self, topics: Sequence[str], limit: int) -> List[LegalSource]:
        if self.driver is None:
            return []
        
        try:
            with self.driver.session(database=self.database) as session:
                rows = session.run(
                    self._CHUNK_QUERY,
                    topics=[t.lower() for t in topics],
                    limit=limit,
                )
                return [LegalSource(**dict(row)) for row in rows]
        except Exception as e:
            print(f"⚠️  Neo4j query failed: {e}")
            return []

    def get_chunks_for_scenario(self, scenario: ConsultationScenario) -> List[LegalSource]:
        primary = self._run_chunk_query(scenario.topics, limit=8)
        secondary = self._run_chunk_query(
            scenario.topics + scenario.extra_topics, limit=6
        ) if scenario.extra_topics else []
        
        all_sources = primary + secondary
        seen: Dict[str, bool] = {}
        deduped: List[LegalSource] = []
        
        for s in all_sources:
            key = hashlib.sha256(s.text.strip().encode("utf-8")).hexdigest()[:_DEDUP_HASH_LENGTH]
            if key not in seen:
                seen[key] = True
                deduped.append(s)
        
        return deduped[:10]


# ============================================================================
# AZURE OPENAI SERVICE
# ============================================================================

class AzureOpenAIService:
    """Calls Azure OpenAI API."""

    SYSTEM_PROMPT = (
        "Tu es un expert fiscal tunisien senior dans un grand cabinet de conseil international. "
        "Tu rédiges des consultations fiscales professionnelles et réalistes en français. "
        "Tu dois TOUJOURS citer explicitement les articles de loi, codes et conventions utilisés. "
        "Utilise UNIQUEMENT les extraits légaux fournis ou ce que tu connais du droit tunisien avéré. "
        "Ne fabrique pas de références légales fictives."
    )

    def __init__(self) -> None:
        self.model = os.getenv("LLM_MODEL", "gpt-4o")
        self.client: Optional[object] = None
        
        if AzureOpenAI is not None:
            api_key = os.getenv("OPENAI_API_KEY", "")
            endpoint = os.getenv("OPENAI_ENDPOINT", "")
            api_version = os.getenv("OPENAI_API_VERSION", "2024-02-15-preview")
            
            if api_key and endpoint:
                try:
                    self.client = AzureOpenAI(
                        api_key=api_key,
                        azure_endpoint=endpoint,
                        api_version=api_version,
                    )
                    print(f"✅ Azure OpenAI initialized (model: {self.model})")
                except Exception as e:
                    print(f"⚠️  Azure OpenAI init failed: {e}")

    def is_available(self) -> bool:
        return self.client is not None

    def generate(self, user_prompt: str, temperature: float = 0.7) -> str:
        if self.client is None:
            raise RuntimeError("Azure OpenAI not available")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                timeout=_LLM_TIMEOUT_SECONDS,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"⚠️  LLM call failed: {str(e)[:200]}")
            raise RuntimeError(f"LLM call failed: {e}") from e


# ============================================================================
# CONTEXT & PROMPT BUILDERS
# ============================================================================

def build_legal_context(sources: Sequence[LegalSource]) -> str:
    """Format Neo4j chunks with metadata."""
    if not sources:
        return "(Aucun extrait légal disponible.)"
    
    lines: List[str] = []
    for i, s in enumerate(sources, 1):
        ref = s.article_ref.strip() if s.article_ref else "—"
        title = s.section_title.strip() if s.section_title else ""
        
        lines.append(
            f"[Extrait {i} | {s.doc_name}, p.{s.page_num} | Art. {ref}"
            f"{' | ' + title if title else ''}]"
        )
        
        text = s.text.strip()
        if len(text) > _MAX_CHUNK_TEXT_CHARS:
            text = text[:_MAX_CHUNK_TEXT_CHARS] + "…"
        
        lines.append(text)
        lines.append("")
    
    return "\n".join(lines)


SECTION_PROMPT_TEMPLATE = """\
=== CONSULTATION FISCALE ===
Référence: {reference}
Client: {client_name} ({client_type})

SITUATION:
{situation}

OBJECTIF:
{objective}

=== EXTRAITS LÉGAUX (utilisez ces sources dans l'ANALYSE) ===
{legal_context}

=== INSTRUCTIONS POUR LA GÉNÉRATION ===

Rédige 5 sections avec ces TITRES EXACTS:

--- SECTION 1 : COMPRÉHENSION DES FAITS ---
Rédige "1.1 Notre compréhension des faits" (300+ mots).
Contexte général: qui est le client, quelle est son activité, d'où/comment achète-t-il, montants impliqués.
Cite les articles de loi applicables (ex. "conformément à l'article 52 du CDPF").

--- SECTION 2 : ÉTENDUE DES TRAVAUX ---
Rédige "1.2 Étendue de nos travaux" (250+ mots).
Format: "Notre analyse portera sur les aspects suivants :" puis liste numérotée de 8-12 points avec articles.
Exemple de format:
1) Régime des rémunérations en matière d'impôt sur les sociétés (articles XXX du CGI)
2) Traitement TVA applicable (articles YYY du CTVA)
3) Obligation de retenue à la source (article ZZZ du CIRPPIS)
[etc.]

--- SECTION 3 : SOMMAIRE EXÉCUTIF ---
Rédige "3. Sommaire Exécutif" (400+ mots).
3-5 paragraphes synthétisant les enjeux et conclusions principales.
Cite les articles/textes utilisés. Inclus un tableau de risques:
| Risque identifié | Probabilité | Impact | Mesure recommandée |
|---|---|---|---|
[4-6 lignes]

--- SECTION 4 : ANALYSES DÉTAILLÉES ---
Rédige "4. Analyses détaillées" (700+ mots).
Utilise les extraits légaux fournis.
Format: Crée un tableau Q&A:
| Question | Règle applicable | Analyse et conclusion |
|---|---|---|
[6-8 lignes avec citations directes des extraits]

--- SECTION 5 : DOCUMENTS ET RÉFÉRENCES ---
Rédige "5. Documents et Références" (150+ mots).
Liste TOUTES les abréviations utilisées dans le document avec leur développement complet.
Inclus aussi les documents communiqués et sources légales.

=== FIN ===
"""


def build_prompt(scenario: ConsultationScenario, legal_context: str) -> str:
    return SECTION_PROMPT_TEMPLATE.format(
        reference=scenario.reference,
        client_name=scenario.client_name,
        client_type=scenario.client_type,
        situation=scenario.situation,
        objective=scenario.objective,
        legal_context=legal_context,
    )


# ============================================================================
# LLM RESPONSE PARSER
# ============================================================================

def extract_abbreviations(text: str) -> str:
    """Extract abbreviations section from LLM response."""
    # Look for section 5 / DOCUMENTS / ABRÉVIATIONS
    patterns = [
        r"--- SECTION 5.*?ABRÉVIATIONS.*?:\s*(.*?)(?=---|$)",
        r"5\.\s*DOCUMENTS.*?ABRÉVIATIONS.*?:\s*(.*?)(?=5\.|$)",
        r"ABRÉVIATIONS\s*:\s*(.*?)(?=---|Sources|$)",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            abbrev_text = match.group(1).strip()
            if len(abbrev_text) > 100:  # Reasonable length
                return abbrev_text
    
    # Fallback: return empty list marker
    return ""


def parse_llm_response(llm_text: str) -> Dict[str, str]:
    """Parse LLM response into sections."""
    sections = {
        "FAITS": "",
        "ETENDUE": "",
        "SOMMAIRE_EXECUTIF": "",
        "ANALYSES": "",
        "ABREVIATIONS": "",
    }
    
    # Extract COMPRÉHENSION DES FAITS (Section 1.1)
    match = re.search(
        r"--- SECTION 1.*?COMPRÉHENSION.*?\n(.*?)--- SECTION 2",
        llm_text,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        sections["FAITS"] = match.group(1).strip()
    
    # Extract ÉTENDUE DES TRAVAUX (Section 1.2)
    match = re.search(
        r"--- SECTION 2.*?ÉTENDUE.*?\n(.*?)--- SECTION 3",
        llm_text,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        sections["ETENDUE"] = match.group(1).strip()
    
    # Extract SOMMAIRE EXÉCUTIF (Section 3)
    match = re.search(
        r"--- SECTION 3.*?SOMMAIRE.*?\n(.*?)--- SECTION 4",
        llm_text,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        sections["SOMMAIRE_EXECUTIF"] = match.group(1).strip()
    
    # Extract ANALYSES (Section 4)
    match = re.search(
        r"--- SECTION 4.*?ANALYSES.*?\n(.*?)--- SECTION 5",
        llm_text,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        sections["ANALYSES"] = match.group(1).strip()
    
    # Extract ABREVIATIONS (Section 5)
    sections["ABREVIATIONS"] = extract_abbreviations(llm_text)
    
    return sections


# ============================================================================
# XML MANIPULATION FOR DOCX
# ============================================================================

def xml_escape(s: str) -> str:
    """Escape XML special characters."""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;"))


def replacement_runs(text: str) -> str:
    """Build WordML runs with <w:br/> for newlines."""
    text = xml_escape(text)
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        out.append(f'<w:r><w:t xml:space="preserve">{line}</w:t></w:r>')
        if i != len(lines) - 1:
            out.append("<w:r><w:br/></w:r>")
    return "".join(out)


def replace_token_in_xml(xml: str, token: str, new_text: str) -> str:
    """Replace token in paragraph runs."""
    p_pat = re.compile(r"(<w:p\b[^>]*>)(.*?)(</w:p>)", re.DOTALL)
    t_pat = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.DOTALL)

    def repl_p(m):
        start, inner, end = m.group(1), m.group(2), m.group(3)
        flat = "".join(t_pat.findall(inner))
        if token not in flat:
            return m.group(0)
        replaced = flat.replace(token, new_text)
        return start + replacement_runs(replaced) + end

    return p_pat.sub(repl_p, xml)


def replace_token_in_textbox(xml: str, token: str, new_text: str) -> str:
    """Replace token in textbox (header/footer)."""
    txbx_pat = re.compile(r"(<w:txbxContent\b[^>]*>)(.*?)(</w:txbxContent>)", re.DOTALL)
    t_pat = re.compile(r"<w:t\b[^>]*>(.*?)</w:t>", re.DOTALL)

    def repl_box(m):
        start, inner, end = m.group(1), m.group(2), m.group(3)
        flat = "".join(t_pat.findall(inner))
        if token not in flat:
            return m.group(0)
        flat = flat.replace(token, new_text)
        new_inner = f"<w:p>{replacement_runs(flat)}</w:p>"
        return start + new_inner + end

    return txbx_pat.sub(repl_box, xml)


def modify_docx_template(
    template_path: Path,
    output_path: Path,
    client_name: str,
    mm_aa: str,
    tokens: Dict[str, str]
) -> None:
    """Modify template by replacing tokens."""
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    
    with zipfile.ZipFile(template_path, "r") as zin:
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if item.filename.startswith("word/") and item.filename.endswith(".xml"):
                    try:
                        xml = data.decode("utf-8")
                    except UnicodeDecodeError:
                        xml = data.decode("utf-16")

                    # Replace textbox tokens (header/footer with yellow background)
                    xml = replace_token_in_textbox(xml, "[NOM_CLIENT]", client_name)
                    xml = replace_token_in_textbox(xml, "[MM/AA]", mm_aa)

                    # Replace body tokens
                    for token_key, token_value in tokens.items():
                        token_placeholder = f"[{token_key}]"
                        xml = replace_token_in_xml(xml, token_placeholder, token_value)

                    data = xml.encode("utf-8")

                zout.writestr(item, data)


# ============================================================================
# MAIN GENERATION LOOP
# ============================================================================

def generate_reports(
    count: int,
    output_dir: Path,
    template_path: Optional[Path],
) -> None:
    """Generate multiple consultation reports."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if count > len(SCENARIOS):
        print(f"⚠️  count={count} exceeds {len(SCENARIOS)} scenarios")
        count = len(SCENARIOS)

    neo4j = Neo4jContextService()
    llm = AzureOpenAIService()

    if not llm.is_available():
        print("⚠️  Azure OpenAI not configured")

    try:
        for scenario in SCENARIOS[:count]:
            print(f"\n📄 [{scenario.idx}/{count}] {scenario.reference} — {scenario.client_name}")

            # Get today's date for [MM/AA] token
            today = dt.date.today()
            mm_aa = today.strftime("%m/%y")

            # Retrieve Neo4j chunks
            try:
                sources = neo4j.get_chunks_for_scenario(scenario)
                print(f"   🔍 Neo4j: {len(sources)} legal chunks retrieved")
            except Exception as exc:
                print(f"   ⚠️  Neo4j failed: {exc}")
                sources = []

            # Build context from chunks
            legal_context = build_legal_context(sources)

            # Call LLM
            if llm.is_available():
                print("   🤖 Calling LLM…")
                try:
                    prompt = build_prompt(scenario, legal_context)
                    llm_text = llm.generate(prompt, temperature=0.7)
                    print("   ✅ LLM response received")
                except Exception as exc:
                    print(f"   ⚠️  {exc}")
                    llm_text = ""
            else:
                llm_text = ""

            if not llm_text:
                print(f"   ❌ No content generated")
                continue

            # Parse response into sections
            sections = parse_llm_response(llm_text)

            # Create tokens for replacement
            tokens = {
                "FAITS": sections.get("FAITS", ""),
                "ETENDUE": sections.get("ETENDUE", ""),
                "ANALYSES": sections.get("ANALYSES", ""),
                "ABREVIATIONS": sections.get("ABREVIATIONS", ""),
            }

            # Modify and save template
            file_stem = f"Consultation_{scenario.reference}_{scenario.case_label}"
            output_path = output_dir / f"{file_stem}.docx"

            if template_path and template_path.exists():
                try:
                    modify_docx_template(
                        template_path,
                        output_path,
                        scenario.client_name,
                        mm_aa,
                        tokens
                    )
                    print(f"   💾 Saved: {output_path}")
                except Exception as exc:
                    print(f"   ❌ Failed: {exc}")
            else:
                print(f"   ⚠️  Template not found")

    finally:
        neo4j.close()

    print(f"\n✅ Done — {count} consultations generated in '{output_dir}'")


# ============================================================================
# CLI
# ============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Neo4j-grounded Tunisian tax consultations"
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=Path("generated_consultations"))
    parser.add_argument("--template-path", type=Path, default=Path("template_fr.docx"))
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_reports(
        count=args.count,
        output_dir=args.output_dir,
        template_path=args.template_path,
    )
