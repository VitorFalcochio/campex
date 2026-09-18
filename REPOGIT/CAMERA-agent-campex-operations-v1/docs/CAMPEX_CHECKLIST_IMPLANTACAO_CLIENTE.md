# Campex — Checklist de Implantação do Piloto

## 1. Antes de sair para o cliente

- Confirmar acesso à Campex Cloud
- Confirmar usuário e senha de acesso
- Confirmar Edge disponível para download
- Confirmar câmera/NVR que será usado no piloto
- Confirmar IP, usuário e senha da câmera/NVR
- Confirmar que o computador do cliente tem internet
- Confirmar que o computador ficará ligado durante o piloto
- Configurar suspensão do Windows como “Nunca” quando conectado à energia
- Levar documentação de Segurança e Privacidade
- Levar Termo de Piloto
- Definir uma máquina ou processo visualmente observável para o teste
- Definir o que caracteriza `ACTIVE`, `STOPPED` e `UNKNOWN`

---

## 2. Chegada ao cliente

- Confirmar responsável interno pelo piloto
- Confirmar autorização para uso das câmeras selecionadas
- Confirmar qual computador ficará com o Campex Edge
- Confirmar que o computador está na mesma rede das câmeras/NVR
- Confirmar acesso à internet
- Confirmar eventuais restrições de TI ou firewall

---

## 3. Instalação do Campex Edge

- Acessar a Campex pelo navegador
- Fazer login
- Abrir área de Edge
- Baixar o instalador correspondente à unidade
- Executar o instalador com permissão de administrador
- Confirmar instalação concluída
- Confirmar Edge `ONLINE` na Cloud
- Aguardar alguns minutos
- Confirmar que permanece `ONLINE`
- Não depender do navegador aberto para manter o Edge funcionando

Se o Edge não ficar `ONLINE`, não avançar para configuração da câmera antes de resolver a conectividade.

---

## 4. Conexão da câmera / NVR

- Confirmar IP do equipamento
- Confirmar porta RTSP
- Confirmar usuário autorizado
- Confirmar senha
- Confirmar canal correto da câmera
- Cadastrar a câmera na Campex
- Validar conexão RTSP
- Confirmar recebimento de frames
- Confirmar imagem correta na visualização ao vivo

Não testar várias câmeras ao mesmo tempo antes de validar completamente a primeira.

---

## 5. Seleção da máquina / processo

Escolher uma máquina em que seja visualmente possível distinguir seu comportamento operacional.

Priorizar:

- partes móveis visíveis;
- fluxo de material visível;
- mudança visual clara entre funcionamento e parada;
- iluminação estável;
- câmera com visão suficiente da área analisada.

Evitar usar como primeiro teste máquinas em que quase todo o funcionamento ocorre internamente e não é visível pela câmera.

---

## 6. Configuração da área operacional

- Abrir visualização da câmera
- Criar zona da máquina
- Criar zona do operador apenas se necessária como contexto
- Confirmar que as zonas estão posicionadas corretamente
- Salvar configuração
- Executar calibração
- Confirmar qualidade do sinal visual
- Ajustar zona ou câmera se necessário

---

## 7. Validação do core operacional

Executar, sempre que possível, uma sequência controlada:

### Estado 1 — ACTIVE

- Máquina funcionando
- Confirmar que Campex reconhece atividade
- Registrar horário

### Estado 2 — STOPPED

- Máquina interrompida de forma segura e autorizada
- Confirmar mudança de estado
- Aguardar tempo mínimo configurado
- Confirmar geração do evento esperado

### Estado 3 — ACTIVE novamente

- Retomar operação
- Confirmar recuperação
- Confirmar encerramento correto da parada
- Confirmar duração registrada

Resultado mínimo esperado:

`ACTIVE → STOPPED → ACTIVE`

---

## 8. Eventos e evidências

Após provocar uma parada controlada:

- Confirmar evento na plataforma
- Confirmar horário correto
- Confirmar duração
- Confirmar máquina/câmera correta
- Confirmar evidência visual
- Confirmar que não houve duplicação absurda de eventos
- Confirmar que ausência de operador não foi tratada como evento crítico isolado

Não considerar o piloto validado apenas porque a tela mostra um evento. O acontecimento registrado deve corresponder ao que realmente ocorreu fisicamente.

---

## 9. Inteligência e histórico

- Abrir histórico operacional
- Confirmar presença do evento testado
- Confirmar leitura coerente do período
- Confirmar que métricas não apresentam dados impossíveis
- Confirmar que períodos sem dados não são interpretados como acontecimentos reais
- Confirmar que a Campex diferencia falta de informação de operação parada

---

## 10. Relatório

Se houver cobertura suficiente de dados:

- Gerar ou revisar relatório operacional
- Confirmar números principais
- Confirmar que eventos técnicos não aparecem como acontecimentos operacionais
- Confirmar linguagem adequada para o cliente
- Confirmar evidências e acontecimentos destacados

Se não houver dados suficientes, a Campex deve informar cobertura insuficiente e não inventar conclusões.

---

## 11. Validação de estabilidade

Antes de sair do cliente:

- Confirmar Edge `ONLINE`
- Fechar navegador e confirmar que Edge permanece `ONLINE`
- Confirmar que Windows não está configurado para suspensão automática
- Confirmar câmera conectada
- Confirmar Live funcionando
- Confirmar último estado operacional recebido
- Confirmar que não existem erros críticos visíveis

Se possível:

- reiniciar o computador;
- não abrir nada da Campex;
- confirmar pela Cloud que Edge retorna `ONLINE` sozinho.

---

## 12. Critérios mínimos de sucesso do piloto

O primeiro piloto será considerado tecnicamente válido quando for possível demonstrar:

1. Edge funcionando sem intervenção manual contínua
2. câmera real conectada
3. imagem recebida corretamente
4. zona operacional configurada
5. estado operacional interpretado de forma coerente
6. pelo menos uma transição real `ACTIVE → STOPPED → ACTIVE`
7. evento correspondente registrado
8. evidência visual associada
9. histórico acessível na Cloud
10. funcionamento mantido durante o período combinado

---

## 13. O que NÃO prometer durante a implantação

Não prometer, sem validação específica:

- 100% de precisão
- identificação nominal de funcionários
- reconhecimento facial
- contagem de produção em qualquer máquina
- funcionamento em qualquer câmera ou ângulo
- detecção de causa de parada sem evidência suficiente
- substituição de sistemas de segurança
- disponibilidade ininterrupta
- integração com ERP/MES/WMS ainda não implementada
- retorno financeiro específico antes de medir a operação real

---

## 14. Ao finalizar a implantação

Registrar internamente:

- cliente
- unidade
- responsável
- computador do Edge
- Edge ID
- câmera utilizada
- máquina/processo analisado
- zonas configuradas
- horário de início
- resultado do teste `ACTIVE / STOPPED / ACTIVE`
- eventos gerados
- problemas encontrados
- próximos ajustes
- data da próxima revisão

A implantação só deve ser considerada concluída quando a Campex estiver coletando dados reais e houver clareza sobre o que será observado durante o piloto.