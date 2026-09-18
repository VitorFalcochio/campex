# Pilot Acceptance

Critérios mínimos para considerar a Campex apta ao teste de piloto.

## Fluxo Principal

O piloto deve comprovar:

```text
observação real
→ estado operacional
→ evento único
→ evidência única
→ métrica agregada
→ insight determinístico
→ alerta
→ outbox
```

## Critérios De Aceite

1. Câmera RTSP abre em runtime real.
2. `/ready` só retorna `ready` com:
   - frame recente;
   - inferência recente;
   - monitor carregado.
3. MachineMonitorEngine usa região persistente.
4. Evento confirmado gera exatamente uma evidência.
5. Evento confirmado gera exatamente uma entrada de `sync_outbox`.
6. Retry de alerta não duplica delivery.
7. Reinício não corrompe evento ativo.
8. Período offline não entra como máquina parada.
9. Agregação por turno confere com eventos originais.
10. Insight mostra métricas e `event_ids` usados.
11. Usuário sem permissão não acessa outro cliente.
12. Logs não expõem senha, token ou RTSP com credenciais.

## Comandos De Validação

```bash
python3 -m pytest tests/test_pilot_data_security_baseline.py -q
python3 -m pytest -q
```

## Preflight De Campo

```bash
CAMPEX_PREFLIGHT_EMAIL="SEU_EMAIL" \
CAMPEX_PREFLIGHT_PASSWORD="SUA_SENHA" \
CAMPEX_PREFLIGHT_CAMERA_ID="ID_DA_CAMERA" \
CAMPEX_EMAIL_MODE=console \
python manage.py factory-preflight --api-url http://127.0.0.1:8000 --timeout 5
```

O teste presencial só deve começar se retornar:

```text
PRONTO PARA TESTE DE CAMPO
```

## Resultado Possível

- `APTO PARA TESTE DE PILOTO`: todos os critérios automáticos passam e os controles humanos foram revisados.
- `APTO PARA TESTE CONTROLADO`: testes automatizados passam, mas ainda há controles humanos pendentes.
- `NÃO APTO`: falha em evento, evidência, outbox, autenticação ou readiness.
