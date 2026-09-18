# VISUAL OPERATIONS — PLANO DE EXECUÇÃO V2

## PROVA ATUAL

> Detectar uma parada real e dizer se havia operador presente ou ausente.

---

## P0 — HOJE

- [ ] Receber vídeo real.
- [ ] Guardar o arquivo original sem edição.
- [ ] Anotar manualmente início e fim das paradas.
- [ ] Anotar quando o operador estava presente ou ausente.
- [ ] Rodar `monitor_context.py`.
- [ ] Comparar sistema com verdade real.
- [ ] Registrar falsos positivos e falsos negativos.
- [ ] Ajustar somente um parâmetro por vez.

### Saída esperada

- `paradas_contextuais.csv`;
- `timeline.csv`;
- snapshots;
- registro de teste preenchido.

---

## P1 — PRÓXIMA ITERAÇÃO

- [ ] Melhorar detecção de pessoas.
- [ ] Testar HOG contra YOLO.
- [ ] Reduzir interferência de pessoas no detector da máquina.
- [ ] Salvar clipe antes/depois da parada.
- [ ] Adicionar versão do código nos eventos.
- [ ] Adicionar campo de causa confirmada pelo gestor.

---

## P2 — PROVA DE VALOR

- [ ] Gerar resumo diário simples.
- [ ] Entregar ao pai/gestor.
- [ ] Registrar se abriu.
- [ ] Registrar se tomou alguma ação.
- [ ] Perguntar quanto valeria receber isso continuamente.

---

## P3 — PILOTO EXTERNO

Gate obrigatório antes de executar:

- precisão aceitável;
- relatório usado;
- evento gera ação.

Depois:

- [ ] escolher uma indústria conhecida;
- [ ] uma câmera;
- [ ] uma máquina;
- [ ] um evento;
- [ ] proposta de piloto paga;
- [ ] registrar objeções e implantação.

---

## CONGELADO

- EPI;
- sala de vendas;
- AutoMapper;
- regras em linguagem natural;
- causa automática;
- impacto financeiro automático;
- dashboard completo;
- identidade visual.

---

## MÉTRICAS

### Técnicas

- paradas reais;
- paradas detectadas;
- precisão;
- falsos positivos;
- falsos negativos;
- erro no tempo;
- disponibilidade do vídeo;
- uso de CPU.

### Produto

- gestor abriu o relatório;
- entendeu sem explicação;
- corrigiu a causa;
- tomou ação;
- pediu novamente;
- aceitou pagar.

---

## GATES

### Gate 1 — técnica

Erro de tempo inferior a 10% e precisão contextual próxima ou superior a 85% após três iterações.

### Gate 2 — comportamento

O gestor usa a informação para investigar ou mudar algo.

### Gate 3 — pagamento

Uma empresa externa aceita pagar por um piloto.

Sem passar um gate, não avançar para funcionalidades futuras.