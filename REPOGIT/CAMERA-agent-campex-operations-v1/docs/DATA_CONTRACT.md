# Campex Data Contract

Este documento congela o contrato mínimo de dados para o piloto Campex.

## Fluxo Auditável

```text
observação
→ estado
→ evento
→ evidência
→ métrica
→ insight
→ alerta
```

## Evento Canônico V1

Todo evento operacional deve poder ser representado como:

| Campo | Regra |
| --- | --- |
| `event_id` | Imutável. Preferencialmente `event_uuid`; nunca reutilizar para outro evento. |
| `factory_id` | Cliente/tenant da fábrica. |
| `edge_id` | Edge responsável pela observação. |
| `camera_id` | Câmera que originou o evento. |
| `machine_id` | Máquina monitorada, quando aplicável. |
| `zone_id` | Zona/região associada, quando aplicável. |
| `event_type` | Tipo operacional, por exemplo `machine_stoppage`. |
| `started_at` | Início em ISO 8601 com timezone. |
| `ended_at` | Fim em ISO 8601 com timezone, nulo enquanto aberto. |
| `duration_seconds` | Duração calculada pelo tempo real da condição. |
| `machine_state` | `ACTIVE`, `STOPPED`, `UNKNOWN` ou nulo. |
| `operator_present` | Booleano ou nulo quando não medido. |
| `confidence` | Confiança da observação. |
| `data_quality` | `reliable`, `partial`, `unavailable` ou `unknown`. |
| `severity` | Severidade da regra/evento. |
| `evidence_id` | Evidência vinculada, quando existir. |
| `rule_id` | Regra que gerou o evento. |
| `rule_version` | Versão da regra/algoritmo. |
| `created_at` | Criação persistida. |
| `updated_at` | Última alteração persistida. |

Implementação atual:

- contrato em código: `app/data_contract.py`;
- tabela principal local: `eventos`;
- outbox: `sync_outbox`;
- evidências indexadas: `evidences`;
- agregações: `hourly_machine_metrics`, `shift_machine_metrics`, `daily_machine_metrics`;
- insights: `generated_insights`.

## Idempotência

- `sync_outbox.event_uuid` é único.
- Cloud recebe eventos com `event_uuid` e `Idempotency-Key`.
- `alert_deliveries` possui unicidade por `evento_id`, `recipient_id` e `canal`.
- `evidences` possui unicidade por `event_id` e `path`.
- agregações possuem chaves únicas por máquina/período.

## Timestamps E Timezone

- Persistir timestamps em ISO 8601.
- Agregações devem respeitar o timezone da fábrica/unidade.
- O padrão local inicial é `America/Sao_Paulo`.

## Ausência De Dados

Ausência de frames, câmera offline ou inferência inativa deve ser marcada como dado indisponível.

Nunca interpretar ausência de dados como:

- máquina parada;
- máquina ativa;
- área vazia;
- operador ausente.

## Métricas Permitidas

As métricas atuais são métricas operacionais estimadas. Não chamar de OEE.

São calculadas por máquina, hora, turno e dia:

- tempo monitorado confiável;
- tempo ativo;
- tempo parado;
- quantidade de paradas;
- duração média;
- maior parada;
- microparadas;
- tempo ativo sem operador;
- tempo parado com operador;
- tempo parado sem operador;
- câmera offline;
- inferência indisponível;
- percentual de cobertura confiável.

## Insights

Insights são determinísticos e rastreáveis.

Cada insight deve conter:

- `insight_id`;
- título;
- descrição factual;
- período analisado;
- métricas utilizadas;
- `event_ids` relacionados;
- `rule_id`;
- `rule_version`;
- qualidade dos dados;
- ação recomendada;
- `created_at`.

Não gerar:

- avaliação subjetiva sobre funcionários;
- reconhecimento facial;
- ranking individual;
- pontuação individual de produtividade.
