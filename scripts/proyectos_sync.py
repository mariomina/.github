"""Automatizaciones de GitHub Projects por GraphQL (sustituyen a los workflows integrados, que no tienen API).

Por cada proyecto abierto y no plantilla de cada dueño:
  1. Auto-add: añade los issues abiertos de los repos enlazados al proyecto.
  2. Item nuevo (sin Status) -> primera opción de Status (Backlog, Brief...).
  3. Item cerrado o PR fusionada/cerrada -> última opción de Status (Hecho, Entregado...).
  4. Item en la última opción, cerrado hace más de ARCHIVAR_DIAS días -> archivado.

Uso: GH_TOKEN=... python proyectos_sync.py <dueño> [<dueño>...] [--dry-run]
"""
import datetime as dt
import json
import os
import sys
import urllib.request

API = "https://api.github.com/graphql"
ARCHIVAR_DIAS = int(os.environ.get("ARCHIVAR_DIAS", "14"))
TOKEN = os.environ.get("GH_TOKEN") or sys.exit("Falta GH_TOKEN")


def gql(query, **variables):
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if d.get("errors"):
        raise RuntimeError(json.dumps(d["errors"], ensure_ascii=False))
    return d["data"]


PROYECTOS = """query($login:String!){ repositoryOwner(login:$login){ ... on ProjectV2Owner { projectsV2(first:50){ nodes{
  id number title closed template
  field(name:"Status"){ ... on ProjectV2SingleSelectField{ id options{ id name } } }
  repositories(first:50){ nodes{ nameWithOwner } } } } } } }"""

ITEMS = """query($id:ID!,$after:String){ node(id:$id){ ... on ProjectV2{ items(first:100, after:$after){
  pageInfo{ hasNextPage endCursor }
  nodes{ id isArchived fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ optionId } }
    content{ __typename ... on Issue{ id state closedAt } ... on PullRequest{ id state closedAt } } } } } } }"""

ABIERTOS = """query($owner:String!,$name:String!,$after:String){ repository(owner:$owner,name:$name){
  issues(states:OPEN, first:100, after:$after){ pageInfo{ hasNextPage endCursor } nodes{ id } } } }"""


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


def sincronizar(p, dry):
    st = p["field"]
    if not st or not st["options"]:
        return f"  {_nombre(p)}: sin campo Status, se salta"
    primera, ultima = st["options"][0], st["options"][-1]
    items = list(paginar(ITEMS, ["node", "items"], id=p["id"]))
    en_proyecto = {i["content"]["id"] for i in items if i.get("content") and i["content"].get("id")}
    añadidos = 0
    for repo in p["repositories"]["nodes"]:
        owner, name = repo["nameWithOwner"].split("/")
        for issue in paginar(ABIERTOS, ["repository", "issues"], owner=owner, name=name):
            if issue["id"] in en_proyecto:
                continue
            añadidos += 1
            if not dry:
                item = gql("mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}",
                           p=p["id"], c=issue["id"])["addProjectV2ItemById"]["item"]
                items.append({"id": item["id"], "isArchived": False, "fieldValueByName": None,
                              "content": {"__typename": "Issue", "id": issue["id"], "state": "OPEN", "closedAt": None}})
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
            if dt.datetime.fromisoformat(c["closedAt"].replace("Z", "+00:00")) < limite:
                archivados += 1
                if not dry:
                    gql("mutation($p:ID!,$i:ID!){archiveProjectV2Item(input:{projectId:$p,itemId:$i}){item{id}}}", p=p["id"], i=i["id"])
    return (f"  {_nombre(p)}: +{añadidos} añadidos · {nuevos} → {primera['name']} · "
            f"{cerrados} → {ultima['name']} · {archivados} archivados")


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
