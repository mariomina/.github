"""Automatizaciones de GitHub Projects por GraphQL (sustituyen a los workflows integrados, que no tienen API).

Por cada proyecto abierto y no plantilla de cada dueño:
  1. Auto-add: añade de los repos enlazados las issues abiertas y, desde la fecha de corte (`corte`), las issues
     cerradas y las PR (abiertas, fusionadas o cerradas). Lo que ya está, archivado o no, no se toca. Con --dry-run
     lista lo que añadiría (en Actions, solo cuántos: el log es público).
  2. Item nuevo (sin Status) -> primera opción de Status (Backlog, Brief...).
  3. Item cerrado o PR fusionada/cerrada -> última opción de Status (Hecho, Entregado...).
  4. Item en la última opción, cerrado hace más de ARCHIVAR_DIAS días -> archivado.
  5. Item abierto sin Prioridad, en un proyecto con ese campo -> la que calcula `prioridad.py` (mariomina/mario-home#239),
     también lo creado en la web. La que ya tiene un valor no se toca: la puso alguien, con su motivo.

Uso: GH_TOKEN=... python proyectos_sync.py <dueño> [<dueño>...] [--dry-run]
"""
import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.request
from pathlib import Path

API = "https://api.github.com/graphql"
ARCHIVAR_DIAS = int(os.environ.get("ARCHIVAR_DIAS", "14"))
TOKEN = os.environ.get("GH_TOKEN") or sys.exit("Falta GH_TOKEN")

# Por ruta: con `python3 -I` la carpeta del script no está en sys.path.
_spec = importlib.util.spec_from_file_location("prioridad", Path(__file__).resolve().parent / "prioridad.py")
prioridad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prioridad)


def gql(query, **variables):
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if d.get("errors"):
        raise RuntimeError(json.dumps(d["errors"], ensure_ascii=False))
    return d["data"]


PROYECTOS = """query($login:String!){ repositoryOwner(login:$login){ ... on ProjectV2Owner { projectsV2(first:50){ nodes{
  id number title closed template shortDescription
  field(name:"Status"){ ... on ProjectV2SingleSelectField{ id options{ id name } } }
  fields(first:50){ nodes{ ... on ProjectV2SingleSelectField{ id name options{ id name } } } }
  repositories(first:50){ nodes{ nameWithOwner } } } } } } }"""

# `items` omite los archivados si no se piden: sin ellos, el auto-add los volvería a añadir.
ITEMS = """query($id:ID!,$after:String){ node(id:$id){ ... on ProjectV2{
  items(first:100, after:$after, archivedStates:[ARCHIVED, NOT_ARCHIVED]){
  pageInfo{ hasNextPage endCursor }
  nodes{ id isArchived createdAt fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ optionId } }
    CAMPOS_ITEM
    content{ __typename ... on Issue{ state closedAt repository{ nameWithOwner } CAMPOS_ISSUE }
             ... on PullRequest{ state closedAt repository{ nameWithOwner } CAMPOS_PR } } } } } } }""".replace(
    "CAMPOS_ITEM", prioridad.CAMPOS_ITEM).replace("CAMPOS_ISSUE", prioridad.CAMPOS_ISSUE).replace(
    "CAMPOS_PR", prioridad.CAMPOS_PR)

CONTENIDO = "__typename id number state closedAt updatedAt repository{ nameWithOwner } " + prioridad.CAMPOS_ISSUE
CONTENIDO_PR = "__typename id number state closedAt updatedAt repository{ nameWithOwner } " + prioridad.CAMPOS_PR

ABIERTAS = """query($owner:String!,$name:String!,$after:String){ repository(owner:$owner,name:$name){
  issues(states:OPEN, first:100, after:$after){ pageInfo{ hasNextPage endCursor } nodes{ %s } } } }""" % CONTENIDO

# `since` filtra por updatedAt, que nunca es anterior a closedAt.
CERRADAS = """query($owner:String!,$name:String!,$after:String,$desde:DateTime!){ repository(owner:$owner,name:$name){
  issues(states:CLOSED, first:100, after:$after, filterBy:{since:$desde}){
    pageInfo{ hasNextPage endCursor } nodes{ %s } } } }""" % CONTENIDO

# Las PR no tienen `since`: se piden de la más a la menos actualizada y se deja de paginar al pasar el corte.
PRS = """query($owner:String!,$name:String!,$after:String){ repository(owner:$owner,name:$name){
  pullRequests(first:100, after:$after, orderBy:{field:UPDATED_AT, direction:DESC}){
    pageInfo{ hasNextPage endCursor } nodes{ %s } } } }""" % CONTENIDO_PR
CORTE_DIAS = 7

# Estado del CI de la rama principal de cada repo, en una consulta con alias: el primer commit con checks.
CI_PRINCIPAL = ('r{}: repository(owner:"{}", name:"{}"){{ nameWithOwner defaultBranchRef{{ target{{ ... on Commit{{ '
                'history(first:5){{ nodes{{ statusCheckRollup{{ state }} }} }} }} }} }} }}')


def paginar(query, ruta, **v):
    after = None
    while True:
        d = gql(query, after=after, **v)
        for k in ruta:
            d = d[k]
        yield from d["nodes"]
        if not d["pageInfo"]["hasNextPage"]:
            return
        after = d["pageInfo"]["endCursor"]


def _nombre(p):
    """Título del proyecto; en Actions, solo su número: el log de este repo es público y un proyecto
    «Cliente — <slug>» nombraría al cliente."""
    return f"proyecto {p.get('number', '?')}" if os.environ.get("GITHUB_ACTIONS") else p["title"]


def _fecha(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def corte(items):
    """Desde cuándo se buscan issues cerradas y PR: hace CORTE_DIAS días, o antes si el alta más reciente del
    proyecto es más antigua (un proyecto sin pases recientes no pierde lo que se cerró entre medias)."""
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=CORTE_DIAS)
    altas = [_fecha(i["createdAt"]) for i in items if i.get("createdAt")]
    return min([limite, max(altas)] if altas else [limite])


def candidatos(owner, name, desde):
    """Contenido del repo que el proyecto debe tener: issues abiertas, y cerradas y PR posteriores al corte."""
    yield from paginar(ABIERTAS, ["repository", "issues"], owner=owner, name=name)
    for c in paginar(CERRADAS, ["repository", "issues"], owner=owner, name=name, desde=desde.isoformat()):
        if _fecha(c["closedAt"]) >= desde:
            yield c
    for c in paginar(PRS, ["repository", "pullRequests"], owner=owner, name=name):
        if _fecha(c["updatedAt"]) < desde:
            return
        if _fecha(c["createdAt"] if c["state"] == "OPEN" else c["closedAt"]) >= desde:
            yield c


def ci_rojo(repos):
    """{owner/repo} con CI rojo en la rama principal, en una sola consulta (como el aviso de github_pendientes)."""
    if not repos:
        return set()
    campos = " ".join(CI_PRINCIPAL.format(i, *r.split("/")) for i, r in enumerate(sorted(repos)))
    rojos = set()
    for nodo in gql(f"query{{ {campos} }}").values():
        historia = ((((nodo or {}).get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}).get("nodes") or []
        estado = next((c["statusCheckRollup"].get("state") for c in historia if c.get("statusCheckRollup")), None)
        if estado in ("FAILURE", "ERROR"):
            rojos.add(nodo["nameWithOwner"])
    return rojos


def campo_prioridad(p):
    """El campo Prioridad del proyecto, o None. Por la lista: `field(name:)` falla si el proyecto no lo tiene."""
    return next((f for f in (p.get("fields") or {}).get("nodes") or [] if f.get("name") == prioridad.CAMPO), None)


def priorizar(p, items, dry):
    """Pone la prioridad calculada a los items abiertos sin ella. [(referencia, nivel, motivo)] de los que cambia."""
    campo = campo_prioridad(p) or {}
    opciones = {o["name"]: o["id"] for o in campo.get("options") or []}
    if not campo.get("id") or not set(prioridad.NIVELES) <= set(opciones):
        return []
    abiertos = [i for i in items if not i["isArchived"] and (i.get("content") or {}).get("state") == "OPEN"
                and i["content"].get("__typename") in ("Issue", "PullRequest")]
    sin_prioridad = [i for i in abiertos if not (i.get("prioridad") or {}).get("name")]
    if not sin_prioridad:
        return []
    def repo(i):
        return (i["content"].get("repository") or {}).get("nameWithOwner")
    rojos = ci_rojo({repo(i) for i in sin_prioridad if repo(i)})
    elementos = {i["content"]["id"]: prioridad.desde_graphql(i["content"], i, repo(i) in rojos) for i in abiertos}
    ctx = prioridad.contexto(list(elementos.values()), prioridad.paso_actual(p.get("shortDescription")))
    puestos = []
    for i in sin_prioridad:
        calculada = prioridad.prioridad(elementos[i["content"]["id"]], ctx)
        puestos.append((f"{repo(i)}#{i['content'].get('number', '?')}", calculada.nivel, calculada.motivo))
        if not dry:
            gql("mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}",
                p=p["id"], i=i["id"], f=campo["id"], o=opciones[calculada.nivel])
    return puestos


def sincronizar(p, dry):
    st = p["field"]
    if not st or not st["options"]:
        return f"  {_nombre(p)}: sin campo Status, se salta"
    primera, ultima = st["options"][0], st["options"][-1]
    items = list(paginar(ITEMS, ["node", "items"], id=p["id"]))
    en_proyecto = {i["content"]["id"] for i in items if i.get("content") and i["content"].get("id")}
    desde = corte(items)
    añadidos = []
    for repo in p["repositories"]["nodes"]:
        owner, name = repo["nameWithOwner"].split("/")
        for c in candidatos(owner, name, desde):
            if c["id"] in en_proyecto:
                continue
            en_proyecto.add(c["id"])
            añadidos.append(f"{repo['nameWithOwner']}#{c['number']} ({c['__typename']}, {c['state']})")
            item_id = None
            if not dry:
                item_id = gql("mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}",
                              p=p["id"], c=c["id"])["addProjectV2ItemById"]["item"]["id"]
            # Sin Status: el bucle siguiente lo deja en la última opción si ya está cerrado, o en la primera si no.
            items.append({"id": item_id, "isArchived": False, "fieldValueByName": None, "content": c})
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=ARCHIVAR_DIAS)
    nuevos = cerrados = archivados = 0
    for i in items:
        c = i.get("content") or {}
        if i["isArchived"] or c.get("__typename") not in ("Issue", "PullRequest"):
            continue
        actual = (i.get("fieldValueByName") or {}).get("optionId")
        cerrado = c.get("state") in ("CLOSED", "MERGED")
        destino = ultima["id"] if cerrado else (primera["id"] if actual is None else None)
        if destino and destino != actual:
            if cerrado:
                cerrados += 1
            else:
                nuevos += 1
            if not dry:
                gql("mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,value:{singleSelectOptionId:$o}}){projectV2Item{id}}}",
                    p=p["id"], i=i["id"], f=st["id"], o=destino)
            actual = destino
        if cerrado and actual == ultima["id"] and c.get("closedAt"):
            if _fecha(c["closedAt"]) < limite:
                archivados += 1
                if not dry:
                    gql("mutation($p:ID!,$i:ID!){archiveProjectV2Item(input:{projectId:$p,itemId:$i}){item{id}}}", p=p["id"], i=i["id"])
    puestos = priorizar(p, items, dry)
    resumen = (f"  {_nombre(p)}: +{len(añadidos)} añadidos · {nuevos} → {primera['name']} · "
               f"{cerrados} → {ultima['name']} · {archivados} archivados")
    if campo_prioridad(p):
        resumen += f" · {len(puestos)} → {prioridad.CAMPO}"
    if dry and not os.environ.get("GITHUB_ACTIONS"):
        resumen += "".join(f"\n    + {a}" for a in añadidos)
        resumen += "".join(f"\n    = {ref} → {nivel} ({motivo})" for ref, nivel, motivo in puestos)
    return resumen


def main(argv):
    dry = "--dry-run" in argv
    dueños = [a for a in argv if not a.startswith("--")] or sys.exit(__doc__)
    for login in dueños:
        print(f"{login}{' (simulación)' if dry else ''}")
        for p in gql(PROYECTOS, login=login)["repositoryOwner"]["projectsV2"]["nodes"]:
            if p["closed"] or p["template"]:
                continue
            print(sincronizar(p, dry))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as e:  # noqa: BLE001
        if not os.environ.get("GITHUB_ACTIONS"):
            raise
        # El log de este repo es público: el detalle (errores de GraphQL) puede nombrar repos o issues privados.
        sys.exit(f"proyectos_sync: {type(e).__name__} (detalle: ejecutarlo en local con --dry-run)")
