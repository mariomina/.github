"""Pendientes de GitHub en los repos de Mario: qué se fusiona solo, qué espera su decisión y qué se avisa.

Decisiones de Mario (mariomina/mario-2-cerebro#280):
  - PR de versión (release-please): se fusiona sola, solo con CI en verde (mariomina/.github#28): la ejecución
    más reciente de cada check del head, como `gh pr checks` (mariomina/mario-home#134). La crea y la fusiona
    el job reutilizable con el token de la GitHub App automatizador-m (antes mariomina-automatizacion; el CI corre en la PR y el merge
    dispara la versión); si su CI acaba después, la fusiona `--fusionar`. CI rojo o sin CI tras 10 min: espera
    la decisión de Mario.
  - Dependabot: espera el veredicto de un verificador y el permiso de Mario, como una PR de trabajo (pstack:
    el CI en verde solo no autoriza una fusión; decisión de Mario en mariomina/mario-home#134). La tabla dice
    si es de parche, menor o mayor (título sin semver o versión 0.x: mayor).
  - PR de trabajo: espera la decisión de Mario.
  - Avisos (nunca se borra ni se cierra nada): workflow desactivado por 60 días sin actividad (no vuelve
    con ningún trigger: el aviso da el `gh workflow enable` que lo recupera), CI rojo en la rama principal,
    ramas sin PR y PR de más de 7 días, issues abiertos sin proyecto, issues en Listo del Project a las que
    les falta un campo obligatorio de .github/ISSUE_TEMPLATE/2-tarea.yml (listo-sin-contrato, mario-home#207),
    issues cuya Prioridad del Project no es la que calcula scripts/prioridad.py y no dan «Motivo de prioridad:»
    (prioridad-distinta), y P0 que ya no se cumplen, con motivo o sin él (prioridad-p0-caducada; mario-home#239).

Métricas (mariomina/mario-home#22), últimos 7 y 28 días, desde el historial de GitHub (sin guardar nada):
  - fusionadas y, de ellas, por bots: creadas y fusionadas por la App, github-actions o Dependabot. El resto no
    se puede atribuir: Mario y los agentes usan hoy la misma identidad (mariomina/mario-home#37, #38).
  - reverts: fusionadas con título `revert:` o `Revert "…"`.
  - CI rojo en la rama principal: commits con FAILURE o ERROR / commits con checks.

Freno de emergencia (mariomina/mario-home#41): un issue abierto en mario-home cuyo título empieza por
«FRENO:» pausa toda fusión automática (barrido y PR de versión). Si no se puede comprobar, tampoco se
fusiona: falla del lado seguro. Reanudar = cerrar el issue. Runbook: mario-home/entorno/freno.md.

Log público: en Actions, si el repo que lo ejecuta no es privado, solo imprime cuentas (sin repos, PR,
ramas ni títulos). El barrido programado vive en mario-home (privado) por eso.

Repos: mario-home y los punteros de su AGENTS.md, en cascada por los home repos (`punteros` de
filtro_global.py). Cada AGENTS.md se lee por la API (rama principal): un clon local puede estar atrasado.

Uso (token: GH_TOKEN, GITHUB_TOKEN o `gh auth token`; GH_TOKEN_<DUEÑO>, p. ej. GH_TOKEN_ESCALA_AGENCIA, manda
en los repos de ese dueño: un token de GitHub App vale para una sola cuenta. Un token de App, ghs_, no ve los
Projects de una cuenta personal: para leerlos, y solo para eso, PROJECTS_TOKEN o la sesión de `gh` de Mario,
`gh auth token` sin GH_TOKEN ni GITHUB_TOKEN; mariomina/.github#65 y mariomina/mario-home#38):
  github_pendientes.py              tabla
  github_pendientes.py --json       todo en JSON
  github_pendientes.py --fusionar   fusiona lo que se fusiona solo, después la tabla; salida 1 si alguna falla
  github_pendientes.py --linea      una línea «GitHub: …» desde la caché; nunca espera a la red: si la caché
                                    tiene más de 10 min, la refresca en segundo plano. Siempre sale con 0
  github_pendientes.py --hermes     hook pre_llm_call de Hermes: {"context": línea} en el primer turno
  github_pendientes.py --fusionar-version
                                    paso del job reutilizable release-please: espera el CI de cada PR de $PRS
                                    en $GITHUB_REPOSITORY (hasta 10 min), la fusiona solo en verde y escribe
                                    `fusionadas=N` en $GITHUB_OUTPUT (también si una falla); salida 1 si alguna
                                    tiene CI rojo, no tiene CI o no se puede fusionar
"""
import argparse
import importlib.util
import json
import os
import re
import select
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.dont_write_bytecode = True  # cargar filtro_global.py no deja __pycache__ en scripts/


def _cargar(nombre):
    """Un script hermano por ruta (con `python3 -I` su carpeta no está en sys.path), o None si no está."""
    ruta = Path(__file__).resolve().parent / f"{nombre}.py"
    if not ruta.exists():
        return None
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# Las reglas de prioridad (mariomina/mario-home#239). Opcional: un checkout parcial que solo trae este script (el
# job de la PR de versión) no las necesita; sin ellas, el barrido lo dice en `errores` y no avisa de prioridades.
prioridad = _cargar("prioridad")

API = "https://api.github.com"
HOME_REPO = "mariomina/mario-home"
FRENO = "FRENO:"
CACHE = Path.home() / ".cache" / "mariomina-github" / "pendientes.json"  # fija: la comparten Claudian y Hermes
CADUCA = timedelta(minutes=10)      # caché más vieja: `--linea` la refresca en segundo plano
BLOQUEO = timedelta(minutes=2)      # un refresco en curso no se lanza dos veces
VERSION_SIN_CI = timedelta(minutes=10)  # PR de versión sin checks tras este tiempo: espera a Mario
VIEJA = timedelta(days=7)
MAX_REFS_LINEA = 4
METODOS = ("squash", "merge", "rebase")  # en este orden, los que el repo permita (squash: mariomina/.github#27)
ESPERA_CI = timedelta(minutes=10)        # `--fusionar-version` espera al CI de la PR hasta este plazo
SIN_CI = timedelta(minutes=2)            # sin ningún check tras este tiempo: la PR no tiene CI
SONDEO = 15                              # segundos entre lecturas del CI
# GITHUB_TOKEN o la GitHub App `automatizador-m` (#28), también con su nombre anterior (mariomina/mario-home#238)
AUTORES_VERSION = {"github-actions", "automatizador-m", "mariomina-automatizacion"}
# Checks del head con su fecha: GraphQL no quita los duplicados de un mismo head (`edited`, `reopened`, re-runs).
ROLLUP = """statusCheckRollup { state contexts(first: 100) { totalCount nodes { __typename
      ... on CheckRun { name status conclusion startedAt checkSuite { workflowRun { event workflow { name } } } }
      ... on StatusContext { context state createdAt } } } }"""
PR_VERSION = """query($o: String!, $n: String!, $pr: Int!) { repository(owner: $o, name: $n) {
  pullRequest(number: $pr) { state merged headRefOid commits(last: 1) { nodes { commit { ROLLUP } } } } } }""".replace(
    "ROLLUP", ROLLUP)
# Estado de cada check como lo agrupa `gh pr checks` (bucket); STARTUP_FAILURE, además, cuenta como rojo.
ROJO = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
VERDE = {"SUCCESS"}
SALTADO = {"SKIPPED", "NEUTRAL"}
RE_SALTO = re.compile(r"\bfrom (\S+) to (\S+)", re.I)
RE_VERSION = re.compile(r"v?(\d+(?:\.\d+)*)")
RE_REVERT = re.compile(r'^(revert(\(.+\))?!?:|Revert ")', re.I)
RE_ELEMENTO = re.compile(r"^\s*-\s+type:\s*(\S+)")              # elemento del `body` de un formulario de issue
RE_ATRIBUTO = re.compile(r"^\s*(label|required):\s*(.*?)\s*$")
RE_ENCABEZADO = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*$")
SIN_RESPUESTA = "_No response_"  # lo que GitHub escribe en un campo vacío de un formulario de issue
LISTO = "Listo"  # Status del Project para una issue lista para un agente (cola de autopilot-stack)
PLANTILLA_TAREA = ("mariomina/.github", ".github/ISSUE_TEMPLATE/2-tarea.yml")  # sus campos obligatorios: el contrato
BOTS = {"github-actions", "automatizador-m", "mariomina-automatizacion", "dependabot"}
VENTANAS = (7, 28)  # días
HISTORIA = """history(since: "DESDE", first: 100CURSOR) { pageInfo { hasNextPage endCursor }
    nodes { committedDate statusCheckRollup { state } } }"""
FUSIONADAS = """pullRequests(states: MERGED, last: 100CURSOR, orderBy: {field: UPDATED_AT, direction: ASC}) {
    pageInfo { hasPreviousPage startCursor } nodes { title mergedAt updatedAt author { login } mergedBy { login } } }"""
FRAGMENTO_METRICAS = f"""fragment M on Repository {{
  defaultBranchRef {{ target {{ ... on Commit {{ {HISTORIA.replace("CURSOR", "")} }} }} }}
  {FUSIONADAS.replace("CURSOR", "")}
}}"""

ISSUES = """issues(states: OPEN, first: 100) { nodes { number title url body CAMPOS projectItems(first: 10) { totalCount
    nodes { fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } ITEM } } } }"""
ISSUES = (ISSUES.replace("CAMPOS", prioridad.CAMPOS_ISSUE).replace("ITEM", "project { id shortDescription } " + prioridad.CAMPOS_ITEM)
          if prioridad else ISSUES.replace("CAMPOS ", "").replace(" ITEM", ""))
FRAGMENTO = """fragment R on Repository {
  nameWithOwner mergeCommitAllowed squashMergeAllowed rebaseMergeAllowed
  defaultBranchRef { name target { ... on Commit { history(first: 5) { nodes { statusCheckRollup { state } } } } } }
  pullRequests(states: OPEN, first: 50) { nodes {
    number title url createdAt updatedAt isDraft isCrossRepository headRefName headRefOid author { login }
    commits(last: 1) { nodes { commit { ROLLUP } } } } }
  refs(refPrefix: "refs/heads/", first: 100, orderBy: {field: TAG_COMMIT_DATE, direction: ASC}) {
    nodes { name target { ... on Commit { committedDate } } } }
  ISSUES
}""".replace("ROLLUP", ROLLUP).replace("ISSUES", ISSUES)
FRAGMENTO_PROYECTOS = f"fragment P on Repository {{ {ISSUES} }}"  # con el token que ve los Projects (#65)


class Fallo(Exception):
    """Error esperado (sin token, sin red, GitHub responde mal): sale como motivo, nunca como traza."""


# --- red ----------------------------------------------------------------------

def http(metodo, url, token, cuerpo=None):
    """Única salida a la red (los tests la sustituyen). Devuelve el JSON de la respuesta."""
    req = urllib.request.Request(url, method=metodo,
                                 data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
                                 headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def obtener_token():
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    return gh_auth_token()


def gh_auth_token(entorno=None):
    """`gh auth token` o None. `entorno`: el del proceso `gh` (None: el de este proceso)."""
    gh = shutil.which("gh") or ("/app/bin/gh" if os.path.exists("/app/bin/gh") else None)  # /app/bin: Flatpak
    if not gh:
        return None
    try:
        p = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=5, check=False, env=entorno)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() or None


def token_proyectos(token):
    """Un token que ve los Projects de una cuenta personal, o None. `token` si no es de una GitHub App (ghs_);
    si lo es, PROJECTS_TOKEN (Actions) o la sesión de `gh` de Mario en la máquina, la misma excepción que hace
    mario-home/entorno/agente/gh con `gh project`. Solo para leer Projects (mariomina/mario-home#38)."""
    if not token.startswith("ghs_"):
        return token
    # Sin GH_TOKEN ni GITHUB_TOKEN: con ellos, `gh auth token` devuelve ese mismo token de App.
    otro = os.environ.get("PROJECTS_TOKEN") or gh_auth_token(
        {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")})
    return otro if otro and not otro.startswith("ghs_") else None


def token_de(repo, token):
    """GH_TOKEN_<DUEÑO> para `owner/repo` si existe; si no, `token`. Mismo criterio que filtro_global.token."""
    dueno = re.sub(r"\W", "_", repo.split("/")[0]).upper()
    return os.environ.get(f"GH_TOKEN_{dueno}") or token


def cargar_filtro():
    """filtro_global.py por ruta: con `python3 -I` la carpeta del script no está en sys.path."""
    return _cargar("filtro_global") or sys.exit("falta filtro_global.py junto a github_pendientes.py")


def repos(filtro):
    """[owner/repo]: mario-home y sus punteros, en cascada por los repos `tipo-repo: home`."""
    texto = filtro.leer_remoto(HOME_REPO)
    if texto is None:
        raise Fallo(f"no se puede leer el AGENTS.md de {HOME_REPO}")
    salida, pendientes = [HOME_REPO], list(filtro.punteros(texto))
    while pendientes:
        _, nombre = pendientes.pop(0)
        if not nombre or nombre in salida:
            continue
        salida.append(nombre)
        texto = filtro.leer_remoto(nombre)
        tipo = filtro.RE_TIPO.search(texto or "")
        if tipo and tipo.group(1) == "home":
            pendientes.extend(filtro.punteros(texto))
    return salida


def consultar(nombres, token, fragmento=FRAGMENTO, por_dueno=True):
    """{owner/repo: nodo GraphQL o None} y [errores por repo], en una consulta con alias por token: el del dueño
    de cada repo (token_de) o, sin `por_dueno`, solo `token`."""
    alias = {f"r{i}": n for i, n in enumerate(nombres)}
    grupos = {}
    for a, n in alias.items():
        grupos.setdefault(token_de(n, token) if por_dueno else token, []).append(a)
    datos, errores = {}, []
    for t, nombres_alias in grupos.items():
        campos = " ".join(f'{a}: repository(owner: "{alias[a].split("/")[0]}", name: "{alias[a].split("/")[1]}") '
                          f"{{ ...{fragmento.split()[1]} }}" for a in nombres_alias)
        d = http("POST", f"{API}/graphql", t, {"query": f"query {{ {campos} }}\n{fragmento}"})
        datos.update(d.get("data") or {})
        for e in d.get("errors") or []:
            repo = alias.get((e.get("path") or [""])[0], "?")
            errores.append({"repo": repo, "detalle": e.get("message", "")[:160]})
    if not datos and errores:
        raise Fallo(errores[0]["detalle"])
    return {n: datos.get(a) for a, n in alias.items()}, errores


def consultar_proyectos(nombres, token):
    """Como consultar, solo las issues con sus Projects y con un solo token, el de token_proyectos. Solo lee:
    la identidad de Mario no escribe nada (mariomina/mario-home#38)."""
    return consultar(nombres, token, FRAGMENTO_PROYECTOS, por_dueno=False)


# --- clasificación (sin red) -----------------------------------------------------

def _fecha(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _version(texto):
    m = RE_VERSION.fullmatch(texto.rstrip(".,;)"))
    if not m:
        return None
    partes = [int(x) for x in m.group(1).split(".")]
    return (partes + [0, 0, 0])[:3]


def salto(titulo):
    """parche | menor | mayor desde «from A to B» del título.

    Mayor: sin semver, con sufijo, bajada de versión, cambio de 0.x o cualquier cambio en 0.0.x.
    """
    m = RE_SALTO.search(titulo)
    a, b = (_version(m.group(1)), _version(m.group(2))) if m else (None, None)
    if not a or not b or b < a or a[0] != b[0] or (b[0] == 0 and (a[1] != b[1] or b[1] == 0)):
        return "mayor"
    return "menor" if a[1] != b[1] else "parche"


def _autor(pr):
    """Login sin `app/` ni `[bot]`: GraphQL, REST y `gh` lo escriben distinto."""
    return ((pr.get("author") or {}).get("login") or "").removeprefix("app/").removesuffix("[bot]")


def _es_version(pr):
    """Rama de release-please, autor github-actions o la App y no desde un fork (una rama así en un fork no cuenta)."""
    return (pr.get("headRefName", "").startswith("release-please--") and _autor(pr) in AUTORES_VERSION
            and pr.get("isCrossRepository") is False)


def _es_dependabot(pr):
    return _autor(pr) == "dependabot" and pr.get("isCrossRepository") is False


def estado_ci(rollup):
    """SUCCESS · PENDING · FAILURE o None (sin checks, o ninguno en verde) del `statusCheckRollup` de un commit,
    con la ejecución más reciente de cada check, como `gh pr checks`: un mismo nombre (y workflow y evento)
    puede tener varias ejecuciones en el mismo head y el `state` de GitHub las cuenta todas (mariomina/.github#51:
    1 `pr` FAILURE antigua + 4 `pr` SUCCESS daba FAILURE). Lado seguro, para cubrir lo que `gh` pueda elegir:
    un check sin fecha cuenta siempre, y con un empate en la fecha más reciente cuentan todos los empatados.
    Sin la lista completa de checks: el `state` de GitHub."""
    if not rollup:
        return None
    contextos = rollup.get("contexts") or {}
    nodos = contextos.get("nodes")
    if nodos is None or len(nodos) < (contextos.get("totalCount") or 0):
        return rollup.get("state")
    grupos = {}  # clave → [(fecha o None, estado)]
    for c in nodos:
        if c.get("__typename") == "StatusContext" or "context" in c:
            clave, estado = ("status", c.get("context")), c.get("state")
        else:
            corrida = ((c.get("checkSuite") or {}).get("workflowRun")) or {}
            clave = ("check", c.get("name"), ((corrida.get("workflow") or {}).get("name")), corrida.get("event"))
            estado = c.get("conclusion") if c.get("status") == "COMPLETED" else c.get("status")
        grupos.setdefault(clave, []).append((c.get("startedAt") or c.get("createdAt"), estado))
    estados = set()
    for ejecuciones in grupos.values():
        ultima = max((f for f, _ in ejecuciones if f), default=None)  # ISO en UTC: se compara como texto
        for fecha, estado in ejecuciones:
            if fecha and fecha != ultima:
                continue
            estados.add("rojo" if estado in ROJO else "verde" if estado in VERDE else
                        "saltado" if estado in SALTADO else "en curso")
    if "rojo" in estados:
        return "FAILURE"
    if "en curso" in estados:
        return "PENDING"
    return "SUCCESS" if "verde" in estados else None  # solo saltados: ningún check probó nada (frontera.py igual)


def clasificar_pr(repo, pr, ahora):
    """Entrada de la tabla: clase, acción (fusionar · esperar · decision · borrador · nada) y motivo."""
    ci = estado_ci((((pr.get("commits") or {}).get("nodes") or [{}])[0].get("commit") or {}).get("statusCheckRollup"))
    e = {"repo": repo, "numero": pr["number"], "titulo": pr["title"], "url": pr.get("url"),
         "sha": pr.get("headRefOid"), "ci": ci, "creada": pr.get("createdAt")}
    if _es_version(pr):
        quieta = ahora - _fecha(pr.get("updatedAt") or pr["createdAt"])
        e["clase"] = "version"
        if ci == "SUCCESS":
            e.update(accion="fusionar", motivo="CI en verde")
        elif ci in ("PENDING", "EXPECTED") or (not ci and quieta < VERSION_SIN_CI):
            e.update(accion="esperar", motivo="CI en curso")
        else:
            e.update(accion="decision", motivo="PR de versión con CI rojo" if ci else "PR de versión sin CI")
    elif _es_dependabot(pr):
        s = salto(pr["title"])
        e["clase"] = f"dependabot-{s}"
        if s == "mayor":
            e.update(accion="decision", motivo="Dependabot mayor")
        elif ci == "SUCCESS":
            e.update(accion="decision", motivo="Dependabot: falta veredicto y permiso")
        elif ci in ("PENDING", "EXPECTED"):
            # «esperar» cuenta como «se fusiona sola» en el informe: Dependabot nunca lo hace (#134)
            e.update(accion="decision", motivo="Dependabot: CI en curso; falta veredicto y permiso")
        else:
            e.update(accion="decision", motivo="Dependabot con CI rojo" if ci else "Dependabot sin CI")
    elif pr.get("isDraft"):
        e.update(clase="trabajo", accion="borrador", motivo="borrador")
    else:
        e.update(clase="trabajo", accion="decision", motivo="PR de trabajo")
    return e


def contrato(texto):
    """Etiquetas de los campos obligatorios del YAML de un formulario de issue, en su orden. Parser de líneas
    mínimo: por cada `- type:` del body, su primer `label:` y si tiene `required: true`; sin `type: markdown`."""
    elementos = []
    for fila in texto.splitlines():
        if m := RE_ELEMENTO.match(fila):
            elementos.append({"type": m.group(1).strip("\"'")})
        elif elementos and (m := RE_ATRIBUTO.match(fila)):
            elementos[-1].setdefault(m.group(1), m.group(2).strip("\"'"))
    return tuple(e["label"] for e in elementos
                 if e["type"] != "markdown" and e.get("label") and e.get("required", "").lower() == "true")


def faltan(cuerpo, etiquetas):
    """Etiquetas sin sección con texto en `cuerpo`, en el orden de `etiquetas`. Sección: `## <etiqueta>` o
    `### <etiqueta>` (sin distinguir mayúsculas) hasta el siguiente encabezado de su nivel o mayor; vacía o
    `_No response_` cuenta como falta."""
    filas = cuerpo.splitlines()
    encabezados = [(i, len(m.group(1)), m.group(2).casefold())
                   for i, fila in enumerate(filas) if (m := RE_ENCABEZADO.match(fila))]
    llenas = set()
    for j, (i, nivel, titulo) in enumerate(encabezados):
        if nivel not in (2, 3):
            continue
        fin = next((k for k, n, _ in encabezados[j + 1:] if n <= nivel), len(filas))
        texto = "\n".join(filas[i + 1:fin]).strip()
        if texto and texto != SIN_RESPUESTA:
            llenas.add(titulo)
    return [e for e in etiquetas if e.strip().casefold() not in llenas]


def avisos_prioridad(issues, rojos):
    """Avisos de las issues cuya Prioridad no es la calculada. `issues`: [(repo, issue)] de los repos que ven los
    Projects; `rojos`: repos con CI rojo en la rama principal. El contexto (paso actual) es el de cada Project."""
    if not prioridad:
        return []
    por_proyecto = {}
    for repo, i in issues:
        for item in (i.get("projectItems") or {}).get("nodes") or []:
            if item and item.get("project"):
                por_proyecto.setdefault(item["project"]["id"], []).append(
                    (repo, i, item, prioridad.desde_graphql(i, item, repo in rojos)))
    avisos = []
    for filas in por_proyecto.values():
        paso = prioridad.paso_actual(filas[0][2]["project"].get("shortDescription"))
        ctx = prioridad.contexto([e for *_, e in filas], paso)
        for repo, i, item, e in filas:
            puesta = (item.get("prioridad") or {}).get("name")
            if puesta not in prioridad.NIVELES:
                continue  # sin Prioridad: la pone el sync
            calculada = prioridad.prioridad(e, ctx)
            if puesta == calculada.nivel:
                continue
            detalle = f"#{i['number']} {i['title']} (puesta {puesta}; calculada {calculada.nivel}: {calculada.motivo}"
            if puesta == "P0":
                avisos.append({"repo": repo, "tipo": "prioridad-p0-caducada", "detalle": detalle + ")", "url": i.get("url")})
            elif not prioridad.tiene_motivo(i.get("body")):
                avisos.append({"repo": repo, "tipo": "prioridad-distinta",
                               "detalle": detalle + "; sin «Motivo de prioridad:»)", "url": i.get("url")})
    return avisos


def analizar(nodos, errores, ahora, sin_proyectos=(), contrato=()):
    """Estado completo desde las respuestas de GitHub: PR clasificadas, avisos y errores.
    `sin_proyectos`: repos cuyo token no ve los Projects; sin avisos de Projects (serían falsos).
    `contrato`: etiquetas obligatorias de la Tarea; sin ellas, no hay aviso listo-sin-contrato."""
    prs, avisos, con_proyectos, rojos = [], [], [], set()
    for repo, n in nodos.items():
        if not n:
            if not any(e["repo"] == repo for e in errores):
                errores.append({"repo": repo, "detalle": "sin acceso o no existe"})
            continue
        abiertas = (n.get("pullRequests") or {}).get("nodes") or []
        for pr in abiertas:
            e = clasificar_pr(repo, pr, ahora)
            e["metodo"] = ("squash" if n.get("squashMergeAllowed") else
                           "merge" if n.get("mergeCommitAllowed") else "rebase")
            prs.append(e)
            if e["clase"] != "version" and ahora - _fecha(pr["createdAt"]) > VIEJA:
                avisos.append({"repo": repo, "tipo": "pr-vieja", "detalle": f"#{pr['number']} {pr['title']}",
                               "url": pr.get("url")})
        principal = n.get("defaultBranchRef") or {}
        # Primer commit con checks: el merge de una PR de versión con GITHUB_TOKEN no tiene ninguno.
        historia = (((principal.get("target") or {}).get("history")) or {}).get("nodes") or []
        estado = next((c["statusCheckRollup"].get("state") for c in historia if c.get("statusCheckRollup")), None)
        if estado in ("FAILURE", "ERROR"):
            avisos.append({"repo": repo, "tipo": "ci-rojo", "detalle": f"CI rojo en {principal.get('name')}"})
            rojos.add(repo)
        con_pr = {pr.get("headRefName") for pr in abiertas}
        for ref in (n.get("refs") or {}).get("nodes") or []:
            fecha = (ref.get("target") or {}).get("committedDate")
            if ref["name"] == principal.get("name") or ref["name"] in con_pr or not fecha:
                continue
            if ahora - _fecha(fecha) > VIEJA:
                avisos.append({"repo": repo, "tipo": "rama-vieja",
                               "detalle": f"{ref['name']} (último commit {fecha[:10]}, sin PR)"})
        for i in [] if repo in sin_proyectos else (n.get("issues") or {}).get("nodes") or []:
            con_proyectos.append((repo, i))
            items = i.get("projectItems") or {}
            if not items.get("totalCount"):
                avisos.append({"repo": repo, "tipo": "issue-sin-proyecto", "detalle": f"#{i['number']} {i['title']}",
                               "url": i.get("url")})
            listo = any(((p or {}).get("fieldValueByName") or {}).get("name") == LISTO for p in items.get("nodes") or [])
            falta = faltan(i.get("body") or "", contrato) if listo else []
            if falta:
                avisos.append({"repo": repo, "tipo": "listo-sin-contrato",
                               "detalle": f"#{i['number']} {i['title']} (falta: {', '.join(falta)})", "url": i.get("url")})
    avisos += avisos_prioridad(con_proyectos, rojos)
    return {"generado": ahora.isoformat(timespec="seconds"), "repos": list(nodos), "prs": prs,
            "avisos": avisos, "errores": errores}


def workflows_desactivados(nombres, token):
    """Avisos de los workflows que GitHub desactivó por 60 días sin actividad: no vuelven con ningún trigger."""
    avisos = []
    for repo in nombres:
        try:
            d = http("GET", f"{API}/repos/{repo}/actions/workflows?per_page=100", token_de(repo, token))
        except (OSError, ValueError):  # sin acceso o sin red: este refresco no lo comprueba; el siguiente sí
            continue
        for w in d.get("workflows") or []:
            if w.get("state") == "disabled_inactivity":
                archivo = (w.get("path") or w.get("name") or "?").rsplit("/", 1)[-1]
                avisos.append({"repo": repo, "tipo": "workflow-desactivado",
                               "detalle": f"{archivo}: 60 días sin actividad; gh workflow enable {archivo} -R {repo}"})
    return avisos


def recoger(token, ahora=None):
    os.environ["GH_TOKEN"] = token  # filtro_global.leer_remoto lo lee del entorno
    filtro = cargar_filtro()
    nombres = repos(filtro)
    nodos, errores = consultar(nombres, token)
    # Un token de instalación de GitHub App (ghs_) no ve los Projects de una cuenta personal: totalCount sería 0.
    # Las issues de esos repos se leen con un token que los ve (#65); sin él, o si esa consulta falla, siguen
    # ciegos (sin avisos de Projects, que serían falsos) y el motivo va a `errores`. El resto, con `token`.
    ciegos = {n for n in nombres if token_de(n, token).startswith("ghs_")}
    if ciegos:
        tp = token_proyectos(token)
        if not tp:
            errores.append({"repo": "proyectos", "detalle": "sin token que vea los Projects (PROJECTS_TOKEN o "
                            "`gh auth token`): sin avisos issue-sin-proyecto ni listo-sin-contrato"})
        else:
            try:  # nunca tumba el barrido
                vistos, fallos = consultar_proyectos([n for n in nombres if n in ciegos], tp)
                errores += fallos
                for n, v in vistos.items():
                    if v and nodos.get(n):
                        nodos[n]["issues"] = v["issues"]
                        ciegos.discard(n)
            except (Fallo, OSError, ValueError, KeyError) as e:
                errores.append({"repo": "proyectos", "detalle": f"{type(e).__name__}: {e}"[:160]})
    try:  # por la API: el barrido de mario-home solo tiene este script y filtro_global.py; nunca lo tumba
        plantilla = filtro.leer_remoto(*PLANTILLA_TAREA)
        motivo = "no existe" if plantilla is None else "sin campos obligatorios"
    except (OSError, ValueError, KeyError) as e:
        plantilla, motivo = None, f"{type(e).__name__}: {e}"
    if not prioridad:
        errores.append({"repo": "prioridad", "detalle": "sin scripts/prioridad.py junto a este script: "
                        "sin avisos prioridad-distinta ni prioridad-p0-caducada"})
    etiquetas = contrato(plantilla or "")
    if not etiquetas:
        errores.append({"repo": "contrato", "detalle": f"{'/'.join(PLANTILLA_TAREA)}: {motivo}"[:160]})
    estado = analizar(nodos, errores, ahora or datetime.now(timezone.utc), ciegos, etiquetas)
    estado["avisos"] = workflows_desactivados(nombres, token) + estado["avisos"]
    try:
        estado["freno"] = freno(token)
    except Fallo:
        estado["freno"] = None
    try:  # las métricas nunca tumban el barrido ni la línea
        estado["metricas"] = metricas(consultar_metricas(nombres, token, ahora or datetime.now(timezone.utc)),
                                      ahora or datetime.now(timezone.utc))
    except (OSError, ValueError, KeyError) as e:
        estado["errores"].append({"repo": "métricas", "detalle": f"{type(e).__name__}: {e}"[:160]})
    return estado


# --- métricas (mariomina/mario-home#22) ------------------------------------------------

def consultar_metricas(nombres, token, ahora):
    """{owner/repo: nodo GraphQL o None} con PR fusionadas e historial de la rama principal de la ventana mayor."""
    desde = (ahora - timedelta(days=max(VENTANAS))).strftime("%Y-%m-%dT%H:%M:%SZ")
    alias = {f"m{i}": n for i, n in enumerate(nombres)}
    grupos, datos = {}, {}
    for a, n in alias.items():
        grupos.setdefault(token_de(n, token), []).append(a)
    for t, lista in grupos.items():
        campos = " ".join(f'{a}: repository(owner: "{alias[a].split("/")[0]}", name: "{alias[a].split("/")[1]}") '
                          "{ ...M }" for a in lista)
        d = http("POST", f"{API}/graphql", t,
                 {"query": f"query {{ {campos} }}\n{FRAGMENTO_METRICAS.replace('DESDE', desde)}"})
        datos.update(d.get("data") or {})
    nodos = {n: datos.get(a) for a, n in alias.items()}
    for n, nodo in nodos.items():
        if nodo:
            _completar(n, nodo, token_de(n, token), desde)
    return nodos


def _completar(repo, nodo, token, desde):
    """Pagina, solo si hace falta, lo que la consulta con alias cortó en 100: commits de la ventana y PR
    actualizadas dentro de ella (una PR fusionada en la ventana se actualizó en la ventana)."""
    dueno, nombre = repo.split("/")
    historia = (((nodo.get("defaultBranchRef") or {}).get("target") or {}).get("history")) or {}
    while (historia.get("pageInfo") or {}).get("hasNextPage"):
        q = (f'query {{ repository(owner: "{dueno}", name: "{nombre}") {{ defaultBranchRef {{ target {{ ... on Commit '
             f'{{ {HISTORIA.replace("DESDE", desde).replace("CURSOR", ", after: " + json.dumps(historia["pageInfo"]["endCursor"]))} }} }} }} }} }}')
        mas = http("POST", f"{API}/graphql", token, {"query": q})["data"]["repository"]["defaultBranchRef"]["target"]["history"]
        historia["nodes"] += mas["nodes"]
        historia["pageInfo"] = mas["pageInfo"]
    prs = nodo.get("pullRequests") or {}
    while ((prs.get("pageInfo") or {}).get("hasPreviousPage") and prs.get("nodes")
           and min(p["updatedAt"] for p in prs["nodes"]) >= desde):
        q = (f'query {{ repository(owner: "{dueno}", name: "{nombre}") {{ '
             f'{FUSIONADAS.replace("CURSOR", ", before: " + json.dumps(prs["pageInfo"]["startCursor"]))} }} }}')
        mas = http("POST", f"{API}/graphql", token, {"query": q})["data"]["repository"]["pullRequests"]
        prs["nodes"] = mas["nodes"] + prs["nodes"]
        prs["pageInfo"] = mas["pageInfo"]


def metricas(nodos, ahora):
    """{"7": {...}, "28": {...}}: fusionadas, por_bots, reverts, ci_rojo y commits_con_ci por ventana."""
    salida = {}
    for dias in VENTANAS:
        limite = ahora - timedelta(days=dias)
        m = {"fusionadas": 0, "por_bots": 0, "reverts": 0, "ci_rojo": 0, "commits_con_ci": 0}
        for n in nodos.values():
            if not n:
                continue
            for pr in (n.get("pullRequests") or {}).get("nodes") or []:
                if not pr.get("mergedAt") or _fecha(pr["mergedAt"]) < limite:
                    continue
                m["fusionadas"] += 1
                m["reverts"] += bool(RE_REVERT.search(pr.get("title") or ""))
                m["por_bots"] += _autor(pr) in BOTS and _autor({"author": pr.get("mergedBy")}) in BOTS
            historia = ((((n.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {})
                        .get("nodes") or [])
            for c in historia:
                if _fecha(c["committedDate"]) < limite or not c.get("statusCheckRollup"):
                    continue
                m["commits_con_ci"] += 1
                m["ci_rojo"] += c["statusCheckRollup"].get("state") in ("FAILURE", "ERROR")
        salida[str(dias)] = m
    return salida


def linea_metricas(m):
    """«7 d: 12 fusionadas (5 por bots) · 0 reverts · CI rojo 1/20» o '' sin datos."""
    if not m:
        return ""
    return (f"{VENTANAS[0]} d: {m['fusionadas']} fusionadas ({m['por_bots']} por bots) · {m['reverts']} reverts · "
            f"CI rojo {m['ci_rojo']}/{m['commits_con_ci']}")


# --- fusión -------------------------------------------------------------------------

def _motivo(x):
    """El `message` del cuerpo de un HTTPError de GitHub ('' si no lo hay)."""
    try:
        return json.load(x).get("message", "")
    except (ValueError, OSError, AttributeError):
        return ""
    finally:
        x.close()


def freno(token):
    """Título del issue de freno abierto en mario-home, o None. Fallo si no se puede comprobar."""
    try:
        issues = http("GET", f"{API}/repos/{HOME_REPO}/issues?state=open&per_page=100", token_de(HOME_REPO, token))
    except (OSError, ValueError) as x:
        raise Fallo(f"no se puede comprobar el freno ({type(x).__name__})") from None
    for i in issues if isinstance(issues, list) else []:
        if (i.get("title") or "").startswith(FRENO) and "pull_request" not in i:
            return i["title"]
    return None


def _freno_o_motivo(token):
    """Motivo para no fusionar (freno activo o sin comprobar), o None."""
    try:
        titulo = freno(token)
    except Fallo as e:
        return str(e)
    return f"freno activo: {titulo}" if titulo else None


def fusionar(estado, token, discreto=False):
    """Fusiona las PR con acción `fusionar` (con el sha revisado). Un error no corta las demás.
    `discreto`: el log no nombra repos, PR ni títulos (log público)."""
    hechas, errores = [], []
    for e in [p for p in estado["prs"] if p["accion"] == "fusionar"]:
        etiqueta = "una PR" if discreto else f"{e['repo']}#{e['numero']}"
        try:
            http("PUT", f"{API}/repos/{e['repo']}/pulls/{e['numero']}/merge", token_de(e["repo"], token),
                 {"merge_method": e.get("metodo") or "merge", "sha": e["sha"]})
        except urllib.error.HTTPError as x:
            motivo = _motivo(x)
            errores.append({"repo": e["repo"], "detalle": f"#{e['numero']}: HTTP {x.code} {motivo}".strip()})
            print(f"Error al fusionar {etiqueta}: HTTP {x.code}" + ("" if discreto else f" {motivo}"))
            continue
        except (urllib.error.URLError, OSError) as x:
            errores.append({"repo": e["repo"], "detalle": f"#{e['numero']}: {x}"})
            print(f"Error al fusionar {etiqueta}: {type(x).__name__ if discreto else x}")
            continue
        e["accion"] = "fusionada"
        hechas.append(e)
        print(f"Fusionada {etiqueta} ({e['clase']})" + ("" if discreto else f": {e['titulo']}"))
    estado["errores"] = estado.get("errores", []) + errores
    return hechas, errores


def estado_pr_version(repo, numero, token):
    """(state, merged, sha de la cabeza, estado_ci de ese commit) de una PR."""
    dueno, nombre = repo.split("/")
    d = http("POST", f"{API}/graphql", token,
             {"query": PR_VERSION, "variables": {"o": dueno, "n": nombre, "pr": numero}})
    p = ((d.get("data") or {}).get("repository") or {}).get("pullRequest")
    if not p:
        raise Fallo(f"#{numero}: no se puede leer la PR ({((d.get('errors') or [{}])[0]).get('message', '')})")
    commit = (((p.get("commits") or {}).get("nodes") or [{}])[0] or {}).get("commit") or {}
    return p["state"], p["merged"], p["headRefOid"], estado_ci(commit.get("statusCheckRollup"))


def _fusionar_sha(repo, numero, token, sha):
    """PUT merge con el sha revisado, con el primer método que el repo permita. Devuelve el método, o None
    si GitHub aún no la deja fusionar (o la red falló: la siguiente lectura dice si entró). Fallo si no se puede."""
    for metodo in METODOS:
        try:
            http("PUT", f"{API}/repos/{repo}/pulls/{numero}/merge", token, {"merge_method": metodo, "sha": sha})
            return metodo
        except urllib.error.HTTPError as x:
            motivo = _motivo(x)
            if x.code == 405 and "not allowed" in motivo.lower():
                continue
            if x.code in (405, 409):  # aún no fusionable o la cabeza cambió: se vuelve a leer
                print(f"#{numero}: HTTP {x.code} {motivo}".strip())
                return None
            raise Fallo(f"#{numero}: HTTP {x.code} {motivo}".strip()) from None
        except OSError as x:
            print(f"#{numero}: {type(x).__name__}: {x}")
            return None
    raise Fallo(f"#{numero}: ningún método de fusión permitido")


def fusionar_pr_version(repo, numero, token, esperar=None, plazo=ESPERA_CI):
    """Espera al CI de una PR de versión y la fusiona solo con estado_ci = SUCCESS, con el sha que
    pasó el CI (mariomina/.github#28). Devuelve el método, «ya estaba fusionada» o None si el CI sigue en
    curso al acabar el plazo (la fusiona el barrido). Fallo con CI rojo, sin CI o si no se puede fusionar."""
    esperar = esperar or time.sleep
    lecturas = int(plazo.total_seconds() // SONDEO)
    for lectura in range(lecturas + 1):
        estado, fusionada, sha, ci = estado_pr_version(repo, numero, token)
        if fusionada:
            return "ya estaba fusionada"
        if estado != "OPEN":
            raise Fallo(f"#{numero}: cerrada sin fusionar")
        if ci in ("FAILURE", "ERROR"):
            raise Fallo(f"#{numero}: CI rojo ({ci})")
        if ci is None and lectura * SONDEO >= SIN_CI.total_seconds():
            raise Fallo(f"#{numero}: sin CI tras {int(SIN_CI.total_seconds() // 60)} min")
        if ci == "SUCCESS":
            metodo = _fusionar_sha(repo, numero, token, sha)
            if metodo:
                return metodo
        if lectura < lecturas:
            esperar(SONDEO)
    return None


def fusionar_version(prs, repo, token, salida=None, esperar=None):
    """`--fusionar-version`: espera el CI de cada PR de `prs` (JSON de `outputs.prs` de release-please) y la
    fusiona en verde. Escribe `fusionadas=N` en `salida` también si una falla."""
    esperar = esperar or time.sleep
    fusionadas, fallos = 0, 0
    try:
        motivo = _freno_o_motivo(token)
        if motivo:
            print(f"::warning::No se fusiona ninguna PR de versión: {motivo} (mariomina/mario-home#41)")
            return 0
        for pr in json.loads(prs or "[]"):
            try:
                metodo = fusionar_pr_version(repo, pr["number"], token, esperar)
            except (Fallo, OSError, ValueError) as e:
                fallos += 1
                print(f"::error::No se fusionó la PR de versión {e}")
                continue
            if metodo:
                fusionadas += 1
                print(f"#{pr['number']} fusionada ({metodo})")
            else:
                print(f"::warning::#{pr['number']}: el CI sigue en curso; la fusiona el barrido cuando esté en verde")
    finally:
        if salida:
            with open(salida, "a", encoding="utf-8") as f:
                f.write(f"fusionadas={fusionadas}\n")
    return 1 if fallos else 0


def log_publico(token):
    """True si corre en Actions en un repo que no consta como privado: cualquiera lee sus logs, así que
    no se imprimen repos, PR, ramas ni títulos (mariomina/mario-2-cerebro#280: el barrido vive en mario-home)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not os.environ.get("GITHUB_ACTIONS") or not repo:
        return False
    try:
        return not http("GET", f"{API}/repos/{repo}", token).get("private")
    except (OSError, ValueError):
        return True  # sin saberlo, se trata como público


def cuentas(estado):
    """Resumen sin nombres para un log público."""
    prs = estado.get("prs", [])
    n = lambda *acciones: sum(p["accion"] in acciones for p in prs)  # noqa: E731
    return (f"GitHub: {n('fusionada')} fusionadas · {n('decision')} esperan decisión · "
            f"{n('fusionar', 'esperar')} se fusionan solas · {len(estado.get('avisos', []))} avisos · "
            f"{len(estado.get('errores', []))} errores (log público: sin detalle)"
            + (f" · {linea_metricas((estado.get('metricas') or {}).get(str(VENTANAS[0])))}" if estado.get("metricas") else "")
            + "\n")


# --- salidas ------------------------------------------------------------------------

def _corto(repo):
    return repo.split("/", 1)[1] if repo.startswith("mariomina/") else repo


def _hace(iso, ahora):
    minutos = int((ahora - _fecha(iso)).total_seconds() // 60)
    if minutos < 60:
        return f"hace {max(minutos, 0)} min"
    return f"hace {minutos // 60} h" if minutos < 48 * 60 else f"hace {minutos // 1440} d"


def resumen(estado, ahora):
    """La línea «GitHub: …» de la apertura de sesión."""
    if estado.get("error"):
        return f"GitHub: sin datos ({estado['error']})"
    if estado.get("freno"):
        return f"GitHub: FRENO activo, no se fusiona nada ({estado['freno']}) · {_hace(estado['generado'], ahora)}"
    prs = estado.get("prs", [])
    decisiones = [p for p in prs if p["accion"] == "decision"]
    if decisiones:
        grupos = {}
        for p in decisiones:
            grupos.setdefault(p["motivo"], []).append(f"{_corto(p['repo'])}#{p['numero']}")
        partes = [f"{m} ({', '.join(r[:MAX_REFS_LINEA])}{', …' if len(r) > MAX_REFS_LINEA else ''})"
                  for m, r in grupos.items()]
        texto = f"GitHub: {len(decisiones)} esperan tu decisión: {'; '.join(partes)}"
    else:
        texto = "GitHub: nada espera tu decisión"
    solas = sum(p["accion"] in ("fusionar", "esperar") for p in prs)
    if solas:
        texto += f" · {solas} se fusionan solas"
    if estado.get("avisos"):
        texto += f" · {len(estado['avisos'])} avisos"
    if estado.get("errores"):
        texto += f" · {len(estado['errores'])} repos con error"
    if linea_metricas((estado.get("metricas") or {}).get(str(VENTANAS[0]))):
        texto += " · " + linea_metricas(estado["metricas"][str(VENTANAS[0])])
    return texto + f" · {_hace(estado['generado'], ahora)}"


ACCIONES = {"fusionar": "se fusiona sola", "esperar": "se fusiona sola", "decision": "espera tu decisión",
            "borrador": "borrador", "fusionada": "fusionada"}


def tabla(estado, ahora):
    generado = _fecha(estado["generado"]).astimezone().strftime("%Y-%m-%d %H:%M")
    filas = [(f"{p['repo']}#{p['numero']}", p["clase"], f"{ACCIONES.get(p['accion'], p['accion'])} ({p['motivo']})",
              p["titulo"]) for p in estado["prs"]]
    lineas = [f"GitHub · {len(estado['repos'])} repos · {generado}", resumen(estado, ahora)]
    m = estado.get("metricas") or {}
    if m:
        lineas.append("Métricas: " + " | ".join(
            linea_metricas(m[str(d)]).replace(f"{VENTANAS[0]} d:", f"{d} d:", 1) for d in VENTANAS if str(d) in m))
    lineas.append("")
    if filas:
        cab = ("PR", "Clase", "Acción", "Título")
        anchos = [max(len(f[i]) for f in filas + [cab]) for i in range(3)]
        for f in [cab] + filas:
            lineas.append("  ".join(c.ljust(anchos[i]) for i, c in enumerate(f[:3])) + "  " + f[3])
    else:
        lineas.append("Sin PR abiertas.")
    if estado["avisos"]:
        lineas += ["", f"Avisos ({len(estado['avisos'])}):"]
        lineas += [f"  {a['repo']} · {a['tipo']} · {a['detalle']}" for a in estado["avisos"]]
    if estado["errores"]:
        lineas += ["", f"Errores ({len(estado['errores'])}):"]
        lineas += [f"  {e['repo']} · {e['detalle']}" for e in estado["errores"]]
    return "\n".join(lineas) + "\n"


# --- caché --------------------------------------------------------------------------

def leer_cache(ruta=CACHE):
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) and datos.get("generado") else None


def guardar_cache(estado, ruta=CACHE):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")  # dos escritores a la vez no comparten tmp
    tmp.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, ruta)


def refrescar(ruta=CACHE, ahora=None):
    """Consulta GitHub y escribe la caché; un fallo queda en la caché como motivo."""
    ahora = ahora or datetime.now(timezone.utc)
    try:
        try:
            token = obtener_token()
            if not token:
                raise Fallo("sin token")
            estado = recoger(token, ahora)
        except Fallo as e:
            estado = {"generado": ahora.isoformat(timespec="seconds"), "error": str(e)}
        except urllib.error.HTTPError as e:
            estado = {"generado": ahora.isoformat(timespec="seconds"), "error": f"GitHub respondió {e.code}"}
        except (urllib.error.URLError, OSError) as e:
            estado = {"generado": ahora.isoformat(timespec="seconds"),
                      "error": f"sin red: {getattr(e, 'reason', e)}"[:120]}
        except Exception as e:  # noqa: BLE001 - el refresco en segundo plano nunca deja traza
            estado = {"generado": ahora.isoformat(timespec="seconds"), "error": f"{type(e).__name__}: {e}"[:120]}
        guardar_cache(estado, ruta)
    finally:
        ruta.with_suffix(".lock").unlink(missing_ok=True)
    return estado


def lanzar_refresco(ruta=CACHE, ahora=None):
    """Refresco en segundo plano, desligado de quien llama; no lanza otro si hay uno en curso."""
    ahora = ahora or datetime.now(timezone.utc)
    bloqueo = ruta.with_suffix(".lock")
    try:
        if bloqueo.exists() and ahora.timestamp() - bloqueo.stat().st_mtime < BLOQUEO.total_seconds():
            return False
        bloqueo.parent.mkdir(parents=True, exist_ok=True)
        bloqueo.touch()
        subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--refrescar"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        return False
    return True


def linea(ruta=CACHE, ahora=None, lanzar=lanzar_refresco):
    """«GitHub: …» desde la caché, sin esperar a la red; nunca lanza excepción."""
    ahora = ahora or datetime.now(timezone.utc)
    try:
        estado = leer_cache(ruta)
        if estado is None or ahora - _fecha(estado["generado"]) > CADUCA:
            lanzar(ruta, ahora)
        if estado is None:
            return "GitHub: sin datos (primera consulta en curso)"
        return resumen(estado, ahora)
    except Exception as e:  # noqa: BLE001 - la apertura de sesión nunca falla
        return f"GitHub: sin datos ({type(e).__name__}: {e})"[:200]


def hermes(entrada, **kw):
    """Hook pre_llm_call: la línea como contexto en el primer turno; nada en los demás."""
    try:
        evento = json.loads(entrada or "{}")
    except ValueError:
        evento = {}
    evento = evento if isinstance(evento, dict) else {}
    extra = evento.get("extra") if isinstance(evento.get("extra"), dict) else {}
    primero = extra.get("is_first_turn", evento.get("is_first_turn"))
    return {"context": linea(**kw)} if primero else {}


def _stdin():
    try:
        if sys.stdin is None or sys.stdin.isatty() or not select.select([sys.stdin], [], [], 0.5)[0]:
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modo = p.add_mutually_exclusive_group()
    modo.add_argument("--json", action="store_true")
    modo.add_argument("--fusionar", action="store_true")
    modo.add_argument("--linea", action="store_true")
    modo.add_argument("--hermes", action="store_true")
    modo.add_argument("--fusionar-version", action="store_true")
    modo.add_argument("--refrescar", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.linea:
        print(linea())
        return 0
    if a.hermes:
        print(json.dumps(hermes(_stdin()), ensure_ascii=False))
        return 0
    if a.refrescar:
        refrescar()
        return 0
    if a.fusionar_version:
        token, repo = obtener_token(), os.environ.get("GITHUB_REPOSITORY")
        if not token or not repo:
            print("::error::--fusionar-version necesita GH_TOKEN y GITHUB_REPOSITORY", file=sys.stderr)
            return 1
        return fusionar_version(os.environ.get("PRS"), repo, token, os.environ.get("GITHUB_OUTPUT"))
    ahora = datetime.now(timezone.utc)
    token = obtener_token()
    if not token:
        print("github_pendientes: sin token (GH_TOKEN, GITHUB_TOKEN o `gh auth login`)", file=sys.stderr)
        return 1
    discreto = log_publico(token)
    try:
        estado = recoger(token, ahora)
    except (Fallo, OSError, ValueError) as e:  # OSError cubre URLError, timeouts y conexiones cortadas
        print(f"github_pendientes: {type(e).__name__}" + ("" if discreto else f": {e}"), file=sys.stderr)
        return 1
    errores = []
    if a.fusionar:  # las fusionadas siguen en la tabla y la caché como `fusionada`
        motivo = _freno_o_motivo(token)
        if motivo:
            print(f"No se fusiona nada: {motivo}" if not discreto else "No se fusiona nada: freno activo o sin comprobar")
        else:
            _, errores = fusionar(estado, token, discreto)
    if not os.environ.get("GITHUB_ACTIONS"):
        guardar_cache(estado)
    if discreto:
        sys.stdout.write(cuentas(estado))
    else:
        sys.stdout.write(json.dumps(estado, ensure_ascii=False, indent=2) + "\n" if a.json else tabla(estado, ahora))
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
