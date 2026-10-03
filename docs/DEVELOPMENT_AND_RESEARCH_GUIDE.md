# Guia de desenvolvimento e pesquisa

Regras. Imperativas, verificáveis, sem exemplo.

---

## Medição

1. Todo script que produz número carrega controle interno que pode falhar.
2. O controle é falsificável e independente do resultado pretendido. Igualdade
   que vale por construção não é controle.
3. Declarar o que o controle não testa.
4. O controle roda antes de gravar. Usar `raise`, não `assert`.
5. Ao reportar número, declarar qual controle passou. Não havendo controle,
   declarar a ausência.
6. Rodar, verificar, reportar. Nessa ordem.

## Amostra e descarte

7. Contabilizar todo descarte e reportá-lo com o motivo e a contagem.
8. Sobre distribuição contínua, corrigir antes de excluir. Excluir só o que a
   correção não resolve.
9. A janela do controle de qualidade é a janela da análise.
10. Aplicar piso e teto físicos ao dado medido.
11. Estimativa que encosta no extremo da grade de busca é censura, não
    estimativa. Reportar como tal.

## Estatística

12. A métrica que seleciona é a métrica que reporta.
13. Reportar dispersão e `n` junto de qualquer medida de posição.
14. Toda comparação corre sobre a mesma amostra. Base diferente entre termos
    invalida a razão entre eles.
15. Declarar sensibilidade a escolha de modelo quando o resultado depender dela.

## Dado externo

16. Verificar o cabeçalho do arquivo em cache, não a existência dele.
17. Requisição a API declara explicitamente fuso, unidade e janela.
18. Não casar registros por nome ou título sem conferir contra um segundo campo.
19. Antes de classificar tarefa como bloqueada, baixar um recurso e abrir.
20. Distinguir três estados: em disco, disponível com tamanho medido,
    indisponível com motivo. Reconciliação e engenharia são disponível.

## Custo

21. Cronometrar antes de afirmar custo.
22. Verificar suporte de hardware antes de propor aceleração.

## Escrita

23. Cada palavra acrescenta informação, precisão, estrutura lógica ou
    referência. As demais saem.
24. Sem metáfora, antropomorfismo ou intensificador sem medida.
25. Sem metadiscurso.
26. Termo avaliativo é substituído pelo número ou removido.
27. A força da afirmação corresponde ao desenho do estudo. `indicam` para
    inferência, `demonstram` para estabelecimento direto.
28. Título de seção é rótulo do conteúdo: objetivo, dados, método, resultados,
    limitações, artefatos.
29. Preservar terminologia técnica. Não variar termo por estilo.

## Documentação de código

30. Docstring descreve o que o código faz e o que o dado exige. Histórico de
    alteração fica no controle de versão.
31. Documentar propriedade do dado que, ignorada, leva à simplificação
    incorreta.
32. Cabeçalho desatualizado é defeito. Ao mudar a saída, mudar o cabeçalho.

## Consistência

33. Número que aparece em mais de um lugar tem uma fonte.
34. Termo não trivial é apresentado na primeira menção de cada documento.
35. Antes de escrever elemento de forma, verificar se já existe na folha de
    estilo.
36. Duas versões do mesmo documento não coexistem. Eleger uma.
37. Diante de inconsistência ampla, levantar o inventário completo antes de
    editar, e editar de uma vez.

## Caminhos

38. Intermediário grande vai para `data/interim/`, sobrescrevível por
    `TERRA_PW_INTERIM`. Nunca para diretório temporário de sessão.
39. Sem caminho absoluto de máquina em arquivo versionado.
40. Script roda da raiz do repositório e cria o diretório de saída antes de
    gravar.
41. Declarar dependência externa: serviço, banco, biblioteca fora da árvore.

## Versionamento

42. Código não é commitado sem revisão.
43. Commit atômico: uma mudança coerente por commit, na ordem de dependência.
44. Mensagem de commit em en-US. Corpo explica o porquê e registra o que foi
    rejeitado.
45. Sem linha `Co-Authored-By`, exceto quando pedida para o commit em questão.

## Idioma

46. Trabalhar em pt-BR. Passar para en-US após auditoria e revisão por pares.
47. A tradução cobre comentário, docstring, mensagem de saída e nome de
    variável local.
48. Identificador que espelha coluna de fonte externa permanece como está.
49. Rótulo gravado em arquivo de dados é interface. Muda com a cadeia inteira,
    não com um arquivo.

## Encerramento

50. Evidência suficiente encerra a questão. Ausência de perfeição não é
    pendência.
51. Distinguir validação pendente de objeto de comparação inexistente. O
    segundo é limite declarado da afirmação.
52. Teste que refatia o mesmo dado com outra estatística não acrescenta.
53. Ajustar a redação ao que a evidência sustenta.

## Procedência

Regra sem fonte é regra local. Estas três têm âncora externa revisada por pares.

Sonare, A.P., Ochawar, R.S., Balamwar, S. e Kulkarni, M.B. *Green energy
estimation using remote sensing techniques: a comprehensive review of methods,
applications, and future directions*. Energy Reports, 15, 109354, 2026.
doi 10.1016/j.egyr.2026.109354. Revisão sistemática sob protocolo PRISMA 2020,
55 estudos incluídos de 312 identificados.

A seção 3.7 gradua conclusão em alta confiança, moderada ou indicativa por seis
critérios, e recusa ranking definitivo:

  (i)   validação de campo robusta
  (ii)  avaliação espacialmente independente, e não treino e teste em
        localidades altamente sobrepostas
  (iii) rigor temporal: separação treino-teste explícita, holdout sazonal ou
        validação orientada a previsão
  (iv)  reporte de incerteza: limites de erro, análise de sensibilidade ou
        discussão de limitação do modelo
  (v)   representatividade geográfica
  (vi)  transparência de fluxo: fonte, pré-processamento e configuração

Correspondência:

  regra 2   critérios (i) e (ii)
  regra 3   critério (iv), pela parte de limitação declarada
  regra 15  critério (iv), pela parte de análise de sensibilidade, e (vi)

A revisão cobre estimativa de recurso: irradiância, velocidade de vento, vazão e
biomassa. Não cobre inventário de ativo, desempenho de planta, uso do solo nem
acesso à energia. Não substitui referência por família de tarefa.

LACUNA DECLARADA. Os critérios (ii) e (iii) não têm regra correspondente neste
guia. Nenhuma regra da seção Estatística exige que o conjunto retido seja
independente em espaço ou em tempo do conjunto de ajuste. Retido na amostra não
é retido no espaço nem no tempo.
