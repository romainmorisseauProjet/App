"""
Module Calcul.

Un seul endroit pour TOUS les calculs, avec une règle : n'afficher que
l'essentiel (résultat, unité), jamais de phrases inutiles. Les formules et
explications existent mais restent masquées tant que l'interrupteur
« Détails » n'est pas activé.

Ce que le module sait faire, sans aucune IA :
  - expressions libres : 4,7k*3 ; 20% de 150 ; 150+20% ; sin(30°) ; mean([1,2,3])
    (suffixes SI p n u m k M G T, virgule décimale, %, degrés, ans = dernier résultat)
  - conversions : « 5 km en mi », « 70 °F en °C », « 3 Go en Mio »
  - maths symboliques (SymPy) : resoudre, derive, integrale, limite, simplifie,
    factorise, developpe
  - une bibliothèque de formules prêtes à remplir (électronique, immobilier,
    TNS, maths, finance) : voir FORMULES plus bas, facile à étendre
  - un historique en base (table calcul_historique)

Ce qui demande une IA (photo, demande en langage naturel) passe par UNE seule
fonction, _appeler_ia(). Elle sait déjà parler à l'API Anthropic ; quand tu
brancheras ton IA locale ou une autre, c'est la seule fonction à remplacer.

Comme les autres modules : toutes les fonctions publiques renvoient des
dictionnaires simples, main.py ne fait que faire le pont.
"""

import ast
import base64
import io
import math
import operator
import os
import re
import sqlite3
import statistics
from concurrent.futures import ThreadPoolExecutor, TimeoutError as DelaiDepasse
from datetime import datetime, timezone

NBSP = "\u202f"  # espace fine insécable pour les milliers
MODELE_IA_DEFAUT = "claude-sonnet-5-5"
HISTORIQUE_MAX = 200


class ErreurCalcul(Exception):
    pass


class VariableManquante(ErreurCalcul):
    pass


# ======================================================================
# 1. Formatage des nombres (virgule française, espaces, préfixes SI)
# ======================================================================

_EXPOSANTS = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
_PREFIXES = {-12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G", 12: "T"}
# Unités auxquelles on peut accoler un préfixe (kΩ, nF, mA…)
_UNITES_SI = {"V", "A", "Ω", "F", "H", "Hz", "W", "s", "VA", "var"}


def _grouper(chiffres):
    negatif = chiffres.startswith("-")
    s = chiffres.lstrip("-")
    blocs = []
    while len(s) > 3:
        blocs.insert(0, s[-3:])
        s = s[:-3]
    blocs.insert(0, s)
    return ("-" if negatif else "") + NBSP.join(blocs)


def _fmt(x, sig=6):
    """Nombre → texte lisible : 1 234,57 ; 4,7×10⁻⁹ ; jamais de bruit flottant."""
    if isinstance(x, bool):
        return "vrai" if x else "faux"
    if isinstance(x, str):
        return x
    if isinstance(x, int):
        if abs(x) < 10 ** 15:
            return _grouper(str(x))
        x = float(x)
    if math.isnan(x):
        return "indéfini"
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    if x == 0:
        return "0"
    ax = abs(x)
    if 1e-4 <= ax < 1e12:
        dec = max(0, sig - 1 - math.floor(math.log10(ax)))
        s = f"{x:.{dec}f}"
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        ent, _, frac = s.partition(".")
        res = _grouper(ent) + ("," + frac if frac else "")
        return "0" if res == "-0" else res
    m, e = f"{x:.{sig - 1}e}".split("e")
    if "." in m:
        m = m.rstrip("0").rstrip(".")
    return f"{m.replace('.', ',')}×10{str(int(e)).translate(_EXPOSANTS)}"


def _fmt_fixe(x, decimales=2):
    s = f"{x:.{decimales}f}"
    ent, _, frac = s.partition(".")
    return _grouper(ent) + ("," + frac if frac else "")


def _eng(x, unite):
    """Notation d'ingénieur : 0,00047 F → 470 µF."""
    if x == 0 or not math.isfinite(x):
        return f"{_fmt(x)} {unite}".strip()
    exp = int(math.floor(math.log10(abs(x)) / 3) * 3)
    exp = max(-12, min(12, exp))
    mant = x / 10 ** exp
    if abs(float(f"{mant:.4g}")) >= 1000 and exp < 12:
        exp += 3
        mant = x / 10 ** exp
    return f"{_fmt(mant, 4)} {_PREFIXES[exp]}{unite}"


def _afficher(x, unite="", mode="leger"):
    if isinstance(x, str):
        return x
    if isinstance(x, (list, tuple)):
        return "[" + " ; ".join(_afficher(v, "", mode) for v in x) + "]"
    if isinstance(x, float) and not math.isfinite(x):
        return _fmt(x)
    if unite == "€":
        return f"{_fmt_fixe(x, 2)} €"
    if unite == "%":
        return f"{_fmt(x, 4)} %"
    if mode == "si" and unite in _UNITES_SI:
        return _eng(x, unite)
    return _fmt(x, 6) + (f" {unite}" if unite else "")


# ======================================================================
# 2. Séries de valeurs normalisées et sections de câble
# ======================================================================

_E12 = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]
_E24 = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9,
        4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]
_E96 = [round(10 ** (i / 96), 2) for i in range(96)]
_SERIES = {"E12": _E12, "E24": _E24, "E96": _E96}
_SECTIONS_MM2 = [1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300]


def _serie(nom, x, sens):
    if x <= 0:
        raise ErreurCalcul("Valeur positive requise")
    tab = _SERIES[nom]
    dec = math.floor(math.log10(x))
    mant = x / 10 ** dec
    cands = tab + [10.0]
    if sens == "sup":
        v = next(c for c in cands if c >= mant * (1 - 1e-9))
    elif sens == "inf":
        v = [c for c in cands if c <= mant * (1 + 1e-9)][-1]
    else:
        v = min(cands, key=lambda c: abs(math.log(c / mant)))
    return float(f"{v * 10 ** dec:.6g}")


def _section_sup(s):
    for v in _SECTIONS_MM2:
        if v >= s * (1 - 1e-9):
            return float(v)
    return float(_SECTIONS_MM2[-1])


# ======================================================================
# 3. Évaluateur d'expressions SÉCURISÉ (aucun eval() : on lit l'arbre)
# ======================================================================

CONSTANTES = {
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "c0": 299792458.0,        # vitesse de la lumière (m/s)
    "g0": 9.80665,            # pesanteur (m/s²)
    "qe": 1.602176634e-19,    # charge élémentaire (C)
    "mu0": 1.25663706212e-6,  # perméabilité du vide (H/m)
    "eps0": 8.8541878128e-12, # permittivité du vide (F/m)
    "kB": 1.380649e-23,       # Boltzmann (J/K)
}


def _aplatir(args):
    out = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(_aplatir(a))
        else:
            out.append(a)
    return out


def _par(*args):
    vals = _aplatir(args)
    if any(v == 0 for v in vals):
        return 0.0
    return 1 / sum(1 / v for v in vals)


def _fact(n):
    if n != int(n) or n < 0 or n > 5000:
        raise ErreurCalcul("Factorielle : entier entre 0 et 5000")
    return math.factorial(int(n))


def _racine(x, n=2):
    if x < 0 and int(n) % 2 == 1:
        return -((-x) ** (1 / n))
    return x ** (1 / n)


FONCTIONS = {
    "sqrt": math.sqrt, "racine": _racine, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "ln": math.log, "log10": math.log10, "log": math.log10, "log2": math.log2, "exp": math.exp,
    "abs": abs, "round": round, "arrondi": round, "floor": math.floor, "ceil": math.ceil,
    "hypot": math.hypot, "mod": lambda a, b: a % b,
    "rad": math.radians, "deg": math.degrees,
    "min": lambda *a: min(_aplatir(a)), "max": lambda *a: max(_aplatir(a)),
    "sum": lambda *a: sum(_aplatir(a)), "somme": lambda *a: sum(_aplatir(a)),
    "mean": lambda *a: statistics.fmean(_aplatir(a)), "moy": lambda *a: statistics.fmean(_aplatir(a)),
    "moyenne": lambda *a: statistics.fmean(_aplatir(a)),
    "median": lambda *a: statistics.median(_aplatir(a)), "med": lambda *a: statistics.median(_aplatir(a)),
    "mediane": lambda *a: statistics.median(_aplatir(a)),
    "ecart": lambda *a: statistics.pstdev(_aplatir(a)),   # écart-type de la population
    "stdev": lambda *a: statistics.stdev(_aplatir(a)),    # écart-type d'échantillon
    "fact": _fact, "comb": lambda n, k: math.comb(int(n), int(k)), "perm": lambda n, k: math.perm(int(n), int(k)),
    "pgcd": lambda *a: math.gcd(*[int(v) for v in _aplatir(a)]),
    "ppcm": lambda *a: math.lcm(*[int(v) for v in _aplatir(a)]),
    "bin": lambda n: bin(int(n)), "hex": lambda n: hex(int(n)), "oct": lambda n: oct(int(n)),
    "par": _par, "ser": lambda *a: sum(_aplatir(a)),   # résistances en parallèle / en série
    "section_sup": _section_sup,
}
for _nom in _SERIES:
    _bas = _nom.lower()
    FONCTIONS[_bas] = (lambda n: lambda x: _serie(n, x, "proche"))(_nom)
    FONCTIONS[_bas + "sup"] = (lambda n: lambda x: _serie(n, x, "sup"))(_nom)
    FONCTIONS[_bas + "inf"] = (lambda n: lambda x: _serie(n, x, "inf"))(_nom)

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_CMP = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
        ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


def _puissance(a, b):
    if isinstance(a, int) and isinstance(b, int) and b > 0 and a not in (0, 1, -1):
        if b * math.log10(abs(a)) > 300:
            raise ErreurCalcul("Résultat trop grand")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if abs(b) > 10000 and abs(a) > 1:
            raise ErreurCalcul("Résultat trop grand")
    r = a ** b
    if isinstance(r, complex):
        raise ErreurCalcul("Résultat complexe (racine d'un nombre négatif)")
    return r


def _eval(node, env):
    t = type(node)
    if t is ast.Expression:
        return _eval(node.body, env)
    if t is ast.Constant:
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ErreurCalcul("Valeur non autorisée")
    if t is ast.Name:
        if node.id in env:
            return env[node.id]
        if node.id in CONSTANTES:
            return CONSTANTES[node.id]
        raise VariableManquante(f"Inconnu : {node.id}")
    if t is ast.BinOp:
        a, b = _eval(node.left, env), _eval(node.right, env)
        if isinstance(node.op, ast.Pow):
            return _puissance(a, b)
        if isinstance(node.op, ast.BitOr):      # R1|R2 = résistances en parallèle
            return _par(a, b)
        op = _BIN.get(type(node.op))
        if op is None:
            raise ErreurCalcul("Opérateur non autorisé")
        return op(a, b)
    if t is ast.UnaryOp:
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
        if isinstance(node.op, ast.Not):
            return not v
        raise ErreurCalcul("Opérateur non autorisé")
    if t is ast.Compare:
        gauche = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            droite = _eval(comp, env)
            f = _CMP.get(type(op))
            if f is None or not f(gauche, droite):
                if f is None:
                    raise ErreurCalcul("Comparaison non autorisée")
                return False
            gauche = droite
        return True
    if t is ast.BoolOp:
        vals = [_eval(v, env) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if t is ast.IfExp:
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if t in (ast.List, ast.Tuple):
        return [_eval(e, env) for e in node.elts]
    if t is ast.Call:
        if not isinstance(node.func, ast.Name) or node.func.id not in FONCTIONS or node.keywords:
            nom = node.func.id if isinstance(node.func, ast.Name) else "?"
            raise ErreurCalcul(f"Fonction inconnue : {nom}")
        return FONCTIONS[node.func.id](*[_eval(a, env) for a in node.args])
    raise ErreurCalcul("Expression non autorisée")


def _evaluer_brut(expr, env):
    """Pour les formules écrites par moi (déjà en syntaxe Python valide)."""
    try:
        arbre = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise ErreurCalcul("Syntaxe invalide")
    return _eval(arbre, env)


# --- Préparation du texte tapé par l'utilisateur ---------------------

_SI_COMPLET = {"p": "/1000000000000", "n": "/1000000000", "u": "/1000000", "m": "/1000",
               "k": "*1000", "M": "*1000000", "G": "*1000000000", "T": "*1000000000000"}
_SI_LEGER = {"k": "*1000", "M": "*1000000"}
_MOTS_FONCTION = re.compile(r"[A-Za-z_]\w*\s*\(|\[")


def _mult_implicite(s):
    s = re.sub(r"(?<![A-Za-z_\d.])(\d+(?:\.\d+)?)\s*(?=\()", r"\1*", s)
    s = re.sub(r"\)\s*(?=[\d(A-Za-z_])", ")*", s)

    def cb(m):
        suite = m.string[m.end():]
        if re.match(r"[eE][-+]?\d", suite):          # notation scientifique 1e-9
            return m.group(0)
        if m.group(1) == "0" and suite[:1] in "xXbBoO":  # 0x1F, 0b101
            return m.group(0)
        return m.group(1) + "*"

    return re.sub(r"(?<![A-Za-z_\d.])(\d+(?:\.\d+)?)\s*(?=[A-Za-z_])", cb, s)


def _preparer(texte, si="complet"):
    s = texte.strip()
    if len(s) > 500:
        raise ErreurCalcul("Expression trop longue")
    for a, b in (("×", "*"), ("·", "*"), ("÷", "/"), ("²", "**2"), ("³", "**3"), ("π", "pi"), ("µ", "u"),
                 ("−", "-"), ("–", "-"), ("’", "'"), ("∥", "|"), ("||", "|")):
        s = s.replace(a, b)
    s = re.sub(r"√\s*\(", "sqrt(", s)
    s = re.sub(r"√\s*(\d+(?:[.,]\d+)?)", r"sqrt(\1)", s)
    s = re.sub(r"Ω|\bohms?\b", "", s, flags=re.I)
    s = re.sub(r"(?<=\d)[ \u202f\u00a0](?=\d{3}(?!\d))", "", s)      # 1 000 000
    s = s.replace(";", ",")
    if not _MOTS_FONCTION.search(s):
        s = re.sub(r"(?<=\d),(?=\d)", ".", s)                         # 4,7 → 4.7
    s = re.sub(r"(\d+(?:\.\d+)?)\s*°", r"rad(\1)", s)                 # 30° → rad(30)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*([+-])\s*(\d+(?:\.\d+)?)\s*%(?!\s*de)", r"\1*(1\2\3/100)", s)
    s = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*(?:de|d')\s*", r"(\1/100)*", s)
    s = s.replace("%", "/100")
    table = {"complet": _SI_COMPLET, "leger": _SI_LEGER}.get(si, {})
    if table:
        def suffixe(m):
            return f"({m.group(1)}{table[m.group(2)]})" if m.group(2) in table else m.group(0)
        s = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?|\.\d+)([pnuµmkMGT])(?![A-Za-z0-9_])", suffixe, s)
    s = _mult_implicite(s)
    s = s.replace("^", "**")
    return s


_ANS = None  # dernier résultat numérique, utilisable via « ans »


def _evaluer_texte(texte, si="complet"):
    prep = _preparer(texte, si)
    try:
        arbre = ast.parse(prep, mode="eval")
    except SyntaxError:
        raise ErreurCalcul("Syntaxe invalide")
    env = {"ans": _ANS} if _ANS is not None else {}
    try:
        return _eval(arbre, env)
    except ZeroDivisionError:
        raise ErreurCalcul("Division par zéro")
    except OverflowError:
        raise ErreurCalcul("Résultat trop grand")
    except ValueError as e:
        raise ErreurCalcul("Hors du domaine de définition" if "domain" in str(e) else f"Calcul impossible ({e})")
    except TypeError as e:
        raise ErreurCalcul("Mauvais nombre d'arguments" if "argument" in str(e) else "Calcul impossible")


_NOMBRE_SI = re.compile(
    r"\s*([-+]?\d[\d\s.,]*(?:[eE][-+]?\d+)?)\s*([pnuµmkMGT]?)\s*[A-Za-zΩµ°%/²³€]{0,6}\s*")
_NOMBRE_LEGER = re.compile(
    r"\s*([-+]?\d[\d\s.,]*(?:[eE][-+]?\d+)?)\s*([kM]?)\s*[^\d\s]{0,6}\s*")


def _lire_nombre(texte, mode):
    """Champ de formule → nombre. Accepte « 4,7k », « 100 nF », « 250 000 », « 2*pi*50 »."""
    t = texte.strip()
    motif = _NOMBRE_SI if mode == "complet" else _NOMBRE_LEGER
    m = motif.fullmatch(t)
    if m:
        num = re.sub(r"\s", "", m.group(1)).replace(",", ".")
        try:
            val = float(num)
            fac = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "": 1,
                   "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}[m.group(2)]
            return val * fac
        except ValueError:
            pass
    v = _evaluer_texte(t, mode)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ErreurCalcul("Nombre attendu")
    return v


def _lire_liste(texte, mode):
    morceaux = [p for p in re.split(r"[\s;]+", texte.strip()) if p]
    if not morceaux:
        raise ErreurCalcul("Liste vide")
    return [_lire_nombre(p, mode) for p in morceaux]


# ======================================================================
# 4. Conversions d'unités
# ======================================================================

_CATEGORIES_UNITES = {
    "longueur": {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001, "µm": 1e-6, "um": 1e-6, "nm": 1e-9,
                 "in": 0.0254, "po": 0.0254, "pouce": 0.0254, "ft": 0.3048, "pied": 0.3048,
                 "yd": 0.9144, "mi": 1609.344, "mile": 1609.344, "nmi": 1852},
    "masse": {"kg": 1, "g": 1e-3, "mg": 1e-6, "t": 1000, "lb": 0.45359237, "oz": 0.028349523125},
    "surface": {"m2": 1, "m²": 1, "km2": 1e6, "km²": 1e6, "cm2": 1e-4, "cm²": 1e-4, "mm2": 1e-6, "mm²": 1e-6,
                "ha": 1e4, "are": 100, "ft2": 0.09290304, "ft²": 0.09290304, "acre": 4046.8564224},
    "volume": {"l": 1e-3, "L": 1e-3, "ml": 1e-6, "mL": 1e-6, "cl": 1e-5, "dl": 1e-4, "m3": 1, "m³": 1,
               "cm3": 1e-6, "cm³": 1e-6, "gal": 3.785411784e-3, "qt": 9.46352946e-4, "floz": 2.95735295625e-5},
    "vitesse": {"m/s": 1, "km/h": 1 / 3.6, "kmh": 1 / 3.6, "mph": 0.44704, "kt": 1852 / 3600, "nœud": 1852 / 3600},
    "énergie": {"J": 1, "kJ": 1e3, "MJ": 1e6, "Wh": 3600, "kWh": 3.6e6, "cal": 4.184, "kcal": 4184, "eV": 1.602176634e-19},
    "puissance": {"W": 1, "kW": 1e3, "MW": 1e6, "mW": 1e-3, "hp": 745.69987158, "ch": 735.49875},
    "pression": {"Pa": 1, "kPa": 1e3, "MPa": 1e6, "bar": 1e5, "mbar": 100, "hPa": 100, "atm": 101325,
                 "psi": 6894.757293168, "mmHg": 133.322387415, "torr": 133.322387415},
    "temps": {"s": 1, "ms": 1e-3, "µs": 1e-6, "us": 1e-6, "min": 60, "h": 3600, "j": 86400, "jour": 86400,
              "sem": 604800, "semaine": 604800, "an": 31557600, "ans": 31557600},
    "données": {"bit": 0.125, "o": 1, "B": 1, "Ko": 1e3, "KB": 1e3, "Mo": 1e6, "MB": 1e6, "Go": 1e9, "GB": 1e9,
                "To": 1e12, "TB": 1e12, "Kio": 1024, "KiB": 1024, "Mio": 1024 ** 2, "MiB": 1024 ** 2,
                "Gio": 1024 ** 3, "GiB": 1024 ** 3, "Tio": 1024 ** 4, "TiB": 1024 ** 4},
    "angle": {"deg": 1, "°": 1, "rad": 180 / math.pi, "tr": 360, "grad": 0.9},
    "fréquence": {"Hz": 1, "kHz": 1e3, "MHz": 1e6, "GHz": 1e9, "rpm": 1 / 60, "tr/min": 1 / 60},
}
_TEMPERATURES = {"°C", "degC", "°F", "degF", "K", "°c", "°f", "kelvin"}

_UNITES_EXACTES = {}
for _cat, _tab in _CATEGORIES_UNITES.items():
    for _u, _f in _tab.items():
        _UNITES_EXACTES[_u] = (_cat, _f)
_UNITES_MINUSCULES = {}
_vus = {}
for _u in _UNITES_EXACTES:
    _vus.setdefault(_u.lower(), []).append(_u)
for _bas, _liste in _vus.items():
    if len(_liste) == 1:
        _UNITES_MINUSCULES[_bas] = _liste[0]


def _trouver_unite(nom):
    if nom in _TEMPERATURES or nom.lower() in _TEMPERATURES:
        return ("température", nom)
    if nom in _UNITES_EXACTES:
        return _UNITES_EXACTES[nom]
    bas = nom.lower()
    if bas in _UNITES_MINUSCULES:
        return _UNITES_EXACTES[_UNITES_MINUSCULES[bas]]
    return None


def _vers_celsius(v, u):
    u = u.lower()
    if u in ("°c", "degc"):
        return v
    if u in ("°f", "degf"):
        return (v - 32) * 5 / 9
    return v - 273.15  # kelvin


def _depuis_celsius(v, u):
    u = u.lower()
    if u in ("°c", "degc"):
        return v
    if u in ("°f", "degf"):
        return v * 9 / 5 + 32
    return v + 273.15


_RE_CONVERSION = re.compile(
    r"\s*(?P<v>[-+]?\d[\d\s.,]*(?:[eE][-+]?\d+)?)\s*(?P<a>[^\d\s]\S*?)\s+(?:en|vers|to|in|->|→|=>)\s+(?P<b>\S+)\s*", re.I)


def _essai_conversion(texte):
    m = _RE_CONVERSION.fullmatch(texte)
    if not m:
        return None
    ua, ub = _trouver_unite(m.group("a")), _trouver_unite(m.group("b"))
    if ua is None or ub is None:
        return None
    try:
        v = float(re.sub(r"\s", "", m.group("v")).replace(",", "."))
    except ValueError:
        return None
    if ua[0] != ub[0]:
        raise ErreurCalcul(f"Unités incompatibles ({ua[0]} ≠ {ub[0]})")
    if ua[0] == "température":
        res = _depuis_celsius(_vers_celsius(v, m.group("a")), m.group("b"))
    else:
        res = v * ua[1] / ub[1]
    return v, m.group("a"), res, m.group("b")


# ======================================================================
# 5. Maths symboliques (SymPy), sans jamais passer par eval()
# ======================================================================

_COMMANDES = {
    "resoudre": "resoudre", "résoudre": "resoudre", "solve": "resoudre",
    "derive": "derive", "dérive": "derive", "derivee": "derive", "dérivée": "derive", "diff": "derive",
    "integrale": "integrale", "intégrale": "integrale", "primitive": "integrale",
    "simplifie": "simplifie", "simplifier": "simplifie",
    "factorise": "factorise", "factoriser": "factorise",
    "developpe": "developpe", "développe": "developpe", "développer": "developpe", "developper": "developpe",
    "limite": "limite",
}
_RE_COMMANDE = re.compile(r"\s*(" + "|".join(sorted(_COMMANDES, key=len, reverse=True)) + r")\s+(.+)", re.I | re.S)


def _sympy():
    try:
        import sympy
        return sympy
    except ImportError:
        raise ErreurCalcul("SymPy manquant : pip install sympy")


def _vers_sympy(texte, sp):
    prep = _preparer(texte, "aucun")
    try:
        arbre = ast.parse(prep, mode="eval")
    except SyntaxError:
        raise ErreurCalcul("Syntaxe invalide")
    fonctions = {
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
        "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh, "exp": sp.exp, "sqrt": sp.sqrt, "abs": sp.Abs,
        "ln": sp.log, "log": lambda x: sp.log(x, 10), "log10": lambda x: sp.log(x, 10),
        "log2": lambda x: sp.log(x, 2), "cbrt": sp.cbrt,
    }

    def conv(n):
        t = type(n)
        if t is ast.Expression:
            return conv(n.body)
        if t is ast.Constant and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return sp.Rational(str(n.value))
        if t is ast.Name:
            if n.id == "pi":
                return sp.pi
            if n.id == "e":
                return sp.E
            if n.id in ("oo", "inf", "infini"):
                return sp.oo
            if len(n.id) > 12 or n.id.startswith("_"):
                raise ErreurCalcul(f"Nom non autorisé : {n.id}")
            return sp.Symbol(n.id)
        if t is ast.BinOp:
            a, b = conv(n.left), conv(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Div):
                return a / b
            if isinstance(n.op, ast.Pow):
                return a ** b
            raise ErreurCalcul("Opérateur non autorisé")
        if t is ast.UnaryOp:
            v = conv(n.operand)
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return v
            raise ErreurCalcul("Opérateur non autorisé")
        if t is ast.Call and isinstance(n.func, ast.Name) and not n.keywords:
            args = [conv(a) for a in n.args]
            if n.func.id in fonctions:
                return fonctions[n.func.id](*args)
            if len(args) == 1 and len(n.func.id) <= 2:       # x(x+1) = x·(x+1)
                return sp.Symbol(n.func.id) * args[0]
            raise ErreurCalcul(f"Fonction inconnue : {n.func.id}")
        raise ErreurCalcul("Expression non autorisée")

    return conv(arbre)


def _txt_sympy(expr, sp):
    return sp.sstr(expr).replace("**", "^").replace("*", "·")


def _approx(expr, sp):
    """« ≈ 1,41421 » si le résultat exact est irrationnel."""
    try:
        if expr.free_symbols or expr.is_Integer or expr.is_Rational:
            return ""
        v = complex(sp.N(expr, 12))
        if abs(v.imag) > 1e-12:
            return ""
        return f" ≈ {_fmt(v.real)}"
    except Exception:
        return ""


def _choisir_variable(expr, voulue, sp):
    if voulue:
        return sp.Symbol(voulue)
    libres = sorted(expr.free_symbols, key=str)
    for s in libres:
        if str(s) == "x":
            return s
    if libres:
        return libres[0]
    return sp.Symbol("x")


def _commande_sympy(cmd, reste):
    sp = _sympy()
    reste = reste.strip()
    lignes = []

    pour = re.search(r"\s+(?:pour|par rapport à|par rapport a|selon)\s+([A-Za-z]\w*)\s*$", reste, re.I)
    variable = None
    if pour and cmd in ("resoudre", "derive", "integrale"):
        variable = pour.group(1)
        reste = reste[:pour.start()]

    if cmd == "resoudre":
        eqs_txt = [p for p in re.split(r"[;\n]|\bet\b", reste) if p.strip()]
        eqs = []
        for e in eqs_txt:
            if "=" in e:
                g, d = e.split("=", 1)
                eqs.append(_vers_sympy(g, sp) - _vers_sympy(d, sp))
            else:
                eqs.append(_vers_sympy(e, sp))
        if len(eqs) == 1:
            expr = eqs[0]
            x = _choisir_variable(expr, variable, sp)
            sol = sp.solveset(expr, x, domain=sp.S.Reals)
            if isinstance(sol, sp.FiniteSet):
                if len(sol) == 0:
                    lignes.append({"label": f"{x} =", "valeur": "aucune solution réelle"})
                for s in sorted(sol, key=lambda v: float(sp.N(v)) if v.is_real else 0):
                    lignes.append({"label": f"{x} =", "valeur": _txt_sympy(s, sp) + _approx(s, sp)})
            elif sol == sp.S.EmptySet:
                lignes.append({"label": f"{x} =", "valeur": "aucune solution réelle"})
            else:
                lignes.append({"label": f"{x} =", "valeur": _txt_sympy(sol, sp)})
        else:
            symboles = sorted(set().union(*[e.free_symbols for e in eqs]), key=str)
            sols = sp.solve(eqs, symboles, dict=True)
            if not sols:
                lignes.append({"label": "", "valeur": "aucune solution"})
            for s in sols:
                for k in symboles:
                    if k in s:
                        lignes.append({"label": f"{k} =", "valeur": _txt_sympy(s[k], sp) + _approx(s[k], sp)})
    elif cmd == "derive":
        expr = _vers_sympy(reste, sp)
        x = _choisir_variable(expr, variable, sp)
        r = sp.diff(expr, x)
        lignes.append({"label": f"d/d{x} =", "valeur": _txt_sympy(r, sp)})
    elif cmd == "integrale":
        bornes = re.search(r"\s+de\s+(.+?)\s+(?:à|a|jusqu'à|jusqu'a)\s+(.+)$", reste, re.I)
        if bornes:
            reste = reste[:bornes.start()]
        expr = _vers_sympy(reste, sp)
        x = _choisir_variable(expr, variable, sp)
        if bornes:
            a, b = _vers_sympy(bornes.group(1), sp), _vers_sympy(bornes.group(2), sp)
            r = sp.integrate(expr, (x, a, b))
            lignes.append({"label": "∫ =", "valeur": _txt_sympy(r, sp) + _approx(r, sp)})
        else:
            r = sp.integrate(expr, x)
            lignes.append({"label": "∫ =", "valeur": _txt_sympy(r, sp) + " + C"})
    elif cmd == "limite":
        m = re.match(r"(.+?)\s+(?:en|quand\s+\w+\s*(?:->|→|tend vers))\s*(.+)$", reste, re.I)
        if not m:
            raise ErreurCalcul("Format : limite f(x) en a")
        expr = _vers_sympy(m.group(1), sp)
        x = _choisir_variable(expr, None, sp)
        r = sp.limit(expr, x, _vers_sympy(m.group(2), sp))
        lignes.append({"label": "lim =", "valeur": _txt_sympy(r, sp) + _approx(r, sp)})
    else:
        expr = _vers_sympy(reste, sp)
        f = {"simplifie": sp.simplify, "factorise": sp.factor, "developpe": sp.expand}[cmd]
        lignes.append({"label": "", "valeur": _txt_sympy(f(expr), sp)})
    return lignes


def _commande_avec_delai(cmd, reste):
    with ThreadPoolExecutor(max_workers=1) as ex:
        futur = ex.submit(_commande_sympy, cmd, reste)
        try:
            return futur.result(timeout=20)
        except DelaiDepasse:
            raise ErreurCalcul("Calcul trop long (plus de 20 s)")


# ======================================================================
# 6. Bibliothèque de formules
#    Pour en ajouter une : copier un bloc de FORMULES, c'est tout.
#    E(...) = un champ de saisie, S(...) = une ligne de résultat.
# ======================================================================

def E(k, l, u="", d="", opt=False, t="nombre"):
    return {"k": k, "l": l, "u": u, "d": d, "opt": opt, "t": t}


def S(l, e, u="", f=""):
    return {"l": l, "e": e, "u": u, "f": f}


def F(id, cat, nom, entrees, sorties, mode="leger", mots="", note="", inter=None, choix=None, special=None):
    return {"id": id, "cat": cat, "nom": nom, "entrees": entrees, "sorties": sorties, "mode": mode,
            "mots": mots, "note": note, "inter": inter or [], "choix": choix, "special": special}


ELEC, IMMO, TNS_, MATH, FIN = "Électronique", "Immobilier", "TNS / Freelance", "Maths", "Finance"
_ACTIVITES_MICRO = [
    {"nom": "Vente de marchandises (BIC)", "set": {"taux": "12.3", "cfp": "0.1", "vl": "1", "abatt": "71"}},
    {"nom": "Services BIC / artisan", "set": {"taux": "21.2", "cfp": "0.3", "vl": "1.7", "abatt": "50"}},
    {"nom": "Libéral BNC (SSI)", "set": {"taux": "25.6", "cfp": "0.2", "vl": "2.2", "abatt": "34"}},
    {"nom": "Libéral réglementé (CIPAV)", "set": {"taux": "23.2", "cfp": "0.2", "vl": "2.2", "abatt": "34"}},
]

FORMULES = [
    # ---------------------------------------------------------- Électronique
    F("ohm", ELEC, "Loi d'Ohm et puissance",
      [E("U", "Tension", "V", opt=True), E("I", "Courant", "A", opt=True),
       E("R", "Résistance", "Ω", opt=True), E("P", "Puissance", "W", opt=True)],
      [], mode="si", special="ohm", mots="ohm tension courant resistance puissance watt",
      note="Renseigne deux grandeurs, les deux autres sont calculées."),
    F("diviseur", ELEC, "Diviseur de tension",
      [E("Vin", "Tension d'entrée", "V", "5"), E("R1", "R1 (haut)", "Ω", "10k"), E("R2", "R2 (bas)", "Ω", "10k")],
      [S("Vout", "Vin*R2/(R1+R2)", "V", "Vout = Vin·R2 / (R1+R2)"),
       S("Courant", "Vin/(R1+R2)", "A", "I = Vin / (R1+R2)"),
       S("Impédance de sortie", "par(R1,R2)", "Ω", "Zs = R1 ∥ R2")],
      mode="si", mots="pont diviseur resistances tension", note="Sans charge en sortie."),
    F("diviseur_r1", ELEC, "Diviseur : R1 pour une tension cible",
      [E("Vin", "Tension d'entrée", "V", "5"), E("Vout", "Tension de sortie voulue", "V", "3.3"),
       E("R2", "R2 (bas)", "Ω", "10k")],
      [S("R1", "R2*(Vin-Vout)/Vout", "Ω", "R1 = R2·(Vin−Vout)/Vout"),
       S("R1 normalisée E24", "e24(R2*(Vin-Vout)/Vout)", "Ω")],
      mode="si", mots="diviseur resistance cible adaptation niveau"),
    F("led", ELEC, "Résistance de LED",
      [E("Vs", "Tension d'alimentation", "V", "5"), E("Vf", "Tension directe LED", "V", "2"),
       E("If", "Courant voulu", "A", "20m")],
      [S("R", "(Vs-Vf)/If", "Ω", "R = (Vs−Vf)/If"),
       S("R normalisée E24 (≥)", "e24sup((Vs-Vf)/If)", "Ω"),
       S("Courant réel", "(Vs-Vf)/e24sup((Vs-Vf)/If)", "A"),
       S("Puissance dans R", "(Vs-Vf)**2/e24sup((Vs-Vf)/If)", "W", "P = (Vs−Vf)² / R")],
      mode="si", mots="led diode resistance limitation courant"),
    F("rc", ELEC, "Filtre RC (fréquence de coupure)",
      [E("R", "Résistance", "Ω", "10k"), E("C", "Capacité", "F", "100n")],
      [S("fc", "1/(2*pi*R*C)", "Hz", "fc = 1 / (2π·R·C)"), S("τ", "R*C", "s", "τ = R·C"),
       S("Charge à 99 % (5τ)", "5*R*C", "s")],
      mode="si", mots="filtre passe-bas passe-haut coupure tau constante de temps"),
    F("rc_r", ELEC, "Filtre RC : R pour une fc cible",
      [E("fc", "Fréquence de coupure", "Hz", "1k"), E("C", "Capacité", "F", "100n")],
      [S("R", "1/(2*pi*fc*C)", "Ω", "R = 1 / (2π·fc·C)"), S("R normalisée E24", "e24(1/(2*pi*fc*C))", "Ω")],
      mode="si", mots="filtre rc resistance cible coupure"),
    F("lc", ELEC, "Circuit LC (résonance)",
      [E("L", "Inductance", "H", "10m"), E("C", "Capacité", "F", "100n")],
      [S("f₀", "1/(2*pi*sqrt(L*C))", "Hz", "f₀ = 1 / (2π√(LC))"), S("Z₀", "sqrt(L/C)", "Ω", "Z₀ = √(L/C)")],
      mode="si", mots="resonance lc bobine condensateur"),
    F("react", ELEC, "Réactances (condensateur, bobine)",
      [E("f", "Fréquence", "Hz", "1k"), E("C", "Capacité", "F", "100n", opt=True),
       E("L", "Inductance", "H", "10m", opt=True)],
      [S("Xc", "1/(2*pi*f*C)", "Ω", "Xc = 1 / (2π·f·C)"), S("Xl", "2*pi*f*L", "Ω", "Xl = 2π·f·L")],
      mode="si", mots="reactance impedance condensateur bobine"),
    F("res_sp", ELEC, "Résistances série / parallèle",
      [E("R", "Valeurs (séparées par un espace)", "Ω", "100 220 330", t="liste")],
      [S("Série", "ser(R)", "Ω", "Rs = R1+R2+…"), S("Parallèle", "par(R)", "Ω", "1/Rp = 1/R1+1/R2+…")],
      mode="si", mots="resistances serie parallele equivalente association"),
    F("cap_sp", ELEC, "Condensateurs série / parallèle",
      [E("C", "Valeurs (séparées par un espace)", "F", "100n 220n", t="liste")],
      [S("Parallèle", "ser(C)", "F", "Cp = C1+C2+…"), S("Série", "par(C)", "F", "1/Cs = 1/C1+1/C2+…")],
      mode="si", mots="condensateurs capacites serie parallele equivalente"),
    F("lissage", ELEC, "Condensateur de lissage (redresseur)",
      [E("I", "Courant de charge", "A", "500m"), E("f", "Fréquence réseau", "Hz", "50"),
       E("dV", "Ondulation admise", "V", "1")],
      [S("C (double alternance)", "I/(2*f*dV)", "F", "C = I / (2·f·ΔV)"),
       S("C normalisée E12 (≥)", "e12sup(I/(2*f*dV))", "F"),
       S("C (simple alternance)", "I/(f*dV)", "F", "C = I / (f·ΔV)")],
      mode="si", mots="lissage filtrage redresseur condensateur ondulation alimentation"),
    F("lineaire", ELEC, "Régulateur linéaire (dissipation)",
      [E("Vin", "Tension d'entrée", "V", "12"), E("Vout", "Tension de sortie", "V", "5"),
       E("I", "Courant", "A", "500m")],
      [S("Puissance dissipée", "(Vin-Vout)*I", "W", "P = (Vin−Vout)·I"),
       S("Rendement", "Vout/Vin*100", "%", "η = Vout / Vin")],
      mode="si", mots="regulateur lineaire ldo 7805 dissipation chaleur rendement"),
    F("buck", ELEC, "Convertisseur Buck (abaisseur)",
      [E("Vin", "Tension d'entrée", "V", "12"), E("Vout", "Tension de sortie", "V", "5"),
       E("Iout", "Courant de sortie", "A", "1"), E("fsw", "Fréquence de découpage", "Hz", "500k"),
       E("r", "Ondulation de courant (ratio de Iout)", "", "0.3"), E("dV", "Ondulation de tension", "V", "50m")],
      [S("Rapport cyclique", "Vout/Vin*100", "%", "D = Vout / Vin"),
       S("ΔIL", "r*Iout", "A", "ΔIL = r·Iout"),
       S("L", "Vout*(1-Vout/Vin)/(fsw*r*Iout)", "H", "L = Vout·(1−D) / (fsw·ΔIL)"),
       S("L normalisée E12 (≥)", "e12sup(Vout*(1-Vout/Vin)/(fsw*r*Iout))", "H"),
       S("Cout", "r*Iout/(8*fsw*dV)", "F", "Cout = ΔIL / (8·fsw·ΔV)"),
       S("Courant crête bobine", "Iout*(1+r/2)", "A", "Ipk = Iout + ΔIL/2")],
      mode="si", mots="buck abaisseur dc-dc convertisseur alimentation decoupage bobine",
      note="Mode continu, composants idéaux. Prévoir une marge sur L (saturation) et Cout (ESR)."),
    F("boost", ELEC, "Convertisseur Boost (élévateur)",
      [E("Vin", "Tension d'entrée", "V", "5"), E("Vout", "Tension de sortie", "V", "12"),
       E("Iout", "Courant de sortie", "A", "500m"), E("fsw", "Fréquence de découpage", "Hz", "500k"),
       E("r", "Ondulation de courant (ratio de Iin)", "", "0.3"), E("dV", "Ondulation de tension", "V", "100m")],
      [S("Rapport cyclique", "(1-Vin/Vout)*100", "%", "D = 1 − Vin/Vout"),
       S("Courant d'entrée", "Iout*Vout/Vin", "A", "Iin = Iout·Vout/Vin"),
       S("L", "Vin*(1-Vin/Vout)/(fsw*r*Iout*Vout/Vin)", "H", "L = Vin·D / (fsw·ΔIL)"),
       S("L normalisée E12 (≥)", "e12sup(Vin*(1-Vin/Vout)/(fsw*r*Iout*Vout/Vin))", "H"),
       S("Cout", "Iout*(1-Vin/Vout)/(fsw*dV)", "F", "Cout = Iout·D / (fsw·ΔV)"),
       S("Courant crête bobine", "Iout*Vout/Vin*(1+r/2)", "A", "Ipk = Iin + ΔIL/2")],
      mode="si", mots="boost elevateur dc-dc convertisseur alimentation decoupage bobine",
      note="Mode continu, rendement 100 %. Le courant d'entrée réel sera plus élevé."),
    F("bjt", ELEC, "Transistor bipolaire en commutation",
      [E("Vin", "Tension de commande", "V", "5"), E("Vbe", "Vbe", "V", "0.7"),
       E("Ic", "Courant collecteur", "A", "20m"), E("hfe", "hFE forcé (saturation)", "", "10")],
      [S("Ib", "Ic/hfe", "A", "Ib = Ic / hFE forcé"), S("Rb", "(Vin-Vbe)*hfe/Ic", "Ω", "Rb = (Vin−Vbe) / Ib"),
       S("Rb normalisée E24 (≤)", "e24inf((Vin-Vbe)*hfe/Ic)", "Ω")],
      mode="si", mots="transistor bipolaire npn pnp base commutation saturation"),
    F("adc", ELEC, "Convertisseur analogique-numérique",
      [E("Vref", "Tension de référence", "V", "3.3"), E("n", "Résolution", "bits", "12"),
       E("N", "Code lu", "", "2048", opt=True), E("V", "Tension mesurée", "V", "", opt=True)],
      [S("LSB", "Vref/2**n", "V", "LSB = Vref / 2ⁿ"), S("Codes", "2**n", "", "2ⁿ"),
       S("Tension du code", "N*Vref/2**n", "V", "V = N·Vref / 2ⁿ"),
       S("Code de la tension", "round(V/(Vref/2**n))", "", "N = V / LSB")],
      mode="si", mots="adc cna convertisseur resolution quantum lsb microcontroleur"),
    F("timer", ELEC, "Timer MCU : fréquence et rapport cyclique",
      [E("fclk", "Horloge du timer", "Hz", "72M"), E("PSC", "Prescaler (PSC)", "", "71"),
       E("ARR", "Auto-reload (ARR)", "", "999"), E("CCR", "Comparaison (CCR)", "", "250", opt=True)],
      [S("Fréquence compteur", "fclk/(PSC+1)", "Hz", "fcnt = fclk / (PSC+1)"),
       S("Fréquence de sortie", "fclk/((PSC+1)*(ARR+1))", "Hz", "f = fclk / ((PSC+1)·(ARR+1))"),
       S("Période", "(PSC+1)*(ARR+1)/fclk", "s"),
       S("Rapport cyclique", "CCR/(ARR+1)*100", "%", "D = CCR / (ARR+1)")],
      mode="si", mots="timer pwm stm32 prescaler arr ccr microcontroleur frequence",
      note="PWM mode 1 (STM32). PSC et ARR sont généralement sur 16 bits (0 à 65535)."),
    F("timer_cible", ELEC, "Timer MCU : PSC / ARR pour une fréquence cible",
      [E("fclk", "Horloge du timer", "Hz", "72M"), E("ft", "Fréquence cible", "Hz", "1k")],
      [], mode="si", special="timer_cible", mots="timer pwm stm32 prescaler arr cible frequence",
      note="Cherche l'erreur la plus faible, puis la meilleure résolution (ARR le plus grand). Timers 16 bits."),
    F("i2c", ELEC, "Résistances de tirage I²C",
      [E("Vdd", "Tension d'alimentation", "V", "3.3"), E("Cb", "Capacité du bus", "F", "100p"),
       E("tr", "Temps de montée max", "s", "300n"), E("IOL", "Courant de sortie bas", "A", "3m"),
       E("VOL", "Tension de sortie basse", "V", "0.4")],
      [S("Rp min", "(Vdd-VOL)/IOL", "Ω", "Rmin = (Vdd−VOL) / IOL"),
       S("Rp max", "tr/(0.8473*Cb)", "Ω", "Rmax = tr / (0,8473·Cb)"),
       S("Rp min normalisée E24 (≥)", "e24sup((Vdd-VOL)/IOL)", "Ω")],
      mode="si", mots="i2c pull-up tirage resistance bus",
      note="Mode standard 1 µs, rapide 300 ns, rapide+ 120 ns (temps de montée max)."),
    F("cable", ELEC, "Chute de tension dans un câble",
      [E("L", "Longueur (aller simple)", "m", "20"), E("I", "Courant", "A", "16"),
       E("S", "Section", "mm²", "2.5"), E("U", "Tension nominale", "V", "230"),
       E("rho", "Résistivité (cuivre à chaud)", "Ω·mm²/m", "0.0225"),
       E("b", "Facteur (2 monophasé, 1,732 triphasé)", "", "2"), E("max", "Chute max admise", "%", "3")],
      [S("Chute de tension", "b*rho*L*I/S", "V", "ΔU = b·ρ·L·I / S"),
       S("Chute relative", "b*rho*L*I/S/U*100", "%", "ΔU / U"),
       S("Résistance d'un conducteur", "rho*L/S", "Ω", "R = ρ·L / S"),
       S("Section mini", "b*rho*L*I/(U*max/100)", "mm²", "S = b·ρ·L·I / (U·ΔU%)"),
       S("Section normalisée", "section_sup(b*rho*L*I/(U*max/100))", "mm²")],
      mode="si", mots="cable section chute de tension cuivre longueur",
      note="Critère de chute de tension uniquement : vérifier aussi le courant admissible.",
      choix={"l": "Réseau", "o": [{"nom": "Monophasé", "set": {"b": "2"}}, {"nom": "Triphasé", "set": {"b": "1.732"}}]}),
    F("puiss_ac", ELEC, "Puissance en alternatif",
      [E("U", "Tension (entre phases si triphasé)", "V", "230"), E("I", "Courant", "A", "10"),
       E("cphi", "cos φ", "", "0.9"), E("k", "Facteur (1 mono, 1,732 tri)", "", "1")],
      [S("P active", "k*U*I*cphi", "W", "P = k·U·I·cos φ"), S("S apparente", "k*U*I", "VA", "S = k·U·I"),
       S("Q réactive", "k*U*I*sqrt(1-cphi**2)", "var", "Q = k·U·I·sin φ")],
      mode="si", mots="puissance active apparente reactive cos phi triphase monophase",
      choix={"l": "Réseau", "o": [{"nom": "Monophasé", "set": {"k": "1"}}, {"nom": "Triphasé", "set": {"k": "1.732"}}]}),
    F("vsi", ELEC, "Onduleur triphasé (tensions de sortie)",
      [E("Vdc", "Tension du bus DC", "V", "400"), E("m", "Indice de modulation", "", "0.9"),
       E("kmod", "Facteur (1 SPWM, 1,1547 SVPWM)", "", "1")],
      [S("Tension simple crête", "kmod*m*Vdc/2", "V", "Vph,pk = k·m·Vdc / 2"),
       S("Tension simple efficace", "kmod*m*Vdc/(2*sqrt(2))", "V", "Vph,rms = Vph,pk / √2"),
       S("Tension composée efficace", "sqrt(3)*kmod*m*Vdc/(2*sqrt(2))", "V", "VLL,rms = √3·Vph,rms")],
      mode="si", mots="onduleur vsi triphase spwm svpwm modulation tension bus",
      note="Zone linéaire (m ≤ 1). Valable pour les composantes fondamentales.",
      choix={"l": "Modulation", "o": [{"nom": "SPWM", "set": {"kmod": "1"}}, {"nom": "SVPWM", "set": {"kmod": "1.1547"}}]}),
    F("thermique", ELEC, "Thermique d'un composant",
      [E("P", "Puissance dissipée", "W", "2"), E("Rth", "Résistance thermique", "°C/W", "50"),
       E("Ta", "Température ambiante", "°C", "25"), E("Tjmax", "Tj max", "°C", "125", opt=True)],
      [S("Tj", "Ta+P*Rth", "°C", "Tj = Ta + P·Rθ"),
       S("Rθ max admissible", "(Tjmax-Ta)/P", "°C/W", "Rθ = (Tjmax−Ta) / P"),
       S("P max admissible", "(Tjmax-Ta)/Rth", "W", "P = (Tjmax−Ta) / Rθ")],
      mots="thermique temperature jonction dissipateur rth"),
    F("batterie", ELEC, "Autonomie d'une batterie",
      [E("cap", "Capacité", "mAh", "2000"), E("I", "Consommation", "mA", "150"), E("eff", "Rendement utile", "", "0.85")],
      [S("Autonomie", "cap*eff/I", "h", "t = C·η / I"), S("Autonomie", "cap*eff/I/24", "j")],
      mots="batterie autonomie capacite mah consommation"),
    F("decibel", ELEC, "Décibels",
      [E("Vout", "Tension de sortie", "V", "2", opt=True), E("Vin", "Tension d'entrée", "V", "1", opt=True),
       E("Pout", "Puissance de sortie", "W", "", opt=True), E("Pin", "Puissance d'entrée", "W", "", opt=True),
       E("G", "Gain en dB", "dB", "", opt=True)],
      [S("Gain en tension", "20*log10(Vout/Vin)", "dB", "G = 20·log₁₀(Vout/Vin)"),
       S("Gain en puissance", "10*log10(Pout/Pin)", "dB", "G = 10·log₁₀(Pout/Pin)"),
       S("Rapport de tension", "10**(G/20)", "", "Vout/Vin = 10^(G/20)"),
       S("Rapport de puissance", "10**(G/10)", "", "Pout/Pin = 10^(G/10)")],
      mots="decibel db gain atténuation rapport"),
    F("moteur", ELEC, "Moteur : couple, vitesse, puissance",
      [E("N", "Vitesse", "tr/min", "3000"), E("C", "Couple", "N·m", "1.2", opt=True),
       E("P", "Puissance mécanique", "W", "", opt=True)],
      [S("Vitesse angulaire", "2*pi*N/60", "rad/s", "ω = 2π·N / 60"),
       S("Puissance", "C*2*pi*N/60", "W", "P = C·ω"), S("Couple", "P/(2*pi*N/60)", "N·m", "C = P / ω")],
      mots="moteur couple vitesse puissance mecanique rpm"),
    F("shunt", ELEC, "Résistance de shunt (mesure de courant)",
      [E("Imax", "Courant max", "A", "10"), E("Vs", "Tension de mesure max", "V", "100m")],
      [S("R shunt", "Vs/Imax", "Ω", "R = Vs / Imax"), S("Puissance dissipée", "Vs*Imax", "W", "P = Vs·Imax")],
      mode="si", mots="shunt mesure courant resistance capteur"),
    F("ampliop", ELEC, "Amplificateur opérationnel",
      [E("Rf", "Rf (réaction)", "Ω", "100k"), E("Rin", "Rin (entrée)", "Ω", "10k")],
      [S("Gain inverseur", "-Rf/Rin", "", "G = −Rf / Rin"), S("Gain non inverseur", "1+Rf/Rin", "", "G = 1 + Rf / Rin")],
      mode="si", mots="ampli op amplificateur operationnel gain inverseur non inverseur"),
    F("ne555", ELEC, "NE555 astable",
      [E("R1", "R1", "Ω", "1k"), E("R2", "R2", "Ω", "10k"), E("C", "C", "F", "100n")],
      [S("Fréquence", "1.44/((R1+2*R2)*C)", "Hz", "f = 1,44 / ((R1+2·R2)·C)"),
       S("Rapport cyclique", "(R1+R2)/(R1+2*R2)*100", "%", "D = (R1+R2) / (R1+2·R2)"),
       S("Temps haut", "0.693*(R1+R2)*C", "s"), S("Temps bas", "0.693*R2*C", "s")],
      mode="si", mots="555 ne555 astable oscillateur timer"),
    F("rc_charge", ELEC, "Charge d'un condensateur",
      [E("V", "Tension source", "V", "5"), E("R", "Résistance", "Ω", "10k"), E("C", "Capacité", "F", "100n"),
       E("t", "Instant", "s", "1m")],
      [S("Vc(t)", "V*(1-exp(-t/(R*C)))", "V", "Vc = V·(1 − e^(−t/RC))"), S("τ", "R*C", "s", "τ = R·C")],
      mode="si", mots="charge condensateur rc tension temps exponentielle"),
    # ---------------------------------------------------------- Immobilier
    F("surface", IMMO, "Surface d'une pièce",
      [E("L", "Longueur", "m", "5"), E("l", "Largeur", "m", "4")],
      [S("Surface", "L*l", "m²", "S = L·l"), S("Périmètre", "2*(L+l)", "m", "P = 2·(L+l)")],
      mots="surface piece m2 metre carre superficie"),
    F("peinture", IMMO, "Peinture d'une pièce",
      [E("L", "Longueur", "m", "5"), E("l", "Largeur", "m", "4"), E("h", "Hauteur", "m", "2.5"),
       E("ouv", "Ouvertures (portes, fenêtres)", "m²", "4"), E("couches", "Couches", "", "2"),
       E("rend", "Rendement de la peinture", "m²/L", "10")],
      [S("Surface des murs", "2*(L+l)*h-ouv", "m²", "S = 2·(L+l)·h − ouvertures"),
       S("Surface du plafond", "L*l", "m²"),
       S("Peinture murs", "(2*(L+l)*h-ouv)*couches/rend", "L", "V = S·couches / rendement"),
       S("Peinture plafond", "L*l*couches/rend", "L")],
      mots="peinture murs plafond litres surface"),
    F("prix_m2", IMMO, "Prix au m²",
      [E("prix", "Prix", "€", "250000", opt=True), E("surf", "Surface", "m²", "65", opt=True),
       E("pm2", "Prix au m²", "€/m²", "", opt=True)],
      [S("Prix au m²", "prix/surf", "€", "prix / surface"), S("Prix total", "pm2*surf", "€", "prix/m² · surface"),
       S("Surface", "prix/pm2", "m²", "prix / prix au m²")],
      mots="prix metre carre m2 achat vente immobilier"),
    F("credit", IMMO, "Crédit immobilier (mensualité)",
      [E("cap", "Capital emprunté", "€", "200000"), E("taux", "Taux annuel (hors assurance)", "%", "3.8"),
       E("ans", "Durée", "ans", "20"), E("ass", "Assurance (par an, sur capital initial)", "%", "0.34")],
      [S("Mensualité hors assurance", "cap*(taux/1200)/(1-(1+taux/1200)**-(ans*12)) if taux > 0 else cap/(ans*12)", "€",
         "M = C·t / (1 − (1+t)⁻ⁿ), t = taux/12"),
       S("Assurance mensuelle", "cap*ass/100/12", "€"),
       S("Mensualité totale", "(cap*(taux/1200)/(1-(1+taux/1200)**-(ans*12)) if taux > 0 else cap/(ans*12))+cap*ass/1200", "€"),
       S("Intérêts totaux", "(cap*(taux/1200)/(1-(1+taux/1200)**-(ans*12)) if taux > 0 else cap/(ans*12))*ans*12-cap", "€"),
       S("Coût total du crédit", "(cap*(taux/1200)/(1-(1+taux/1200)**-(ans*12)) if taux > 0 else cap/(ans*12))*ans*12-cap+cap*ass/1200*ans*12", "€",
         "intérêts + assurance")],
      mots="credit pret immobilier mensualite taux assurance emprunt"),
    F("capacite", IMMO, "Capacité d'emprunt",
      [E("rev", "Revenus nets mensuels", "€", "3500"), E("charges", "Crédits en cours (mensuel)", "€", "0"),
       E("endet", "Taux d'endettement max", "%", "35"), E("taux", "Taux annuel", "%", "3.8"),
       E("ans", "Durée", "ans", "20"), E("ass", "Assurance (par an)", "%", "0.34")],
      [S("Mensualité max", "rev*endet/100-charges", "€", "M = revenus·endettement − crédits"),
       S("Capital empruntable",
         "(rev*endet/100-charges)/((((taux/1200)/(1-(1+taux/1200)**-(ans*12))) if taux > 0 else 1/(ans*12))+ass/1200)", "€",
         "C = M / (facteur mensuel + assurance)")],
      mots="capacite emprunt endettement budget revenus pret"),
    F("notaire", IMMO, "Frais de notaire",
      [E("prix", "Prix du bien", "€", "250000"), E("taux", "Taux de frais", "%", "7.5")],
      [S("Frais", "prix*taux/100", "€", "prix · taux"), S("Total à financer", "prix*(1+taux/100)", "€")],
      mots="notaire frais acquisition achat", note="Estimation : le taux réel dépend du département et du bien.",
      choix={"l": "Bien", "o": [{"nom": "Ancien (≈ 7,5 %)", "set": {"taux": "7.5"}},
                                {"nom": "Neuf (≈ 2,5 %)", "set": {"taux": "2.5"}}]}),
    F("rendement", IMMO, "Rendement locatif",
      [E("prix", "Prix d'achat", "€", "150000"), E("loyer", "Loyer mensuel", "€", "700"),
       E("charges", "Charges annuelles non récupérables", "€", "1200"), E("notaire", "Frais de notaire", "%", "7.5")],
      [S("Rendement brut", "loyer*12/prix*100", "%", "loyers annuels / prix"),
       S("Rendement net", "(loyer*12-charges)/(prix*(1+notaire/100))*100", "%",
         "(loyers − charges) / (prix + notaire)")],
      mots="rendement locatif investissement loyer rentabilite"),
    # ---------------------------------------------------------- TNS / Freelance
    F("micro", TNS_, "Micro-entrepreneur : cotisations et net",
      [E("ca", "Chiffre d'affaires annuel encaissé", "€", "40000"),
       E("taux", "Cotisations sociales", "%", "25.6"), E("cfp", "Formation professionnelle", "%", "0.2"),
       E("vl", "Versement libératoire", "%", "2.2"), E("vl_on", "Versement libératoire activé", "", "0", t="bool"),
       E("abatt", "Abattement fiscal", "%", "34")],
      [S("Cotisations sociales", "ca*taux/100", "€", "CA · taux"),
       S("Formation professionnelle", "ca*cfp/100", "€"),
       S("Versement libératoire", "ca*vl/100*vl_on", "€"),
       S("Net avant impôt", "ca-ca*(taux+cfp)/100", "€", "CA − cotisations − CFP"),
       S("Net après prélèvements", "ca-ca*(taux+cfp)/100-ca*vl/100*vl_on", "€"),
       S("Net mensuel", "(ca-ca*(taux+cfp)/100-ca*vl/100*vl_on)/12", "€"),
       S("Base imposable (abattement)", "ca*(1-abatt/100) if vl_on == 0 else 0", "€")],
      mots="micro entrepreneur auto-entrepreneur cotisations urssaf net freelance bnc bic",
      note="Taux 2026 pré-remplis : vérifie-les sur urssaf.fr, ils sont modifiables. ACRE non pris en compte.",
      choix={"l": "Activité", "o": _ACTIVITES_MICRO}),
    F("tns", TNS_, "TNS au réel (estimation)",
      [E("benef", "Bénéfice avant cotisations", "€", "50000"), E("taux", "Cotisations (% du revenu net)", "%", "45")],
      [S("Revenu net", "benef/(1+taux/100)", "€", "net = bénéfice / (1 + taux)"),
       S("Cotisations", "benef-benef/(1+taux/100)", "€"), S("Net mensuel", "benef/(1+taux/100)/12", "€")],
      mots="tns travailleur non salarie reel cotisations ssi net",
      note="Ordre de grandeur : les cotisations TNS tournent autour de 40 à 45 % du revenu net. Modifie le taux."),
    F("tjm", TNS_, "TJM et chiffre d'affaires",
      [E("tjm", "TJM", "€", "400"), E("jours", "Jours facturés par an", "", "200")],
      [S("CA annuel", "tjm*jours", "€"), S("CA mensuel moyen", "tjm*jours/12", "€")],
      mots="tjm taux journalier freelance chiffre affaires jours"),
    # ---------------------------------------------------------- Finance
    F("pourcent", FIN, "Pourcentages et variations",
      [E("v0", "Valeur de départ", "", "200", opt=True), E("v1", "Valeur d'arrivée", "", "250", opt=True),
       E("pct", "Pourcentage", "%", "", opt=True)],
      [S("Évolution", "(v1-v0)/v0*100", "%", "(v1 − v0) / v0"), S("Après hausse", "v0*(1+pct/100)", "", "v0·(1 + p)"),
       S("Après baisse", "v0*(1-pct/100)", "", "v0·(1 − p)"), S("Part", "v0*pct/100", "", "v0 · p")],
      mots="pourcentage pourcent variation evolution hausse baisse remise"),
    F("tva", FIN, "TVA (HT ↔ TTC)",
      [E("ht", "Montant HT", "€", "100", opt=True), E("ttc", "Montant TTC", "€", "", opt=True),
       E("taux", "Taux de TVA", "%", "20")],
      [S("TVA", "ht*taux/100", "€"), S("TTC", "ht*(1+taux/100)", "€", "HT · (1 + taux)"),
       S("HT", "ttc/(1+taux/100)", "€", "TTC / (1 + taux)"), S("TVA incluse", "ttc-ttc/(1+taux/100)", "€")],
      mots="tva ht ttc taxe prix"),
    F("interets", FIN, "Intérêts composés",
      [E("cap", "Capital de départ", "€", "10000"), E("taux", "Rendement annuel", "%", "4"),
       E("ans", "Durée", "ans", "10"), E("verse", "Versement mensuel", "€", "0")],
      [S("Valeur finale", "cap*(1+taux/100)**ans+verse*(((1+taux/100)**ans-1)/((1+taux/100)**(1/12)-1) if taux > 0 else 12*ans)",
         "€", "C·(1+r)ⁿ + versements capitalisés"),
       S("Total versé", "cap+verse*12*ans", "€"),
       S("Gain", "cap*(1+taux/100)**ans+verse*(((1+taux/100)**ans-1)/((1+taux/100)**(1/12)-1) if taux > 0 else 12*ans)-cap-verse*12*ans", "€")],
      mots="interets composes epargne placement capital rendement"),
    F("trois", FIN, "Règle de trois",
      [E("a", "A", "", "4"), E("b", "correspond à B", "", "10"), E("c", "Alors C", "", "6")],
      [S("C correspond à", "c*b/a", "", "x = C·B / A")],
      mots="regle de trois proportion produit en croix"),
    # ---------------------------------------------------------- Maths
    F("triangle", MATH, "Triangle rectangle",
      [E("a", "Côté a", "", "3"), E("b", "Côté b", "", "4")],
      [S("Hypoténuse", "hypot(a,b)", "", "c = √(a²+b²)"), S("Angle A", "deg(atan2(a,b))", "°", "A = atan(a/b)"),
       S("Angle B", "deg(atan2(b,a))", "°"), S("Aire", "a*b/2", "", "a·b / 2")],
      mots="triangle rectangle pythagore hypotenuse angle"),
    F("cercle", MATH, "Cercle et sphère",
      [E("r", "Rayon", "", "5")],
      [S("Périmètre", "2*pi*r", "", "2πr"), S("Aire du disque", "pi*r**2", "", "πr²"),
       S("Aire de la sphère", "4*pi*r**2", "", "4πr²"), S("Volume de la sphère", "4/3*pi*r**3", "", "4πr³/3")],
      mots="cercle disque sphere rayon perimetre aire volume"),
]

_INDEX = {f["id"]: f for f in FORMULES}


def _special_ohm(v):
    U, I, R, P = v.get("U"), v.get("I"), v.get("R"), v.get("P")
    connu = [k for k in ("U", "I", "R", "P") if v.get(k) is not None]
    if len(connu) < 2:
        raise ErreurCalcul("")  # silencieux : l'interface n'affiche rien
    a, b = connu[0], connu[1]
    res = {}
    if (a, b) == ("U", "I"):
        res = {"R": U / I, "P": U * I}
    elif (a, b) == ("U", "R"):
        res = {"I": U / R, "P": U * U / R}
    elif (a, b) == ("U", "P"):
        res = {"I": P / U, "R": U * U / P}
    elif (a, b) == ("I", "R"):
        res = {"U": I * R, "P": I * I * R}
    elif (a, b) == ("I", "P"):
        res = {"U": P / I, "R": P / (I * I)}
    elif (a, b) == ("R", "P"):
        res = {"U": math.sqrt(P * R), "I": math.sqrt(P / R)}
    noms = {"U": ("Tension", "V"), "I": ("Courant", "A"), "R": ("Résistance", "Ω"), "P": ("Puissance", "W")}
    formules = {"R": "R = U / I", "P": "P = U·I", "I": "I = U / R", "U": "U = R·I"}
    return [(noms[k][0], val, noms[k][1], formules.get(k, "")) for k, val in res.items()]


def _special_timer_cible(v):
    fclk, ft = v["fclk"], v["ft"]
    if fclk <= 0 or ft <= 0:
        raise ErreurCalcul("Valeurs positives requises")
    meilleur = None
    for psc in range(0, 65536):
        arr = round(fclk / ((psc + 1) * ft)) - 1
        if arr < 1 or arr > 65535:
            continue
        f = fclk / ((psc + 1) * (arr + 1))
        err = abs(f - ft) / ft
        if meilleur is None or err < meilleur[0] - 1e-15 or (abs(err - meilleur[0]) <= 1e-15 and arr > meilleur[2]):
            meilleur = (err, psc, arr, f)
        if err == 0 and arr >= 1000:
            break
    if meilleur is None:
        raise ErreurCalcul("Fréquence inaccessible avec un timer 16 bits")
    err, psc, arr, f = meilleur
    return [("PSC", psc, "", "PSC"), ("ARR", arr, "", "ARR = fclk / ((PSC+1)·f) − 1"),
            ("Fréquence obtenue", f, "Hz", ""), ("Erreur", err * 100, "%", "")]


_SPECIAUX = {"ohm": _special_ohm, "timer_cible": _special_timer_cible}


def catalogue():
    """Description des formules pour construire l'interface (sans les expressions)."""
    cats = []
    for f in FORMULES:
        if f["cat"] not in cats:
            cats.append(f["cat"])
    formules = [{"id": f["id"], "cat": f["cat"], "nom": f["nom"], "mots": f["mots"], "mode": f["mode"],
                 "entrees": f["entrees"], "choix": f["choix"]} for f in FORMULES]
    return {"categories": cats, "formules": formules}


def calculer_formule(db_path, fid, valeurs, enregistrer=False):
    f = _INDEX.get(fid)
    if f is None:
        return {"ok": False, "message": "Formule inconnue"}
    mode = "complet" if f["mode"] == "si" else "leger"
    affichage = "si" if f["mode"] == "si" else "leger"
    env = {}
    try:
        for e in f["entrees"]:
            brut = str(valeurs.get(e["k"], "") or "").strip()
            if brut == "":
                if e["opt"]:
                    continue
                return {"ok": False, "message": f"{e['l']} : valeur manquante"}
            try:
                env[e["k"]] = _lire_liste(brut, mode) if e["t"] == "liste" else _lire_nombre(brut, mode)
            except ErreurCalcul as ex:
                detail = "valeur invalide" if isinstance(ex, VariableManquante) else str(ex)
                return {"ok": False, "message": f"{e['l']} : {detail}"}

        lignes = []
        if f["special"]:
            for label, val, unite, formule in _SPECIAUX[f["special"]](env):
                lignes.append({"label": label, "valeur": _afficher(val, unite, affichage), "formule": formule})
        else:
            for k, expr in f["inter"]:
                try:
                    env[k] = _evaluer_brut(expr, env)
                except VariableManquante:
                    pass
            for s in f["sorties"]:
                try:
                    val = _evaluer_brut(s["e"], env)
                except VariableManquante:
                    continue
                except ZeroDivisionError:
                    lignes.append({"label": s["l"], "valeur": "division par zéro", "formule": s["f"]})
                    continue
                except (ValueError, OverflowError):
                    lignes.append({"label": s["l"], "valeur": "indéfini", "formule": s["f"]})
                    continue
                lignes.append({"label": s["l"], "valeur": _afficher(val, s["u"], affichage), "formule": s["f"]})
    except ZeroDivisionError:
        return {"ok": False, "message": "Division par zéro"}
    except ErreurCalcul as ex:
        return {"ok": False, "message": str(ex)}
    except (ValueError, OverflowError) as ex:
        return {"ok": False, "message": f"Calcul impossible ({ex})"}
    except Exception as ex:
        return {"ok": False, "message": f"Calcul impossible ({type(ex).__name__})"}

    if not lignes:
        return {"ok": False, "message": "Entrées insuffisantes"}
    res = {"ok": True, "type": "formule", "id": fid, "nom": f["nom"], "lignes": lignes, "note": f["note"]}
    if enregistrer:
        saisie = ", ".join(f"{k}={v}" for k, v in valeurs.items() if str(v).strip())
        _historiser(db_path, "formule", f"{f['nom']} · {saisie}", " ; ".join(
            (f"{l['label']} = " if l["label"] else "") + l["valeur"] for l in lignes))
    return res


# ======================================================================
# 7. Historique (SQLite)
# ======================================================================

def _connexion(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def creer_tables(db_path):
    conn = _connexion(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calcul_historique (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cree_le TEXT NOT NULL,
            type TEXT NOT NULL,
            entree TEXT NOT NULL,
            resultat TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def _historiser(db_path, type_, entree, resultat):
    try:
        conn = _connexion(db_path)
        dernier = conn.execute(
            "SELECT entree, resultat FROM calcul_historique ORDER BY id DESC LIMIT 1").fetchone()
        if not dernier or dernier["entree"] != entree or dernier["resultat"] != resultat:
            conn.execute(
                "INSERT INTO calcul_historique (cree_le, type, entree, resultat) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), type_, entree[:500], resultat[:1000]))
            conn.execute(
                "DELETE FROM calcul_historique WHERE id NOT IN "
                "(SELECT id FROM calcul_historique ORDER BY id DESC LIMIT ?)", (HISTORIQUE_MAX,))
            conn.commit()
        conn.close()
    except sqlite3.Error:
        pass  # l'historique est un confort : on ne fait jamais échouer un calcul pour lui


def historique_lister(db_path, limite=60):
    try:
        conn = _connexion(db_path)
        rows = conn.execute(
            "SELECT id, type, entree, resultat FROM calcul_historique ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def historique_supprimer(db_path, entree_id):
    conn = _connexion(db_path)
    conn.execute("DELETE FROM calcul_historique WHERE id = ?", (entree_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


def historique_vider(db_path):
    conn = _connexion(db_path)
    conn.execute("DELETE FROM calcul_historique")
    conn.commit()
    conn.close()
    return {"ok": True}


# ======================================================================
# 8. Pont IA : photo + demandes en langage naturel
#    _appeler_ia() est LA fonction à remplacer pour brancher une autre IA.
# ======================================================================

SYSTEME_IA = (
    "Tu es le moteur de calcul d'un assistant personnel. Réponds UNIQUEMENT par un objet JSON, sans aucun texte "
    "autour, de la forme : {\"lignes\":[{\"label\":\"...\",\"valeur\":\"...\"}],\"explication\":\"...\"}.\n"
    "Règles :\n"
    "- N'affiche que l'essentiel : une ligne par grandeur finale, label court, valeur numérique avec son unité.\n"
    "- Aucune politesse, aucune introduction, aucun commentaire.\n"
    "- Si plusieurs calculs sont demandés ou visibles, une ligne par résultat.\n"
    "- Virgule décimale, 4 à 6 chiffres significatifs, unités SI avec préfixes lisibles (kΩ, nF, mA).\n"
    "- « explication » reste une chaîne vide, sauf si detail=true : alors 2 à 6 lignes maximum "
    "(formule puis application numérique), séparées par des retours à la ligne.\n"
    "- Si une donnée essentielle manque ou est illisible : une seule ligne {\"label\":\"Manque\",...} qui la nomme.\n"
    "- Si tu dois faire une hypothèse : une seule ligne {\"label\":\"Hypothèse\",...}."
)


def _param(db_path, cle, defaut=None):
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT valeur FROM parametres WHERE cle = ?", (cle,)).fetchone()
        conn.close()
        return row[0] if row and row[0] else defaut
    except sqlite3.Error:
        return defaut


def _ecrire_param(db_path, cle, valeur):
    conn = sqlite3.connect(db_path)
    if valeur is None:
        conn.execute("DELETE FROM parametres WHERE cle = ?", (cle,))
    else:
        conn.execute("INSERT INTO parametres (cle, valeur) VALUES (?, ?) "
                     "ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur", (cle, valeur))
    conn.commit()
    conn.close()


def _cle_ia(db_path):
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env, "environnement"
    cle = _param(db_path, "ia_cle_api")
    return (cle, "application") if cle else (None, None)


def ia_statut(db_path):
    cle, source = _cle_ia(db_path)
    return {"actif": bool(cle), "source": source,
            "modele": _param(db_path, "ia_modele", MODELE_IA_DEFAUT),
            "apercu": ("…" + cle[-4:]) if cle else ""}


def ia_configurer(db_path, cle, modele):
    cle = (cle or "").strip()
    modele = (modele or "").strip()
    if cle:
        _ecrire_param(db_path, "ia_cle_api", cle)
    if modele:
        _ecrire_param(db_path, "ia_modele", modele)
    return {"ok": True, **ia_statut(db_path)}


def ia_retirer_cle(db_path):
    _ecrire_param(db_path, "ia_cle_api", None)
    return {"ok": True, **ia_statut(db_path)}


def _preparer_image(data_url):
    """Data-URL ou base64 → (base64 JPEG/PNG réduit, type MIME)."""
    brut = data_url.split(",", 1)[1] if data_url.startswith("data:") else data_url
    try:
        octets = base64.b64decode(brut)
        from PIL import Image
        img = Image.open(io.BytesIO(octets))
        img.load()
        if max(img.size) > 1600:
            img.thumbnail((1600, 1600))
        sortie = io.BytesIO()
        if img.mode in ("RGBA", "LA", "P"):
            img.convert("RGBA").save(sortie, format="PNG", optimize=True)
            mime = "image/png"
        else:
            img.convert("RGB").save(sortie, format="JPEG", quality=90)
            mime = "image/jpeg"
        return base64.b64encode(sortie.getvalue()).decode("ascii"), mime
    except Exception:
        raise ErreurCalcul("Image illisible")


def _appeler_ia(db_path, texte, image_data_url, detail):
    """Envoie la demande (et l'image) à l'IA, renvoie le texte brut de sa réponse.
    >>> POUR BRANCHER UNE AUTRE IA : remplace uniquement le corps de cette fonction. <<<
    Elle doit renvoyer un texte JSON {"lignes":[{"label","valeur"}],"explication":""}."""
    import requests

    cle, _ = _cle_ia(db_path)
    if not cle:
        raise ErreurCalcul("IA non configurée (bouton IA en haut à droite)")
    modele = _param(db_path, "ia_modele", MODELE_IA_DEFAUT)

    contenu = []
    if image_data_url:
        b64, mime = _preparer_image(image_data_url)
        contenu.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
    consigne = texte.strip() or "Calcule ce qui figure sur l'image."
    contenu.append({"type": "text", "text": f"detail={'true' if detail else 'false'}\nDemande : {consigne}"})

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": cle, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": modele, "max_tokens": 1500, "system": SYSTEME_IA,
                  "messages": [{"role": "user", "content": contenu}]},
            timeout=90)
    except requests.RequestException:
        raise ErreurCalcul("IA injoignable (connexion ?)")
    if r.status_code == 401:
        raise ErreurCalcul("Clé API refusée")
    if r.status_code == 429:
        raise ErreurCalcul("IA : trop de requêtes, réessaie dans un instant")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        raise ErreurCalcul(f"IA : erreur {r.status_code} {msg}".strip())
    try:
        blocs = r.json()["content"]
        return "".join(b.get("text", "") for b in blocs if b.get("type") == "text")
    except (ValueError, KeyError, TypeError):
        raise ErreurCalcul("Réponse de l'IA illisible")


def _lire_reponse_ia(texte):
    import json
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut != -1 and fin > debut:
        try:
            data = json.loads(texte[debut:fin + 1])
            lignes = []
            for l in data.get("lignes", []):
                if isinstance(l, dict):
                    lignes.append({"label": str(l.get("label", "")), "valeur": str(l.get("valeur", ""))})
                else:
                    lignes.append({"label": "", "valeur": str(l)})
            if lignes:
                return lignes, str(data.get("explication", "") or "")
        except (ValueError, AttributeError):
            pass
    propre = texte.strip()
    if not propre:
        raise ErreurCalcul("Réponse vide de l'IA")
    return [{"label": "", "valeur": propre}], ""


def _demander_ia(db_path, texte, image_data_url, detail):
    brut = _appeler_ia(db_path, texte, image_data_url, detail)
    lignes, explication = _lire_reponse_ia(brut)
    entree = ("📷 " if image_data_url else "") + (texte.strip() or "photo")
    _historiser(db_path, "ia", entree, " ; ".join(
        (f"{l['label']} = " if l["label"] else "") + l["valeur"] for l in lignes))
    return {"ok": True, "type": "ia", "entree": entree, "lignes": lignes, "explication": explication}


# ======================================================================
# 9. Point d'entrée unique : la barre de calcul
# ======================================================================

def _local(texte):
    global _ANS
    m = _RE_COMMANDE.fullmatch(texte)
    if m:
        cmd = _COMMANDES[m.group(1).lower()]
        lignes = _commande_avec_delai(cmd, m.group(2))
        return {"ok": True, "type": "maths", "entree": texte, "lignes": lignes}

    conv = _essai_conversion(texte)
    if conv:
        v, ua, res, ub = conv
        return {"ok": True, "type": "conversion", "entree": texte,
                "lignes": [{"label": f"{_fmt(v)} {ua} =", "valeur": f"{_fmt(res)} {ub}"}]}

    val = _evaluer_texte(texte)
    if isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(val):
        _ANS = val
    return {"ok": True, "type": "expression", "entree": texte, "lignes": [{"label": "", "valeur": _afficher(val)}]}


def demander(db_path, texte, image_data_url=None, detail=False):
    texte = (texte or "").strip()
    if image_data_url:
        try:
            return _demander_ia(db_path, texte, image_data_url, bool(detail))
        except ErreurCalcul as e:
            return {"ok": False, "message": str(e)}
    if not texte:
        return {"ok": False, "message": ""}
    try:
        res = _local(texte)
    except ErreurCalcul as e:
        # Pas compris en local : si l'IA est branchée, c'est probablement du langage naturel.
        naturel = (str(e) == "Syntaxe invalide" or isinstance(e, VariableManquante)) \
            and re.search(r"[A-Za-zÀ-ÿ]{3,}\s+\S+", texte) is not None
        if naturel and ia_statut(db_path)["actif"]:
            try:
                return _demander_ia(db_path, texte, None, bool(detail))
            except ErreurCalcul as e2:
                return {"ok": False, "message": str(e2)}
        if naturel:
            return {"ok": False, "message": f"{e} · demande en langage naturel : IA non configurée"}
        return {"ok": False, "message": str(e)}
    except Exception as e:  # filet de sécurité : SymPy ou autre
        return {"ok": False, "message": f"Calcul impossible ({type(e).__name__})"}
    _historiser(db_path, res["type"], texte, " ; ".join(
        (f"{l['label']} " if l["label"] else "") + l["valeur"] for l in res["lignes"]))
    return res
