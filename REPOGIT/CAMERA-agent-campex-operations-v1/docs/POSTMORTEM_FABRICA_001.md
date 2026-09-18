# Postmortem Fábrica 001

Data: 03/08/2026

## Resumo

A ida à fábrica mostrou que a base visual da Campex já consegue abrir câmera real e detectar pessoas, mas ainda não houve validação operacional completa de máquina + operador + evento.

Este postmortem transforma os problemas observados em critérios objetivos de pré-validação antes de novo teste presencial.

## O que funcionou

- A câmera/DVR abriu na Live View.
- O vídeo real apareceu no navegador.
- A detecção de pessoas funcionou.
- Duas câmeras já foram abertas anteriormente em validações anteriores.
- Uma zona de trabalho já havia sido criada anteriormente.

## Problemas observados

- FPS de inferência apareceu zerado.
- Frames analisados apareceram zerados.
- Um vídeo/canvas duplicado apareceu sobre a página e bloqueou partes da interface.
- O elemento duplicado cobriu a coluna “Contexto operacional”.
- O cadastro/configuração da máquina não ficou utilizável durante o teste.
- Alertas visíveis na Live View não foram comprovados.
- E-mail não foi comprovado.
- Acesso remoto não foi concluído.
- Não houve validação real de máquina + operador + evento.
- O pré-teste automatizado inicial consultou a API sem autenticação completa.

## Impacto

O teste comprovou partes técnicas importantes, mas não comprovou ainda o fluxo comercial principal:

vídeo real
→ IA
→ zona
→ operador ausente
→ evento automático
→ evidência real
→ alerta
→ histórico
→ duração.

## Causa provável

Os problemas foram menos ligados à detecção e mais ligados à preparação operacional do ambiente antes do teste:

- falta de checklist automático antes da ida;
- falta de confirmação objetiva de IA ativa;
- falta de confirmação de frames analisados aumentando;
- falta de confirmação de zonas e monitor de máquina prontos;
- falta de confirmação visual de SSE/alertas antes do teste real.
- falta de autenticação explícita no comando de pré-validação.

## Decisão

Antes de nova validação presencial, executar:

```bash
CAMPEX_PREFLIGHT_EMAIL="usuario@empresa.com" \
CAMPEX_PREFLIGHT_PASSWORD="senha" \
CAMPEX_PREFLIGHT_CAMERA_ID="camera_id" \
CAMPEX_EMAIL_MODE=console \
python manage.py factory-preflight --api-url http://127.0.0.1:8000 --timeout 5
```

O teste presencial só deve começar se o comando concluir:

```text
PRONTO PARA TESTE DE CAMPO
```

Se retornar:

```text
NÃO PRONTO PARA TESTE DE CAMPO
```

os itens marcados como `FAIL` devem ser corrigidos antes da ida à fábrica.

Itens marcados como `NOT TESTED` indicam que a checagem não teve pré-condição suficiente para ser comprovada, por exemplo câmera alvo ausente ou rede da fábrica indisponível. `NOT TESTED` não deve ser tratado como sucesso.

## Itens que precisam ser comprovados na próxima ida

1. API iniciada.
2. Login funcionando.
3. Banco acessível.
4. Câmera cadastrada.
5. Câmera online.
6. Stream recebendo frames.
7. IA realmente iniciada.
8. FPS de inferência maior que zero.
9. Frames analisados aumentando.
10. Zona do operador salva.
11. Região da máquina salva.
12. Monitor de máquina configurado.
13. Calibração ativa/parada válida.
14. SSE de eventos conectado.
15. Pasta de evidências gravável.
16. Modo de alertas configurado.
17. Espaço em disco suficiente.

## Critério para repetir o teste presencial

A próxima validação presencial deve ser curta e objetiva:

1. abrir a Live View;
2. confirmar vídeo real;
3. confirmar IA ativa;
4. confirmar frames analisados aumentando;
5. confirmar operator_zone salva;
6. pessoa dentro da zona: normal;
7. pessoa sai por mais de 5 segundos;
8. evento `workstation_unattended` aparece na Live View;
9. evidência real abre pelo link;
10. pessoa volta;
11. evento fecha com duração.

## Classificação

**NÃO VALIDADO COMO FLUXO OPERACIONAL COMPLETO**

A base técnica funcionou parcialmente, mas a Campex ainda precisa comprovar em campo o fluxo real de máquina + operador + evento antes de ser considerada pronta para piloto assistido contínuo.
