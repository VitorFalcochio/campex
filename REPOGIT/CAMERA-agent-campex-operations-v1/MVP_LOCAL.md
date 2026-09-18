# MVP local de produto

Esta etapa organiza o projeto para vários clientes, unidades, câmeras e regras,
sem conectar câmeras ao vivo ainda.

O detector atual continua separado:

- `monitor_machine.py`
- `monitor_context.py`
- `check_source.py`

## O que foi criado

- Cadastro de clientes.
- Cadastro de unidades.
- Cadastro de câmeras.
- Cadastro de regras monitoradas.
- Registro de eventos.
- Registro de alertas.
- Relatório diário em texto.
- Banco local SQLite em `data/visual_ops_mvp.sqlite3`.

Importante: cadastrar uma câmera no banco não conecta a câmera. A conexão ao vivo
fica para a próxima etapa.

## Primeiro comando

```bash
python3 mvp.py init-db
```

## Exemplo de uso

Cadastre um cliente:

```bash
python3 mvp.py add-tenant --name "Cliente Exemplo"
```

O comando vai imprimir um `tenant_id`. Use esse código nos próximos comandos.

Cadastre uma unidade:

```bash
python3 mvp.py add-site --tenant-id TENANT_ID --name "Fabrica 1" --location "Sao Paulo"
```

Cadastre uma câmera:

```bash
python3 mvp.py add-camera --tenant-id TENANT_ID --site-id SITE_ID --name "Camera Linha 1"
```

Cadastre uma regra:

```bash
python3 mvp.py add-rule --tenant-id TENANT_ID --site-id SITE_ID --camera-id CAMERA_ID --name "Maquina parada" --rule-type machine_stopped
```

Registre um evento:

```bash
python3 mvp.py add-event --tenant-id TENANT_ID --site-id SITE_ID --camera-id CAMERA_ID --rule-id RULE_ID --event-type machine_stopped --duration-seconds 300 --severity warning
```

Registre um alerta:

```bash
python3 mvp.py add-alert --tenant-id TENANT_ID --site-id SITE_ID --camera-id CAMERA_ID --rule-id RULE_ID --title "Maquina parada" --message "Parada detectada por mais de 5 minutos."
```

Gere o relatório diário:

```bash
python3 mvp.py daily-report
```

Para uma data específica:

```bash
python3 mvp.py daily-report --date 2026-07-15
```

## Consultar registros

```bash
python3 mvp.py list tenants
python3 mvp.py list sites
python3 mvp.py list cameras
python3 mvp.py list rules
python3 mvp.py list events
python3 mvp.py list alerts
```

## Próxima etapa

A próxima etapa deve criar um agente de câmera ao vivo. Esse agente deve ler cada
câmera separadamente, gravar eventos no banco local e nunca misturar dados de
clientes ou câmeras diferentes.

