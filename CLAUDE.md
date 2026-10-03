# Instruções

## Resposta no chat

Não narrar. Vale para toda resposta, não só para documento.

1. Resultado primeiro. A conclusão abre a resposta, não a fecha.
2. Sem relato de processo. Não escrever o que se foi fazer, o que se decidiu
   verificar, nem em que ordem. O que a verificação achou é conteúdo; a
   verificação não é.
3. Sem transição. Nada de "agora", "antes de opinar", "vou verificar",
   "duas coisas saem disso".
4. Título de seção é rótulo do conteúdo, não etapa de enredo. Vale a regra 28
   do `docs/DEVELOPMENT_AND_RESEARCH_GUIDE.md`.
5. Sem suspense. Não adiar o número para depois do raciocínio que levou a ele.
6. Primeira pessoa só quando o agente é o sujeito do achado: "medi X e deu Y"
   passa; "fui atrás de", "parei de", "estreitei cedo demais" não.
7. Concordância e discordância entram como fato, não como abertura. Cortar
   "você tem razão", "boa pergunta", "isso muda tudo".

As regras 23 a 29 do guia continuam valendo, e esta seção as estende do
documento para o chat.

## Escopo e edição

8. Achado de revisão vai para arquivo, não para o chat em série. O chat recebe
   o veredito.
9. Não commitar código sem revisão. Documento pode.
10. Antes de escrever elemento de forma em LaTeX, conferir
    `report/estilo-reporte.sty`.

## Trabalho

11. Rodar da raiz do repositório. Intermediário grande em `data/interim/`,
    sobrescrevível por `LUCERTAE_INTERIM`.
12. `data/`, `figures/`, `models/` e `logs/` estão fora do git.
13. O guia completo é `docs/DEVELOPMENT_AND_RESEARCH_GUIDE.md`, 53 regras.
    Ele vale para código, medição e escrita.
