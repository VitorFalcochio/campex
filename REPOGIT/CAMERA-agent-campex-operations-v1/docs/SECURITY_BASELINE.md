# Campex Security Baseline

Baseline mínimo de segurança para o piloto.

## Segredos

- Não versionar `.env`.
- Não versionar senha RTSP, SMTP, tokens ou `edge_secret`.
- `.env.example` deve conter apenas placeholders.
- Logs não devem conter URL RTSP com usuário/senha.

## Autenticação E Autorização

- Endpoints privados devem usar `require_user`.
- Alterações administrativas devem usar `require_role`.
- Consultas por cliente devem usar `tenant_filter` ou checagem equivalente.
- Usuário de um cliente não pode acessar câmeras, regras, eventos ou configurações de outro cliente.

## Edge → Cloud

- Cada instalação deve possuir `CAMPEX_EDGE_ID` e `CAMPEX_EDGE_SECRET`.
- Mensagens Edge → Cloud usam headers:
  - `X-Edge-Id`;
  - `X-Edge-Secret`;
  - `Idempotency-Key`.
- O Cloud valida secret, tenant e idempotência por `event_uuid`.

## Audit Log

Tabela local:

```text
audit_log
```

Eventos mínimos auditáveis:

- login;
- cadastro/alteração/remoção de câmera;
- cadastro/alteração/remoção de monitor de máquina;
- regras;
- destinatários de alerta;
- exportações, quando existirem.

O audit log não deve armazenar senha, RTSP completo, tokens ou `edge_secret`.

## Evidências E Retenção

- Evidências ficam em `data/evidence`.
- Retenção configurável por `CAMPEX_EVIDENCE_RETENTION_DAYS`.
- Não apagar eventos recentes, abertos ou não reconhecidos sem procedimento humano.
- Não armazenar vídeo contínuo.

## Exposição De Rede

- A aplicação não deve ser exposta publicamente por padrão.
- No piloto, operar em rede local.
- Não abrir DVR/RTSP para a internet.

## Backup E Restauração

Backup:

```bash
python manage.py backup --output-dir backups
```

Restauração:

```bash
python manage.py restore --archive CAMINHO_DO_BACKUP
```

## Limites Operacionais

- Monitorar espaço em disco via `/edge/status`.
- Usar `/ready` antes de teste de campo.
- Usar `factory-preflight` antes de validação presencial.

## Revisão Humana Obrigatória

Ainda dependem de revisão humana antes de piloto contínuo:

- rotação real de segredos;
- política final de retenção;
- permissões por perfil em todos os fluxos de tela;
- procedimento formal de exportação de dados;
- termos de uso e aviso de monitoramento ao cliente.
