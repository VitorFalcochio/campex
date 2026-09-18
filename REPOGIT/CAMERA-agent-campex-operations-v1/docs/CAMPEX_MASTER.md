# Campex — Documento Mestre

Última atualização: 31/07/2026

## 1. Visão

A Campex transforma câmeras já instaladas em inteligência para operações físicas, identificando eventos relevantes e gerando evidências, histórico e informações úteis para a gestão.

A ambição é construir uma empresa séria, capaz de gerar resultados mensuráveis para grandes operações industriais e logísticas.

## 2. Objetivo dos próximos 12 meses

- Validar o produto em ambiente industrial real.
- Conquistar os primeiros clientes pagantes.
- Produzir pelo menos dois cases com resultados mensuráveis.
- Dominar inicialmente um ou dois casos de uso.
- Construir um processo repetível de implantação.
- Começar a entrar em empresas grandes.

## 3. Estado real do produto

Classificação atual:

MVP tecnicamente testável.

Elementos que parecem existir no repositório:

- backend FastAPI;
- processamento local/Edge;
- conexão com fontes de vídeo e RTSP;
- modelo de visão computacional;
- zonas e regras;
- geração de eventos;
- evidências;
- banco de dados;
- dashboard;
- testes automatizados.

Ainda precisa ser comprovado de ponta a ponta, sem mocks:

- vídeo real sendo processado;
- evento automático;
- evidência real originada do vídeo;
- duração correta;
- persistência após reiniciar;
- exibição no dashboard;
- estabilidade durante execução contínua;
- conexão com câmera industrial real.

Não declarar o produto como validado industrialmente antes desses testes.

## 4. Próximos marcos

1. Aprovar o Teste 001 Local.
2. Corrigir apenas os bloqueios encontrados.
3. Executar o Teste 001 Industrial na fábrica.
4. Definir o primeiro piloto externo.
5. Conquistar o primeiro cliente.

## 5. Produto inicial

O primeiro piloto deve possuir:

- uma câmera;
- uma área operacional;
- uma ou duas regras;
- eventos automáticos;
- evidência visual;
- horário e duração;
- histórico no painel;
- relatório simples.

Não tentar monitorar toda a fábrica no primeiro piloto.

## 6. Casos de uso iniciais

Priorizar situações visualmente verificáveis:

- entrada em zona;
- saída de zona;
- permanência acima do limite;
- ausência em uma área;
- ocupação de doca;
- veículo parado;
- corredor obstruído;
- circulação em área restrita.

“Máquina parada” deve continuar como hipótese técnica até ser validada de forma confiável.

## 7. Contas comerciais prioritárias

Curto prazo:

- Grupo DBK;
- Cânovas Bebedouros;
- AGR Log;
- Sigramar;
- Plásticos Mirassol.

Conta estratégica de ciclo longo:

- Facchini.

## 8. Decisões atuais

- A Campex será operada como empresa séria, não como experimento de ideias.
- Produto, cliente e resultado têm prioridade sobre branding.
- Não tentar atender todos os setores e casos de uso agora.
- Uma hipótese não será comunicada como funcionalidade validada.
- O primeiro produto precisa funcionar com uma câmera e uma regra.
- Landing page não é prioridade enquanto houver bloqueios técnicos ou comerciais.
- WhatsApp, novas integrações e funcionalidades extras não fazem parte do caminho crítico.
- A organização deve ser simples e usada diariamente.

## 9. O que não fazer agora

- Redesenhar a landing page.
- Criar dezenas de funcionalidades.
- Expandir para muitos setores.
- Criar uma arquitetura corporativa complexa.
- Montar outro repositório para gestão.
- Apresentar números ou resultados ainda não comprovados.

## 10. Regra operacional

Nenhum dia deve terminar sem pelo menos um avanço concreto em uma destas frentes:

- produto;
- validação;
- cliente;
- comercial;
- implantação.
