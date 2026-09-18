# Mapa de duplicidades

| Item | Classe | Decisao | Evidencia |
|---|---|---|---|
| camera vs operation | NEWER_VERSION | origin/agent/campex-operations-v1 canonica por fast-forward | main e ancestral direto; sem conflito. |
| operation/frontend/frontend/styles.css vs rontend/styles.css | SEMANTIC_DUPLICATE | ARCHIVE, nao copiar para canonico | Mesmo SHA-256 apos normalizar CRLF; nenhum HTML referencia rontend/frontend. |
| equirements-yolo.txt vs equirements.txt | DIFFERENT_PURPOSE | KEEP | Arquivo separado preserva instalacao opcional de YOLO. |
| mvp.py/isual_ops_mvp vs pp/* | DIFFERENT_PURPOSE | KEEP | CLI/historico legado continua separado do backend FastAPI. |
| edge_agent/main.py vs pp/edge_runtime.py | DIFFERENT_PURPOSE | KEEP | Edge legado/diagnostico e runtime de producao tem entradas distintas. |
|  context_config.json vs context_config.json | UNCERTAIN | ARCHIVE candidato futuro, sem remocao automatica | Nome com espaco inicial existe nas duas arvores; precisa validacao humana antes de exclusao. |
| 	mp/db-backups/*.sqlite3 | SECURITY_RUNTIME_ARTIFACT | UNTRACK/ARCHIVE local | Banco populado de backup nao deve ser empacotado em Docker/Git futuro. |
| 	mp/*.png | HISTORICAL_EVIDENCE | KEEP em docs/archive ou untrack futuro | Evidencias visuais historicas, sem impacto runtime. |
