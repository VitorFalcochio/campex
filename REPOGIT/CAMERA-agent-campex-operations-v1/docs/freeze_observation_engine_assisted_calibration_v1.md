# Campex Observation Engine + Assisted Calibration V1

Este arquivo congela o procedimento de validacao presencial do marco **Campex Observation Engine + Assisted Calibration V1**.

Escopo congelado:

- Live View com camera RTSP cadastrada.
- Deteccao de pessoas ja existente.
- Zonas persistentes por camera.
- Machine region persistente.
- Observation Engine para estados de maquina e operador.
- Calibracao assistida de maquina ativa e parada usando frames reais.
- Persistencia local em SQLite.
- Outbox local para sincronizacao posterior.

Nao fazem parte deste marco:

- Novas classes YOLO.
- Novo algoritmo de deteccao.
- Alteracao de arquitetura.
- Alteracao de interface fora do fluxo existente.
- Envio de video continuo para nuvem.
- Configuracao fixa para qualquer cliente especifico.

## Variaveis de ambiente

Variaveis principais da aplicacao local:

```bash
API_HOST=127.0.0.1
API_PORT=8000
CAMPEX_SECRET_KEY=troque-por-uma-chave-grande-antes-do-piloto
CAMPEX_CREDENTIAL_KEY=troque-por-outra-chave-grande-se-desejar
CAMPEX_ENV=development
CAMPEX_APP_URL=http://127.0.0.1:8000
```

Credenciais e fonte RTSP:

```bash
RTSP_URL=rtsp://usuario:senha@endereco-da-camera/caminho
CAMERA_RTSP_HOST=192.168.1.20
CAMERA_RTSP_PORT=554
CAMERA_RTSP_PATH=/caminho/do/stream
```

IA e rastreamento:

```bash
CAMPEX_YOLO_MODEL=yolo11n.pt
CAMPEX_YOLO_CONFIDENCE=0.35
CAMPEX_ANALYSIS_FPS=2
CAMPEX_TRACKING_ENABLED=true
CAMPEX_YOLO_CLASSES=person
```

Video local de validacao sem DVR:

```bash
CAMPEX_VIDEO_SOURCE_MODE=file
CAMPEX_VIDEO_FILE=/caminho/para/video.mp4
```

Eventos de area e operador:

```bash
CAMPEX_EVENT_ENTRY_DELAY_SECONDS=1.0
CAMPEX_EVENT_EXIT_GRACE_SECONDS=2.0
CAMPEX_EVENT_COOLDOWN_SECONDS=3.0
CAMPEX_EVENT_SEVERITY=high
CAMPEX_WORKSTATION_ABSENCE_SECONDS=30
CAMPEX_ZONE_DWELL_SECONDS=300
CAMPEX_ZONE_EVENT_SECONDS=5
CAMPEX_ZONE_COOLDOWN_SECONDS=60
CAMPEX_ZONE_EXIT_GRACE_SECONDS=2
```

Monitoramento de maquina e replay:

```bash
CAMPEX_MACHINE_ANALYSIS_FPS=5
CAMPEX_MACHINE_STOP_SECONDS=10
CAMPEX_MACHINE_RECOVERY_SECONDS=3
CAMPEX_MACHINE_MOTION_SMOOTHING_SECONDS=2
CAMPEX_OPERATOR_ABSENCE_SECONDS=30
CAMPEX_STOPPED_WITH_OPERATOR_SECONDS=120
CAMPEX_MICROSTOP_WINDOW_SECONDS=3600
CAMPEX_MICROSTOP_LIMIT=5
CAMPEX_REPLAY_PRE_SECONDS=60
CAMPEX_REPLAY_POST_SECONDS=30
CAMPEX_REPLAY_FPS=5
CAMPEX_REPLAY_MAX_WIDTH=1280
```

Snapshots e retencao:

```bash
CAMPEX_OPERATION_SNAPSHOT_RETENTION_DAYS=30
CAMPEX_EVIDENCE_RETENTION_DAYS=90
```

E-mail:

```bash
CAMPEX_EMAIL_MODE=console
CAMPEX_EMAIL_MAX_ATTEMPTS=3
CAMPEX_EMAIL_FROM=campex@localhost
CAMPEX_SMTP_HOST=smtp.exemplo.com
CAMPEX_SMTP_PORT=587
CAMPEX_SMTP_USERNAME=usuario_smtp
CAMPEX_SMTP_PASSWORD=senha_smtp
CAMPEX_SMTP_USE_TLS=true
```

Edge e Cloud local:

```bash
CAMPEX_EDGE_ID=edge_cliente_01
CAMPEX_EDGE_SECRET=troque-por-um-segredo-gerado-para-este-edge
CAMPEX_CLOUD_URL=http://127.0.0.1:8010
CAMPEX_TENANT_ID=cliente_configurado
CAMPEX_UNIDADE_ID=unidade_configurada
CAMPEX_CAMERA_ID=camera_configurada
DATABASE_URL=postgresql://usuario:senha@127.0.0.1:5432/campex_cloud
CLOUD_HOST=0.0.0.0
CLOUD_PORT=8000
PORT=8000
```

## Procedimento presencial de validacao

### 1. Preparar ambiente

No computador local da fabrica:

```bash
cd /caminho/para/CAMERA
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Edite o `.env` local com as chaves do piloto, credenciais SMTP se forem usadas e dados do Edge. Nao coloque senha RTSP em arquivos versionados nem em mensagens publicas.

### 2. Iniciar a Campex local

```bash
python3 -m app.main
```

Abrir no navegador:

```text
http://127.0.0.1:8000/dashboard
```

Para acesso por outro dispositivo da mesma rede, iniciar com `API_HOST=0.0.0.0` e abrir o IP local do computador na porta configurada.

### 3. Cadastrar cliente, unidade, Edge e camera

Use a interface de configuracoes da Campex para cadastrar:

1. Cliente.
2. Unidade.
3. Edge.
4. Camera RTSP.

O cadastro deve ser feito por configuracao. O codigo nao deve ser alterado para implantar um novo cliente.

### 4. Validar RTSP e Live View

1. Testar conexao da camera.
2. Confirmar status online.
3. Abrir a Live View.
4. Confirmar video, resolucao, FPS e deteccao de pessoas.

Se a camera nao abrir, validar rede local, usuario, senha, canal RTSP e permissao do DVR.

### 5. Criar zonas

Na Live View:

1. Clicar em `Nova zona`.
2. Selecionar o tipo adequado.
3. Nomear a zona.
4. Desenhar o poligono sobre o video.
5. Salvar.
6. Atualizar a pagina e confirmar que a zona continua desenhada.
7. Reiniciar o backend e confirmar novamente.

Para calibracao de maquina, deve existir uma zona do tipo `machine_region`.

### 6. Selecionar ou cadastrar maquina

Na Live View:

1. Selecionar uma maquina ja vinculada a camera; ou
2. Cadastrar uma nova maquina vinculada a camera persistente.

Confirmar que a maquina possui ID persistente, camera, cliente e unidade resolvidos pelo cadastro.

### 7. Calibrar maquina ativa

Com a maquina em funcionamento real:

1. Confirmar que a `machine_region` esta carregada.
2. Clicar em `Calibrar maquina ativa`.
3. Aguardar 30 segundos.
4. Ver progresso de 0% a 100%.
5. Confirmar quantidade de amostras.
6. Confirmar media, mediana, desvio, minimo, maximo e percentis.

A 5 FPS, a expectativa e coletar aproximadamente 150 amostras em 30 segundos, descontando frames invalidos ou intervalos de inicializacao.

### 8. Calibrar maquina parada

Com a maquina parada de forma natural e autorizada:

1. Clicar em `Calibrar maquina parada`.
2. Aguardar 30 segundos.
3. Confirmar amostras e estatisticas.
4. Confirmar o `separation score`.

Resultados possiveis:

- `READY`: separacao adequada para monitorar.
- `WEAK_SEPARATION`: separacao fraca; reposicionar ROI ou revisar iluminacao.
- `INVALID`: dados insuficientes ou invalidos.

Se o resultado for fraco ou invalido, nao considerar o monitoramento aprovado sem revisao tecnica.

### 9. Iniciar monitoramento

Quando a calibracao estiver `READY`:

1. Clicar em `Iniciar monitoramento`.
2. Confirmar `activity_score` em tempo real.
3. Confirmar estado `ACTIVE`, `STOPPED` ou `UNKNOWN`.
4. Confirmar confianca.
5. Confirmar tempo no estado.

O monitoramento nao deve depender de `curl` nem de arrays manuais.

### 10. Validar persistencia

1. Atualizar a pagina.
2. Confirmar maquina, zonas e calibracoes.
3. Reiniciar o backend.
4. Abrir a Live View novamente.
5. Confirmar que tudo foi preservado.

### 11. Validar eventos e outbox

Quando uma regra operacional confirmar um evento:

1. Confirmar que o evento tem `event_uuid`.
2. Confirmar que foi salvo no SQLite local.
3. Confirmar que entrou na `sync_outbox`.
4. Se Cloud estiver desligado, confirmar status pendente.
5. Ligar Cloud local.
6. Rodar sincronizacao.
7. Confirmar que o evento aparece uma unica vez no dashboard Cloud.

## Auditoria de hardcode de cliente

O produto deve funcionar por configuracao:

```text
tenant -> unidade -> Edge -> cameras -> zonas -> regras -> eventos
```

No freeze deste marco, nao ha nomes, IDs, cameras, unidades, segredos ou comportamentos de um cliente laboratorio hardcoded na logica operacional de `app/`, `edge_agent/` ou `cloud/`.

Referencias a cliente laboratorio podem existir apenas como:

- exemplos de README;
- testes automatizados;
- valores demonstrativos em comandos locais;
- dados locais configurados pelo operador.

Para implantar um segundo cliente, o procedimento esperado e cadastrar novos registros e variaveis locais, sem alteracao de codigo.

## Comandos de verificacao do marco

Executar a suite completa:

```bash
python3 -m pytest -q
```

Resultado esperado neste freeze:

```text
127 passed
```

Verificar referencias de laboratorio fora de dados locais:

```bash
rg -n "FL Pl[aá]sticos|fl_plasticos|Extrusora|Felipe|192\\.168|Intelbras|supabase" app edge_agent cloud frontend scripts manage.py README.md .env.example tests
```

Ao encontrar referencias, confirmar se estao apenas em exemplos, testes ou placeholders, nunca em decisao de regra, tenant, evento, camera ou autorizacao.
