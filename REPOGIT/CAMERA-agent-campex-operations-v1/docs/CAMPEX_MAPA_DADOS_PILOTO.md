    # Campex — Mapa Interno de Dados do Piloto

Este documento é de uso interno da Campex e registra quais informações podem ser tratadas durante um piloto, onde elas surgem e qual sua finalidade.

## 1. Fluxo geral

Câmera / NVR
→ Campex Edge
→ processamento operacional
→ Campex Cloud
→ usuário autorizado

A Campex não utiliza a Cloud como substituta do sistema de gravação contínua do cliente.

---

## 2. Mapa de dados

| Dado | Origem | Edge | Cloud | Finalidade |
|---|---|---|---|---|
| Fluxo de vídeo RTSP | Câmera/NVR | Sim | Não como gravação contínua | Análise operacional |
| Frames analisados | Câmera/NVR | Sim | Quando necessários à funcionalidade | Processamento visual |
| Latest frame / visualização | Edge | Sim | Sim, quando Live estiver ativo | Visualização da operação |
| Evidência visual de evento | Edge | Sim | Sim | Comprovar acontecimento |
| Estado da máquina (`ACTIVE / STOPPED / UNKNOWN`) | Edge | Sim | Sim | Monitoramento operacional |
| Eventos operacionais | Edge | Sim | Sim | Histórico e alertas |
| Horário e duração dos eventos | Edge | Sim | Sim | Métricas e análise |
| Presença/ausência em zona | Edge | Sim | Pode gerar contexto operacional | Contextualização |
| Configuração de zonas | Plataforma/Edge | Sim | Sim conforme sincronização | Configuração da análise |
| Dados da câmera | Cliente | Sim | Apenas informações necessárias ao gerenciamento | Configuração |
| Credencial RTSP/NVR | Cliente | Protegida localmente | Não deve ser exposta em texto claro | Conexão à câmera |
| Identidade do Edge | Campex | Sim | Sim | Autenticação Edge ↔ Cloud |
| Segredo do Edge | Campex | Sim | Cloud mantém mecanismo de verificação, não deve expor o segredo | Autenticação |
| Logs técnicos | Edge/Cloud | Sim | Conforme componente | Diagnóstico |
| Conta do usuário Campex | Usuário | — | Sim | Autenticação |
| Nome individual de funcionário por imagem | — | Não | Não | Fora do piloto |
| Biometria facial | — | Não | Não | Fora do piloto |
| Base de reconhecimento facial | — | Não | Não | Fora do piloto |

---

## 3. Retenção inicial do piloto

Política proposta:

- dados necessários à validação: durante o piloto;
- evidências visuais: durante o piloto;
- exclusão dos dados do piloto: em até 30 dias após encerramento, salvo acordo diferente;
- credenciais e acessos: devem ser revogados quando deixarem de ser necessários;
- não manter imagens indefinidamente sem finalidade operacional definida.

---

## 4. Princípio de minimização

Antes de coletar, transferir ou armazenar qualquer informação, a Campex deve avaliar:

1. Esse dado é necessário para gerar valor operacional?
2. Precisa sair do Edge?
3. Precisa ser armazenado?
4. Por quanto tempo?
5. Quem realmente precisa ter acesso?

Quando a resposta não justificar coleta ou armazenamento, o dado não deve ser mantido.

---

## 5. Itens que devem ser confirmados antes do piloto comercial definitivo

- prazo técnico real de retenção das evidências na Cloud;
- política de backup;
- comportamento dos dados após redeploy da Cloud;
- armazenamento persistente das evidências;
- permissões de acesso entre clientes/unidades;
- procedimento interno de exclusão de dados;
- procedimento de revogação das credenciais do Edge;
- confirmação de que segredos e credenciais não aparecem em logs ou interface.