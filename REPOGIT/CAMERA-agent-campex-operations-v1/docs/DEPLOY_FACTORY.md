# Deploy Da Campex Na Fábrica

## Pré-requisitos

- Docker e Docker Compose instalados;
- acesso à rede interna do DVR/RTSP;
- arquivo `.env` criado localmente a partir de `.env.example`;
- portas locais liberadas no computador da fábrica, sem abrir portas no roteador.

## Variáveis Principais

```bash
CAMPEX_EDGE_ID=edge_fabrica_01
CAMPEX_EDGE_SECRET=definir_localmente
CAMPEX_CLOUD_URL=
CAMPEX_EMAIL_MODE=console
API_HOST=0.0.0.0
API_PORT=8000
DATABASE_PATH=/app/data/visual_ops_product.sqlite3
CAMPEX_HEARTBEAT_SECONDS=10
CAMPEX_SYNC_SECONDS=10
```

As fontes RTSP continuam configuradas por cadastro seguro no backend ou por variáveis locais como `CAMERA_SOURCE_<CAMERA_ID>`. Não coloque senha RTSP no Git.

## Desenvolvimento Local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py init-db
API_HOST=127.0.0.1 API_PORT=8000 python -m app.main
```

Abrir:

```text
http://127.0.0.1:8000
```

## Produção Local Sem Docker

```bash
CAMPEX_EDGE_ID=edge_fabrica_01 \
API_HOST=0.0.0.0 \
API_PORT=8000 \
python manage.py run-edge-production
```

## Produção Com Docker Compose

```bash
docker compose build
docker compose up -d
docker compose logs -f campex-edge
```

Abrir no próprio computador:

```text
http://127.0.0.1:8000
```

Abrir em outro dispositivo da mesma rede:

```text
http://IP_DO_COMPUTADOR_DA_FABRICA:8000
```

Não exponha essa porta para a internet.

## Healthchecks

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/edge/status
```

## Volumes Persistentes

O `docker-compose.yml` mantém:

- `campex-data`: SQLite e dados locais;
- `campex-evidence`: evidências;
- `campex-logs`: logs.

Reiniciar o container não deve apagar banco, configurações, eventos ou evidências.

## Parar E Reiniciar

```bash
docker compose restart campex-edge
docker compose stop campex-edge
docker compose up -d
```

## Pré-Validação Antes Do Teste De Campo

```bash
CAMPEX_PREFLIGHT_EMAIL="SEU_EMAIL" \
CAMPEX_PREFLIGHT_PASSWORD="SUA_SENHA" \
CAMPEX_PREFLIGHT_CAMERA_ID="ID_DA_CAMERA" \
CAMPEX_EMAIL_MODE=console \
python manage.py factory-preflight --api-url http://127.0.0.1:8000 --timeout 5
```

Comece o teste presencial apenas se retornar:

```text
PRONTO PARA TESTE DE CAMPO
```
