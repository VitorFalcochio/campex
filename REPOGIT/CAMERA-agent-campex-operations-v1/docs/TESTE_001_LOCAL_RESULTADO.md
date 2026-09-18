# TESTE 001 LOCAL - Resultado

Data: 2026-07-31
Projeto: `/Users/felipeesteves/CAMERA`
Commit inicial testado: `4a4836e2`
Branch: `agent/campex-operations-v1`

## Classificação final

**PARCIALMENTE APROVADO**

O teste comprovou leitura de vídeo local, persistência de câmera/monitor/região, cálculo de `activity_score`, tentativa real de calibração assistida, API operacional e persistência após reinício.

O teste **não comprovou de forma limpa** a cadeia completa exigida:

```text
vídeo local -> processamento -> machine_stoppage fechado -> evidência -> duração correta -> dashboard/API -> persistência
```

O motivo principal foi que a calibração assistida com `data/synthetic_stop_test.mp4` ficou instável/inválida quando executada pelo runtime real. Em uma tentativa intermediária houve evento, evidência, outbox e fechamento, mas também houve eventos duplicados durante calibração. Na tentativa final controlada, com monitor inativo até a calibração terminar, nenhum `machine_stoppage` foi gerado.

## Comandos executados

Confirmar commit e estado:

```bash
git rev-parse --short HEAD
git status -sb
```

Resultado:

```text
4a4836e2
## agent/campex-operations-v1...origin/agent/campex-operations-v1
```

Rodar suíte completa antes da validação:

```bash
python3 -m pytest -q
```

Resultado:

```text
140 passed, 60 warnings
```

Iniciar sistema com vídeo local:

```bash
DATABASE_PATH=/Users/felipeesteves/CAMERA/data/teste_001_local.sqlite3 \
CAMPEX_VIDEO_SOURCE_MODE=file \
CAMPEX_VIDEO_FILE=/Users/felipeesteves/CAMERA/data/synthetic_stop_test.mp4 \
CAMPEX_EMAIL_MODE=console \
API_HOST=127.0.0.1 \
API_PORT=8013 \
python3 -m app.main
```

Servidor:

```text
Uvicorn running on http://127.0.0.1:8013
```

Rodar suíte completa após a correção mínima:

```bash
python3 -m pytest -q
```

Resultado:

```text
140 passed, 60 warnings
```

## Arquivos envolvidos

Arquivos auditados:

- `app/live_stream.py`
- `app/machine_monitoring.py`
- `app/observation_engine.py`
- `app/models.py`
- `app/database.py`
- `app/alerts.py`

Arquivo corrigido durante o teste:

- `app/live_stream.py`

Arquivo criado:

- `docs/TESTE_001_LOCAL_RESULTADO.md`

Banco utilizado:

- `data/teste_001_local.sqlite3`

Vídeo utilizado:

- `data/synthetic_stop_test.mp4`

## Etapas executadas

### 1. Health check

Comando HTTP:

```text
GET http://127.0.0.1:8013/health
```

Resultado:

```json
{"status":"ok"}
```

### 2. Criação de câmera local

Endpoint usado:

```text
POST /cameras
```

Payload:

```json
{
  "nome": "Teste 001 synthetic video ROI",
  "config_ref": "validation-file",
  "source_type": "file"
}
```

Registro persistido na tentativa final:

```json
{
  "id": "cam_0cda1564ea",
  "nome": "Teste 001 synthetic video ROI",
  "source_type": "file",
  "config_ref": "validation-file"
}
```

### 3. Região de máquina persistente

Endpoint usado:

```text
POST /cameras/cam_0cda1564ea/areas
```

Payload:

```json
{
  "name": "Machine region Teste 001 ROI",
  "area_type": "machine_region",
  "polygon": [
    {"x": 0.3, "y": 0.3},
    {"x": 0.6, "y": 0.3},
    {"x": 0.6, "y": 0.6},
    {"x": 0.3, "y": 0.6}
  ],
  "active": true,
  "machine_id": "mach_361093e76f"
}
```

Linha real no SQLite:

```json
{
  "id": "area_327463261d",
  "nome": "Machine region Teste 001 ROI",
  "tipo": "machine_region",
  "camera_id": "cam_0cda1564ea",
  "machine_id": "mach_361093e76f",
  "ativa": 1,
  "pontos_json": "[{\"x\": 0.3, \"y\": 0.3}, {\"x\": 0.6, \"y\": 0.3}, {\"x\": 0.6, \"y\": 0.6}, {\"x\": 0.3, \"y\": 0.6}]"
}
```

### 4. Frames reais lidos

Endpoint:

```text
GET /cameras/cam_0cda1564ea/status
```

Resultado relevante:

```json
{
  "status": "online",
  "width": 640,
  "height": 360,
  "fps": 2022.91,
  "last_frame_at": "2026-07-31T11:58:54-03:00"
}
```

Conclusão: frames reais foram lidos do arquivo `data/synthetic_stop_test.mp4`.

### 5. Calibração assistida

Endpoints usados:

```text
POST /machine-monitors/mach_361093e76f/calibration/active/start
POST /machine-monitors/mach_361093e76f/calibration/stopped/start
```

Resultado da calibração ativa:

```json
{
  "samples_count": 404,
  "mean": 5.2832,
  "median": 0.0,
  "std": 14.2748,
  "max": 173.3604
}
```

Resultado da calibração parada:

```json
{
  "samples_count": 1123,
  "mean": 5.2646,
  "median": 0.0,
  "std": 15.5991,
  "max": 173.3604
}
```

Resultado:

```json
{
  "calibration_status": "calibration_needs_review",
  "calibration_result": "INVALID",
  "active_baseline": 5.2832,
  "stopped_baseline": 5.2646,
  "separation_score": null
}
```

Conclusão: a calibração não separou corretamente ativa/parada no runtime real com este MP4.

### 6. Processamento e estado

Após ativar o monitor:

```text
POST /machine-monitors/mach_361093e76f/activate
```

Status observado:

```text
poll 0 UNKNOWN 0.979 5.274 None
poll 1 UNKNOWN 39.801 5.274 None
poll 2 ACTIVE 34.526 5.274 None
...
poll 24 ACTIVE 81.494 5.274 None
```

Conclusão: houve processamento e estado `ACTIVE`, mas não houve transição comprovada `ACTIVE -> STOPPED -> ACTIVE` na tentativa final.

### 7. Eventos no SQLite

Consulta:

```sql
SELECT id,event_uuid,tipo,status,inicio,fim,duracao,camera_id,machine_monitor_id,motion_level,confianca,midia_path,metadata_json
FROM eventos
WHERE tipo='machine_stoppage'
ORDER BY criado_em;
```

Resultado na tentativa final:

```json
[]
```

Conclusão: a tentativa final controlada não gerou `machine_stoppage`.

### 8. Outbox

Consulta:

```sql
SELECT id,event_uuid,status,attempts,payload_json
FROM sync_outbox
ORDER BY created_at;
```

Resultado na tentativa final:

```json
[]
```

Conclusão: sem evento final, nada entrou na outbox nessa tentativa.

### 9. Evidência

Na tentativa final não houve evidência porque não houve evento.

Em tentativa intermediária, antes de isolar o monitor durante calibração, houve evidência real salva:

```text
/Users/felipeesteves/CAMERA/data/evidence/cam_242ed285a9/2026/07/31/115442_mach_82b03b547b_machine.jpg
```

Tamanho:

```text
28412 bytes
```

Essa evidência veio do frame processado da fonte `data/synthetic_stop_test.mp4`, não de `/dev/test-event`.

Essa tentativa intermediária também gerou evento fechado:

```json
{
  "id": "evt_885b6215c9",
  "tipo": "machine_stoppage",
  "status": "closed",
  "inicio": "2026-07-31T11:54:42-03:00",
  "fim": "2026-07-31T11:54:44-03:00",
  "duracao": 1.2037705409999973,
  "midia_path": "data/evidence/cam_242ed285a9/2026/07/31/115442_mach_82b03b547b_machine.jpg"
}
```

Mas essa tentativa não foi considerada aprovação limpa porque também gerou eventos duplicados durante a calibração.

### 10. API de eventos

Na tentativa intermediária, o evento foi consultado por:

```text
GET /eventos/evt_885b6215c9
```

Na tentativa final:

```text
GET /eventos
```

Resultado:

```json
[]
```

### 11. Persistência após reinício

Após parar e reiniciar o servidor com o mesmo banco:

```bash
DATABASE_PATH=/Users/felipeesteves/CAMERA/data/teste_001_local.sqlite3 \
CAMPEX_VIDEO_SOURCE_MODE=file \
CAMPEX_VIDEO_FILE=/Users/felipeesteves/CAMERA/data/synthetic_stop_test.mp4 \
CAMPEX_EMAIL_MODE=console \
API_HOST=127.0.0.1 \
API_PORT=8013 \
python3 -m app.main
```

Persistência confirmada:

```json
{
  "camera": {
    "id": "cam_0cda1564ea",
    "nome": "Teste 001 synthetic video ROI"
  },
  "monitor": {
    "id": "mach_361093e76f",
    "nome": "Máquina Teste 001 ROI",
    "ativo": 1,
    "active_baseline": 5.2832,
    "stopped_baseline": 5.2646,
    "calibration_result": "INVALID"
  },
  "area": {
    "id": "area_327463261d",
    "nome": "Machine region Teste 001 ROI",
    "tipo": "machine_region"
  },
  "machine_stoppage_events": 0
}
```

### 12. Dashboard/API operacional

Endpoint consultado:

```text
GET /operations/events
```

Resultado: o endpoint respondeu, mas exibiu apenas eventos técnicos `camera_status`, não um evento operacional `machine_stoppage`.

Exemplo observado:

```json
{
  "event_type": "camera_status",
  "previous_state": "offline",
  "new_state": "online",
  "camera_id": "cam_0cda1564ea",
  "machine_name": "Máquina Teste 001 ROI"
}
```

Conclusão: dashboard/API operacional está acessível, mas não exibiu o evento operacional alvo na tentativa final.

## Problemas encontrados

### Problema 1 - cache do monitor após calibração

Erro original observado:

```text
Banco: motion_threshold = 0.9207
Status runtime: machine_threshold = 25.0
Evento: ficou aberto e não fechou
```

Causa:

O `MachineMonitorEngine` em memória podia ser carregado antes da calibração e continuar com configuração antiga depois que a calibração era persistida.

Correção mínima feita:

Arquivo:

```text
app/live_stream.py
```

Correção:

```python
self._machine_engines.pop(monitor_id, None)
```

após persistir a calibração, forçando recarga do monitor atualizado.

Resultado após correção:

- evento pôde fechar em tentativa intermediária;
- suíte completa continuou passando.

### Problema 2 - calibração com vídeo local mistura estados

Com `data/synthetic_stop_test.mp4`, a calibração assistida pelo runtime real capturou muitas amostras por segundo e misturou trechos ativos/parados.

Sintoma:

```text
active_baseline ~= stopped_baseline
calibration_result = INVALID
```

Isso impediu uma validação limpa e reprodutível da cadeia final.

### Problema 3 - eventos técnicos de câmera em excesso

`GET /operations/events` mostrou muitos eventos `camera_status` alternando online/offline no vídeo local.

Isso não bloqueia diretamente `machine_stoppage`, mas polui a leitura do dashboard operacional durante validação local.

## Correções feitas

Foi feita uma única correção mínima:

- invalidar o `MachineMonitorEngine` em memória após a calibração ser persistida.

Nenhuma funcionalidade nova foi criada.
Nenhum endpoint de teste foi usado.
Nenhum evento foi inserido manualmente no banco.

## Validação dos requisitos

| Requisito | Resultado |
|---|---|
| Confirmar commit atual | OK |
| Rodar suíte completa | OK, `140 passed` |
| Iniciar sistema com vídeo local | OK |
| Confirmar frames reais | OK |
| Criar/persistir região de máquina | OK |
| Ativar processamento | OK |
| Produzir ACTIVE -> STOPPED -> ACTIVE limpo | NÃO comprovado |
| Gerar evento automático limpo | NÃO na tentativa final |
| Mostrar linha SQLite de evento | NÃO na tentativa final |
| Evidência real | Parcial, ocorreu em tentativa intermediária |
| Duração correta | Parcial, ocorreu em tentativa intermediária |
| Consultar evento pela API | Parcial, ocorreu em tentativa intermediária |
| Persistir após reinício | OK para configuração; sem evento final |
| Dashboard exibir evento real | NÃO; exibiu apenas eventos técnicos |

## Conclusão

**PARCIALMENTE APROVADO**

A base técnica existe e partes importantes funcionaram, mas a versão atual ainda não está aprovada para teste industrial controlado usando este roteiro local. O ponto crítico é tornar a calibração/validação com vídeo local determinística o suficiente para produzir uma transição limpa e um único `machine_stoppage` fechado, com evidência e outbox, sem eventos duplicados ou ruído de `camera_status`.

## Rodada 2 — Diagnóstico da calibração

Objetivo desta rodada:

Investigar por que a calibração ativa/parada ficou inválida no Teste 001 Local:

```text
active_baseline: 5.2832
stopped_baseline: 5.2646
```

Hipóteses avaliadas:

1. O vídeo usado não possui diferença visual suficiente.
2. A região da máquina foi configurada incorretamente.
3. O `activity_score` atual não consegue separar os estados.

### 1. Inspeção do vídeo

Arquivo analisado:

```text
data/synthetic_stop_test.mp4
```

Características medidas com OpenCV:

| Item | Valor |
|---|---:|
| Duração | 18,0 s |
| FPS | 10,0 |
| Frames | 180 |
| Resolução | 640x360 |

Intervalos inferidos pela variação visual e pelo `activity_score`:

| Intervalo | Estado esperado |
|---|---|
| 00-05 s | ATIVA provável |
| 05-13 s | PARADA provável |
| 13-17 s | ATIVA provável |
| 17-18 s | PARADA provável |

Conclusão visual/estatística:

O vídeo possui diferença mensurável entre movimento e parada quando os trechos são analisados separadamente.

### 2. Região utilizada

Região usada no Teste 001:

```json
[
  {"x": 0.3, "y": 0.3},
  {"x": 0.6, "y": 0.3},
  {"x": 0.6, "y": 0.6},
  {"x": 0.3, "y": 0.6}
]
```

Em pixels, no vídeo 640x360:

```text
x: 192..384
y: 108..216
```

A análise espacial de movimento mostrou os maiores blocos de variação no centro do vídeo:

| Bloco normalizado | Média de movimento |
|---|---:|
| x 0.4..0.5, y 0.4..0.5 | 7.8179 |
| x 0.5..0.6, y 0.4..0.5 | 7.1112 |
| x 0.6..0.7, y 0.4..0.5 | 5.6536 |
| x 0.3..0.4, y 0.4..0.5 | 5.4558 |

Conclusão sobre a ROI:

A região do relatório cobre a parte que realmente se movimenta. A hipótese de ROI claramente errada não foi confirmada.

### 3. Tabela de activity_score

Função usada:

```text
app.machine_monitoring.machine_activity_score
```

Tabela por segundo usando a ROI do relatório:

| Timestamp | activity_score médio | Estado esperado | Média do trecho | Mínimo | Máximo | Desvio |
|---|---:|---|---:|---:|---:|---:|
| 00-01 s | 6.8123 | ATIVA provável | 10.1465 | 6.8041 | 6.8135 | 0.0029 |
| 01-02 s | 8.8683 | ATIVA provável | 10.1465 | 6.7724 | 13.6409 | 3.0437 |
| 02-03 s | 11.7886 | ATIVA provável | 10.1465 | 6.8147 | 13.7071 | 2.8710 |
| 03-04 s | 6.8206 | ATIVA provável | 10.1465 | 6.7950 | 6.8369 | 0.0111 |
| 04-05 s | 9.4482 | ATIVA provável | 10.1465 | 0.0000 | 94.4706 | 28.3408 |
| 05-06 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 06-07 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 07-08 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 08-09 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 09-10 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 10-11 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 11-12 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 12-13 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| 13-14 s | 25.5209 | ATIVA provável | 10.1465 | 6.8143 | 173.3604 | 49.3691 |
| 14-15 s | 11.7886 | ATIVA provável | 10.1465 | 6.8147 | 13.7071 | 2.8710 |
| 15-16 s | 6.8206 | ATIVA provável | 10.1465 | 6.7950 | 6.8369 | 0.0111 |
| 16-17 s | 3.1171 | ATIVA provável | 10.1465 | 0.0000 | 6.8191 | 3.2248 |
| 17-18 s | 0.0000 | PARADA provável | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Resumo por trecho:

| Estado esperado | Amostras | Média | Mínimo | Máximo | Desvio | Mediana |
|---|---:|---:|---:|---:|---:|---:|
| ATIVA provável | 89 | 10.1465 | 0.0000 | 173.3604 | 20.1179 | 6.8190 |
| PARADA provável | 90 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Conclusão:

O `activity_score` atual consegue separar esse vídeo quando cada trecho é respeitado. Portanto, a hipótese 3 não foi confirmada nesta rodada.

### 4. Controle positivo no repositório

Vídeos encontrados:

| Arquivo | Resultado |
|---|---|
| `teste_maquina.mp4` | existe, mas OpenCV não abre: `moov atom not found` |
| `data/check_camera_test.mp4` | abre, mas tem apenas 2 s e movimento fraco |
| `data/edge_cam_a.mp4` | abre, mas é estático para `activity_score` |
| `data/edge_cam_b.mp4` | abre, mas é estático para `activity_score` |
| `data/synthetic_stop_test.mp4` | abre e possui diferença clara, mas tem apenas 18 s |

Não foi encontrado no repositório um vídeo adequado para a calibração assistida real de 30 segundos por estado.

### 5. Causa mais provável da calibração inválida

A causa mais provável não é falta de separação visual no vídeo, nem ROI errada, nem falha direta da fórmula de `activity_score`.

A causa mais provável é operacional:

- `data/synthetic_stop_test.mp4` tem apenas 18 segundos;
- a calibração assistida coleta por 30 segundos;
- a fonte de arquivo no runtime lê o vídeo em loop e muito mais rápido do que tempo real;
- cada calibração acaba misturando trechos ativos e parados;
- por isso `active_baseline` e `stopped_baseline` ficam praticamente iguais.

Isso explica os números observados:

```text
active_baseline ~= 5.28
stopped_baseline ~= 5.26
```

Esses valores são compatíveis com uma média misturada do vídeo inteiro, não com calibrações isoladas de ativa e parada.

### 6. Decisão da rodada

Não foi feita alteração no algoritmo.

Não foi feita nova validação ACTIVE -> STOPPED -> ACTIVE porque não há, no repositório, uma fonte adequada para a calibração assistida real de 30 segundos por estado.

Para continuar o Teste 001 Local sem mexer no algoritmo, Felipe precisa gravar um novo vídeo local com:

1. câmera fixa, sem tremer;
2. mesma iluminação do começo ao fim;
3. uma região claramente visível da máquina;
4. pelo menos 45 segundos de máquina rodando de forma contínua;
5. pelo menos 45 segundos de máquina parada de forma contínua;
6. pelo menos mais 20 segundos de máquina rodando novamente;
7. sem cortes no arquivo;
8. salvar em MP4 válido, testável pelo OpenCV.

Com esse vídeo, a próxima rodada deve:

1. calibrar ativa durante um trecho totalmente ativo;
2. calibrar parada durante um trecho totalmente parado;
3. validar a separação;
4. executar ACTIVE -> STOPPED -> ACTIVE;
5. confirmar evento, evidência, outbox, API e persistência.

### 7. Classificação final após Rodada 2

**PARCIALMENTE APROVADO**

O diagnóstico melhorou: o vídeo sintético possui diferença visual e a ROI cobre a área correta, mas o arquivo não é adequado para a calibração assistida real de 30 segundos. A Campex ainda não está aprovada para teste industrial controlado por este roteiro local até rodar com uma fonte de vídeo longa o suficiente ou com uma câmera real em tempo contínuo.
