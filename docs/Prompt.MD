# CAMPEX — ENGINEERING STANDARD

> Documento obrigatório para qualquer agente de IA que modifique este repositório.
> Este arquivo define o padrão mínimo de engenharia do CAMPEX.
> Ele possui prioridade sobre preferências individuais do agente.

---

# 1. REGRA ZERO

Antes de escrever código:

1. Leia este arquivo completamente.
2. Inspecione a estrutura atual do repositório.
3. Leia o README.
4. Leia a documentação relevante em `/docs`.
5. Entenda a implementação existente.
6. Identifique dependências entre módulos.
7. Identifique testes existentes.
8. Entenda como executar o projeto.
9. Só então altere código.

NUNCA comece implementando baseado apenas no prompt da tarefa.

O repositório existente é a fonte da verdade.

---

# 2. PRINCÍPIO CENTRAL

Não queremos código que apenas "funciona".

Queremos código:

- correto;
- simples;
- legível;
- modular;
- testável;
- observável;
- seguro;
- previsível;
- documentado;
- fácil de manter;
- preparado para evolução;
- consistente com a arquitetura existente.

Qualidade > quantidade.

Uma feature pequena e sólida é preferível a uma implementação grande e frágil.

---

# 3. NÃO REESCREVA O QUE JÁ FUNCIONA

Antes de criar qualquer:

- classe;
- serviço;
- endpoint;
- model;
- helper;
- componente;
- tabela;
- worker;
- interface;

procure se já existe algo equivalente.

Prefira:

EXTENDER
→ REUTILIZAR
→ REFATORAR COM SEGURANÇA

antes de:

DUPLICAR
→ SUBSTITUIR
→ REESCREVER

Não faça grandes refactors sem necessidade concreta.

---

# 4. RESPEITE A ARQUITETURA

O CAMPEX deve possuir fronteiras claras entre responsabilidades.

Exemplo conceitual:

Camera
↓
Video Engine
↓
Frame Management
↓
Motion
↓
Vision
↓
Tracking
↓
Spatial
↓
Events
↓
Temporal
↓
Patterns
↓
CAMPEX Intelligence

Uma camada não deve assumir responsabilidades de outra.

Evite módulos "Deus" que fazem tudo.

---

# 5. DEPENDENCY DIRECTION

Camadas de domínio não devem depender diretamente de detalhes de infraestrutura quando isso puder ser evitado.

Preferir:

Domain
↑
Interfaces
↑
Infrastructure

Exemplo:

VisionDetector
    ↑
RFDETRDetector

e não:

Todo o sistema
    ↓
RF-DETR diretamente

Bibliotecas externas devem ficar encapsuladas atrás de abstrações quando forem componentes substituíveis.

---

# 6. OPEN SOURCE NÃO É ARQUITETURA

Projetos GitHub podem ser utilizados como:

- referência;
- biblioteca;
- inspiração arquitetural;
- implementação de componentes específicos;

mas nunca devem automaticamente definir a arquitetura do CAMPEX.

Antes de adicionar uma dependência:

1. verifique se realmente precisamos dela;
2. verifique licença;
3. verifique manutenção;
4. verifique impacto no projeto;
5. verifique peso/dependências;
6. encapsule quando apropriado.

Nunca copie código sem entender origem, licença e implicações.

---

# 7. BACKEND

Backend deve ser:

- modular;
- tipado quando apropriado;
- previsível;
- observável;
- testável.

Evite lógica complexa dentro de endpoints.

Endpoint deve preferencialmente:

Request
↓
Validation
↓
Service
↓
Domain
↓
Repository/Infrastructure
↓
Response

Não transformar controllers/routes em services.

---

# 8. FASTAPI

Endpoints devem:

- possuir contratos claros;
- validar entrada;
- retornar status HTTP coerentes;
- tratar erros;
- evitar bloquear event loop;
- não executar processamento pesado diretamente na request thread/event loop;
- usar schemas consistentes.

Não criar endpoints duplicados.

Antes de adicionar rota, procure equivalente existente.

---

# 9. BANCO DE DADOS

Banco não é depósito de tudo.

Persistir somente informação que possui valor persistente.

Evitar:

- frame por frame;
- métricas temporárias desnecessárias;
- bounding boxes infinitas;
- estados efêmeros que pertencem à memória.

Toda alteração estrutural deve considerar:

- compatibilidade;
- migração;
- índices;
- constraints;
- relacionamentos;
- crescimento futuro.

Não apagar dados silenciosamente.

---

# 10. CONCORRÊNCIA E WORKERS

Qualquer thread/task/worker deve possuir lifecycle explícito.

Precisa ser possível:

START
STOP
RESTART
FAIL
RECOVER

Nunca criar:

while True

sem:

- condição de saída;
- tratamento de erro;
- cleanup;
- controle de lifecycle.

Evitar concorrência global descontrolada.

---

# 11. PERFORMANCE

Não otimizar cegamente.

Primeiro medir.

Depois otimizar.

Para pipelines realtime:

LATÊNCIA > PROCESSAR TODO FRAME.

Quando necessário:

frame novo
substitui
frame antigo.

Evitar filas infinitas.

Evitar processamento redundante.

Modelos pesados devem ser carregados uma vez e reutilizados.

---

# 12. VISÃO COMPUTACIONAL

Nunca misturar conceitos.

Detection ≠ Tracking.

LocalTrack ≠ GlobalEntity.

Re-ID ≠ Employee Identity.

Motion ≠ Object Detection.

Object Detection ≠ Action Recognition.

Inference ≠ Fact.

Cada conceito deve permanecer separado no código.

---

# 13. CONFIANÇA E INCERTEZA

O CAMPEX nunca deve transformar incerteza em certeza artificial.

O sistema deve ser capaz de representar:

OBSERVED
DERIVED
INFERRED
CONFIRMED
UNKNOWN

Quando não souber:

UNKNOWN

é uma resposta válida.

Nunca inventar continuidade de tracking, identidade ou evento.

---

# 14. FRONTEND

O frontend deve continuar renderizando mesmo quando serviços específicos falham.

Exemplos:

Backend offline
→ interface renderiza.

Camera offline
→ interface renderiza.

Vision ERROR
→ interface renderiza.

Um componente não pode derrubar toda a aplicação.

Sempre implementar:

- loading;
- empty state;
- error state;
- offline state;

quando aplicável.

---

# 15. UX

Não alterar identidade visual sem necessidade da tarefa.

Preserve:

- layout;
- linguagem visual;
- hierarquia;
- componentes;
- padrões existentes.

Nova funcionalidade deve parecer parte do mesmo produto.

Evite UI genérica criada apenas para expor backend.

---

# 16. CONFIGURAÇÃO

Nunca espalhar:

URLs
ports
thresholds
tokens
paths
FPS
timeouts
magic numbers

pelo código.

Centralizar configurações.

Usar `.env` quando apropriado.

Nunca commitar secrets.

Fornecer `.env.example` sem credenciais reais.

---

# 17. LOGGING

Logs devem ajudar diagnóstico.

Preferir eventos estruturados como:

CAMERA_CONNECTED
CAMERA_DISCONNECTED
VISION_STARTED
VISION_ERROR

Adicionar contexto:

camera_id
component
state
duration
error

quando relevante.

Não logar cada frame.

Não logar secrets.

Não logar dados sensíveis desnecessariamente.

---

# 18. ERROR HANDLING

Nunca usar:

except:
    pass

Erros devem:

1. ser tratados;
2. ser propagados quando necessário;
3. ser registrados adequadamente;
4. deixar o sistema em estado consistente.

Uma falha parcial não deve necessariamente derrubar todo o sistema.

---

# 19. TESTES

Código novo importante precisa de teste.

Priorizar:

UNIT
↓
INTEGRATION
↓
MANUAL / E2E

Teste comportamento, não implementação interna irrelevante.

Bugs corrigidos devem receber teste de regressão quando viável.

Não declarar feature pronta apenas porque compilou.

---

# 20. TESTE DE REGRESSÃO

Antes de concluir:

execute testes existentes.

Verifique funcionalidades anteriores relevantes.

Nova feature não pode quebrar Sprint anterior.

Sempre perguntar:

"O que já funcionava antes e pode ter sido afetado?"

---

# 21. TESTE REAL

Quando a feature envolve UI, câmera, stream, rede ou integração:

teste o fluxo real quando o ambiente permitir.

Exemplo:

não basta endpoint retornar 200.

Se a tarefa é Live View:

abra Live View.

Veja o vídeo.

Ative Vision.

Observe resultado.

Teste falha.

Teste recuperação.

---

# 22. DEFINIÇÃO DE PRONTO

Uma tarefa só está DONE quando:

[ ] código implementado
[ ] arquitetura respeitada
[ ] testes relevantes passando
[ ] regressões verificadas
[ ] erros tratados
[ ] logs adequados
[ ] frontend validado quando aplicável
[ ] documentação atualizada
[ ] código morto removido
[ ] nenhum workaround temporário escondido
[ ] limitações conhecidas documentadas

Compilar != pronto.

Endpoint 200 != pronto.

Tela abrir != pronto.

---

# 23. SEM "FAKE SUCCESS"

Nunca diga que algo foi testado se não foi.

Use claramente:

TESTADO
NÃO TESTADO
PARCIALMENTE TESTADO
BLOQUEADO

Se algo depende de:

- câmera física;
- GPU;
- credencial;
- serviço externo;
- hardware;

e não está disponível, documente.

Nunca simule sucesso no relatório.

---

# 24. NÃO ESCONDA PROBLEMAS

Não faça workaround apenas para fazer teste passar.

Se encontrar problema arquitetural:

1. identifique;
2. explique;
3. estime impacto;
4. corrija se estiver no escopo;
5. documente se não estiver.

Não aumentar escopo silenciosamente.

---

# 25. ALTERAÇÕES PEQUENAS

Prefira mudanças incrementais.

Depois de cada bloco importante:

IMPLEMENTAR
↓
EXECUTAR
↓
TESTAR
↓
VALIDAR
↓
CONTINUAR

Não modificar 40 arquivos e testar somente no final.

---

# 26. NÃO CRIE COMPLEXIDADE PREMATURA

Não implementar agora porque "pode ser útil no futuro".

Evitar:

- abstrações sem uso;
- tabelas vazias para features distantes;
- microservices prematuros;
- filas distribuídas sem necessidade;
- sistemas genéricos gigantes;
- patterns apenas por elegância.

Prepare pontos de extensão sem implementar o futuro inteiro.

---

# 27. COMPATIBILIDADE

Ao alterar contratos existentes:

verifique consumidores.

API
→ frontend
→ tests
→ workers
→ integrations

Não alterar response schema silenciosamente.

Quando necessário, migrar consumidores juntos.

---

# 28. SEGURANÇA

Nunca:

- expor secrets;
- confiar cegamente em input;
- executar conteúdo arbitrário;
- permitir paths inseguros;
- registrar credenciais;
- desabilitar segurança apenas para resolver bug.

Credenciais de câmera devem ser tratadas como secrets.

---

# 29. DOCUMENTAÇÃO

Documentação deve acompanhar arquitetura real.

Quando uma implementação mudar:

atualize documentação correspondente.

Não deixar docs descrevendo arquitetura que não existe mais.

Documentos em `/docs` são parte do projeto.

---

# 30. COMENTÁRIOS

Não comentar o óbvio.

Ruim:

# incrementa contador
counter += 1

Bom:

# Drop stale frames to preserve realtime latency.
latest_frame = frame

Comentários devem explicar:

POR QUÊ

e não simplesmente:

O QUÊ.

---

# 31. NOMENCLATURA

Nomes devem expressar responsabilidade.

Preferir:

VisionSessionManager
LatestFrameBuffer
CameraRegistry
MotionDetector

Evitar:

Manager2
UtilsNew
HelperFinal
TempService
test2
final_final

Não criar arquivos com nomes temporários em código de produção.

---

# 32. CÓDIGO MORTO

Depois de refactor:

remover:

- imports não usados;
- funções abandonadas;
- arquivos temporários;
- debug prints;
- código comentado;
- duplicações antigas.

Git mantém histórico.

Não precisamos preservar lixo dentro do código.

---

# 33. DEBUG

Não deixar:

print("teste")
console.log("aaaa")
TODO temporário sem contexto
mock habilitado em produção

Se um TODO permanecer, deve explicar:

- o que falta;
- por que falta;
- quando será necessário.

---

# 34. FORMATAÇÃO E QUALIDADE

Respeitar ferramentas já existentes no projeto.

Se houver:

formatter
linter
type checker
test runner

use-os.

Não introduzir ferramenta nova sem necessidade.

Código novo deve seguir estilo existente.

---

# 35. DECISÕES ARQUITETURAIS

Se surgir uma decisão relevante com impacto futuro:

documente.

Exemplo:

"Por que usamos latest-frame buffer?"

"Por que LocalTrack não é persistido frame a frame?"

"Por que Vision roda fora do event loop?"

Evitar decisões importantes existirem apenas na cabeça do agente.

---

# 36. QUANDO HOUVER DÚVIDA

Ordem de prioridade:

1. Segurança e integridade dos dados.
2. Requisitos explícitos da tarefa.
3. Este Engineering Standard.
4. Documentação arquitetural do CAMPEX.
5. Arquitetura existente.
6. Testes existentes.
7. Simplicidade.
8. Preferência pessoal do agente.

Não substituir arquitetura existente apenas porque o agente prefere outra abordagem.

---

# 37. PROTOCOLO DE EXECUÇÃO DO AGENTE

Toda tarefa significativa deve seguir:

DISCOVER
↓
UNDERSTAND
↓
PLAN
↓
IMPLEMENT
↓
TEST
↓
VERIFY
↓
DOCUMENT
↓
REPORT

### DISCOVER

Inspecionar arquivos e dependências.

### UNDERSTAND

Entender fluxo atual e impacto.

### PLAN

Definir alterações mínimas necessárias.

### IMPLEMENT

Executar incrementalmente.

### TEST

Executar testes automatizados relevantes.

### VERIFY

Validar comportamento real.

### DOCUMENT

Atualizar documentação necessária.

### REPORT

Explicar exatamente o que aconteceu.

---

# 38. RELATÓRIO FINAL OBRIGATÓRIO

Ao finalizar uma tarefa relevante, responder:

## IMPLEMENTADO

O que foi feito.

## ARQUIVOS ALTERADOS

Arquivos principais modificados/criados.

## DECISÕES TÉCNICAS

Decisões importantes e motivo.

## TESTES EXECUTADOS

Comandos/testes realmente executados.

## RESULTADOS

O que foi comprovado funcionando.

## NÃO TESTADO

O que não pôde ser validado.

## PROBLEMAS CONHECIDOS

Problemas ainda existentes.

## PRÓXIMO PASSO

Próxima ação lógica.

---

# 39. REGRA PARA MÚLTIPLOS AGENTES

Este repositório pode ser modificado por diferentes agentes de IA.

Portanto:

NÃO presuma que você foi o último agente.

Antes de editar:

- leia o estado atual;
- verifique alterações recentes;
- não dependa de memória de conversa;
- não reverta código que você não entende;
- não sobrescreva trabalho existente silenciosamente.

O estado atual do Git e dos arquivos é a fonte da verdade.

---

# 40. HANDOFF ENTRE AGENTES

Ao concluir trabalho significativo, mantenha:

docs/AGENT_HANDOFF.md

com um resumo curto:

CURRENT STATE
LAST COMPLETED TASK
IMPORTANT DECISIONS
KNOWN ISSUES
NEXT RECOMMENDED TASK

Atualize esse documento, não crie um novo handoff a cada execução.

Isso permite que Codex, Kilo Code e outros agentes continuem o mesmo trabalho sem depender do histórico do chat.

---

# 41. CAMPEX-SPECIFIC INVARIANTS

Estas regras não podem ser quebradas sem decisão arquitetural explícita:

Camera != Vision

Camera ONLINE + Vision ERROR é válido.

Detection != Tracking.

LocalTrack != GlobalEntity.

GlobalEntity != EmployeeIdentity.

Re-ID != reconhecimento nominal.

Motion != Detection.

Inference != Fact.

UNKNOWN é válido.

Video bruto != Event Store.

Detector != CAMPEX Brain.

Biblioteca externa != arquitetura do produto.

---

# 42. FILOSOFIA CAMPEX

Use inteligência onde inteligência é necessária.

Use software determinístico onde software determinístico resolve melhor.

Exemplo:

IA:
"isso é uma empilhadeira"

Software:
"ela entrou na zona às 14:03"

Software:
"ela saiu às 14:25"

Matemática:
"permaneceu 22 minutos"

Pattern Engine:
"isso está 43% acima do comportamento típico"

Não gastar IA para resolver operações determinísticas.

---

# 43. PRINCÍPIO FINAL

Não desenvolva apenas para a demonstração atual.

Também não desenvolva uma arquitetura gigantesca para um futuro hipotético.

Construa a menor solução que:

- funciona corretamente hoje;
- possui fronteiras limpas;
- pode evoluir amanhã;
- pode ser entendida pelo próximo engenheiro ou agente.

O objetivo não é gerar código.

O objetivo é construir CAMPEX.