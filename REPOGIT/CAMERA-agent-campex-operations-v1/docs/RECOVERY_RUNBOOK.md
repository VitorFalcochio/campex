# Recovery Runbook Campex Edge

Este runbook descreve ações simples para recuperar a Campex Edge em ambiente de fábrica.

## 1. Verificar Se O Processo Está Vivo

```bash
curl http://127.0.0.1:8000/health
```

Se falhar no Docker:

```bash
docker compose ps
docker compose logs --tail=200 campex-edge
docker compose restart campex-edge
```

## 2. Verificar Prontidão Operacional

```bash
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/edge/status
```

Se `/health` passa e `/ready` falha, o processo está vivo, mas algum componente operacional não está pronto.

## 3. Câmera Offline

1. Confirmar rede local do DVR.
2. Confirmar que o computador está na mesma rede.
3. Confirmar que a câmera está cadastrada e ativa.
4. Rodar:

```bash
python manage.py factory-preflight --api-url http://127.0.0.1:8000 --timeout 5
```

Não recrie a câmera antes de confirmar o `camera_id` persistente.

## 4. Eventos Não Chegam Na Cloud

Verificar outbox:

```bash
sqlite3 data/visual_ops_product.sqlite3 "SELECT status, COUNT(*) FROM sync_outbox GROUP BY status;"
```

Se houver `pending` ou `failed`, o Edge continua protegido. Verificar:

- `CAMPEX_CLOUD_URL`;
- `CAMPEX_EDGE_ID`;
- `CAMPEX_EDGE_SECRET`;
- internet;
- `/health` da Cloud.

Forçar sincronização:

```bash
python manage.py sync-cloud
```

## 5. Alertas Pendentes

```bash
sqlite3 data/visual_ops_product.sqlite3 "SELECT status, attempts, erro FROM alert_deliveries ORDER BY criado_em DESC LIMIT 20;"
```

Em campo inicial, `CAMPEX_EMAIL_MODE=console` é suficiente para validar o fluxo sem depender de SMTP.

## 6. Disco Cheio

```bash
curl http://127.0.0.1:8000/edge/status
```

Se o disco estiver baixo, não apagar banco. Remover apenas evidências antigas conforme política aprovada:

```bash
python manage.py prune-evidence --days 30 --confirm
```

## 7. Reinício Durante Evento Ativo

Após reiniciar:

```bash
curl http://127.0.0.1:8000/edge/status
sqlite3 data/visual_ops_product.sqlite3 "SELECT id, tipo, status, inicio, fim, duracao FROM eventos ORDER BY criado_em DESC LIMIT 20;"
```

Eventos abertos devem ser revisados. Não editar diretamente o banco sem backup.

## 8. Backup Antes De Intervenção

```bash
python manage.py backup --output-dir backups
```

## 9. Critério Para Voltar Ao Teste

Retomar validação presencial somente quando:

- `/health` retornar ok;
- `/ready` retornar ready;
- `factory-preflight` retornar `PRONTO PARA TESTE DE CAMPO`;
- Live View mostrar frames reais;
- FPS de inferência e frames analisados estiverem aumentando.
