# Auditoria de dependencias e seguranca

## Dependencias

| Dependencia | Classe | Motivo |
|---|---|---|
| fastapi | USED | pp/api.py e cloud/api.py. |
| uvicorn | USED | pp/main.py, cloud/main.py e comandos de serve. |
| numpy | USED | Processamento de frames/visao e testes. |
| opencv-python | USED | Captura RTSP/video e processamento visual. |
| psutil | USED | Diagnosticos/processos. |
| httpx | USED | Clientes/testes HTTP e comunicacao Edge/Cloud. |
| openai | USED/OPTIONAL | Provider de entendimento de video quando configurado. |
| psycopg[binary] | USED | Cloud/PostgreSQL. |
| ultralytics | USED/OPTIONAL | Detector YOLO de pessoa; nao validado no baseline por peso externo. |
| pytest | USED | Suite de testes. |
| playwright | UNKNOWN/TOOLING | Testes de browser; baseline atual falha por caminho macOS no Windows. |

Nenhuma versao foi atualizada no projeto. As instalacoes feitas ficaram no venv externo temporario $taskRoot\venv.

## Seguranca

- Foi identificado backup SQLite em 	mp/db-backups/visual_ops_product_before_cleanup.sqlite3 contendo tabelas operacionais e campos de credencial. Valores nao foram impressos nem copiados para relatorios.
- .dockerignore original nao protegia 	mp/, data/, caches e arquivos locais; sera endurecido para evitar empacotar banco/evidencias em imagem.
- .gitignore ja ignora 	mp/, mas o arquivo de backup ja estava rastreado na branch de operacoes; sera removido apenas do indice Git, preservando copia local e snapshot externo.
