# Campex P0 Vertical Slice Validation

Este documento congela o procedimento de validação do P0 operacional da Campex:

```text
fonte de vídeo
-> machine_region persistente
-> activity_score
-> calibração ativa/parada
-> ACTIVE / STOPPED / UNKNOWN
-> machine_stoppage
-> evidência
-> SQLite
-> sync_outbox
-> fechamento
-> duração correta
```

## Arquitetura real encontrada

O caminho oficial do runtime é:

```text
LiveCameraStream
-> PersonAnalysisEngine
-> PeopleZonesEngine
-> MachineMonitorEngine
-> ObservationEngine
-> MachineMonitorEngine._evaluate_official_events()
-> app.models.criar_evento_machine_stoppage()
-> app.machine_monitoring.save_machine_evidence()
-> edge_agent.sync_outbox.enqueue_sync_event()
-> app.alerts.enqueue_event_alert()
```

`app/live_view_ops.py` permanece apenas como compatibilidade de renderização. Ele não deve classificar máquina, calibrar, determinar operador ou abrir eventos.

## Funções principais chamadas

- `app.live_stream.LiveCameraStream._maybe_analyze`
- `app.live_stream.LiveCameraStream._update_machines`
- `app.machine_monitoring.MachineMonitorEngine.update`
- `app.machine_monitoring.machine_activity_score`
- `app.machine_monitoring.MachineMonitorEngine.calibrate_active`
- `app.machine_monitoring.MachineMonitorEngine.calibrate_stopped`
- `app.machine_monitoring.MachineMonitorEngine._open_event`
- `app.machine_monitoring.MachineMonitorEngine._close_event_type`
- `app.machine_monitoring.save_machine_evidence`
- `app.observation_engine.ObservationEngine.build`
- `app.models.criar_evento_machine_stoppage`
- `app.models.fechar_evento_machine_stoppage`
- `app.alerts.enqueue_event_alert`

## Tabelas usadas

- `machine_monitors`: configuração persistente da máquina, ROI, baselines, thresholds e estado atual.
- `machine_calibrations`: amostras e estatísticas das calibrações assistidas.
- `eventos`: evento operacional `machine_stoppage`, status, início, fim, duração, confiança e evidência.
- `sync_outbox`: payload do evento pronto para sincronização Edge -> Cloud.
- `alert_recipients`: destinatários configurados.
- `alert_deliveries`: entregas de alerta geradas para o evento.

## Diagnóstico exposto

O motor de máquina agora expõe:

- `WAITING_FOR_REGION`
- `WAITING_FOR_PREVIOUS_FRAME`
- `ANALYZING`
- `INVALID_ROI`
- `FRAME_STALE`
- `ERROR`

O painel da Live View também exibe:

- raw score;
- smoothed score;
- frames analisados;
- tamanho da ROI;
- estado;
- confiança;
- motivo;
- tempo no estado.

## Procedimento manual

1. Iniciar a aplicação:

```bash
python3 -m app.main
```

2. Abrir:

```text
http://127.0.0.1:8000/live-view
```

3. Abrir uma câmera cadastrada ou fonte local configurada.

4. Criar/salvar uma `machine_region` para a câmera.

5. Cadastrar ou selecionar a máquina vinculada à câmera.

6. Ligar a IA/monitoramento.

7. Validar que o painel mostra:

```text
analysis_status = ANALYZING
frames_analyzed aumentando
ROI com largura e altura maiores que zero
raw score variando com movimento
smoothed score variando com movimento
```

8. Calibrar máquina ativa pelo botão da Live View, que chama:

```text
POST /machine-monitors/{machine_id}/calibration/active/start
```

9. Calibrar máquina parada pelo botão da Live View, que chama:

```text
POST /machine-monitors/{machine_id}/calibration/stopped/start
```

10. Confirmar baselines, threshold e separação.

11. Deixar a máquina parar até ultrapassar `stop_seconds`.

12. Confirmar no SQLite:

```sql
SELECT id, tipo, status, inicio, fim, duracao, midia_path
FROM eventos
WHERE tipo = 'machine_stoppage'
ORDER BY criado_em DESC
LIMIT 5;
```

13. Confirmar outbox:

```sql
SELECT event_uuid, status, payload_json
FROM sync_outbox
ORDER BY created_at DESC
LIMIT 5;
```

14. Retornar a máquina para ACTIVE e confirmar que o evento fecha com duração real.

## Comando dos testes

Teste determinístico do P0:

```bash
python3 -m pytest tests/test_p0_vertical_slice.py -q
```

Suíte completa:

```bash
python3 -m pytest -q
```

## Limitações

- O teste P0 usa frames sintéticos para ser determinístico; ele não valida RTSP físico.
- O alerta do P0 usa `CAMPEX_EMAIL_MODE=console`; SMTP não faz parte desta validação.
- Apenas `machine_stoppage` é validado no P0.
- A qualidade do `activity_score` depende da ROI estar bem posicionada e do contraste visual da máquina.
