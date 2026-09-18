# CAMPEX

CAMPEX e um MVP de operacao visual: transforma cameras, webcams ou videos locais em sensores operacionais com deteccao de pessoas, tracking, zonas, eventos, evidencias e revisao pelo operador.

## Fluxo principal

```text
Camera/video
-> Detection
-> Tracking
-> Zona
-> Evento
-> Evidencia
-> Revisao operacional
```

O caso principal do MVP e detectar uma pessoa entrando em uma zona restrita.

## Rodar o projeto

```bash
./start.sh
```

O script cria/atualiza o ambiente, instala dependencias, inicializa o SQLite e sobe:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:5174`

Portas customizadas:

```bash
CAMPEX_BACKEND_PORT=8001 CAMPEX_FRONTEND_PORT=5175 ./start.sh
```

## Como testar com video local

1. Abra `http://127.0.0.1:5174`.
2. Entre em `Câmeras` e cadastre um `video_file`, por exemplo `palace.mp4`.
3. Entre em `Áreas & zonas`.
4. Selecione a câmera/video e desenhe uma zona com pelo menos 3 pontos.
5. Use tipo `Restrita` para gerar evento crítico.
6. Entre em `Ao vivo` e ligue `Vision: ON`.
7. Abra `Eventos` para revisar ocorrências e evidências.

## Funcionalidades atuais

- CRUD de câmeras.
- Fontes `webcam`, `video_file` e `rtsp`.
- Stream MJPEG com overlay.
- RF-DETR com fallback configurado.
- Tracking por câmera.
- Mapeamento/pose quando o modelo estiver disponível.
- Desenho visual de zonas sobre vídeo/câmera.
- Eventos estruturados por regras determinísticas.
- Evidência automática por evento: frame limpo, overlay e metadata.
- Investigações persistidas no SQLite.
- Painel operacional, eventos, zonas, regras, evidências, diagnóstico e configurações.

## Endpoints principais

```text
GET    /api/v1/health
GET    /api/v1/cameras
POST   /api/v1/cameras
POST   /api/v1/cameras/{id}/vision/start
POST   /api/v1/cameras/{id}/vision/stop
GET    /api/v1/cameras/{id}/stream
GET    /api/v1/events
GET    /api/v1/events/{id}
GET    /api/v1/events/{id}/evidence
GET    /api/v1/zones
POST   /api/v1/zones
GET    /api/v1/operations/summary
GET    /api/v1/operations/diagnostics
GET    /api/v1/investigations
```

## Testes

```bash
.venv/bin/python -m pytest tests --maxfail=1 -q
node --check frontend/js/app.js
node --check frontend/js/api.js
```

## Observações

- RTSP precisa ser validado com câmera real no ambiente alvo.
- O primeiro uso de modelos de IA pode baixar pesos e demorar.
- `VISION_VIDEO_LOOP=true` e videos locais são úteis para desenvolvimento.
- Evidências ficam em `storage/evidence/`.
