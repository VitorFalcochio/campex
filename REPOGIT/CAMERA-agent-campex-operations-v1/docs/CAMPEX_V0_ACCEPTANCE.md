# CAMPEX V0 - Roteiro de Aceite Integrado

Este roteiro valida a Campex como um produto integrado:

Setup -> Live -> Evento real -> Events -> Operations -> Intelligence -> Evidência.

## Pré-requisitos

- API local iniciada.
- Usuário com permissão administrativa.
- Câmera cadastrada e acessível na rede local.
- Modo de e-mail configurado conforme o piloto.
- Banco SQLite preservado em `data/`.
- Sem uso de dados fictícios ou endpoint `/dev/test-event`.

## A. Configurar uma fábrica

1. Abra `http://127.0.0.1:8000/settings/cameras`.
2. Entre com o usuário administrativo.
3. Na seção **Setup -> Estrutura da operação**, crie ou selecione o cliente.
4. Crie a unidade/fábrica.
5. Confirme que a unidade aparece em **Hierarquia configurada**.

## B. Configurar área, processo e ativo

1. Em **Área**, selecione a unidade e crie a área operacional.
2. Em **Processo/Estação**, selecione a área e crie o processo.
3. Em **Máquina/Posto**, selecione o processo e crie o ativo.
4. Confirme a hierarquia:
   `Unidade -> Área -> Processo -> Ativo`.

## C. Associar câmera

1. Cadastre a câmera RTSP em **Câmeras RTSP**, se ela ainda não existir.
2. Teste a conexão.
3. Salve a câmera.
4. Em **Associar câmera ao ativo**, selecione a câmera e o ativo.
5. Clique em **Associar câmera**.
6. Confirme que a câmera aparece vinculada ao ativo.

## D. Configurar monitoramento

1. Em **Zonas, tolerâncias e monitor**, selecione a câmera.
2. Clique em **Abrir câmera para desenhar zonas**.
3. No vídeo, clique em **Preparar área**.
4. Desenhe a região da máquina e salve com tipo `machine_region`.
5. Desenhe a zona do operador e salve com tipo `operator_zone`.
6. Defina:
   - Considere parada após;
   - Considere ausência após;
   - Parada com operador após.
7. Clique em **Salvar monitor com zonas desenhadas**.
8. Confirme em **Status de configuração**:
   `Pronto para monitorar`.

## E. Provocar evento

1. Abra `http://127.0.0.1:8000/live-grid`.
2. Abra a câmera/setor configurado.
3. Ative a análise conforme o fluxo atual.
4. Provoque uma condição real suportada:
   - parada/interrupção; ou
   - ausência de operador na zona.
5. Aguarde a tolerância configurada.
6. Confirme que o evento aparece sem ação manual.

## F. Visualizar Live

1. Em `Live`, confirme:
   - ativo/processo/área como contexto principal;
   - vídeo ativo;
   - status operacional;
   - evento aberto quando existir;
   - link **Ver evento** quando aplicável.

## G. Abrir Events

1. Abra `http://127.0.0.1:8000/events`.
2. Localize o evento pelo horário, ativo ou família.
3. Abra o detalhe.
4. Confirme:
   - `event_uuid`;
   - início;
   - fim ou em andamento;
   - duração;
   - contexto operacional;
   - evidência quando disponível.

## H. Reconhecer

1. No detalhe do evento, clique em **Reconhecer**.
2. Confirme que o workflow muda para `acknowledged`.
3. O estado físico do evento não deve ser alterado por essa ação.

## I. Adicionar causa e ação

1. Registre a causa confirmada somente se ela for conhecida por uma pessoa.
2. Registre a ação tomada.
3. Adicione notas humanas, se necessário.
4. Confirme que os fatos observados pela Campex permanecem separados do contexto humano.

## J. Resolver

1. Clique em **Resolver**.
2. Confirme:
   - `resolved_at`;
   - `resolved_by`;
   - causa;
   - ação;
   - notas.
3. A resolução não deve alterar início, fim, duração ou evidência original.

## K. Verificar Operations

1. Abra `http://127.0.0.1:8000/operations-view`.
2. Confirme que o mesmo evento aparece nas métricas e rastreabilidade.
3. Confirme que `unknown` não lidera briefing nem principais perdas.
4. Confirme cobertura, período e contexto em linguagem humana.

## L. Verificar Intelligence

1. Abra `http://127.0.0.1:8000/insights`.
2. Confirme que insights só aparecem quando sustentados por dados reais.
3. Abra um insight e valide os `event_uuid` que sustentam a afirmação.
4. Clique para investigar e confirme navegação para Events.

## M. Reiniciar aplicação

1. Pare a aplicação com `Ctrl+C`.
2. Inicie novamente:

```bash
python3 -m app.main
```

3. Abra novamente `http://127.0.0.1:8000/settings/cameras`.

## N. Confirmar persistência

Após reiniciar, confirme:

- hierarquia preservada;
- câmera preservada;
- zonas preservadas;
- monitor preservado;
- evento preservado;
- evidência preservada;
- workflow humano preservado;
- outbox/alertas preservados conforme estado real.

## Rotas oficiais da Campex V0

- Operations: `/operations-view`
- Events: `/events`
- Intelligence: `/insights`
- Live: `/live-grid`
- Setup: `/settings/cameras`

## Arquivos legado auditados

### MANTER

- `app/models.py`: fonte de persistência local.
- `app/api.py`: API principal.
- `app/machine_monitoring.py`: runtime oficial de máquina.
- `app/observation_engine.py`: motor de observação.
- `app/people_zones.py`: zonas e presença.
- `app/visual_rule_engine.py`: regras visuais ainda usadas.
- `app/operational_context.py`: hierarquia operacional.
- `app/operational_read_model.py`: leitura canônica para Operations/Intelligence.
- `frontend/workspace.html` e `frontend/workspace.js`: shell de Operations, Events e Intelligence.
- `frontend/live-grid.html`, `frontend/live-grid.js`, `frontend/live-view.html`, `frontend/live-view.js`: Live.
- `frontend/index.html`, `frontend/app.js`: Setup V0.
- `edge_agent/*`: execução Edge e sincronização.
- `cloud/*`: integração Edge -> Cloud local.
- `tools/vision_lab.py`: laboratório isolado, fora do runtime principal.

### ARQUIVAR

- `frontend/dashboard.html`: rota legada preservada para compatibilidade.
- `frontend/operations-dashboard.html`: dashboard antigo.
- `frontend/operations-dashboard.js`: lógica visual antiga de dashboard.
- `frontend/people-zones.html`: tela técnica anterior de zonas.
- `frontend/people-zones.js`: lógica técnica anterior de zonas.
- `app/live_view_ops.py`: compatibilidade de renderização antiga, não deve decidir máquina/eventos.
- `app/operations_history.py`: compatibilidade histórica; não deve ser fonte canônica de eventos.
- `app/analytics.py`: analytics anterior, deve convergir para Read Model quando usado.
- `app/reports.py`: relatórios legados simples.

### REMOVIDOS EM LIMPEZA SEGURA PRÉ-VISION V1

Removidos em etapa dedicada de limpeza após auditoria de referências e testes:

- `app/api.py.orig`
- `app/api.py.backup`
- `app/live_stream.py.orig`
- `app/live_stream.py.backup`
- `app/machine_monitoring.py.orig`
- `app/machine_monitoring.py.backup`
- `frontend/campex-brand-board.png`
- `frontend/campex-logo-hero.png`
- `frontend/.DS_Store`

## Critério final

A Campex V0 está integrada quando:

- Setup configura a operação;
- Live observa usando o mesmo contexto;
- eventos usam `eventos` como fonte canônica;
- Events mostra o acontecimento e evidência;
- Operations agrega pelo Read Model;
- Intelligence gera insights determinísticos;
- deep links preservam `event_uuid`;
- reinício não apaga configuração nem histórico.
