# CAMPEX

CAMPEX e uma plataforma local de visao operacional para cameras, areas produtivas, eventos, alertas, relatorios e execucao Edge. A arvore canonica do projeto agora vive na raiz deste repositorio.

## Entradas principais

### Backend local

```powershell
python -m app.main
```

Alternativa pelo gerenciador:

```powershell
python manage.py serve
```

Por padrao, a API FastAPI usa `127.0.0.1:8000`. O banco SQLite local vem de `DATABASE_PATH`; se a variavel nao existir, o projeto usa `data/visual_ops_product.sqlite3`.

### Frontend

O frontend nao tem build npm separado. As paginas em `frontend/` sao servidas pelo backend FastAPI.

Principais telas:

- `/`
- `/operations-view`
- `/cameras`
- `/events`
- `/alerts`
- `/evidence`
- `/reports`
- `/live-view`
- `/live-grid`
- `/operations`
- `/people-zones`
- `/local-diagnostics`

### Edge de producao

```powershell
python manage.py edge-run --edge-id <EDGE_ID>
```

O runtime de producao usa `app.edge_runtime.ProductionEdgeRuntime`. Os modulos em `edge_agent/` continuam preservados para compatibilidade, conectores e diagnosticos.

### Cloud

```powershell
python -m cloud.main
```

Use porta diferente da API local quando rodar no mesmo host, por exemplo via variavel `PORT`.

## Configuracao

Copie `.env.example` para `.env` quando precisar configurar credenciais e caminhos locais. Valores sensiveis devem ficar fora do Git.

Variaveis importantes:

- `DATABASE_PATH`
- `CAMPEX_EVIDENCE_DIR`
- `CAMPEX_ENV_FILE`
- `CAMPEX_EMAIL_MODE`
- `API_HOST`
- `API_PORT`

## Testes

```powershell
python -m pytest tests -q
```

No Windows, o baseline atual tem falhas herdadas registradas em `docs/consolidation/BASELINE_TESTS.md`. A consolidacao nao altera contratos de API nem ajusta testes apenas para mascarar essas falhas.

## Documentacao de consolidacao

Os relatorios da consolidacao ficam em `docs/consolidation/`:

- `REPOSITORY_INVENTORY.md`
- `BRANCH_ANALYSIS.md`
- `CURRENT_ARCHITECTURE.md`
- `FEATURE_MATRIX.md`
- `DUPLICATION_MAP.md`
- `DEPENDENCY_SECURITY_AUDIT.md`
- `CONSOLIDATION_PLAN.md`
- `BASELINE_TESTS.md`
- `FINAL_REPORT.md`

O README historico anterior foi preservado em `docs/archive/historical/README_CAMPEX_OPERATIONS_HISTORY.md`.
