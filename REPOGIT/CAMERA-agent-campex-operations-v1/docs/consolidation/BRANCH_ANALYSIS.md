# Analise de branches

## Estado confirmado

- Branch de trabalho: $branch.
- HEAD inicial da main: $mainHead.
- Branch de operacoes: origin/agent/campex-operations-v1 em $opsHead.
- Merge-base: $mergeBase.
- Resultado: main e ancestral direto da branch de operacoes. A consolidacao foi feita por git merge --ff-only origin/agent/campex-operations-v1.

## Classificacao

| Classe | Resultado |
|---|---|
| MAIN ONLY | Nenhum arquivo exclusivo da main apos comparar com a branch de operacoes. |
| OTHER ONLY | Arquivos de pp, cloud, deployment, docs, rontend, scripts, 	ests, 	mp e 	ools adicionados pela branch de operacoes. |
| SHARED | 45 arquivos da base camera preservados no historico. |
| CONFLICTING | Nenhum conflito de merge: fast-forward puro. |
| SUPERSEDED | Implementacao antiga da main foi substituida por commits posteriores da propria linhagem. |
| UNCERTAIN | operation/frontend/frontend/styles.css existia fora do Git; e duplicata semantica/normalizada de rontend/styles.css e sera preservada apenas no arquivo local externo. |

## Decisao

A branch canonica e efactor/campex-consolidation, baseada em main e avancada para origin/agent/campex-operations-v1. Nada foi alterado em main e nenhuma branch foi apagada.
