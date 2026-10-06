# Shell genérico para Sistemas Baseados em Conhecimento (SBC)

Ferramenta em Python, **independente de domínio**, que implementa a arquitetura conceitual de um agente baseado em conhecimento (disciplina de Inteligência Artificial, 2026.2 – Lista 1, Questão 5).

O programa não contém nenhum conhecimento específico: ele fornece a infraestrutura (base de conhecimento, editor, motor de inferência, explicação e interface). Uma aplicação concreta surge quando se carrega uma base de conhecimento em JSON. O repositório traz três bases de exemplo (classificação de animais, diagnóstico de impressora e risco de crédito), que rodam na mesma ferramenta sem alterar uma linha de código.

## Arquitetura

```
                    USUARIO
                       |
                       v
        +------------------------------+
        |  INTERFACE (dialogo em       |
        |  linguagem natural, PT-BR)   |
        +--------------+---------------+
                       |
        +--------------+---------------+
        v                              v
+---------------------+      +---------------------+
| ENGENHO DE INFERENCIA|<---->|     EXPLICACAO      |
| * encadeamento p/    |      | * POR QUE?          |
|   frente             |      | * COMO?             |
| * encadeamento p/    |      | * trilha (rastro)   |
|   tras               |      +---------------------+
| * encadeamento misto |
+----------+-----------+
           |
           v
+------------------------------+
|     BASE DE CONHECIMENTO     |
|  FATOS  |  REGRAS SE...ENTAO |
+--------------+---------------+
               ^
+--------------+---------------+
|  EDITOR DA BASE              |
|  criar / editar / excluir    |
+------------------------------+
```

| Módulo | Onde está no código |
|---|---|
| Base de conhecimento | classes `BaseConhecimento`, `Regra`, `Cond` |
| Editor | `Shell.editor()` (menu) e comandos `adicionar/editar/excluir` |
| Engenho de inferência | classe `Engine` (`encadeia_frente`, `buscar`/`prova_regra`, `misto`) |
| Explicação | `Engine.explica_por_que`, `Engine.explica_como`, `Engine.rastro` |
| Interface | `Shell.interpretar()` (linguagem natural) e `Shell.repl()` |

## Requisitos e execução

- Python 3.8 ou superior. **Nenhuma biblioteca externa.**

```bash
python shell_sbc.py                        # inicia sem base (use "carregar" ou "editor")
python shell_sbc.py bases/animais.json     # inicia com uma base
python shell_sbc.py bases/credito.json --modo tras
```

## Representação do conhecimento

**Fatos** têm a forma `atributo = valor` (ex: `cor = pardo amarelado`). Um atributo sem operador (`febre`) equivale a `febre = sim`.

**Regras** têm a forma:

```
SE cond1 E cond2 E ... ENTAO atributo = valor
```

- Operadores nas condições: `=`, `!=`, `<`, `>`, `<=`, `>=` (comparação numérica automática quando os dois lados são números; decimais com vírgula ou ponto).
- O conectivo `E` deve estar em **maiúsculas**, o que permite valores como `preto e branco`.
- A conclusão usa sempre `=`.
- Comparações de texto ignoram maiúsculas e acentos.
- Cada atributo tem um único valor por consulta. Quando duas regras concluiriam valores diferentes, vale a que disparou primeiro (o conflito aparece no `rastro`).

### Formato do arquivo JSON

```json
{
  "nome": "Diagnostico de impressora",
  "descricao": "Texto livre exibido ao carregar.",
  "objetivos": ["falha", "acao"],
  "perguntas": {
    "liga": { "texto": "A impressora liga?", "opcoes": ["sim", "nao"] },
    "nivel tinta": { "texto": "Qual o nivel de tinta (0 a 100 %)?" }
  },
  "fatos": ["cabo energia = conectado"],
  "regras": [
    { "id": "R1", "regra": "SE liga = nao E cabo energia = desconectado ENTAO falha = cabo desconectado", "descricao": "" }
  ]
}
```

- `objetivos`: atributos que a consulta deve descobrir. Se omitido, são usados os atributos derivados que nenhuma outra regra consome.
- `perguntas`: texto e opções de resposta de cada atributo que pode ser perguntado ao usuário. Sem entrada, o shell pergunta "Qual o valor de '...'?".
- Atributos que **nenhuma regra conclui** são dados de entrada e podem ser perguntados ao usuário.

## Motor de inferência

| Modo | Estratégia | Quando usar |
|---|---|---|
| `frente` | Dirigido por dados. O usuário informa o que sabe e o motor dispara regras até o ponto fixo. O conflito é resolvido por **maior especificidade** (mais condições) e, em seguida, pela ordem na base. | Já se tem todos os dados. |
| `tras` | Dirigido por objetivos. Para provar `objetivo`, busca regras que o concluem e prova suas condições recursivamente; só pergunta o que for necessário, quando nenhuma regra conclui o atributo. Detecta ciclos. | Poucos dados; evitar perguntas inúteis. |
| `misto` | (1) propagação para frente com os fatos conhecidos; (2) encadeamento para trás para os objetivos ainda abertos; **a cada resposta do usuário, nova propagação para frente**. | Padrão. Combina eficiência e economia de perguntas. |

Se o usuário responde `?` (ou Enter), o atributo fica marcado como **desconhecido**: não é perguntado de novo e as condições que dependem dele falham.

## Explicação

- **POR QUÊ?** Ao ser perguntado algo, responda `porque`. O shell mostra a regra e a cadeia de regras/objetivos que motivam a pergunta. Depois da consulta, `por que <atributo>` lista as regras que usam aquele atributo.
- **COMO?** `como <atributo>` mostra a árvore de justificativa: regra aplicada, condições usadas e origem de cada fato (fato inicial, informado ou derivado).
- **Rastro.** `rastro` mostra a trilha completa da inferência (regras tentadas, disparadas e falhas). `detalhar on` exibe a trilha em tempo real.

## Interface em linguagem natural

Além dos comandos, o shell entende frases em português:

| Você escreve | O shell faz |
|---|---|
| `consultar`, `diagnosticar`, `classificar`, `avaliar`, `recomendar` | inicia a consulta (aceita `frente`, `tras` ou `misto` na frase) |
| `qual é a falha?`, `quem é o animal?` | objetivo específico (encadeamento para trás) |
| `a renda é acima de 35k`, `liga = sim` | registra um fato (no modo misto já propaga) |
| `como animal`, `como chegou ao risco?` | justificativa (COMO) |
| `por que renda` | por que esse dado é necessário (POR QUÊ) |
| `adicionar regra SE ... ENTAO ...` | cria regra |
| `editar regra R3 SE ... ENTAO ...` | substitui regra |
| `excluir regra R3`, `excluir fato febre` | remove |
| `regras`, `fatos`, `rastro`, `validar`, `reiniciar` | listagens e utilitários |

O interpretador é baseado em padrões (expressões regulares) e casamento aproximado de nomes de atributos (`difflib`), não em um modelo de linguagem. As mensagens do programa não usam acentos para evitar problemas de codificação em terminais Windows.

## Editor da base

`editor` abre um menu para listar/criar/editar/excluir regras, criar/excluir fatos iniciais, definir perguntas e objetivos, validar e salvar. O comando `validar` detecta objetivos sem regra e **dependências circulares**. Qualquer alteração reinicia a memória de trabalho.

## Exemplo de sessão (encadeamento para trás)

```
sbc> carregar animais
sbc> consultar tras
Qual a cobertura do corpo? [pelo/penas/escamas/nenhuma] > porque
   Pergunto 'cobertura' porque preciso avaliar a condicao (cobertura = pelo) da regra R1:
      R1: SE cobertura = pelo ENTAO classe = mamifero
   Se R1 for confirmada, concluo (classe = mamifero), necessario para a condicao (classe = mamifero) de R5.
   Se R5 for confirmada, concluo (ordem = carnivoro), necessario para a condicao (ordem = carnivoro) de R7.
   Objetivo em andamento: descobrir 'animal'.
Qual a cobertura do corpo? > pelo
...
--- Resultado ---
  animal = guepardo
sbc> como animal
   * animal = guepardo   [derivado pela regra R7]
     SE ordem = carnivoro E cor = pardo amarelado E padrao = manchas escuras ENTAO animal = guepardo
      * ordem = carnivoro   [derivado pela regra R5]
      ...
```

## Criando sua própria base

1. Copie `bases/impressora.json` como modelo (ou use `editor` e `salvar`).
2. Liste os atributos de entrada e escreva as regras que levam às conclusões.
3. Defina `perguntas` para os atributos de entrada e `objetivos`.
4. Rode `validar` e teste nos três modos.

## Estrutura do repositório

```
.
├── shell_sbc.py        # a ferramenta (arquivo único)
├── bases/
│   ├── animais.json    # classificação de animais
│   ├── impressora.json # diagnóstico / suporte técnico
│   └── credito.json    # risco de crédito (derivada dos 14 exemplos da Questão 1)
└── README.md
```

## Limitações

- Regras só têm conjunção (`E`). A disjunção se expressa com várias regras de mesma conclusão.
- Sem fatores de certeza ou lógica difusa; os valores são categóricos ou numéricos exatos.
- Um valor por atributo por consulta (sem atributos multivalorados).
- A linguagem natural é baseada em padrões e cobre um conjunto controlado de frases.

## Autores

Pedro Neves (202413121) – disciplina de Inteligência Artificial (Prof. Evandro Costa), 2026.2.
