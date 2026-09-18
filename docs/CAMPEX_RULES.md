# CAMPEX — Engineering Rules

Estas regras são obrigatórias para qualquer agente que trabalhe neste repositório.

## 1. ESCOPO

- Trabalhe somente no escopo solicitado.
- Não implemente funcionalidades de Sprints futuras.
- Não transforme uma tarefa pequena em uma refatoração geral.
- Não altere componentes funcionais sem necessidade comprovada.
- Se encontrar uma melhoria fora do escopo, registre-a como sugestão; não a implemente automaticamente.

## 2. CÓDIGO EXISTENTE

Antes de modificar qualquer componente:

1. Localize a implementação atual.
2. Entenda suas dependências.
3. Verifique onde ela é utilizada.
4. Faça a menor alteração capaz de resolver a tarefa.

Nunca presuma que um componente não existe antes de procurar no projeto.

## 3. ARQUITETURA

Preserve a separação conceitual:

Camera
→ Capture
→ Frame Pipeline
→ Vision
→ Detection
→ Tracking
→ Zones
→ Events
→ Analytics
→ Intelligence

Evite dependências desnecessárias entre essas camadas.

Frontend não deve conter lógica central de visão computacional.

Vision Core não deve depender da interface para funcionar.

Uma câmera com erro não deve derrubar outras câmeras.

## 4. VISÃO COMPUTACIONAL

- Capture, Detection, Tracking e Events devem permanecer desacoplados sempre que razoável.
- Detecções devem possuir representação estruturada.
- Tracking deve manter contexto independente por câmera.
- Overlays e bounding boxes visuais não devem destruir ou substituir o frame original.
- Não carregue modelos repetidamente sem necessidade.
- Considere CPU, GPU, RAM, FPS e latência.
- Não processe frames que não precisam ser processados.

## 5. PERFORMANCE

CAMPEX é um sistema de processamento contínuo.

Portanto:

- evite loops bloqueantes desnecessários;
- evite cópias desnecessárias de frames;
- evite crescimento ilimitado de filas;
- evite vazamentos de memória;
- não acumule frames antigos quando o processamento estiver atrasado;
- considere backpressure/frame dropping quando necessário;
- não carregue modelos pesados múltiplas vezes sem necessidade.

O sistema deve ser projetado pensando progressivamente em múltiplas câmeras.

## 6. RTSP E CÂMERAS

Sempre considere:

- câmera offline;
- timeout;
- stream interrompido;
- frame inválido;
- reconexão;
- encerramento correto de recursos.

Credenciais RTSP nunca devem aparecer em logs.

Falha individual de câmera deve permanecer isolada.

## 7. SEGURANÇA

Nunca:

- coloque secrets diretamente no código;
- registre passwords, tokens ou URLs RTSP completas com credenciais;
- exponha streams privados sem controle;
- desabilite validações apenas para facilitar desenvolvimento.

Use variáveis de ambiente para dados sensíveis.

## 8. TESTES

Toda alteração relevante deve possuir validação.

Antes de concluir:

1. Execute os testes relacionados.
2. Execute regressão quando aplicável.
3. Corrija falhas provocadas pela implementação.
4. Execute novamente.

Nunca:

- remova um teste válido para fazer a suíte passar;
- altere expectativas corretas para esconder um bug;
- declare sucesso sem executar os testes disponíveis;
- substitua integração real por mock e declare a integração real funcionando.

## 9. DEPENDÊNCIAS

Antes de adicionar uma biblioteca:

- verifique se a necessidade já pode ser atendida pelas dependências existentes;
- considere impacto no tamanho, instalação e performance;
- justifique dependências grandes.

Não troque frameworks ou bibliotecas centrais sem necessidade explícita.

## 10. BANCO DE DADOS

- Preserve dados existentes.
- Mudanças de schema devem ser controladas.
- Não apague tabelas/dados automaticamente.
- Evite alterações incompatíveis sem migração.
- Nunca use dados fictícios para mascarar ausência de dados reais.

## 11. IA

Princípio CAMPEX:

> Use inteligência para compreender; use software para repetir.

Não utilize LLM onde regras determinísticas resolvem o problema.

Fluxo preferencial:

Video
→ Detection
→ Tracking
→ Events
→ Metrics
→ Intelligence

Evite enviar vídeo continuamente para modelos multimodais/LLMs.

## 12. PRIVACIDADE

Vídeo empresarial deve ser tratado como dado sensível.

- Minimize armazenamento desnecessário.
- Não implemente reconhecimento facial por padrão.
- Não introduza identificação biométrica sem solicitação explícita e revisão específica.
- Prefira processamento local quando tecnicamente adequado.

## 13. CONTEXTO E TOKENS

Não leia o repositório inteiro por padrão.

Use:

1. busca;
2. indexação;
3. arquivos diretamente relacionados;
4. dependências desses arquivos;
5. somente depois expanda a investigação.

Não releia arquivos sem necessidade.

Evite respostas intermediárias extensas.

## 14. GIT

- Não faça alterações destrutivas.
- Não sobrescreva trabalho existente do usuário.
- Não descarte alterações não relacionadas.
- Não faça commit/push sem solicitação ou regra explícita do workflow.
- Mantenha alterações focadas na tarefa atual.

## 15. DEFINITION OF DONE

Uma tarefa NÃO está concluída apenas porque o código foi escrito.

Só considere concluída quando:

- implementação solicitada existe;
- código relevante executa;
- testes relevantes passaram;
- regressões importantes foram verificadas;
- resultado foi comparado ao objetivo inicial.

Ao finalizar, reporte brevemente:

### IMPLEMENTADO
Principais mudanças.

### TESTES
Comandos executados e resultados reais.

### ARQUIVOS
Principais arquivos modificados.

### PENDÊNCIAS
Somente problemas reais ainda existentes.