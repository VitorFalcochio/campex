# Campex Edge 24/7

Este documento descreve a camada operacional criada para rodar a Campex dentro da fábrica com foco em continuidade, persistência e recuperação.

## Arquitetura Encontrada

O produto já possuía:

- FastAPI em `app/api.py` e `app/main.py`;
- Live Stream RTSP em `app/live_stream.py`;
- inferência de pessoas em `app/person_detection.py`;
- motor de máquina em `app/machine_monitoring.py`;
- eventos, evidências, alertas e outbox em `app/models.py`, `app/alerts.py` e `edge_agent/sync_outbox.py`;
- supervisor local de câmeras em `edge_agent/service.py`;
- comando `run-edge` em `manage.py`.

A evolução 24/7 preserva esse caminho. O novo comando de produção apenas orquestra os componentes existentes.

## Comando Único De Produção

```bash
CAMPEX_EDGE_ID=edge_fabrica_01 python manage.py run-edge-production
```

Esse comando inicia:

- API FastAPI;
- supervisor das câmeras do Edge;
- heartbeat persistido;
- retomada de entregas de alerta pendentes;
- worker de sincronização da `sync_outbox`, quando `CAMPEX_CLOUD_URL` e `CAMPEX_EDGE_SECRET` estiverem configurados.

## Health E Readiness

- `GET /health`: confirma que o processo HTTP está vivo.
- `GET /ready`: valida banco, câmeras, inferência e workers.
- `GET /edge/status`: mostra câmera, FPS, frames analisados, último frame, último evento, outbox pendente e disco.

## Heartbeat

A tabela `edge_heartbeats` registra periodicamente:

- `edge_id`;
- horário do heartbeat;
- câmera online;
- último frame;
- FPS de captura;
- FPS de inferência;
- frames analisados;
- tamanho da outbox;
- disco livre;
- uso de disco.

## Pipeline Confiável

Fluxo operacional:

```text
detecção
→ MachineMonitorEngine / regras
→ evento transacional no SQLite
→ evidência
→ sync_outbox
→ alerta
→ retry com backoff
→ confirmação Cloud quando disponível
```

O Edge continua funcionando offline. Quando a Cloud estiver indisponível, os eventos permanecem na `sync_outbox` com `pending` ou `failed`.

## Dados Persistidos

Foram preparadas ou preservadas as estruturas:

- `operational_samples`;
- `machine_state_samples`;
- `operator_presence_samples`;
- `eventos`;
- `operational_events`;
- `evidences`;
- `alert_deliveries`;
- `sync_outbox`;
- `edge_heartbeats`;
- `hourly_machine_metrics`;
- `daily_machine_metrics`;
- `shift_machine_metrics`;
- `generated_insights`.

Não há gravação contínua de vídeo. A Campex salva métricas, eventos, imagens de evidência e pequenos replays quando o motor já os gerar.

## Campex Intelligence

Fluxo:

```text
samples brutos
→ eventos consolidados
→ métricas agregadas
→ insights acionáveis
```

Endpoints:

- `GET /analytics/summary`
- `GET /analytics/timeline`
- `GET /analytics/insights`
- `GET /analytics/data-quality`

Parâmetros principais:

- `machine_id`;
- `camera_id`;
- `start`;
- `end`;
- `aggregation`: `hour`, `shift`, `day`, `week`.

## Métricas E Fórmulas

- tempo total monitorado: `end - start`;
- tempo parado: soma do overlap de eventos `machine_stoppage`, `machine_stopped_with_operator` e `repeated_microstops` dentro do período;
- tempo em operação: estimativa por amostras `ACTIVE`; se não houver amostras, `tempo total - tempo parado - tempo offline`;
- disponibilidade estimada: `tempo em operação / tempo total monitorado * 100`;
- quantidade de paradas: quantidade de eventos de parada consolidados;
- duração média das paradas: `tempo parado / quantidade de paradas`;
- maior parada: maior duração de evento de parada no período;
- tempo entre paradas: `tempo total / quantidade de paradas`;
- máquina funcionando sem operador: soma de `machine_running_without_operator` e `workstation_unattended`;
- parada com operador presente: soma de `machine_stopped_with_operator`;
- parada sem operador: `tempo parado - parada com operador presente`;
- eventos por tipo: contagem por `tipo`;
- alertas: contagem de `alert_deliveries` por `sent`, `pending` e `failed`;
- períodos sem dados: lacunas em `operational_samples`, câmera offline ou inferência inativa.

Essas métricas não são chamadas de OEE, porque ainda não existem dados confiáveis de velocidade, produção e qualidade.

## Insights

Os insights são determinísticos e rastreáveis. Cada insight contém:

- título;
- descrição;
- severidade;
- período;
- métricas utilizadas;
- ids de eventos relacionados;
- regra que gerou o insight;
- ação recomendada.

Exemplos gerados apenas quando os dados sustentarem:

- máquina acumulou tempo parado no período;
- máquina operou sem operador;
- existem lacunas de dados por câmera offline ou inferência inativa.

## Limitações

- O comando 24/7 não substitui validação presencial com RTSP real.
- O readiness só marca câmera/inferência como prontas quando há comprovação via runtime.
- A sincronização Cloud depende de `CAMPEX_CLOUD_URL`, `CAMPEX_EDGE_ID` e `CAMPEX_EDGE_SECRET`.
- Os testes de reboot físico e queda real de energia ainda precisam ser feitos na máquina da fábrica.
