# Campex MVP Instalável V1

Este é o caminho oficial para instalar e configurar a Campex em uma indústria nova no estado atual do MVP.

Use esta documentação em vez de instruções históricas espalhadas pelo repositório.

## 1. Preparar O Computador

Requisitos:

- Python 3.11 recomendado;
- FFmpeg recomendado para diagnósticos/replays, mas não é requisito crítico do runtime RC1: o pipeline atual usa OpenCV para captura e gravação de evidências/clipes;
- acesso à rede local das câmeras/DVR/NVR;
- navegador Chrome ou Edge;
- arquivo `.env` local, nunca versionado.

No Windows:

```powershell
.\scripts\setup_factory_windows.ps1
```

No Mac/Linux, use o instalador idempotente oficial:

```bash
python3 -m deployment.setup
```

Para instalar também o serviço local quando o SO for suportado:

```bash
python3 -m deployment.setup --install-service
```

O setup pode ser executado novamente. Ele reutiliza `.venv`, preserva banco, evidências e configuração existente.

## 2. Configurar `.env`

Copie `.env.example` para `.env` se ele ainda não existir.

Valores mínimos:

```bash
DATABASE_PATH=data/visual_ops_product.sqlite3
API_HOST=0.0.0.0
API_PORT=8000
CAMPEX_EDGE_ID=edge_cliente_01
CAMPEX_CREDENTIAL_KEY=gere-uma-chave-longa-e-unica-para-esta-instalacao
CAMPEX_EMAIL_MODE=console
```

O comando oficial `python manage.py run-edge-production` carrega o `.env` local automaticamente. Em produção, `CAMPEX_CREDENTIAL_KEY` precisa estar configurada com uma chave segura; placeholders do `.env.example` não são aceitos para iniciar o Edge.

Para e-mail real por SMTP:

```bash
CAMPEX_EMAIL_MODE=smtp
CAMPEX_SMTP_HOST=smtp.gmail.com
CAMPEX_SMTP_PORT=587
CAMPEX_SMTP_USERNAME=seu-email
CAMPEX_SMTP_PASSWORD=senha-de-app
CAMPEX_SMTP_USE_TLS=true
CAMPEX_EMAIL_FROM=seu-email
```

Não coloque RTSP, senha de câmera ou SMTP no Git.
O backup operacional padrão não inclui `.env`; guarde segredos em um local seguro separado.

## 3. Iniciar A Campex Edge

Windows:

```powershell
.\scripts\start_factory_windows.ps1
```

Mac/Linux:

```bash
python manage.py edge-service start
```

Para rodar em foreground durante instalação/validação:

```bash
python manage.py run-edge-production
```

Abrir no computador:

```text
http://127.0.0.1:8000/settings/cameras
```

Abrir em outro dispositivo da mesma rede:

```text
http://IP_DO_COMPUTADOR:8000/settings/cameras
```

Não exponha essa porta na internet.

## 4. First Run

Se o banco estiver vazio e não existir usuário, a tela de Setup mostra “Primeira instalação da Campex”.

Preencha:

1. nome do primeiro administrador;
2. e-mail;
3. senha;
4. empresa;
5. unidade inicial.

Depois que o primeiro usuário existir, o First Run fica bloqueado automaticamente.

## 5. Setup Da Operação

Em `Setup`, configure:

1. empresa;
2. unidade;
3. área;
4. processo/estação;
5. ativo/máquina/posto;
6. câmera RTSP;
7. associação da câmera ao ativo;
8. região da máquina;
9. zona do operador;
10. monitor e tolerâncias.

Use nomes humanos. A interface resolve os IDs internamente.

## 6. Cadastrar E Testar Câmera

Na seção `Câmeras RTSP`:

1. informe nome da câmera;
2. selecione unidade;
3. informe RTSP completo ou host/porta/caminho/usuário/senha;
4. clique `Testar conexão`;
5. se estiver OK, clique `Cadastrar câmera`;
6. mantenha marcada a opção `Ativar câmera no Edge após salvar` se ela deve iniciar no runtime.

Câmera desativada não é iniciada pelo Edge.

Se uma câmera ficar offline, ela não deve derrubar a interface nem as outras câmeras.

## 7. Configurar Monitor

Abra a câmera no Setup:

1. desenhe a `machine_region`;
2. desenhe a `operator_zone`;
3. informe nome da máquina;
4. configure tempos em linguagem operacional;
5. salve o monitor.

O checklist deve mostrar o que ainda falta.

## 8. Calibrar

Com a câmera online:

1. deixe a máquina funcionando;
2. execute calibração ativa;
3. aguarde a captura;
4. deixe a máquina parada de forma segura;
5. execute calibração parada;
6. confirme se o resultado ficou `READY`.

Se a câmera não estiver online, o checklist mostra:

```text
Pendente: câmera precisa estar online para calibrar
```

## 9. Alertas

Cadastre responsáveis em `Responsáveis por alertas`.

O Setup mostra:

- SMTP configurado;
- SMTP não configurado;
- modo console.

Use `CAMPEX_EMAIL_MODE=console` para validação local sem SMTP real.

Para testar e-mail pelo terminal:

```bash
python manage.py send-test-email --to "email@dominio.com"
```

## 10. Verificações

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8000/edge/status
python -m deployment.doctor
```

Antes de teste físico:

```bash
python -m deployment.preflight --profile local --api-url http://127.0.0.1:8000 --camera-timeout 5
```

Para piloto externo com Cloud obrigatória:

```bash
python -m deployment.preflight --profile external --api-url http://127.0.0.1:8000 --camera-timeout 5
```

Compatibilidade com o preflight histórico:

```bash
CAMPEX_PREFLIGHT_EMAIL="admin@cliente.com" \
CAMPEX_PREFLIGHT_PASSWORD="senha" \
CAMPEX_PREFLIGHT_CAMERA_ID="CAMERA_ID" \
python manage.py factory-preflight --api-url http://127.0.0.1:8000 --timeout 5
```

Só iniciar validação física quando o resultado for:

```text
PRONTO PARA TESTE DE CAMPO
```

## 11. Restart E Recovery Básico

Comandos oficiais mínimos no Mac/Linux:

```bash
# INSTALL
python3 -m deployment.setup --install-service

# START
python manage.py edge-service start

# STOP
python manage.py edge-service stop

# RESTART
python manage.py edge-service restart

# STATUS
python manage.py edge-service status

# DOCTOR
python -m deployment.doctor

# PREFLIGHT
python -m deployment.preflight --profile local --api-url http://127.0.0.1:8000 --camera-timeout 5

# PREFLIGHT EXTERNAL PILOT
python -m deployment.preflight --profile external --api-url http://127.0.0.1:8000 --camera-timeout 5

# LOGS
python manage.py edge-service logs
```

Parar no Windows:

```powershell
.\scripts\stop_factory_windows.ps1
```

Iniciar novamente:

```powershell
.\scripts\start_factory_windows.ps1
```

Dados persistidos:

- banco SQLite em `data/`;
- evidências em `data/evidence/`;
- logs em `logs/`;
- Edge ID estável em `data/edge_id.txt` quando não configurado no `.env`.

Reiniciar não deve apagar cliente, unidade, câmera, zonas, monitor, eventos, evidências, alertas ou outbox.
