# Relatorio final de consolidacao CAMPEX

Data: 2026-09-08

## Resultado

A arvore canonica do CAMPEX foi promovida para `C:\Projetos\Campex`.

- Repositorio Git ativo: `C:\Projetos\Campex`.
- Branch: `refactor/campex-consolidation`.
- HEAD canonico: `c38331cfdc8728e2c9c99b4b9823b88c9beab795`.
- Origem historica preservada: `main` em `a8128c6bd6cce1565a60f75834d69a9365f4632d`.
- Integracao de operacoes: fast-forward para `origin/agent/campex-operations-v1`.

## Antes

O workspace tinha duas estruturas concorrentes:

- `camera/`: unico repositorio Git, baseado na `main`.
- `operation/`: arvore de operacoes mais nova, equivalente a branch remota de operacoes, com um CSS extra fora do Git.

`C:\Projetos\Campex` nao era o repositorio Git antes da consolidacao.

## Depois

A raiz contem a aplicacao canonica:

- `app/`
- `cloud/`
- `deployment/`
- `docs/`
- `edge_agent/`
- `frontend/`
- `scripts/`
- `shared/`
- `tests/`
- `tools/`
- `visual_ops_mvp/`
- arquivos raiz de config, Docker, requisitos, CLI e README

As pastas locais antigas `camera/` e `operation/` foram adicionadas ao `.gitignore` e `.dockerignore` para nao competirem com a raiz canonica. O Windows negou `Move-Item` e `Rename-Item` em `operation/`; por isso ela ficou fisicamente preservada no workspace e tambem foi copiada para `archive/local/operation-pre-consolidation` com manifesto verificado.

## Preservacao

Arquivos de seguranca antes da consolidacao foram criados fora do repositorio em:

`%TEMP%\campex-consolidation-20260908\preservation`

Conteudo:

- bundle Git da base anterior;
- ZIP da arvore `operation`;
- manifesto SHA-256 pre-consolidacao.

Tambem foi criada copia local verificada de `operation/` em:

`archive/local/operation-pre-consolidation`

Essa pasta e ignorada pelo Git.

## Seguranca

O backup SQLite `tmp/db-backups/visual_ops_product_before_cleanup.sqlite3` foi removido somente do indice Git com `git rm --cached`. O arquivo continua no disco e no snapshot externo. Valores de segredo nao foram impressos nem documentados.

`.dockerignore` agora exclui bancos locais, `tmp/`, `data/`, caches, `archive/`, `camera/` e `operation/`, reduzindo risco de empacotar artefatos sensiveis em imagem Docker.

## Documentacao criada

- `docs/consolidation/REPOSITORY_INVENTORY.md`
- `docs/consolidation/BRANCH_ANALYSIS.md`
- `docs/consolidation/CURRENT_ARCHITECTURE.md`
- `docs/consolidation/FEATURE_MATRIX.md`
- `docs/consolidation/DUPLICATION_MAP.md`
- `docs/consolidation/DEPENDENCY_SECURITY_AUDIT.md`
- `docs/consolidation/CONSOLIDATION_PLAN.md`
- `docs/consolidation/BASELINE_TESTS.md`

O README historico anterior foi preservado em:

`docs/archive/historical/README_CAMPEX_OPERATIONS_HISTORY.md`

## Validacao

Baseline antes do movimento:

- `camera`: 6 passed, 4 failed.
- `operation`: 267 passed, 299 failed, 11 errors, 47 warnings.

Validacao apos promover a raiz:

- `pytest --collect-only -q`: 569 testes coletados, sem erro de coleta depois de adicionar `pytest.ini`.
- Import smoke: `from app.api import api` carregou 184 rotas; `import app.main` passou.
- Route smoke via `fastapi.testclient`: `/`, `/operations-view`, `/cameras`, `/events`, `/alerts`, `/evidence`, `/reports`, `/live-view`, `/live-grid`, `/operations`, `/people-zones` e `/local-diagnostics` retornaram 200.
- Suite final: 267 passed, 299 failed, 10 errors, 47 warnings.

As falhas finais repetem o perfil herdado: handles SQLite abertos no Windows, testes de Playwright apontando para caminho macOS de Chrome, fixture de protecao detectando inicializacao de banco persistente, e falhas funcionais preexistentes em contratos operacionais. Nenhum teste foi alterado para mascarar falhas.

## Riscos remanescentes

- `operation/` original nao pode ser renomeada pelo Windows neste momento, embora exista copia verificada em `archive/local` e ZIP externo.
- O detector YOLO real nao foi validado porque `ultralytics` nao foi instalado no venv temporario.
- A suite herdada precisa de uma frente propria de correcao funcional; a consolidacao manteve os contratos e registrou o estado real.

## Proximos passos recomendados

1. Investigar locks/permissoes da pasta `operation/` e remover ou mover a pasta original quando o Windows liberar.
2. Corrigir os testes Windows que mantem conexoes SQLite abertas.
3. Ajustar testes Playwright para descoberta de browser multiplataforma.
4. Criar commit da consolidacao apos revisao do diff.
