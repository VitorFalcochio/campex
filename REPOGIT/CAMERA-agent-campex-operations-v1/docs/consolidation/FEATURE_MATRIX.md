# Matriz de features e arquitetura atual

## Runtime atual

O backend principal e FastAPI em pp/api.py, iniciado por python -m app.main, python manage.py serve ou scripts de inicializacao. O frontend e estatico em rontend/ e e servido pelo proprio backend. Nao ha projeto npm/package/build separado.

O Edge de producao roda por python manage.py edge-run --edge-id ... e usa pp.edge_runtime.ProductionEdgeRuntime, com threads de API/bootstrap, captura, inferencia, upload de latest frame, decisao operacional, outbox e retries. O modulo edge_agent.main e legado/diagnostico e nao substitui o runtime de producao.

## Matriz

| Dominio | Entrada principal | Dependencias internas | Status canonico |
|---|---|---|---|
| API principal | pp/main.py, pp/api.py | database, models, auth, live_stream, people_zones, operations/read models | KEEP |
| Frontend web | rontend/*.html, rontend/*.js, rontend/styles.css | rotas static do FastAPI | KEEP |
| Banco local | pp/database.py, pp/models.py | SQLite por DATABASE_PATH, migracoes/backfills em runtime | KEEP com cautela |
| Edge runtime | manage.py edge-run, pp/edge_runtime.py | edge_config, edge_service, edge_agent/sync_outbox, camera_rtsp | KEEP |
| Edge legado | edge_agent/main.py, conectores e workers | sync_outbox e health | KEEP como compatibilidade/diagnostico |
| Cloud | cloud/main.py, cloud/api.py | PostgreSQL via psycopg, migracao SQL | KEEP separado |
| MVP legado | mvp.py, isual_ops_mvp/ | sqlite/reports locais | KEEP como CLI historico |
| Observacao operacional | pp/observation_engine.py, machine_monitoring.py, people_zones.py | events, areas, samples, restricted_area | KEEP |
| IA/entendimento | pp/ai_provider.py, ideo_understanding.py, ecommendation_engine.py | OpenAI opcional, contratos auditaveis | KEEP |
| Relatorios/alertas | pp/report_delivery.py, pp/reports.py, pp/alerts.py | email console/cloud, outbox | KEEP |
| Deploy/instalacao | deployment/, scripts/, Dockerfile, compose | Windows/macOS/Linux service helpers | KEEP |
| Evidencias temporarias | 	mp/*.png, 	mp/db-backups/*.sqlite3 | artefatos historicos | ARCHIVE/UNTRACK candidato |

## Riscos conhecidos

- A suite atual tem falhas herdadas; a consolidacao nao deve mascarar nem editar testes para esconder falhas.
- Alguns testes esperam Chrome em caminho macOS e falham no Windows.
- Alguns testes mantem handles SQLite abertos no Windows durante limpeza de temporarios.
- pp/database.py executa migracoes/backfills no startup; qualquer teste deve usar DATABASE_PATH isolado.
