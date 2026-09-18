# Auditoria visual Campex V0 - câmeras do banco local
Banco auditado: `data/visual_ops_product.sqlite3`.
Total de câmeras após a suíte completa: **74**.
## Resumo por origem provável
- compatibilidade: 3
- fixture/dev: 64
- real ou cadastrada manualmente: 4
- teste automatizado: 3

## Critério de classificação
- `compatibilidade`: IDs `compat_live_*` ou nomes com `compat`.
- `teste automatizado`: IDs técnicos explícitos como `cam_ai`, `cam_fail`, `cam_resources`.
- `fixture/dev`: IDs `cam_*` sem fonte configurada e sem contexto operacional.
- `real ou cadastrada manualmente`: câmera com fonte/RTSP/configuração preenchida.
- `desconhecido`: sem evidência suficiente para classificar.

Nenhuma câmera foi removida nesta auditoria. Câmeras reais ou com fonte configurada exigem confirmação humana antes de qualquer cleanup.

## Registros
| id | nome | unidade | asset_id | area_context_id | process_id | fonte | status | último frame | criado em | origem provável |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cam_0a7783e752 | cam_0a7783e752 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:15:22 | fixture/dev |
| cam_2ebf9fcd29 | cam_2ebf9fcd29 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:15:20 | fixture/dev |
| cam_099ff6c7b5 | cam_099ff6c7b5 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:11:51 | fixture/dev |
| cam_50459740fd | cam_50459740fd | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:11:49 | fixture/dev |
| cam_3cb65f6367 | cam_3cb65f6367 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:02:43 | fixture/dev |
| cam_d6dba2b957 | cam_d6dba2b957 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:02:42 | fixture/dev |
| cam_9085c5ce31 | cam_9085c5ce31 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:02:18 | fixture/dev |
| cam_0e436edd67 | cam_0e436edd67 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:02:16 | fixture/dev |
| cam_5e4eaffee7 | cam_5e4eaffee7 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:00:44 | fixture/dev |
| cam_eeb3670921 | cam_eeb3670921 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 20:00:42 | fixture/dev |
| cam_d98e4e62ea | cam_d98e4e62ea | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:59:18 | fixture/dev |
| cam_8f503ec6e4 | cam_8f503ec6e4 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:59:17 | fixture/dev |
| cam_de2edfc0ea | cam_de2edfc0ea | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:58:57 | fixture/dev |
| cam_07e220f180 | cam_07e220f180 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:58:56 | fixture/dev |
| cam_2982d343c3 | cam_2982d343c3 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:58:40 | fixture/dev |
| cam_001ea490c0 | cam_001ea490c0 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:58:38 | fixture/dev |
| cam_086b8b97af | cam_086b8b97af | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:50:12 | fixture/dev |
| cam_fabcebe36a | cam_fabcebe36a | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:50:11 | fixture/dev |
| cam_666a9ce6f9 | cam_666a9ce6f9 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:39:49 | fixture/dev |
| cam_fee6c24d0d | cam_fee6c24d0d | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:39:47 | fixture/dev |
| cam_14669c6f83 | cam_14669c6f83 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:39:07 | fixture/dev |
| cam_09ee705908 | cam_09ee705908 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:39:05 | fixture/dev |
| cam_7df00a75ae | cam_7df00a75ae | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:23:23 | fixture/dev |
| cam_04da48e065 | cam_04da48e065 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:23:21 | fixture/dev |
| cam_ee5b1e3512 | cam_ee5b1e3512 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:16:11 | fixture/dev |
| cam_3833d1eb99 | cam_3833d1eb99 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:16:10 | fixture/dev |
| cam_1378323c32 | cam_1378323c32 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:09:16 | fixture/dev |
| cam_fb68d065f3 | cam_fb68d065f3 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 19:09:14 | fixture/dev |
| cam_010e0a1e45 | cam_010e0a1e45 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:59:21 | fixture/dev |
| cam_27de33052c | cam_27de33052c | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:59:19 | fixture/dev |
| cam_b4f740e4d8 | cam_b4f740e4d8 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:49:25 | fixture/dev |
| cam_661c0d1420 | cam_661c0d1420 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:49:23 | fixture/dev |
| cam_e4ea892d1e | cam_e4ea892d1e | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:32:04 | fixture/dev |
| cam_1c3aa43572 | cam_1c3aa43572 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:32:02 | fixture/dev |
| cam_e405518064 | cam_e405518064 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:23:00 | fixture/dev |
| cam_c6556f102e | cam_c6556f102e | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:22:59 | fixture/dev |
| cam_1a9b4ddc07 | cam_1a9b4ddc07 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:03:56 | fixture/dev |
| cam_b363690664 | cam_b363690664 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 18:03:54 | fixture/dev |
| cam_b8e54a3cdf | cam_b8e54a3cdf | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:59:36 | fixture/dev |
| cam_fb7becf669 | cam_fb7becf669 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:59:34 | fixture/dev |
| cam_f150d22e4f | cam_f150d22e4f | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:58:53 | fixture/dev |
| cam_cda81b7087 | cam_cda81b7087 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:58:51 | fixture/dev |
| cam_a893dc131b | cam_a893dc131b | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:52:59 | fixture/dev |
| cam_1e446e7497 | cam_1e446e7497 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:52:58 | fixture/dev |
| cam_1392a4dad4 | cam_1392a4dad4 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:52:09 | fixture/dev |
| cam_5f99d97acb | cam_5f99d97acb | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:52:08 | fixture/dev |
| cam_b50a5397ad | cam_b50a5397ad | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:45:10 | fixture/dev |
| cam_9047ca6405 | cam_9047ca6405 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:45:08 | fixture/dev |
| cam_9ac80b0eff | cam_9ac80b0eff | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:35:17 | fixture/dev |
| cam_0a2228624f | cam_0a2228624f | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:35:15 | fixture/dev |
| cam_6557690825 | cam_6557690825 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:33:29 | fixture/dev |
| cam_404d8171ec | cam_404d8171ec | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:33:27 | fixture/dev |
| cam_794e4519d5 | cam_794e4519d5 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:32:14 | fixture/dev |
| cam_d6e8800a44 | cam_d6e8800a44 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:32:13 | fixture/dev |
| cam_ai | cam_ai | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:15 | teste automatizado |
| cam_fail | cam_fail | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:14 | teste automatizado |
| cam_f337646f3b | cam_f337646f3b | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:07 | fixture/dev |
| cam_b | cam_b | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:07 | fixture/dev |
| cam_a | cam_a | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:07 | fixture/dev |
| compat_live_46c3cbbbc53cda4e | compat_live_46c3cbbbc53cda4e | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:06 | compatibilidade |
| compat_live_fail | compat_live_fail | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:06 | compatibilidade |
| cam_resources | cam_resources | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:05 | teste automatizado |
| cam_edce23a565 | cam_edce23a565 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:05 | fixture/dev |
| compat_live_08c055a9898b9981 | compat_live_08c055a9898b9981 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:05 | compatibilidade |
| cam_1 | cam_1 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:04 | fixture/dev |
| cam_2 | cam_2 | Unidade local | — | — | — | sem fonte | nao_conectada | — | 2026-08-07 17:31:03 | fixture/dev |
| cam_215cf86f0f | FL plasticos | Fabrica Rio Preto | — | — | — | configurada | reconectando | — | 2026-08-03 13:35:17 | real ou cadastrada manualmente |
| cam_3065cc5357 | FL plasticos | Fabrica Rio Preto | — | — | — | configurada | reconectando | 2026-08-06T16:02:25-03:00 | 2026-07-27 16:29:37 | real ou cadastrada manualmente |
| cam_128572299c | FL plasticos | Fabrica Rio Preto | — | — | — | configurada | reconectando | 2026-08-06T16:02:33-03:00 | 2026-07-27 16:28:06 | real ou cadastrada manualmente |
| cam_e99537c60a | FL plasticos | Fabrica Rio Preto | — | — | — | configurada | reconectando | — | 2026-07-27 16:23:55 | real ou cadastrada manualmente |

## Testes e poluição do banco principal
A suíte automatizada usa banco temporário na maior parte dos testes por `tempfile`, `tmp_path` ou patch de `app.api.connect`. A auditoria encontrou, porém, registros com timestamp próximo da execução de testes e IDs técnicos (`cam_*`, `compat_live_*`, `cam_ai`, `cam_fail`, `cam_resources`) no banco operacional local. Isso indica poluição histórica do banco de desenvolvimento, provavelmente de testes ou validações manuais anteriores feitas contra `data/visual_ops_product.sqlite3`.

Nesta entrega os novos testes adicionados usam SQLite temporário e não escrevem no banco operacional persistente. A suíte completa atual, porém, aumentou o total do banco principal de 70 para 74 câmeras durante a validação final. Isso confirma que ainda existe teste legado ou fluxo de teste antigo escrevendo em `data/visual_ops_product.sqlite3`. Nenhum registro foi removido automaticamente.

## Cleanup recomendado
Remover somente em etapa dedicada, após backup e confirmação humana. Candidatos seguros: registros `compat_live_*`, `cam_ai`, `cam_fail`, `cam_resources` e `cam_*` sem fonte, sem último frame e sem contexto operacional. Não remover automaticamente câmeras chamadas `FL plasticos` porque possuem fonte configurada/RTSP e podem representar testes reais.
