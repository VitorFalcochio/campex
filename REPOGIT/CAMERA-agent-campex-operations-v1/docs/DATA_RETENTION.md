# Data Retention

Política inicial de retenção para o piloto Campex.

## Dados Persistidos

SQLite local:

- clientes;
- unidades;
- usuários;
- câmeras;
- zonas;
- monitores de máquina;
- eventos;
- outbox;
- entregas de alerta;
- métricas;
- insights;
- audit log.

Arquivos:

- evidências em `data/evidence`;
- replays curtos, quando gerados, em `data/replays`;
- logs em `logs`.

## O Que Não Armazenar

- vídeo contínuo;
- senha RTSP em texto puro;
- senha SMTP em logs;
- tokens;
- segredo do Edge;
- dados biométricos;
- reconhecimento facial.

## Retenção Inicial

Variável:

```bash
CAMPEX_EVIDENCE_RETENTION_DAYS=90
```

Comando:

```bash
python manage.py prune-evidence --days 90 --confirm
```

## Regras De Segurança

- Não apagar eventos abertos.
- Não apagar eventos não reconhecidos sem revisão humana.
- Não apagar banco principal como forma de limpar teste.
- Fazer backup antes de qualquer limpeza grande.

## Backup

```bash
python manage.py backup --output-dir backups
```

## Restauração

```bash
python manage.py restore --archive CAMINHO_DO_BACKUP
```

## Limite De Disco

Monitorar:

```bash
curl http://127.0.0.1:8000/edge/status
```

Se disco estiver baixo:

1. fazer backup;
2. revisar evidências antigas;
3. aplicar retenção;
4. validar `/ready` novamente.

## Observação Para O Piloto

A política acima é inicial. O cliente precisa aprovar:

- prazo de retenção;
- quem pode exportar evidências;
- quem pode excluir evidências;
- processo de resposta a incidente;
- aviso interno de monitoramento.
