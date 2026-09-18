# Campex — Estado Real do Produto

Última atualização: 08/09/2026

Este documento registra o estado real da Campex.
A regra é simples:

- ✅ = comprovado
- 🟡 = existe, mas ainda precisa validação final
- 🔴 = bloqueador ou não comprovado
- ❌ = não existe / fora do piloto

| Componente | Existe | Testado no código | Testado real | Quinta-feira | Próxima prova |
|---|---|---|---|---|---|
| Login Cloud | ✅ | ✅ | ✅ | ✅ | smoke final |
| Cadastro de usuário | ✅ | ✅ | ✅ | ✅ | confirmar configuração final |
| Cloud hospedada | ✅ | ✅ | ✅ | 🟡 | estabilidade + plano Render |
| Banco Cloud | ✅ | ✅ | ✅ | 🟡 | confirmar persistência |
| Edge Windows | ✅ | ✅ | ✅ | 🟡 | instalação limpa final |
| Edge independente do navegador | ✅ | ✅ | ✅ | ✅ | nenhuma |
| Inicialização automática do Edge | ✅ | ✅ | ✅ | 🟡 | novo reboot controlado |
| Recuperação após queda do processo | ✅ | ✅ | 🟡 | 🟡 | teste controlado |
| Atualização remota do Edge | ❌ | ❌ | ❌ | 🟡 gap conhecido | definir estratégia do piloto |
| RTSP / câmera real | ✅ | ✅ | ✅ | ✅ | testar câmera do cliente |
| Live pela Cloud | ✅ | ✅ | ✅ | ✅ | validar no cliente |
| Cadastro/configuração de câmera | ✅ | ✅ | ✅ | ✅ | validar credencial do cliente |
| Zonas operacionais | ✅ | ✅ | ✅ | ✅ | configurar máquina escolhida |
| Calibração visual | ✅ | ✅ | ✅ | 🟡 | calibrar máquina real |
| Estado ACTIVE | ✅ | ✅ | 🟡 | 🔴 | provar em máquina adequada |
| Estado STOPPED | ✅ | ✅ | 🟡 | 🔴 | provar parada real |
| Estado UNKNOWN | ✅ | ✅ | 🟡 | 🟡 | validar comportamento |
| ACTIVE → STOPPED → ACTIVE | ✅ | ✅ | ❌ definitivo | 🔴 | principal teste do piloto |
| Evento de parada | ✅ | ✅ | 🟡 | 🟡 | gerar a partir de evento físico |
| Evidência visual | ✅ | ✅ | 🟡 | 🟡 | validar evidência real |
| Histórico operacional | ✅ | ✅ | 🟡 | 🟡 | validar após evento real |
| Inteligência operacional | ✅ | ✅ | 🟡 | 🟡 | validar com dados reais |
| Relatório operacional | ✅ | ✅ | 🟡 | 🟡 | validar cobertura suficiente |
| Presença de operador | ✅ | ✅ | ✅ | contexto | não gerar alerta crítico isolado |
| Reconhecimento facial | ❌ | — | — | ❌ fora | não oferecer |
| Identificação nominal de funcionário | ❌ | — | — | ❌ fora | não oferecer |
| Contagem de produção | hipótese | — | ❌ | ❌ fora inicial | avaliar máquina primeiro |
| Duas máquinas por câmera | possível por zonas | 🟡 | ❌ | ❌ não prometer | validar depois |
| Integração ERP/MES/WMS | ❌ | — | — | ❌ fora | futuro |

## Regra do piloto

O piloto inicial da Campex será considerado tecnicamente comprovado quando houver:

Câmera real
→ Edge
→ processamento
→ ACTIVE
→ STOPPED
→ ACTIVE
→ evento
→ evidência
→ histórico na Cloud

Até essa sequência acontecer de ponta a ponta em uma máquina real, a detecção de parada deve ser tratada como funcionalidade em validação.

## Prioridades até o piloto de quinta-feira

### P0 — precisa estar resolvido/provado

1. Máquina real:
   - provar `ACTIVE → STOPPED → ACTIVE`.

2. Edge Windows:
   - instalar;
   - ficar Online;
   - fechar navegador;
   - reiniciar Windows;
   - voltar Online sozinho.

3. Fluxo ponta a ponta:
   - câmera → Edge → estado → evento → evidência → Cloud.

4. Cloud:
   - sem sleep durante o piloto;
   - banco persistente;
   - confirmar comportamento das evidências;
   - definir plano final do Render.

5. Versão do piloto:
   - revisar alterações;
   - rodar testes;
   - fazer smoke test;
   - congelar uma versão antes da implantação.

### P1 — importante durante os 30 dias

- atualização remota controlada do Edge;
- proteção final de identidade do Edge;
- recuperação automática mais robusta;
- melhorias de calibração;
- ajustes encontrados no cliente.

### Fora do piloto inicial

- reconhecimento facial;
- identificação nominal;
- contagem de produção sem validação visual;
- múltiplas máquinas por câmera sem teste;
- integrações ERP/MES/WMS.

## Plano B do piloto

### Se a máquina escolhida não tiver sinal visual claro
- testar outra área da mesma máquina;
- testar outra máquina;
- não forçar uma detecção sem evidência visual suficiente.

### Se a câmera não conectar
- conferir IP, usuário, senha, porta e canal;
- testar outra câmera autorizada;
- registrar o problema e não alterar a infraestrutura do cliente sem autorização.

### Se o Edge não instalar
- identificar a etapa exata da falha;
- tentar novamente somente após entender o erro;
- não improvisar alterações no Windows do cliente.

### Se a internet cair
- verificar funcionamento local do Edge;
- aguardar reconexão;
- usar hotspot apenas para diagnóstico, se necessário.

### Se ACTIVE / STOPPED não funcionar
- confirmar primeiro se existe diferença visual real;
- ajustar zona e calibração;
- testar uma transição controlada;
- se continuar inconsistente, registrar como não comprovado e continuar a calibração durante o piloto.

### Regra
Não esconder falhas do cliente e não inventar resultado.
O objetivo do piloto é descobrir o que funciona, o que precisa ser ajustado e se a Campex gera valor real.