# Baseline de testes antes da consolidacao estrutural

Ambiente: venv externo $taskRoot\venv, DATABASE_PATH e CAMPEX_EVIDENCE_DIR apontando para %TEMP%, CAMPEX_EMAIL_MODE=console, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1.

| Estrutura | Total | Passed | Failed | Errors | Skipped | Warnings | Resultado |
|---|---:|---:|---:|---:|---:|---:|---|
| camera antes do fast-forward | 10 | 6 | 4 | 0 | 0 | n/d | Falha herdada Windows SQLite handle |
| operation antes da consolidacao | 570 | 260 | 299 | 11 | 0 | 47 | Falhas herdadas massivas |

Logs brutos e XML JUnit estao em $baseline.

## Familias principais de falha observadas

- PermissionError [WinError 32] ao limpar SQLite temporario em testes que mantem conexoes abertas no Windows.
- Testes de Playwright procurando Chrome em caminho macOS (/Applications/Google Chrome.app/...) durante execucao Windows.
- Fixture de protecao do banco operacional detectando criacao de tabelas em banco persistente quando alguns testes chamam inicializacao global.
- Muitas falhas funcionais herdadas em contratos operacionais, leitura, timeline, impacto, memoria operacional, zonas, alertas, relatorios, seguranca e visao.
