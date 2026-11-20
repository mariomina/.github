"""Prioridad de una issue o PR: la única implementación de las reglas (mariomina/mario-home#239).

Tan no usa una escala: ordena por reglas. Aquí las reglas dan un nivel y una clave de orden dentro del nivel.
Quien crea, sincroniza u ordena llama a `prioridad()`: `control.py alta` (mario-home), `proyectos_sync.py`, la
cola de agentes (mariomina/mario-home#207) y `github_pendientes.py`, que avisa si el nivel puesto es otro.

Niveles (gana el primero que se cumple):
  P0  rompe algo en uso: el issue `FRENO:`; seguridad (etiqueta, tipo o ámbito del título convencional, o una
      Bug con una vulnerabilidad o un CVE en el título); regresión (lo mismo, o un Bug con «regresión» en el título); CI rojo
      en la rama principal de su repo, si el elemento es de CI (`area/ci`, `ci` en el título convencional o
      «CI» en el título)
  P1  está en el paso actual del plan, bloquea a uno que lo está, o es un Bug en uso (tipo Bug, etiqueta `bug` o
      título convencional `fix`: muchas issues de bug nacen sin tipo)
  P2  el resto

Orden dentro del nivel (CRITERIOS, en este orden): lo que bloquea a más elementos → verificación antes que
funciones → restar antes que añadir → lo más arriesgado → el error más frecuente → lo más antiguo.

Datos de entrada, todos legibles por máquina:
  - «paso actual» = la línea `Paso actual: <valor>` de la descripción corta del Project (`paso_actual()`), y el
    paso de cada elemento, el campo `Paso` del Project (CAMPO_PASO). Sin ellos, la regla del paso no aplica.
  - «bloquea» = la relación «bloqueado por» de GitHub (`blocking` de la issue).
  - riesgo = campo `Tamaño` (L, M, S): lo más grande tiene más incógnitas.
  - frecuencia = reacciones 👍 de la issue: cada vez que el error se repite, un 👍.
  - motivo = una línea `Motivo de prioridad: <texto>` en el cuerpo (RE_MOTIVO): con él, el nivel puesto a mano
    manda y nadie lo cambia ni lo avisa (salvo un P0 que ya no se cumple).

Solo biblioteca estándar y sin red: los llamadores leen GitHub una vez y pasan los datos.
"""
import re
from dataclasses import dataclass, field

NIVELES = ("P0", "P1", "P2")
CAMPO = "Prioridad"
CAMPO_PASO = "Paso"
CAMPO_TAMANO = "Tamaño"
FRENO = "FRENO:"
RE_PASO_ACTUAL = re.compile(r"Paso actual:\s*([^\n·|;]+?)\s*(?:$|[\n·|;])", re.IGNORECASE | re.MULTILINE)
RE_MOTIVO = re.compile(r"^\W*Motivo de prioridad\W*:\s*\S", re.IGNORECASE | re.MULTILINE)
# Tipo y ámbito de un título convencional: `fix(ci)!: …` → ("fix", "ci").
RE_CONVENCIONAL = re.compile(r"^\s*(\w+)(?:\(([^)]*)\))?!?:")
SEGURIDAD = {"seguridad", "security"}
REGRESION = {"regresión", "regresion", "regression"}
RE_VULNERABILIDAD = re.compile(r"\b(vulnerab\w*|CVE-\d+)", re.IGNORECASE)
RE_REGRESION = re.compile(r"\b(regresi[oó]n|regression)\b", re.IGNORECASE)
RE_CI = re.compile(r"\bCI\b")
RE_VERIFICACION = re.compile(r"\b(verifica\w*|tests?|pruebas?)\b", re.IGNORECASE)
RE_RESTAR = re.compile(r"\b(quitar|quita|borrar|borra|eliminar|elimina|retirar|retira|simplifica\w*|"
                       r"remove|delete|drop|revert)\b", re.IGNORECASE)
RIESGO = {"L": 0, "M": 1, "S": 2}  # sin Tamaño: como M


@dataclass(frozen=True)
class Elemento:
    """Lo que las reglas leen de una issue o PR. `id`: el id de nodo de GitHub (el de `blocking`)."""
    id: str
    titulo: str
    creado: str  # ISO 8601: ordena como texto
    tipo: str = "Issue"  # Issue o PullRequest
    tipo_issue: str | None = None  # Bug, Tarea, Mejora, Épica
    etiquetas: frozenset = frozenset()
    paso: str | None = None
    bloquea: frozenset = frozenset()  # ids de los elementos abiertos que bloquea
    tamano: str | None = None
    frecuencia: int = 0
    ci_rojo: bool = False  # CI rojo en la rama principal de su repo


@dataclass(frozen=True)
class Contexto:
    """Lo que depende del conjunto: el paso actual y los ids de los elementos que están en él."""
    paso_actual: str | None = None
    del_paso: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class Prioridad:
    nivel: str
    motivo: str
    clave: tuple  # ordena entre niveles y dentro de cada uno: sorted(..., key=lambda p: p.clave)


def _convencional(e):
    m = RE_CONVENCIONAL.match(e.titulo)
    return (m.group(1).lower(), (m.group(2) or "").lower()) if m else ("", "")


def _es_ci(e):
    tipo, ambito = _convencional(e)
    return "area/ci" in e.etiquetas or "ci" in (tipo, ambito) or bool(RE_CI.search(e.titulo))


def _es_bug(e):
    return e.tipo_issue == "Bug" or "bug" in e.etiquetas or _convencional(e)[0] == "fix"


def _marca(e, palabras):
    """True si una etiqueta, o el tipo o el ámbito del título convencional, es una de `palabras`."""
    return bool({x.lower() for x in e.etiquetas} & palabras) or bool(set(_convencional(e)) & palabras)


def _bloquea_al_paso(e, ctx):
    return bool(e.bloquea & ctx.del_paso)


# (nivel, motivo, regla): la primera que se cumple da el nivel.
REGLAS = (
    ("P0", "issue FRENO:", lambda e, ctx: e.titulo.startswith(FRENO)),
    ("P0", "seguridad", lambda e, ctx: _marca(e, SEGURIDAD) or (_es_bug(e) and bool(RE_VULNERABILIDAD.search(e.titulo)))),
    ("P0", "regresión", lambda e, ctx: _marca(e, REGRESION) or (_es_bug(e) and bool(RE_REGRESION.search(e.titulo)))),
    ("P0", "CI rojo en la rama principal", lambda e, ctx: e.ci_rojo and _es_ci(e)),
    ("P1", "paso actual del plan", lambda e, ctx: bool(ctx.paso_actual) and e.paso == ctx.paso_actual),
    ("P1", "bloquea el paso actual", _bloquea_al_paso),
    ("P1", "Bug en uso", lambda e, ctx: _es_bug(e)),
)

# Orden dentro del nivel: cada criterio da un número; menor va antes.
CRITERIOS = (
    ("bloquea", lambda e: -len(e.bloquea)),
    ("verificación", lambda e: 0 if _es_ci(e) or _convencional(e)[0] in ("test", "ci")
     or RE_VERIFICACION.search(e.titulo) else 1),
    ("restar", lambda e: 0 if _convencional(e)[0] == "revert" or RE_RESTAR.search(e.titulo) else 1),
    ("riesgo", lambda e: RIESGO.get(e.tamano or "M", 1)),
    ("frecuencia", lambda e: -e.frecuencia),
)


def prioridad(e, ctx=None):
    """Nivel, motivo y clave de orden de `e`. La clave: (nivel, criterios…, antigüedad, id). Sin `ctx`, sin paso actual."""
    ctx = ctx or Contexto()
    nivel, motivo = next(((n, m) for n, m, regla in REGLAS if regla(e, ctx)), ("P2", "el resto"))
    return Prioridad(nivel, motivo, (NIVELES.index(nivel), *(f(e) for _, f in CRITERIOS), e.creado, e.id))


def contexto(elementos, paso_actual):
    """Contexto de un conjunto: los ids de los elementos cuyo `paso` es `paso_actual`."""
    return Contexto(paso_actual, frozenset(e.id for e in elementos if paso_actual and e.paso == paso_actual))


def ordenar(elementos, paso_actual=None):
    """[(elemento, Prioridad)] en el orden de trabajo: la cola de agentes (mariomina/mario-home#207)."""
    ctx = contexto(elementos, paso_actual)
    return sorted(((e, prioridad(e, ctx)) for e in elementos), key=lambda par: par[1].clave)


def paso_actual(texto):
    """El valor de `Paso actual: <valor>` en `texto` (descripción corta del Project), o None."""
    m = RE_PASO_ACTUAL.search(texto or "")
    return m.group(1).strip() if m else None


def tiene_motivo(cuerpo):
    """True si el cuerpo de la issue da un motivo para un nivel puesto a mano."""
    return bool(RE_MOTIVO.search(cuerpo or ""))


# --- GraphQL: la misma forma para todos los llamadores -------------------------------------------

# Campos del contenido (Issue o PullRequest) que `desde_graphql` lee. Los llamadores los insertan en su consulta.
CAMPOS_ISSUE = ("id title createdAt issueType { name } labels(first: 20) { nodes { name } } "
                "blocking(first: 20) { nodes { id state } } reactions(content: THUMBS_UP) { totalCount }")
CAMPOS_PR = "id title createdAt labels(first: 20) { nodes { name } }"
# Campos del elemento del Project, con alias: un elemento puede pedir varios `fieldValueByName`.
CAMPOS_ITEM = " ".join(
    f'{alias}: fieldValueByName(name: "{nombre}") {{ ... on ProjectV2ItemFieldSingleSelectValue {{ name optionId }} }}'
    for alias, nombre in (("prioridad", CAMPO), ("paso", CAMPO_PASO), ("tamano", CAMPO_TAMANO)))


def _valor(item, alias):
    return ((item or {}).get(alias) or {}).get("name")


def desde_graphql(contenido, item=None, ci_rojo=False):
    """Elemento desde el contenido GraphQL (CAMPOS_ISSUE o CAMPOS_PR) y su elemento del Project (CAMPOS_ITEM)."""
    c = contenido or {}
    return Elemento(
        id=c.get("id") or "",
        titulo=c.get("title") or "",
        creado=c.get("createdAt") or "",
        tipo=c.get("__typename") or ("Issue" if "blocking" in c or "issueType" in c else "PullRequest"),
        tipo_issue=(c.get("issueType") or {}).get("name"),
        etiquetas=frozenset(n["name"] for n in (c.get("labels") or {}).get("nodes") or []),
        paso=_valor(item, "paso"),
        bloquea=frozenset(n["id"] for n in (c.get("blocking") or {}).get("nodes") or [] if n.get("state") != "CLOSED"),
        tamano=_valor(item, "tamano"),
        frecuencia=(c.get("reactions") or {}).get("totalCount") or 0,
        ci_rojo=ci_rojo,
    )
