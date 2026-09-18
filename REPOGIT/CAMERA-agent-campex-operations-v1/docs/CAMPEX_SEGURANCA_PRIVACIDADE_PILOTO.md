# Campex — Segurança e Privacidade

## Piloto Operacional

A Campex transforma câmeras já existentes na operação em informações operacionais, permitindo identificar acontecimentos relevantes, registrar evidências e acompanhar o histórico da operação.

Este documento apresenta, de forma objetiva, como os dados são tratados durante o piloto da Campex e quais medidas são adotadas para reduzir riscos relacionados a acesso, armazenamento e uso das informações.

---

## 1. Como a Campex funciona

A arquitetura da Campex é dividida em duas partes principais:

### Campex Edge

O Campex Edge é instalado em um computador autorizado dentro da infraestrutura do cliente.

Ele é responsável por:

- conectar-se às câmeras ou ao NVR autorizado pelo cliente;
- receber os fluxos de vídeo necessários para o funcionamento da Campex;
- executar processamento local relacionado à análise operacional;
- comunicar à Campex Cloud os dados necessários para disponibilização das funcionalidades contratadas;
- manter a comunicação entre a operação física e a plataforma Campex.

O Edge funciona em segundo plano e não exige que o navegador permaneça aberto.

### Campex Cloud

A Campex Cloud é a plataforma acessada pelo cliente através do navegador.

Ela pode receber e disponibilizar, conforme as funcionalidades utilizadas no piloto:

- eventos operacionais;
- estados e métricas da operação;
- horários e duração de acontecimentos;
- informações técnicas sobre câmeras e Edge;
- evidências visuais associadas a acontecimentos relevantes;
- dados necessários para relatórios, histórico e análise operacional.

O objetivo da arquitetura é limitar o processamento e a transferência de informações ao que é necessário para o funcionamento da solução e para a geração de valor operacional ao cliente.
## 2. Dados tratados durante o piloto

Durante o piloto, a Campex poderá processar apenas os dados necessários para analisar a operação e disponibilizar os recursos da plataforma.

Entre eles:

- imagens e frames provenientes das câmeras autorizadas pelo cliente;
- estados operacionais identificados pela Campex, como atividade, parada ou condição desconhecida;
- horários, duração e frequência de acontecimentos;
- eventos operacionais identificados;
- evidências visuais associadas a eventos relevantes;
- informações sobre presença ou ausência de pessoas em áreas previamente configuradas, quando necessárias para contexto operacional;
- informações técnicas sobre conexão das câmeras, Edge e disponibilidade da operação;
- métricas, históricos e informações utilizadas na geração de relatórios operacionais.

A Campex busca limitar a coleta e o armazenamento ao que for necessário para o objetivo definido no piloto.

### O que não faz parte do piloto

Nesta etapa, a Campex não utiliza reconhecimento facial ou identificação biométrica de pessoas.

A solução não tem como objetivo identificar funcionários nominalmente a partir das imagens.

Portanto, no piloto:

- não é realizado reconhecimento facial;
- não é criada base biométrica facial de funcionários;
- não são associados rostos a nomes de colaboradores;
- não é utilizado reconhecimento de identidade individual para controle de produtividade;
- não são utilizados os vídeos para finalidades diferentes das previstas no escopo operacional acordado com o cliente.

Quando a presença de uma pessoa é relevante para uma análise operacional, a Campex trata essa informação como contexto da operação — por exemplo, presença ou ausência em uma determinada área — sem necessidade de identificar quem é aquela pessoa.
## 3. Credenciais, acesso e segurança

### Acesso às câmeras e ao NVR

Para conectar a Campex à infraestrutura de vídeo do cliente, pode ser necessário utilizar credenciais autorizadas de câmera ou NVR.

Sempre que possível, recomenda-se a criação de um usuário específico para a Campex, com permissões limitadas ao necessário para leitura e acesso aos fluxos de vídeo utilizados no piloto.

A Campex não solicita credenciais pessoais de e-mail ou contas que não sejam necessárias para o funcionamento da integração.

As credenciais utilizadas para conexão com câmeras e NVRs devem ser tratadas como informações sensíveis de infraestrutura e ter acesso restrito.

### Comunicação entre Edge e Cloud

A comunicação entre o Campex Edge e a Campex Cloud ocorre por conexão autenticada pela internet.

O Edge utiliza uma identidade própria para se autenticar com a Cloud e enviar informações relacionadas à operação.

A plataforma busca evitar que informações de uma unidade sejam misturadas com informações de outra unidade ou de outro cliente.

### Controle de acesso à plataforma

O acesso à Campex Cloud é realizado por autenticação de usuário.

O objetivo é permitir que apenas pessoas autorizadas tenham acesso às informações disponibilizadas na plataforma.

Durante o piloto, o acesso deve ser limitado às pessoas definidas entre o cliente e a Campex como necessárias para instalação, acompanhamento e validação da solução.

### Proteção das credenciais

Credenciais de acesso a câmeras e demais informações sensíveis não devem ser exibidas desnecessariamente na interface da plataforma ou compartilhadas por canais inseguros.

A Campex adota mecanismos técnicos para reduzir a exposição dessas informações durante o funcionamento da solução.

Nenhum sistema conectado à internet pode ser considerado livre de risco absoluto. Por isso, a Campex trabalha com medidas de prevenção, restrição de acesso e redução de exposição, em vez de prometer ausência total de incidentes de segurança.
## 4. Armazenamento, retenção e exclusão

A Campex busca armazenar somente as informações necessárias para o funcionamento da solução e para a validação dos resultados do piloto.

Dependendo da funcionalidade utilizada, determinadas informações podem permanecer armazenadas localmente no Campex Edge ou ser enviadas para a Campex Cloud.

Entre essas informações podem estar:

- eventos operacionais;
- métricas e históricos;
- configurações da unidade;
- informações técnicas do Edge e das câmeras;
- imagens ou frames utilizados como evidência de acontecimentos relevantes.

### Retenção durante o piloto

Durante o piloto, os dados necessários para acompanhamento, validação e análise poderão ser mantidos enquanto o piloto estiver ativo.

Como política inicial para o piloto, a Campex propõe que dados operacionais e evidências visuais sejam excluídos em até 30 dias após o encerramento do piloto, salvo quando:

- o cliente solicitar a exclusão antecipada;
- houver necessidade técnica ou jurídica devidamente justificada;
- cliente e Campex acordarem formalmente outro período de retenção.

A retenção definitiva utilizada em uma operação comercial poderá ser definida posteriormente de acordo com a necessidade operacional do cliente e com os requisitos aplicáveis de segurança e proteção de dados.

### Exclusão dos dados

Ao término do piloto, o cliente poderá solicitar a exclusão das informações associadas à operação que estiverem sob responsabilidade da Campex, observados eventuais registros cuja manutenção seja necessária por obrigação legal ou necessidade técnica justificada.

A Campex buscará evitar a manutenção indefinida de imagens e demais dados quando eles não forem mais necessários para a finalidade do piloto.

### Evidências visuais

A Campex não tem como objetivo utilizar a Cloud como sistema de gravação contínua ou substituto do NVR do cliente.

Quando imagens forem armazenadas pela Campex, a finalidade principal será registrar evidências relacionadas a acontecimentos operacionais relevantes, permitindo que o cliente compreenda o que ocorreu, quando ocorreu e em qual contexto.
## 5. LGPD e responsabilidades

A Campex reconhece que imagens captadas em ambientes de trabalho podem conter informações relacionadas a pessoas identificadas ou identificáveis e, portanto, devem ser tratadas com cuidado e de acordo com a legislação aplicável.

Durante o piloto, cada parte deverá atuar dentro das responsabilidades que lhe cabem em relação ao tratamento de dados pessoais.

### Responsabilidade do cliente

O cliente é responsável por definir a finalidade do uso das câmeras e da Campex em sua operação, bem como por garantir que o monitoramento existente e o uso das imagens estejam amparados pelos fundamentos jurídicos aplicáveis.

Cabe ao cliente, entre outros pontos:

- autorizar formalmente a utilização das câmeras e do NVR incluídos no piloto;
- definir quais áreas e operações poderão ser analisadas;
- determinar quais pessoas internas poderão acessar as informações disponibilizadas pela Campex;
- adotar, quando necessário, avisos, políticas internas ou outros procedimentos relacionados ao monitoramento de empregados e terceiros;
- comunicar à Campex restrições específicas relacionadas ao tratamento das informações da operação.

### Responsabilidade da Campex

Na medida em que tratar dados pessoais por conta e de acordo com as finalidades definidas pelo cliente, a Campex atuará no processamento dessas informações para viabilizar as funcionalidades contratadas no piloto.

Cabe à Campex:

- utilizar os dados apenas para as finalidades relacionadas ao funcionamento e à validação do piloto;
- restringir o acesso às informações às pessoas que necessitem delas para prestação, suporte ou validação do serviço;
- adotar medidas técnicas e organizacionais compatíveis com a natureza da solução e com os riscos envolvidos;
- evitar utilização das imagens para finalidades diferentes das acordadas com o cliente;
- comunicar ao cliente situações relevantes de segurança envolvendo informações sob responsabilidade da Campex;
- colaborar com o cliente, dentro de sua esfera de atuação, em solicitações relacionadas aos dados tratados pelo sistema.

### Funcionários e reconhecimento individual

A Campex não define, em nome do cliente, a base jurídica utilizada para o monitoramento dos empregados.

Essa definição deve ser realizada pelo próprio cliente de acordo com sua realidade, políticas internas e orientação jurídica aplicável.

No piloto atual, a Campex não utiliza reconhecimento facial, não cria cadastro biométrico e não identifica colaboradores nominalmente através das imagens.
## 6. Medidas de segurança e encerramento do piloto

A Campex adota medidas técnicas e operacionais voltadas à redução de riscos relacionados ao acesso indevido, perda, alteração ou exposição das informações tratadas durante o piloto.

Entre as medidas previstas estão:

- autenticação para acesso à plataforma;
- utilização de identidade própria para comunicação entre Edge e Cloud;
- restrição de acesso às informações conforme necessidade operacional;
- proteção das credenciais utilizadas nas integrações;
- separação lógica das informações entre unidades e clientes;
- utilização de conexões protegidas para comunicação pela internet;
- manutenção de registros técnicos necessários para diagnóstico e funcionamento da solução;
- redução da coleta e do armazenamento ao que for necessário para o objetivo do piloto.

### Incidentes de segurança

Caso a Campex identifique um incidente relevante envolvendo informações relacionadas ao piloto, deverá avaliar o ocorrido e comunicar o cliente quando o incidente puder afetar seus dados, sua operação ou suas responsabilidades relacionadas à proteção de dados.

A comunicação deverá apresentar, quando disponível:

- a natureza do incidente;
- as informações potencialmente afetadas;
- as medidas adotadas para contenção;
- as ações recomendadas ao cliente, quando aplicáveis.

### Limitações

A Campex adota medidas para reduzir riscos de segurança, mas nenhum sistema conectado a redes, computadores ou serviços de internet pode ser considerado totalmente imune a falhas, indisponibilidades ou incidentes.

O piloto possui caráter de validação operacional e poderá sofrer ajustes técnicos ao longo de sua execução.

Esses ajustes não autorizam a utilização dos dados para finalidades diferentes das acordadas com o cliente.

### Encerramento do piloto

Ao término do piloto, Campex e cliente deverão definir:

- encerramento ou continuidade da operação;
- manutenção ou remoção do Campex Edge;
- exclusão ou retenção dos dados gerados;
- revogação de acessos utilizados durante a implantação;
- eventual continuidade comercial da solução.

Caso o piloto seja encerrado, a Campex deverá desativar os acessos e integrações que não sejam mais necessários e aplicar a política de retenção e exclusão definida neste documento e no Termo de Piloto.

---

## Considerações finais

A Campex foi desenvolvida para transformar informações visuais da operação em dados operacionais úteis, mantendo segurança, controle de acesso e proteção de dados como requisitos da implantação.

Durante o piloto, qualquer necessidade específica de segurança, infraestrutura ou proteção de dados identificada pelo cliente deverá ser comunicada à Campex para avaliação antes de sua implementação.