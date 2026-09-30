#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shell generico para Sistemas Baseados em Conhecimento (SBC).

Modulos (arquitetura conceitual de um agente baseado em conhecimento):
  1. BaseConhecimento : fatos + regras SE ... ENTAO ... (persistidas em JSON)
  2. Editor           : criar / editar / excluir regras e fatos
  3. Engine           : motor de inferencia (frente, tras e misto)
  4. Explicacao       : POR QUE? / COMO? / trilha de inferencia (rastro)
  5. Shell (interface): dialogo em linguagem natural (portugues) via terminal

Nenhum conhecimento de dominio esta no codigo: ele vem das bases em JSON.
Uso:  python shell_sbc.py [base.json] [--modo frente|tras|misto]
Somente biblioteca padrao (Python 3.8+).
"""
import argparse
import difflib
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass


# ----------------------------------------------------------------------------
# Utilitarios
# ----------------------------------------------------------------------------
def semacento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s))
                   if unicodedata.category(c) != "Mn")


def norm(s):
    """minusculas, sem acento, espacos normalizados."""
    return re.sub(r"\s+", " ", semacento(s).lower().strip())


def chave(s):
    """chave interna de um atributo: 'Historia de Credito' -> 'historia_de_credito'."""
    return norm(s).replace(" ", "_")


def num(v):
    try:
        return float(str(v).replace(",", "."))
    except ValueError:
        return None


def compara(a, op, b):
    """Compara dois valores (numericamente se ambos forem numeros)."""
    na, nb = num(a), num(b)
    if op in ("=", "!="):
        igual = (na == nb) if (na is not None and nb is not None) else norm(a) == norm(b)
        return igual if op == "=" else not igual
    if na is None or nb is None:
        return False
    return {"<": na < nb, ">": na > nb, "<=": na <= nb, ">=": na >= nb}[op]


# ----------------------------------------------------------------------------
# 1. BASE DE CONHECIMENTO
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class Cond:
    attr: str
    op: str
    val: str

    @property
    def key(self):
        return chave(self.attr)

    def __str__(self):
        return f"{self.attr} {self.op} {self.val}"


def parse_cond(txt):
    txt = txt.strip()
    m = re.match(r"^(.+?)\s*(<=|>=|!=|=|<|>)\s*(.+)$", txt)
    if m:
        return Cond(m.group(1).strip(), m.group(2), m.group(3).strip())
    if txt:
        return Cond(txt, "=", "sim")          # condicao booleana: "febre" == "febre = sim"
    raise ValueError("Condicao vazia.")


@dataclass
class Regra:
    id: str
    conds: list
    concl: Cond
    desc: str = ""

    def texto(self):
        return "SE " + " E ".join(str(c) for c in self.conds) + f" ENTAO {self.concl}"


def parse_regra(texto, rid, desc=""):
    """SE c1 E c2 ENTAO a = v   (conectivo 'E' em MAIUSCULAS, para permitir valores como 'preto e branco')."""
    m = re.match(r"^\s*(?:SE|IF)\s+(.+?)\s+(?:ENT[AÃ]O|THEN)\s+(.+?)\s*$", texto, re.I | re.S)
    if not m:
        raise ValueError("Formato esperado: SE cond1 E cond2 ENTAO atributo = valor")
    conds = [parse_cond(p) for p in re.split(r"\s+(?:E|AND)\s+", m.group(1))]
    concl = parse_cond(m.group(2))
    if concl.op != "=":
        raise ValueError("A conclusao deve usar '=' (atributo = valor).")
    return Regra(rid, conds, concl, desc)


class BaseConhecimento:
    def __init__(self, nome="Base vazia", descricao=""):
        self.nome, self.descricao = nome, descricao
        self.regras = []          # [Regra]
        self.fatos = []           # [(atributo, valor)]  fatos iniciais
        self.perguntas = {}       # chave -> {"attr", "texto", "opcoes"}
        self.objetivos = []       # atributos-objetivo (opcional)

    # ---- regras
    def _novo_id(self):
        ids, n = {r.id for r in self.regras}, 1
        while f"R{n}" in ids:
            n += 1
        return f"R{n}"

    def get_regra(self, rid):
        for r in self.regras:
            if norm(r.id) == norm(rid):
                return r
        raise KeyError(f"Regra '{rid}' nao encontrada.")

    def add_regra(self, texto, desc="", rid=None):
        rid = rid or self._novo_id()
        if any(r.id == rid for r in self.regras):
            raise ValueError(f"Ja existe uma regra {rid}.")
        r = parse_regra(texto, rid, desc)
        self.regras.append(r)
        return r

    def edit_regra(self, rid, texto):
        antiga = self.get_regra(rid)
        nova = parse_regra(texto, antiga.id, antiga.desc)
        self.regras[self.regras.index(antiga)] = nova
        return nova

    def del_regra(self, rid):
        self.regras.remove(self.get_regra(rid))

    # ---- fatos
    def add_fato(self, texto):
        c = parse_cond(texto)
        if c.op != "=":
            raise ValueError("Fato deve ter a forma atributo = valor.")
        self.fatos = [f for f in self.fatos if chave(f[0]) != c.key]
        self.fatos.append((c.attr, c.val))

    def del_fato(self, attr):
        n = len(self.fatos)
        self.fatos = [f for f in self.fatos if chave(f[0]) != chave(attr)]
        if len(self.fatos) == n:
            raise KeyError(f"Fato '{attr}' nao encontrado.")

    # ---- consultas sobre a estrutura
    def regras_para(self, key):
        return [r for r in self.regras if r.concl.key == key]

    def todos_atributos(self):
        d = {}
        for r in self.regras:
            for c in r.conds + [r.concl]:
                d.setdefault(c.key, c.attr)
        for a, _ in self.fatos:
            d.setdefault(chave(a), a)
        for k, p in self.perguntas.items():
            d.setdefault(k, p["attr"])
        return d

    def derivados(self):
        return {r.concl.key: r.concl.attr for r in self.regras}

    def atributos_base(self):
        """Atributos que nenhuma regra conclui (dados de entrada)."""
        der = self.derivados()
        base = {}
        for r in self.regras:
            for c in r.conds:
                if c.key not in der:
                    base.setdefault(c.key, c.attr)
        return base

    def objetivos_padrao(self):
        if self.objetivos:
            return list(self.objetivos)
        usados = {c.key for r in self.regras for c in r.conds}
        return [a for k, a in self.derivados().items() if k not in usados]

    def validar(self):
        av = []
        for g in self.objetivos:
            if not self.regras_para(chave(g)):
                av.append(f"Objetivo '{g}' nao e concluido por nenhuma regra.")
        grafo = {}
        for r in self.regras:
            grafo.setdefault(r.concl.key, set()).update(c.key for c in r.conds)
        cor = {}

        def dfs(u, caminho):
            cor[u] = 1
            for v in grafo.get(u, ()):
                if cor.get(v) == 1:
                    av.append("Dependencia circular: " + " -> ".join(caminho + [u, v]))
                elif v not in cor:
                    dfs(v, caminho + [u])
            cor[u] = 2
        for k in list(grafo):
            if k not in cor:
                dfs(k, [])
        return av

    # ---- persistencia
    def salvar(self, caminho):
        dados = {
            "nome": self.nome, "descricao": self.descricao,
            "objetivos": self.objetivos,
            "perguntas": {p["attr"]: {"texto": p["texto"], "opcoes": p["opcoes"]}
                          for p in self.perguntas.values()},
            "fatos": [f"{a} = {v}" for a, v in self.fatos],
            "regras": [{"id": r.id, "regra": r.texto(), "descricao": r.desc} for r in self.regras],
        }
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)

    @classmethod
    def carregar(cls, caminho):
        with open(caminho, encoding="utf-8") as f:
            d = json.load(f)
        kb = cls(d.get("nome", os.path.basename(caminho)), d.get("descricao", ""))
        kb.objetivos = d.get("objetivos", [])
        for attr, p in d.get("perguntas", {}).items():
            kb.perguntas[chave(attr)] = {"attr": attr, "texto": p.get("texto", ""),
                                         "opcoes": p.get("opcoes", [])}
        for f in d.get("fatos", []):
            kb.add_fato(f)
        for r in d.get("regras", []):
            kb.add_regra(r["regra"], r.get("descricao", ""), r.get("id"))
        return kb


# ----------------------------------------------------------------------------
# Entrada/saida
# ----------------------------------------------------------------------------
class ES:
    def say(self, t=""):
        print(t)

    def ask(self, prompt):
        try:
            r = input(prompt + " > ")
        except EOFError:
            print()
            return "?"
        if not sys.stdin.isatty():           # ecoa a entrada quando vem de pipe/arquivo
            print(r)
        return r


# ----------------------------------------------------------------------------
# 3. ENGENHO DE INFERENCIA  (+ 4. EXPLICACAO)
# ----------------------------------------------------------------------------
@dataclass
class Fato:
    attr: str
    valor: str
    origem: tuple      # ("inicial",) | ("usuario",) | ("regra", id, texto, [atributos])


class Engine:
    def __init__(self, kb, io, verbose=False):
        self.kb, self.io, self.verbose = kb, io, verbose
        self.modo = "misto"
        self.reset()

    def reset(self):
        self.wm = {}                  # memoria de trabalho: chave -> Fato
        self.desconhecidos = set()
        self.disparadas = set()
        self.conflitos = set()
        self.rastro = []
        self.frames = []              # pilha (regra, condicao) do encadeamento para tras
        self.objetivo_atual = None
        self.ultimo_por_que = None
        for a, v in self.kb.fatos:
            self.asserta(a, v, ("inicial",), log=False)

    # ---- utilidades
    def log(self, msg):
        self.rastro.append(msg)
        if self.verbose:
            self.io.say("   " + msg)

    def asserta(self, attr, valor, origem, log=True):
        k = chave(attr)
        if k in self.wm:
            return False
        self.wm[k] = Fato(attr, valor, origem)
        self.desconhecidos.discard(k)
        if log:
            self.log(f"fato novo: {attr} = {valor}")
        return True

    def avalia(self, c):
        """True/False se o atributo e conhecido; None caso contrario."""
        f = self.wm.get(c.key)
        return None if f is None else compara(f.valor, c.op, c.val)

    def dispara(self, r):
        k = r.concl.key
        if k in self.wm:
            return compara(self.wm[k].valor, "=", r.concl.val)
        self.asserta(r.concl.attr, r.concl.val,
                     ("regra", r.id, r.texto(), [c.attr for c in r.conds]), log=False)
        self.disparadas.add(r.id)
        self.log(f"{r.id} disparada: {r.concl}")
        return True

    # ---- ENCADEAMENTO PARA FRENTE (dirigido por dados)
    def encadeia_frente(self):
        ciclo, novos = 0, []
        while True:
            aplic = []
            for r in self.kb.regras:
                if r.id in self.disparadas:
                    continue
                k = r.concl.key
                if k in self.wm:
                    if (not compara(self.wm[k].valor, "=", r.concl.val) and r.id not in self.conflitos
                            and all(self.avalia(c) is True for c in r.conds)):
                        self.conflitos.add(r.id)
                        self.log(f"conflito: {r.id} concluiria {r.concl}, mas ja ha {k} = {self.wm[k].valor}")
                    continue
                if all(self.avalia(c) is True for c in r.conds):
                    aplic.append(r)
            if not aplic:
                break
            ciclo += 1
            # resolucao de conflito: maior especificidade (mais condicoes), depois ordem
            esc = max(aplic, key=lambda r: (len(r.conds), -self.kb.regras.index(r)))
            self.log(f"[frente] ciclo {ciclo}: conjunto de conflito = "
                     f"{{{', '.join(r.id for r in aplic)}}}; escolhida {esc.id}")
            self.dispara(esc)
            novos.append(esc)
        return novos

    # ---- ENCADEAMENTO PARA TRAS (dirigido por objetivos)
    def prova_regra(self, r):
        if r.id in self.disparadas:
            return True
        if any(fr[0].id == r.id for fr in self.frames):
            return False                                  # evita ciclos
        self.log(f"[tras] tentando {r.id} para provar {r.concl}")
        for c in r.conds:
            self.frames.append((r, c))
            ok = self.prova_cond(c)
            self.frames.pop()
            if not ok:
                self.log(f"[tras] {r.id} falhou em: {c}")
                return False
        return self.dispara(r)

    def prova_cond(self, c):
        a = self.avalia(c)
        if a is not None:
            return a
        k = c.key
        if k in self.desconhecidos:
            return False
        for r in self.kb.regras_para(k):
            if c.op == "=" and not compara(r.concl.val, "=", c.val):
                continue
            if self.prova_regra(r):
                return self.avalia(c) is True
        if self.pode_perguntar(k):
            self.perguntar(c)
            return self.avalia(c) is True
        return False

    def pode_perguntar(self, k):
        return k not in self.desconhecidos and (k in self.kb.perguntas or not self.kb.regras_para(k))

    def buscar(self, attr):
        """Objetivo: descobrir o valor de 'attr'."""
        k = chave(attr)
        self.objetivo_atual = attr
        self.log(f"[tras] objetivo: descobrir {attr}")
        if k not in self.wm:
            for r in self.kb.regras_para(k):
                if self.prova_regra(r):
                    break
            if k not in self.wm and self.pode_perguntar(k):
                self.perguntar(Cond(attr, "=", "?"))
        return self.wm.get(k)

    # ---- ENCADEAMENTO MISTO
    def misto(self, objetivos):
        self.log("[misto] fase 1: propagacao para frente com os fatos conhecidos")
        self.encadeia_frente()
        for g in objetivos:
            if chave(g) not in self.wm:
                self.log(f"[misto] fase 2: para tras rumo a '{g}' (perguntas disparam nova propagacao)")
                self.buscar(g)
                self.encadeia_frente()

    # ---- pergunta ao usuario (com suporte a POR QUE?)
    def perguntar(self, c, coleta=False):
        k = c.key
        info = self.kb.perguntas.get(k, {})
        opcoes = info.get("opcoes", [])
        texto = info.get("texto") or f"Qual o valor de '{c.attr}'?"
        if opcoes:
            texto += " [" + "/".join(opcoes) + "]"
        dica = "'porque' = razao da pergunta, '?' = nao sei"
        while True:
            resp = self.io.ask(f"{texto} ({dica})").strip()
            r = norm(resp)
            if r in ("porque", "por que", "why", "pq"):
                self.ultimo_por_que = self.explica_por_que(c, coleta)
                self.io.say(self.ultimo_por_que)
                continue
            if r in ("?", "", "nao sei", "ns", "desconhecido", "unknown"):
                self.desconhecidos.add(k)
                self.log(f"'{c.attr}' marcado como desconhecido")
                return False
            if opcoes:
                match = [o for o in opcoes if norm(o) == r]
                if not match:
                    self.io.say("   Resposta fora das opcoes. Tente novamente.")
                    continue
                resp = match[0]
            self.asserta(c.attr, resp, ("usuario",))
            if self.modo == "misto":
                self.encadeia_frente()          # propaga o dado novo imediatamente
            return True

    # ---- EXPLICACAO
    def explica_por_que(self, c, coleta=False):
        if not self.frames:
            if coleta:
                return "   Estou coletando os dados de entrada para o encadeamento para frente."
            return f"   Voce pediu diretamente o valor de '{c.attr}'."
        r, cond = self.frames[-1]
        L = [f"   Pergunto '{c.attr}' porque preciso avaliar a condicao ({cond}) da regra {r.id}:",
             f"      {r.id}: {r.texto()}"]
        for i in range(len(self.frames) - 1, 0, -1):
            filha, (pai, cp) = self.frames[i][0], self.frames[i - 1]
            L.append(f"   Se {filha.id} for confirmada, concluo ({filha.concl}), "
                     f"necessario para a condicao ({cp}) de {pai.id}.")
        if self.objetivo_atual:
            L.append(f"   Objetivo em andamento: descobrir '{self.objetivo_atual}'.")
        return "\n".join(L)

    def usado_em(self, key):
        return [r for r in self.kb.regras if any(c.key == key for c in r.conds)]

    def explica_como(self, attr, nivel=0):
        k, ind = chave(attr), "   " * (nivel + 1)
        f = self.wm.get(k)
        if f is None:
            if k in self.desconhecidos:
                return f"{ind}* {attr}: informado como desconhecido."
            return f"{ind}* {attr}: ainda nao e conhecido."
        o = f.origem
        if o[0] == "inicial":
            return f"{ind}* {f.attr} = {f.valor}   [fato inicial da base]"
        if o[0] == "usuario":
            return f"{ind}* {f.attr} = {f.valor}   [informado por voce]"
        L = [f"{ind}* {f.attr} = {f.valor}   [derivado pela regra {o[1]}]",
             f"{ind}  {o[2]}"]
        for a in o[3]:
            L.append(self.explica_como(a, nivel + 1))
        return "\n".join(L)


# ----------------------------------------------------------------------------
# 5. INTERFACE (dialogo em linguagem natural) + 2. EDITOR
# ----------------------------------------------------------------------------
ARTIGOS = {"o", "a", "os", "as", "um", "uma", "meu", "minha", "do", "da", "de", "no", "na", "que", "qual",
           "quais", "quem", "quanto", "quanta", "e", "eh", "esta", "estao", "sao", "foi", "para", "por"}

AJUDA = """Comandos (voce tambem pode escrever frases naturais):
  consultar [frente|tras|misto]   inicia a consulta (ex.: "consultar", "diagnosticar")
  qual e o <atributo>?            objetivo especifico (ex.: "qual e a falha?")
  <atributo> e <valor>            informa um fato (ex.: "a cor e amarelo")
  por que <atributo>              razao de um dado ser necessario (durante perguntas: 'porque')
  como <atributo>                 mostra COMO o valor foi obtido (arvore de justificativa)
  fatos | regras | rastro         mostra memoria de trabalho / regras / trilha de inferencia
  modo frente|tras|misto          escolhe o encadeamento padrao
  detalhar on|off                 mostra a trilha de inferencia em tempo real
  reiniciar                       novo caso (limpa a memoria de trabalho)
  editor                          menu de edicao da base de conhecimento
  adicionar regra SE ... ENTAO ...   | editar regra R1 SE ... ENTAO ...   | excluir regra R1
  adicionar fato atributo = valor    | excluir fato atributo
  validar | salvar [arq] | carregar <arq> | sair"""


class Shell:
    def __init__(self, kb=None, modo="misto", io=None):
        self.io = io or ES()
        self.kb = kb or BaseConhecimento()
        self.caminho = None
        self.modo = modo
        self.engine = Engine(self.kb, self.io)

    # ---------- base
    def carregar(self, caminho):
        for c in (caminho, caminho + ".json", os.path.join("bases", caminho),
                  os.path.join("bases", caminho + ".json")):
            if os.path.isfile(c):
                self.kb = BaseConhecimento.carregar(c)
                self.caminho = c
                self.reiniciar(silencioso=True)
                self.io.say(f"Base '{self.kb.nome}' carregada: {len(self.kb.regras)} regras, "
                            f"{len(self.kb.fatos)} fatos.")
                if self.kb.descricao:
                    self.io.say(f"   {self.kb.descricao}")
                return
        self.io.say(f"Arquivo '{caminho}' nao encontrado.")

    def reiniciar(self, silencioso=False):
        verbose = self.engine.verbose
        self.engine = Engine(self.kb, self.io, verbose)
        if not silencioso:
            self.io.say("Memoria de trabalho reiniciada.")

    def apos_edicao(self):
        self.reiniciar(silencioso=True)
        self.io.say("   (base alterada; memoria de trabalho reiniciada)")

    # ---------- resolucao de atributos em texto livre
    def achar_attr(self, texto):
        t = re.sub(r"[?!.,;:]", " ", norm(texto))
        todos = self.kb.todos_atributos()
        for k in sorted(todos, key=len, reverse=True):
            if re.search(rf"\b{re.escape(k.replace('_', ' '))}\b", t):
                return todos[k]
        palavras = [w for w in t.split() if w not in ARTIGOS]
        nomes = {k.replace("_", " "): a for k, a in todos.items()}
        for cand in [" ".join(palavras)] + palavras:
            if not cand:
                continue
            m = difflib.get_close_matches(cand, list(nomes), n=1, cutoff=0.72)
            if m:
                return nomes[m[0]]
        return None

    # ---------- consulta
    def consultar(self, modo=None):
        e, modo = self.engine, (modo or self.modo)
        e.modo = modo
        objetivos = self.kb.objetivos_padrao()
        if not self.kb.regras:
            self.io.say("A base nao tem regras. Use 'editor' ou 'carregar'.")
            return
        if not objetivos:
            self.io.say("Nao ha atributos-objetivo definidos na base.")
            return
        self.io.say(f"--- Consulta ({ {'frente':'encadeamento para frente','tras':'encadeamento para tras','misto':'encadeamento misto'}[modo] }) "
                    f"| objetivos: {', '.join(objetivos)} ---")
        if modo == "frente":
            self.io.say("Informe os dados que conhece (responda '?' ou Enter para pular):")
            for k, nome in self.kb.atributos_base().items():
                if k not in e.wm and k not in e.desconhecidos:
                    e.perguntar(Cond(nome, "=", "?"), coleta=True)
            e.encadeia_frente()
        elif modo == "tras":
            for g in objetivos:
                e.buscar(g)
        else:
            e.misto(objetivos)
        self.mostra_resultado(objetivos)

    def mostra_resultado(self, objetivos):
        e = self.engine
        self.io.say("--- Resultado ---")
        for g in objetivos:
            f = e.wm.get(chave(g))
            self.io.say(f"  {g} = {f.valor}" if f else f"  {g}: nao foi possivel concluir com os dados fornecidos.")
        self.io.say("Digite 'como <atributo>' para ver a justificativa ou 'rastro' para a trilha completa.")

    # ---------- listagens
    def lista_regras(self):
        if not self.kb.regras:
            self.io.say("(nenhuma regra)")
        for r in self.kb.regras:
            self.io.say(f"  {r.id}: {r.texto()}" + (f"    # {r.desc}" if r.desc else ""))

    def lista_fatos(self):
        if not self.engine.wm:
            self.io.say("(memoria de trabalho vazia)")
        for f in self.engine.wm.values():
            o = {"inicial": "fato inicial", "usuario": "informado", "regra": None}[f.origem[0]]
            self.io.say(f"  {f.attr} = {f.valor}   [{o or 'derivado por ' + f.origem[1]}]")
        if self.engine.desconhecidos:
            self.io.say("  desconhecidos: " + ", ".join(sorted(self.engine.desconhecidos)))

    # ---------- editor (menu)
    def editor(self):
        menu = ("\n=== EDITOR DA BASE DE CONHECIMENTO ===\n"
                " 1) listar regras      2) nova regra        3) editar regra     4) excluir regra\n"
                " 5) listar fatos base  6) novo fato         7) excluir fato\n"
                " 8) definir pergunta   9) definir objetivos 10) validar         11) salvar\n"
                " 0) voltar")
        while True:
            self.io.say(menu)
            op = self.io.ask("Opcao").strip()
            try:
                if op == "1":
                    self.lista_regras()
                elif op == "2":
                    self.io.say("Digite as condicoes uma por linha (ex.: temperatura > 38). Linha vazia encerra.")
                    conds = []
                    while True:
                        c = self.io.ask(f"  Condicao {len(conds) + 1}").strip()
                        if not c:
                            break
                        conds.append(str(parse_cond(c)))
                    concl = self.io.ask("  Conclusao (atributo = valor)").strip()
                    desc = self.io.ask("  Descricao (opcional)").strip()
                    r = self.kb.add_regra(f"SE {' E '.join(conds)} ENTAO {concl}", desc)
                    self.io.say(f"  Criada {r.id}: {r.texto()}")
                    self.apos_edicao()
                elif op == "3":
                    rid = self.io.ask("  Id da regra").strip()
                    self.io.say(f"  Atual: {self.kb.get_regra(rid).texto()}")
                    self.kb.edit_regra(rid, self.io.ask("  Nova regra (SE ... ENTAO ...)"))
                    self.io.say("  Regra atualizada.")
                    self.apos_edicao()
                elif op == "4":
                    self.kb.del_regra(self.io.ask("  Id da regra").strip())
                    self.io.say("  Regra excluida.")
                    self.apos_edicao()
                elif op == "5":
                    for a, v in self.kb.fatos:
                        self.io.say(f"  {a} = {v}")
                    if not self.kb.fatos:
                        self.io.say("  (nenhum fato inicial)")
                elif op == "6":
                    self.kb.add_fato(self.io.ask("  Fato (atributo = valor)"))
                    self.apos_edicao()
                elif op == "7":
                    self.kb.del_fato(self.io.ask("  Atributo do fato"))
                    self.apos_edicao()
                elif op == "8":
                    attr = self.io.ask("  Atributo").strip()
                    texto = self.io.ask("  Texto da pergunta").strip()
                    ops = [o.strip() for o in self.io.ask("  Opcoes separadas por virgula (opcional)").split(",") if o.strip()]
                    self.kb.perguntas[chave(attr)] = {"attr": attr, "texto": texto, "opcoes": ops}
                    self.io.say("  Pergunta definida.")
                elif op == "9":
                    self.kb.objetivos = [o.strip() for o in self.io.ask("  Objetivos separados por virgula").split(",") if o.strip()]
                elif op == "10":
                    self.valida()
                elif op == "11":
                    self.salvar(None)
                elif op == "0":
                    return
                else:
                    self.io.say("  Opcao invalida.")
            except (ValueError, KeyError) as ex:
                self.io.say(f"  Erro: {ex}")

    def valida(self):
        av = self.kb.validar()
        self.io.say("Base consistente." if not av else "\n".join("  Aviso: " + a for a in av))

    def salvar(self, caminho):
        caminho = caminho or self.caminho or "minha_base.json"
        self.kb.salvar(caminho)
        self.caminho = caminho
        self.io.say(f"Base salva em '{caminho}'.")

    # ---------- interpretador de linguagem natural
    def interpretar(self, linha):
        """Retorna False para encerrar."""
        raw = linha.strip()
        if not raw:
            return True
        t = norm(raw)
        sa = semacento(raw)
        e = self.engine
        m = None

        if t in ("sair", "exit", "quit", "tchau", "fim"):
            return False
        if t in ("ajuda", "help", "?", "comandos"):
            self.io.say(AJUDA)
        elif (m := re.match(r"^(?:carregar|abrir|load)\s+(.+)$", raw, re.I)):
            self.carregar(m.group(1).strip())
        elif (m := re.match(r"^(?:salvar|gravar|save)(?:\s+(.+))?$", raw, re.I)):
            self.salvar(m.group(1))
        elif re.match(r"^(regras|listar regras|mostrar regras|quais sao as regras)\b", t):
            self.lista_regras()
        elif re.match(r"^(fatos|listar fatos|mostrar fatos|memoria|o que voce sabe)\b", t):
            self.lista_fatos()
        elif t in ("rastro", "trace", "log", "trilha"):
            self.io.say("\n".join("  " + x for x in e.rastro) or "(rastro vazio)")
        elif (m := re.match(r"^modo\s+(frente|tras|misto)$", t)):
            self.modo = m.group(1)
            self.io.say(f"Modo padrao: {self.modo}.")
        elif (m := re.match(r"^detalhar\s+(on|off|sim|nao)$", t)):
            e.verbose = m.group(1) in ("on", "sim")
            self.io.say(f"Trilha em tempo real: {'ligada' if e.verbose else 'desligada'}.")
        elif t == "editor":
            self.editor()
        elif t == "validar":
            self.valida()
        elif t in ("reiniciar", "limpar", "reset", "novo caso"):
            self.reiniciar()
        elif (m := re.match(r"^(?:adicionar|adiciona|criar|nova|add)\s+regra\s+(.+)$", raw, re.I)):
            try:
                r = self.kb.add_regra(m.group(1))
                self.io.say(f"Criada {r.id}: {r.texto()}")
                self.apos_edicao()
            except ValueError as ex:
                self.io.say(f"Erro: {ex}")
        elif (m := re.match(r"^(?:adicionar|adiciona|criar|add)\s+fato\s+(.+)$", raw, re.I)):
            try:
                self.kb.add_fato(m.group(1))
                self.apos_edicao()
            except ValueError as ex:
                self.io.say(f"Erro: {ex}")
        elif (m := re.match(r"^(?:excluir|remover|apagar|deletar)\s+regra\s+(\S+)$", raw, re.I)):
            try:
                self.kb.del_regra(m.group(1))
                self.io.say("Regra excluida.")
                self.apos_edicao()
            except KeyError as ex:
                self.io.say(f"Erro: {ex.args[0]}")
        elif (m := re.match(r"^(?:excluir|remover|apagar|deletar)\s+fato\s+(.+)$", raw, re.I)):
            try:
                self.kb.del_fato(m.group(1))
                self.apos_edicao()
            except KeyError as ex:
                self.io.say(f"Erro: {ex.args[0]}")
        elif (m := re.match(r"^editar\s+regra\s+(\S+)\s+(SE\s+.+)$", raw, re.I)):
            try:
                self.kb.edit_regra(m.group(1), m.group(2))
                self.io.say("Regra atualizada.")
                self.apos_edicao()
            except (ValueError, KeyError) as ex:
                self.io.say(f"Erro: {ex.args[0]}")
        elif re.match(r"^(consultar|iniciar|comecar|diagnosticar|classificar|avaliar|recomendar|executar|rodar)\b", t):
            mm = re.search(r"\b(frente|tras|misto)\b", t)
            self.consultar(mm.group(1) if mm else None)
        elif re.match(r"^(por ?que|porque|pq)\b", t):
            alvo = self.achar_attr(re.sub(r"^\S+(\s+que)?", "", t, count=1))
            if alvo:
                usos = e.usado_em(chave(alvo))
                if usos:
                    self.io.say(f"'{alvo}' e necessario porque aparece nas regras:")
                    for r in usos:
                        self.io.say(f"   {r.id}: {r.texto()}")
                else:
                    self.io.say(f"'{alvo}' nao e usado como condicao em nenhuma regra (e um resultado final).")
            else:
                self.io.say(e.ultimo_por_que or "Ainda nao fiz nenhuma pergunta. Use 'porque' quando eu perguntar algo.")
        elif re.match(r"^como\b", t):
            alvo = self.achar_attr(t[4:])
            alvos = [alvo] if alvo else [a for a in self.kb.objetivos_padrao() if chave(a) in e.wm]
            if not alvos:
                self.io.say("Ainda nao ha conclusoes. Rode 'consultar' primeiro ou diga 'como <atributo>'.")
            for a in alvos:
                self.io.say("Justificativa:")
                self.io.say(e.explica_como(a))
        elif re.match(r"^(qual|quais|quem|o que|que|quanto|quanta|onde)\b", t) and self.achar_attr(t):
            a = self.achar_attr(t)
            e.modo = self.modo
            f = e.buscar(a)
            self.io.say(f"  {f.attr} = {f.valor}" if f else f"  Nao foi possivel concluir '{a}'.")
        elif (m := re.match(r"^(.+?)\s+(?:e|eh|=|igual a|igual|esta|estao|sao)\s+(.+)$", sa, re.I)) \
                and self.achar_attr(m.group(1)):
            a = self.achar_attr(m.group(1))
            val = m.group(2).strip(" .!")
            if e.asserta(a, val, ("usuario",)):
                self.io.say(f"Anotado: {a} = {val}.")
                if self.modo == "misto":
                    e.modo = "misto"
                    for r in e.encadeia_frente():
                        self.io.say(f"   -> {r.id} concluiu {r.concl}")
            else:
                self.io.say(f"'{a}' ja tem valor ({e.wm[chave(a)].valor}). Use 'reiniciar' para um novo caso.")
        else:
            self.io.say("Nao entendi. Digite 'ajuda' para ver o que posso fazer.")
        return True

    def repl(self):
        self.io.say("=" * 66)
        self.io.say(" SHELL DE SISTEMA BASEADO EM CONHECIMENTO  (digite 'ajuda')")
        self.io.say("=" * 66)
        while True:
            try:
                linha = input("sbc> ")
            except EOFError:
                print()
                break
            if not sys.stdin.isatty():
                print(linha)
            try:
                if not self.interpretar(linha):
                    break
            except KeyboardInterrupt:
                print()
        self.io.say("Ate logo!")


def main():
    ap = argparse.ArgumentParser(description="Shell generico para sistemas baseados em conhecimento")
    ap.add_argument("base", nargs="?", help="arquivo .json com a base de conhecimento")
    ap.add_argument("--modo", choices=["frente", "tras", "misto"], default="misto")
    args = ap.parse_args()
    sh = Shell(modo=args.modo)
    if args.base:
        sh.carregar(args.base)
    else:
        sh.io.say("Nenhuma base carregada. Use 'carregar <arquivo>' ou 'editor' para criar uma.")
    sh.repl()


if __name__ == "__main__":
    main()