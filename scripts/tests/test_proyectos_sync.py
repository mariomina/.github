"""Tests de proyectos_sync.py con respuestas GraphQL simuladas. Sin red."""
import datetime as dt
import importlib.util
import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

RUTA = Path(__file__).resolve().parents[1] / "proyectos_sync.py"
with mock.patch.dict(os.environ, {"GH_TOKEN": "t"}):
    spec = importlib.util.spec_from_file_location("proyectos_sync", RUTA)
    ps = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ps)

AHORA = dt.datetime.now(dt.timezone.utc)
HACE_7 = (AHORA - dt.timedelta(days=7)).timestamp()


def hace(dias):
    return (AHORA - dt.timedelta(days=dias)).isoformat().replace("+00:00", "Z")


def pagina(nodos, siguiente=None):
    return {"pageInfo": {"hasNextPage": siguiente is not None, "endCursor": siguiente}, "nodes": nodos}


def issue(n, estado="OPEN", cerrada=None, actualizada=None):
    return {"__typename": "Issue", "id": f"I{n}", "number": n, "state": estado, "closedAt": cerrada,
            "updatedAt": actualizada or cerrada or hace(0)}


def pr(n, estado, creada, cerrada=None, actualizada=None):
    return {"__typename": "PullRequest", "id": f"P{n}", "number": n, "state": estado, "createdAt": creada,
            "closedAt": cerrada, "updatedAt": actualizada or cerrada or creada}


def item(id_, contenido, creado, archivado=False, status=None):
    return {"id": id_, "isArchived": archivado, "createdAt": creado,
            "fieldValueByName": {"optionId": status} if status else None, "content": contenido}


PROYECTO = {"id": "PRJ", "number": 2, "title": "Sistema",
            "field": {"id": "ST", "options": [{"id": "back", "name": "Backlog"}, {"id": "hecho", "name": "Hecho"}]},
            "repositories": {"nodes": [{"nameWithOwner": "dueno/repo"}]}}


class GraphQLFalso:
    """Responde por consulta; `prs` es una lista de páginas para probar el corte de la paginación."""

    def __init__(self, items, abiertas=(), cerradas=(), prs=((),)):
        self.items, self.abiertas, self.cerradas, self.prs = items, list(abiertas), list(cerradas), prs
        self.llamadas = []

    def __call__(self, query, **v):
        self.llamadas.append((query, v))
        if query == ps.ITEMS:
            # Como la API: sin `archivedStates` que incluya ARCHIVED, los archivados no salen.
            ver = "ARCHIVED," in query
            return {"node": {"items": pagina([i for i in self.items if ver or not i["isArchived"]])}}
        if query == ps.ABIERTAS:
            return {"repository": {"issues": pagina(self.abiertas)}}
        if query == ps.CERRADAS:
            return {"repository": {"issues": pagina(self.cerradas)}}
        if query == ps.PRS:
            n = int(v["after"] or 0)
            siguiente = str(n + 1) if n + 1 < len(self.prs) else None
            return {"repository": {"pullRequests": pagina(list(self.prs[n]), siguiente)}}
        if "addProjectV2ItemById" in query:
            return {"addProjectV2ItemById": {"item": {"id": "N" + v["c"]}}}
        return {}

    def mutaciones(self, nombre):
        return [v for q, v in self.llamadas if nombre in q]

    def consultas(self, query):
        return [v for q, v in self.llamadas if q == query]


def sincronizar(falso, dry=False, actions=""):
    with mock.patch.object(ps, "gql", falso), mock.patch.dict(os.environ, {"GITHUB_ACTIONS": actions}):
        return ps.sincronizar(PROYECTO, dry)


class LogPublico(unittest.TestCase):
    def test_en_actions_el_proyecto_sale_por_numero(self):
        p = {"number": 4, "title": "Cliente — acme", "field": None}
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            self.assertEqual(ps.sincronizar(p, True), "  proyecto 4: sin campo Status, se salta")
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            self.assertIn("Cliente — acme", ps.sincronizar(p, True))

    def test_en_actions_la_simulacion_no_nombra_lo_que_añadiria(self):
        falso = GraphQLFalso([], cerradas=[issue(9, "CLOSED", hace(1))])
        self.assertNotIn("repo#9", sincronizar(falso, dry=True, actions="true"))
        self.assertIn("dueno/repo#9", sincronizar(GraphQLFalso([], cerradas=[issue(9, "CLOSED", hace(1))]), dry=True))


class Corte(unittest.TestCase):
    def test_sin_elementos_son_7_dias(self):
        self.assertAlmostEqual(ps.corte([]).timestamp(), HACE_7, delta=5)

    def test_un_alta_reciente_no_acorta_los_7_dias(self):
        self.assertAlmostEqual(ps.corte([item("a", issue(1), hace(0))]).timestamp(), HACE_7, delta=5)

    def test_sin_altas_hace_30_dias_mira_hasta_la_ultima(self):
        d = ps.corte([item("a", issue(1), hace(40)), item("b", issue(2), hace(30)), item("c", None, None)])
        self.assertAlmostEqual(d.timestamp(), (AHORA - dt.timedelta(days=30)).timestamp(), delta=5)


class AltaDeCerradasYPR(unittest.TestCase):
    def test_añade_issue_cerrada_y_pr_fusionada_directas_a_la_ultima_opcion(self):
        falso = GraphQLFalso([], cerradas=[issue(5, "CLOSED", hace(1))],
                             prs=[[pr(6, "MERGED", hace(3), hace(2)), pr(7, "OPEN", hace(1))]])
        salida = sincronizar(falso)
        self.assertEqual({v["c"] for v in falso.mutaciones("addProjectV2ItemById")}, {"I5", "P6", "P7"})
        estados = {v["i"]: v["o"] for v in falso.mutaciones("updateProjectV2ItemFieldValue")}
        self.assertEqual(estados, {"NI5": "hecho", "NP6": "hecho", "NP7": "back"})
        self.assertIn("+3 añadidos", salida)
        self.assertEqual(falso.mutaciones("archiveProjectV2Item"), [])

    def test_no_duplica_ni_reabre_archivados(self):
        cerrada, fusionada = issue(5, "CLOSED", hace(1)), pr(6, "MERGED", hace(3), hace(2))
        falso = GraphQLFalso([item("x", cerrada, hace(1), archivado=True, status="hecho"),
                              item("y", fusionada, hace(2), status="hecho")],
                             cerradas=[cerrada], prs=[[fusionada]])
        self.assertIn("+0 añadidos", sincronizar(falso))
        self.assertEqual(falso.mutaciones("addProjectV2ItemById"), [])
        self.assertEqual(falso.mutaciones("updateProjectV2ItemFieldValue"), [])

    def test_lo_cerrado_antes_del_corte_no_entra(self):
        falso = GraphQLFalso([], cerradas=[issue(5, "CLOSED", hace(9), actualizada=hace(1))],
                             prs=[[pr(6, "MERGED", hace(20), hace(10), actualizada=hace(1)),
                                   pr(7, "OPEN", hace(12), actualizada=hace(1))]])
        self.assertIn("+0 añadidos", sincronizar(falso))
        self.assertEqual(falso.mutaciones("addProjectV2ItemById"), [])

    def test_las_cerradas_se_piden_desde_el_corte(self):
        falso = GraphQLFalso([])
        sincronizar(falso, dry=True)
        (v,) = falso.consultas(ps.CERRADAS)
        self.assertAlmostEqual(dt.datetime.fromisoformat(v["desde"].replace("Z", "+00:00")).timestamp(), HACE_7,
                               delta=5)

    def test_las_pr_dejan_de_paginar_al_pasar_el_corte(self):
        falso = GraphQLFalso([], prs=[[pr(8, "MERGED", hace(2), hace(1)), pr(3, "CLOSED", hace(30), hace(20))],
                                      [pr(2, "MERGED", hace(1), hace(1))]])
        sincronizar(falso, dry=True)
        self.assertEqual(len(falso.consultas(ps.PRS)), 1)

    def test_simulacion_sin_mutaciones_cuenta_lo_que_haria(self):
        falso = GraphQLFalso([], abiertas=[issue(4)], cerradas=[issue(5, "CLOSED", hace(1))],
                             prs=[[pr(6, "MERGED", hace(3), hace(2))]])
        salida = sincronizar(falso, dry=True)
        self.assertEqual([q for q, _ in falso.llamadas if q.startswith("mutation")], [])
        self.assertIn("+3 añadidos · 1 → Backlog · 2 → Hecho", salida)
        for ref in ("dueno/repo#4", "dueno/repo#5", "dueno/repo#6"):
            self.assertIn(ref, salida)


class Principal(unittest.TestCase):
    def test_salta_proyectos_cerrados_y_plantillas(self):
        nodos = [{**PROYECTO, "closed": True, "template": False}, {**PROYECTO, "closed": False, "template": True}]
        respuesta = {"repositoryOwner": {"projectsV2": {"nodes": nodos}}}
        with mock.patch.object(ps, "gql", return_value=respuesta), redirect_stdout(io.StringIO()) as out:
            ps.main(["dueno", "--dry-run"])
        self.assertEqual(out.getvalue(), "dueno (simulación)\n")


if __name__ == "__main__":
    unittest.main()
