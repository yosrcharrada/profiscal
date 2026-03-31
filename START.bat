@echo off
echo ================================================
echo   FiscalPRO — Plateforme Fiscale Tunisienne
echo ================================================
echo.

REM Check .NET SDK
dotnet --version >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERREUR] .NET SDK non trouve. Installez depuis: https://dotnet.microsoft.com/download
  pause
  exit /b 1
)

echo [1/3] Restauration des packages NuGet...
dotnet restore
if %errorlevel% neq 0 (
  echo [ERREUR] dotnet restore a echoue.
  pause
  exit /b 1
)

echo.
echo [2/3] Build du projet...
dotnet build -c Release --no-restore
if %errorlevel% neq 0 (
  echo [ERREUR] Build a echoue.
  pause
  exit /b 1
)

echo.
echo [3/3] Lancement de FiscalPRO...
echo.
echo   >>> Ouvrez http://localhost:5000 dans votre navigateur <<<
echo.
echo   Services requis:
echo     - Elasticsearch : http://localhost:9200
echo     - Neo4j         : neo4j://127.0.0.1:7687
echo     - Ollama        : http://localhost:11434  (optionnel)
echo.
dotnet run --no-build -c Release
pause
