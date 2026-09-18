# Plano de consolidacao

## Objetivo canonico

Transformar C:\Projetos\Campex em uma unica arvore CAMPEX, preservando historico Git da pasta camera, preservando a implementacao mais nova de operacoes e arquivando incertezas sem apagar conteudo.

## Lotes autorizados

| Lote | Acao | Teste antes | Teste depois | Risco | Rollback |
|---|---|---|---|---|---|
| 0 | Snapshot externo e manifesto SHA-256 | git status, bundle, ZIP | manifesto presente | baixo | restaurar ZIP/bundle |
| 1 | Fast-forward para origin/agent/campex-operations-v1 | baseline camera/operation | git status limpo | baixo | branch anterior no bundle |
| 2 | Gravar docs de consolidacao | baseline existente | leitura dos MDs | baixo | remover docs gerados |
| 3 | Endurecer .dockerignore e remover backup SQLite do indice | baseline registrado | git status, arquivo permanece no disco | medio seguranca | git add tmp/db-backups/... se necessario |
| 4 | Promover checkout Git de camera para a raiz Campex | docs e fast-forward prontos | imports/test collection a partir da raiz | medio caminho relativo | mover .git e arquivos de volta ou restaurar ZIP |
| 5 | Arquivar operation como snapshot local ignorado | ZIP externo pronto | manifesto comparado | baixo | mover pasta de volta |
| 6 | README raiz curto e docs historicas preservadas | baseline registrado | import smoke e rotas basicas | baixo | restaurar README historico de Git |
| 7 | Relatorio final | verificacoes finais | git status, testes finais | baixo | docs sao reversiveis |

## Regras de movimento

- Nao apagar arquivos incertos; arquivar ou manter.
- Nao alterar contratos de API para fazer testes passarem.
- Nao atualizar dependencias automaticamente.
- Nao expor valores de segredo em relatorios.
- Manter comandos antigos (python -m app.main, python manage.py serve, python manage.py edge-run) funcionando a partir da nova raiz.
