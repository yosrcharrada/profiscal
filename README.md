# FiscalPRO — Plateforme Juridique & Fiscale Tunisienne

Une plateforme .NET 8 qui fusionne votre moteur de recherche Elasticsearch (BM25/fuzzy)
et votre chatbot GraphRAG Neo4j en une interface professionnelle inspirée de DBProfiscal.

---

## Architecture

```
FiscalPlatform/
├── Controllers/
│   └── Controllers.cs          # HomeController, SearchController, ChatController, StatsController
├── Models/
│   └── Models.cs               # SearchRequest/Response, ChatRequest/Response, KnowledgeBaseStats
├── Services/
│   ├── ElasticsearchService.cs # BM25 + fuzzy search, highlight, aggregations
│   ├── Neo4jService.cs         # Stats, vector search (GNN), graph expansion, keyword fallback
│   └── GraphRagService.cs      # Orchestration: embed → retrieve → rank → LLM
├── Views/
│   └── Home/
│       └── Index.cshtml        # Full SPA — search engine + chatbot
├── Program.cs
├── appsettings.json
└── FiscalPlatform.csproj
```

## Prérequis

- **.NET 8 SDK** : https://dotnet.microsoft.com/download/dotnet/8
- **Elasticsearch 8.x** déjà lancé (votre projet search engine existant)
- **Neo4j** avec le graphe déjà construit (`tunisian-fiscal-tables`)
- **Ollama** (optionnel, pour réponses LLM) : https://ollama.com

---

## Installation rapide

### 1. Cloner / copier le projet

```bash
cd FiscalPlatform
```

### 2. Configurer appsettings.json

Éditez `appsettings.json` avec vos valeurs :

```json
{
  "Elasticsearch": {
    "Host": "http://localhost:9200",
    "Index": "tunisian_legal"
  },
  "Neo4j": {
    "Uri": "neo4j://127.0.0.1:7687",
    "Database": "tunisian-fiscal-tables",
    "Username": "neo4j",
    "Password": "neo4j123"
  },
  "Llm": {
    "Provider": "ollama",
    "Model": "phi3:mini",
    "OllamaHost": "http://localhost:11434"
  }
}
```

### 3. Restaurer les packages et lancer

```bash
dotnet restore
dotnet run
```

Accédez à : **http://localhost:5000**

---

## Services requis

### Elasticsearch (déjà fonctionnel dans votre projet search engine)
```batch
REM Votre START_ELASTICSEARCH.bat ou :
docker run -d -p 9200:9200 ^
  -e discovery.type=single-node ^
  -e xpack.security.enabled=false ^
  elasticsearch:8.13.0
```

### Neo4j (graphe déjà construit)
```
Démarrez Neo4j Desktop ou votre instance Neo4j
Base de données : tunisian-fiscal-tables
```

### Ollama (pour le LLM, optionnel)
```bash
ollama serve
ollama pull phi3:mini
# Pour les embeddings (recommandé) :
ollama pull nomic-embed-text
```

Si Ollama est absent, la plateforme affiche les sources brutes sans synthèse LLM.

---

## API Endpoints

| Méthode | Route              | Description                          |
|---------|--------------------|--------------------------------------|
| GET     | `/`                | Interface principale (SPA)           |
| POST    | `/api/search`      | Recherche BM25 + fuzzy Elasticsearch |
| GET     | `/api/search/health` | Statut Elasticsearch               |
| POST    | `/api/chat`        | Chatbot GraphRAG (Neo4j + LLM)       |
| GET     | `/api/chat/health` | Statut Neo4j                         |
| GET     | `/api/stats`       | Statistiques combinées ES + Neo4j    |

### Exemple POST /api/search

```json
{
  "query": "TVA retenue source",
  "docType": "all",
  "chunkType": "all",
  "size": 50
}
```

### Exemple POST /api/chat

```json
{
  "question": "Quels sont les taux de TVA applicables en 2024?",
  "history": []
}
```

---

## Pipeline GraphRAG (ChatController → GraphRagService)

```
Question utilisateur
       │
       ▼
 [EmbedAsync] ──── Ollama nomic-embed-text ──► float[]
       │                   (fallback: null)
       ▼
 [VectorSearch] ── Neo4j GNN index ──► top-8 chunks
       │           (fallback: text embedding index)
       ▼
 [GraphExpand] ─── Entity mentions ──► top-6 chunks supplémentaires
       │
       ▼
 [MergeAndRank] ── Déduplication + tri par score
       │
       ▼
 [BuildContext] ── Formatage des 8 meilleurs chunks
       │
       ▼
 [GenerateAnswer] ─ Ollama phi3:mini ──► Réponse en français
       │
       ▼
    ChatResponse (answer + sources + method + timing)
```

---

## Fonctionnalités

### Moteur de recherche
- BM25 avec paramètres personnalisés (k1=1.5, b=0.6)
- Fuzzy search (tolérance fautes de frappe, accents)
- Highlighting des mots-clés dans les résultats
- Top 5 résultats mis en avant, reste masqué
- Filtres : type de document, type de chunk
- Agrégations par type affiché comme tags
- Score bar de pertinence visuelle

### Chatbot GraphRAG
- Recherche vectorielle dans Neo4j (embeddings GNN 256-dim ou texte 768-dim)
- Expansion de graphe via les entités mentionnées
- Fallback keyword quand les embeddings sont indisponibles
- Synthèse LLM (Ollama phi3:mini)
- Historique de conversation (6 derniers échanges)
- Panel sources cliquables avec modal de texte complet
- Indicateur de méthode (vector / vector+graph / keyword)

### Interface
- Design inspiré DBProfiscal (navbar bleue marine, jaune doré)
- Sidebar avec statistiques en temps réel (ES + Neo4j)
- Deux onglets : Recherche / Assistant IA
- Points de statut verts/rouges (Elasticsearch, Neo4j)
- Toasts de notification
- Modal pour texte complet des sources
- Responsive (mobile : sidebar masquée)

### Génération de consultations fiscales (Neo4j-grounded)
- Script : `create_reports.py`
- Génère **10 consultations distinctes** (cas réalistes tunisiens) en `.docx`

**Pipeline par consultation :**
1. Sélection d'un scénario parmi 10 cas prédéfinis et entièrement différents
2. Récupération des chunks juridiques Neo4j pertinents (GraphRAG keyword scoring)
3. Construction d'un contexte légal réel (extraits de lois, articles, codes)
4. Appel Azure OpenAI avec le contexte Neo4j → génération des sections :
   - `1.1 Compréhension des faits`
   - `1.2 Étendue des travaux` (avec références d'articles)
   - `3. Sommaire exécutif` (conclusions fondées sur les textes + tableau de risques)
   - `4. Analyses` (tableau Q&A avec articles cités)
   - `5. Documents et références` + abréviations
5. Remplacement des tokens dans `template_fr.docx` → `.docx` final
   (crée un `.docx` structuré de zéro si le template est absent)

**Les 10 scénarios :**
| # | Cas | Profil |
|---|-----|--------|
| 1 | Achats SaaS USA | TechPark Innovations SARL — TVA, retenue IS, CDPF |
| 2 | Équipements Allemagne | Carthage Industries SA — TVA importation, retenue prestation |
| 3 | DG français en Tunisie | M. Laurent Dupont — IRPP, convention franco-tunisienne |
| 4 | Télétravailleur UAE | Mme Sana Mejri — IRPP, change, rapatriement |
| 5 | Management fees intra-groupe | Med Services SARL — Prix de transfert, déductibilité IS |
| 6 | Redevances PI (NL) | TunisTech SARL — Redevances, convention, retenue |
| 7 | Médecin / SARL | Dr. Ben Salah — IRPP libéral vs rémunération gérance |
| 8 | Consultante RH mix | Mme Chaabane — IRPP BNC + IS, jetons de présence |
| 9 | Services numériques TVA | StreamTN — TVA services dématérialisés |
| 10 | Chantier BTP belge | BuildCon Belgium — Établissement stable, IS, retenues |

**Variables d'environnement (`.env`) :**
```
# Azure OpenAI (même que GraphRagService.cs)
OPENAI_API_KEY=...
OPENAI_ENDPOINT=https://...
OPENAI_API_VERSION=2024-02-15-preview
LLM_MODEL=gpt-4o

# Neo4j
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_DATABASE=fiscal
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=neo4j123
```

**Utilisation :**
```bash
python create_reports.py --count 10 --template-path template_fr.docx --output-dir generated_consultations
```

---

## Publication (production)

```bash
dotnet publish -c Release -o ./publish
cd publish
dotnet FiscalPlatform.dll
```

Ou avec Docker :

```dockerfile
FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY publish/ .
EXPOSE 80
ENTRYPOINT ["dotnet", "FiscalPlatform.dll"]
```

---

## Dépendances NuGet

| Package              | Version  | Usage                    |
|----------------------|----------|--------------------------|
| Elasticsearch.Net    | 7.17.5   | Client HTTP Elasticsearch|
| NEST                 | 7.17.5   | ORM Elasticsearch        |
| Neo4j.Driver         | 5.18.0   | Client Neo4j Bolt        |
| Microsoft.Extensions.Http | 8.0.0 | HttpClientFactory      |

---

## Support

- **Elasticsearch down** : Le moteur de recherche affiche une erreur, le chatbot continue via Neo4j
- **Neo4j down** : Le chatbot affiche une erreur, la recherche continue via Elasticsearch  
- **Ollama down** : Le chatbot affiche les sources brutes sans synthèse LLM
- **GNN inactif** : Fallback automatique sur les embeddings texte standard
