"""Tests de github_pendientes.py (mariomina/mario-2-cerebro#280), sin red. Ejecutar: python3 -m unittest discover -s scripts/tests"""
import importlib.util
import io
import json
import re
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

RUTA = Path(__file__).resolve().parents[1] / "github_pendientes.py"
spec = importlib.util.spec_from_file_location("github_pendientes", RUTA)
gp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gp)

AHORA = datetime(2026, 11, 14, 20, 0, tzinfo=timezone.utc)


def iso(delta):
    return (AHORA - delta).isoformat().replace("+00:00", "Z")


def pr(numero, titulo, cabeza, autor="mario", ci=None, edad=timedelta(hours=1), borrador=False, fork=False):
    return {"number": numero, "title": titulo, "url": f"https://x/{numero}", "createdAt": iso(edad),
            "updatedAt": iso(edad), "isDraft": borrador, "isCrossRepository": fork, "headRefName": cabeza,
            "headRefOid": f"sha{numero}", "author": {"login": autor},
            "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": ci} if ci else None}}]}}


def dependabot(numero, desde, hasta, ci="SUCCESS"):
    return pr(numero, f"chore: Bump org/accion from {desde} to {hasta}", f"dependabot/github_actions/x-{numero}",
              autor="dependabot", ci=ci)


def version(numero, ci="SUCCESS"):
    """PR de versión de la App: la única que el barrido fusiona solo (Dependabot espera veredicto, #134)."""
    return pr(numero, "chore(main): release 1.0.0", f"release-please--branches--r{numero}",
              "mariomina-automatizacion", ci=ci)


def repo(prs=(), principal="SUCCESS", ramas=(), issues=(), merge=True, historia=None):
    historia = [{"statusCheckRollup": {"state": e} if e else None} for e in (historia or [principal])]
    return {"mergeCommitAllowed": merge, "squashMergeAllowed": True, "rebaseMergeAllowed": True,
            "defaultBranchRef": {"name": "main", "target": {"history": {"nodes": historia}}},
            "pullRequests": {"nodes": list(prs)},
            "refs": {"nodes": [{"name": "main", "target": {"committedDate": iso(timedelta(days=30))}}]
                     + [{"name": n, "target": {"committedDate": iso(e)}} for n, e in ramas]},
            "issues": {"nodes": [{"number": n, "title": f"issue {n}", "url": "u",
                                  "projectItems": {"totalCount": t}} for n, t in issues]}}


def acciones(estado):
    return {(p["repo"], p["numero"]): (p["clase"], p["accion"]) for p in estado["prs"]}


class Clasificacion(unittest.TestCase):
    def test_salto_semver(self):
        casos = {"Bump a from 5.1 to 5.2": "menor", "Bump a from 1.2.3 to 1.2.4": "parche",
                 "Bump a from 5 to 7": "mayor", "Bump a from v4.1.0 to v5.0.0": "mayor",
                 "Bump the x group across 1 directory with 3 updates": "mayor",
                 "Bump a from 0.1.0 to 0.2.0": "mayor", "Bump a from 0.1.0 to 0.1.1": "parche",
                 "Bump a from 1.2.3 to 1.3.0-rc.1": "mayor", "Update requirement from >=1.0 to >=1.1": "mayor",
                 "Bump a from 5.2 to 5.1": "mayor", "Bump a from 1.2.4 to 1.2.3": "mayor",
                 "Bump a from 0.0.1 to 0.0.2": "mayor"}
        for titulo, esperado in casos.items():
            self.assertEqual(gp.salto(titulo), esperado, titulo)

    def test_matriz_de_prs(self):
        nodos = {"o/a": repo([
            pr(1, "chore(main): release 1.1.0", "release-please--branches--main", "github-actions",
               edad=timedelta(minutes=2)),
            pr(2, "chore(master): release pkm 1.1.0", "release-please--branches--master--components--pkm",
               "github-actions", ci="SUCCESS", edad=timedelta(minutes=30)),
            dependabot(3, "5.1", "5.2"),
            dependabot(4, "5.1", "5.2", ci="PENDING"),
            dependabot(5, "5.1", "5.2", ci=None),
            dependabot(6, "5.1", "5.2", ci="FAILURE"),
            dependabot(7, "5", "7"),
            pr(8, "chore: Bump the x group with 2 updates", "dependabot/npm/g", "dependabot[bot]", ci="SUCCESS"),
            pr(9, "feat: algo", "feat/9-algo"),
            pr(10, "feat: borrador", "feat/10-b", borrador=True),
            pr(11, "chore: release", "release-please--branches--a", "github-actions", edad=timedelta(minutes=30)),
            pr(12, "chore: release", "release-please--branches--b", "mariomina-automatizacion[bot]", ci="FAILURE"),
            pr(13, "chore: release", "release-please--branches--c", "mariomina-automatizacion", ci="PENDING"),
            pr(14, "chore: release", "release-please--branches--d", "app/mariomina-automatizacion", ci="SUCCESS"),
        ])}
        estado = gp.analizar(nodos, [], AHORA)
        self.assertEqual(acciones(estado), {
            ("o/a", 1): ("version", "esperar"), ("o/a", 2): ("version", "fusionar"),
            ("o/a", 3): ("dependabot-menor", "decision"), ("o/a", 4): ("dependabot-menor", "esperar"),
            ("o/a", 5): ("dependabot-menor", "decision"), ("o/a", 6): ("dependabot-menor", "decision"),
            ("o/a", 7): ("dependabot-mayor", "decision"), ("o/a", 8): ("dependabot-mayor", "decision"),
            ("o/a", 9): ("trabajo", "decision"), ("o/a", 10): ("trabajo", "borrador"),
            ("o/a", 11): ("version", "decision"), ("o/a", 12): ("version", "decision"),
            ("o/a", 13): ("version", "esperar"), ("o/a", 14): ("version", "fusionar")})
        self.assertEqual(next(p["motivo"] for p in estado["prs"] if p["numero"] == 3),
                         "Dependabot: falta veredicto y permiso")
        motivos = {p["numero"]: p["motivo"] for p in estado["prs"] if p["clase"] == "version"}
        self.assertEqual(motivos, {1: "CI en curso", 2: "CI en verde", 11: "PR de versión sin CI",
                                   12: "PR de versión con CI rojo", 13: "CI en curso", 14: "CI en verde"})

    def test_ramas_de_version_o_dependabot_desde_un_fork_son_trabajo(self):
        rama_rp = "release-please--branches--main"
        nodos = {"o/a": repo([
            pr(1, "chore: release", rama_rp, "github-actions", fork=True),
            pr(2, "chore: release", rama_rp, "mario"),
            pr(3, "chore: Bump a from 5.1 to 5.2", "dependabot/x", "mario", ci="SUCCESS"),
            pr(4, "chore: Bump a from 5.1 to 5.2", "dependabot/x", "dependabot", ci="SUCCESS", fork=True),
            pr(5, "chore: release", rama_rp, "github-actions[bot]"),
            pr(6, "chore: release", rama_rp, "app/github-actions"),
            pr(7, "chore: Bump a from 5.1 to 5.2", "otra", "dependabot[bot]", ci="SUCCESS"),
        ])}
        clases = {n: c for (_, n), (c, _) in acciones(gp.analizar(nodos, [], AHORA)).items()}
        self.assertEqual(clases, {1: "trabajo", 2: "trabajo", 3: "trabajo", 4: "trabajo", 5: "version",
                                  6: "version", 7: "dependabot-menor"})

    def test_ci_rojo_mira_el_primer_commit_con_checks(self):
        def tipos(historia):
            return [a["tipo"] for a in gp.analizar({"o/a": repo(historia=historia)}, [], AHORA)["avisos"]]
        self.assertEqual(tipos([None, "FAILURE", "SUCCESS"]), ["ci-rojo"])
        self.assertEqual(tipos([None, "SUCCESS", "FAILURE"]), [])
        self.assertEqual(tipos([None, None]), [])

    def test_las_9_prs_de_hoy(self):
        version = [("mariomina/mario-home", 1, "main"), ("mariomina/mario-2-cerebro", 278, "master--components--sistema"),
                   ("mariomina/mario-2-cerebro", 279, "master--components--pkm"), ("mariomina/mario-copy-os", 16, "main"),
                   ("Escala-Agencia/agencia-web", 2, "main")]
        nodos = {}
        for r, n, rama in version:
            nodos.setdefault(r, repo())["pullRequests"]["nodes"].append(
                pr(n, "chore: release", f"release-please--branches--{rama}", "github-actions", ci="SUCCESS",
                   edad=timedelta(hours=1)))
        nodos["mariomina/.github"] = repo([dependabot(1, "6", "7", ci=None), dependabot(2, "4", "5"),
                                           dependabot(3, "5", "6", ci=None), dependabot(4, "5", "7")])
        estado = gp.analizar(nodos, [], AHORA)
        fusionar = sorted((p["repo"], p["numero"]) for p in estado["prs"] if p["accion"] == "fusionar")
        self.assertEqual(fusionar, sorted((r, n) for r, n, _ in version))
        self.assertEqual([p["numero"] for p in estado["prs"] if p["accion"] == "decision"], [1, 2, 3, 4])

    def test_avisos(self):
        nodos = {"o/a": repo([pr(1, "feat: vieja", "feat/1", edad=timedelta(days=9))], principal="FAILURE",
                             ramas=[("feat/vieja", timedelta(days=8)), ("feat/nueva", timedelta(days=1)),
                                    ("feat/1", timedelta(days=9))],
                             issues=[(5, 0), (6, 1)])}
        avisos = sorted((a["tipo"], a["detalle"].split(" ")[0]) for a in gp.analizar(nodos, [], AHORA)["avisos"])
        self.assertEqual(avisos, [("ci-rojo", "CI"), ("issue-sin-proyecto", "#5"), ("pr-vieja", "#1"),
                                  ("rama-vieja", "feat/vieja")])

    def test_sin_aviso_de_proyecto_si_el_token_no_ve_los_projects(self):
        nodos = {"o/a": repo(issues=[(5, 0)]), "o/b": repo(issues=[(7, 0)])}
        avisos = [(a["repo"], a["tipo"]) for a in gp.analizar(nodos, [], AHORA, sin_proyectos={"o/a"})["avisos"]]
        self.assertEqual(avisos, [("o/b", "issue-sin-proyecto")])

    def test_recoger_trata_los_tokens_de_app_como_ciegos_a_projects(self):
        nodos = {"o/a": repo(issues=[(5, 0)]), "e/w": repo(issues=[(7, 0)])}
        with mock.patch.object(gp, "repos", return_value=["o/a", "e/w"]), \
                mock.patch.object(gp, "consultar", return_value=(nodos, [])), \
                mock.patch.object(gp, "workflows_desactivados", return_value=[]), \
                mock.patch.object(gp, "consultar_metricas", return_value={}), \
                mock.patch.object(gp, "freno", return_value=None), \
                mock.patch.dict("os.environ", {"GH_TOKEN_E": "gho_usuario"}):
            avisos = [(a["repo"], a["tipo"]) for a in gp.recoger("ghs_app", AHORA)["avisos"]]
        self.assertEqual(avisos, [("e/w", "issue-sin-proyecto")])

    def test_repo_sin_acceso_es_error(self):
        estado = gp.analizar({"o/a": None}, [], AHORA)
        self.assertEqual(estado["errores"], [{"repo": "o/a", "detalle": "sin acceso o no existe"}])


class Repos(unittest.TestCase):
    def test_cascada_por_home_repos(self):
        filtro = gp.cargar_filtro()
        textos = {
            gp.HOME_REPO: "tipo-repo: home\n\n## Otros repos\n\n"
                          "- **a**: `~/Documentos/Mario/a`. `git clone git@github.com:o/a.git`.\n"
                          "- **ag**: `~/Documentos/Mario/ag`. `git clone git@github.com:e/ag.git`.\n"
                          "- **x**: `~/Documentos/Mario/x-<slug>`.\n",
            "o/a": "tipo-repo: producto\n",
            "e/ag": "tipo-repo: home\n\n## Otros repos\n\n"
                    "- **w**: `~/Documentos/Mario/w`. `git clone git@github.com:e/w.git`.\n"
                    "- **a**: `~/Documentos/Mario/a`. `git clone git@github.com:o/a.git`.\n",
        }
        with mock.patch.object(filtro, "leer_remoto", side_effect=textos.get):
            self.assertEqual(gp.repos(filtro), [gp.HOME_REPO, "o/a", "e/ag", "e/w"])

    def test_sin_agents_md_de_home(self):
        filtro = gp.cargar_filtro()
        with mock.patch.object(filtro, "leer_remoto", return_value=None), self.assertRaises(gp.Fallo):
            gp.repos(filtro)


class Fusion(unittest.TestCase):
    def test_fusiona_con_sha_y_metodo_y_sigue_tras_un_error(self):
        nodos = {"o/a": repo([version(3), dependabot(7, "5", "7")], merge=False),
                 "o/b": repo([pr(2, "chore: release", "release-please--branches--main", "github-actions",
                                 ci="SUCCESS", edad=timedelta(hours=1))])}
        estado = gp.analizar(nodos, [], AHORA)
        llamadas = []

        def http(metodo, url, token, cuerpo=None):
            llamadas.append((metodo, url, cuerpo))
            if "/o/a/" in url:
                raise urllib.error.HTTPError(url, 405, "x", {}, io.BytesIO(b'{"message": "not mergeable"}'))
            return {"merged": True}

        with mock.patch.object(gp, "http", http), mock.patch("builtins.print"):
            hechas, errores = gp.fusionar(estado, "t")
        self.assertEqual(llamadas, [
            ("PUT", f"{gp.API}/repos/o/a/pulls/3/merge", {"merge_method": "squash", "sha": "sha3"}),
            ("PUT", f"{gp.API}/repos/o/b/pulls/2/merge", {"merge_method": "squash", "sha": "sha2"})])
        self.assertEqual([(h["repo"], h["numero"]) for h in hechas], [("o/b", 2)])
        self.assertEqual(errores, [{"repo": "o/a", "detalle": "#3: HTTP 405 not mergeable"}])

    def test_fusiona_con_el_token_del_dueno(self):
        estado = gp.analizar({"Escala-Agencia/w": repo([version(3)]),
                              "o/a": repo([version(4)])}, [], AHORA)
        tokens = []
        with mock.patch.object(gp, "http", lambda m, url, token, c=None: tokens.append((url.split("/")[5], token))), \
                mock.patch.dict("os.environ", {"GH_TOKEN_ESCALA_AGENCIA": "te"}), mock.patch("builtins.print"):
            gp.fusionar(estado, "t")
        self.assertEqual(tokens, [("w", "te"), ("a", "t")])

    def test_main_fusionar_registra_las_fusionadas_y_sale_con_1_si_alguna_falla(self):
        nodos = {"o/a": repo([version(3)]),
                 "o/b": repo([pr(2, "chore: release", "release-please--branches--main", "github-actions",
                                 ci="SUCCESS")])}
        estado = gp.analizar(nodos, [], AHORA)

        def http(metodo, url, token, cuerpo=None):
            if "/o/a/" in url:
                raise urllib.error.HTTPError(url, 409, "x", {}, io.BytesIO(b'{"message": "Head branch was modified"}'))
            return {"merged": True}

        salida = io.StringIO()
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.object(gp, "recoger", return_value=estado), mock.patch.object(gp, "http", http), \
                mock.patch.object(gp, "guardar_cache") as guardar, mock.patch("sys.stdout", salida), \
                mock.patch.dict("os.environ", {"GITHUB_ACTIONS": ""}):  # en Actions, main no escribe la caché
            self.assertEqual(gp.main(["--fusionar"]), 1)
        acc = {(p["repo"], p["numero"]): p["accion"] for p in guardar.call_args.args[0]["prs"]}
        self.assertEqual(acc, {("o/a", 3): "fusionar", ("o/b", 2): "fusionada"})
        self.assertIn("fusionada (", salida.getvalue())


class Consulta(unittest.TestCase):
    def test_error_de_un_repo_va_a_ese_repo(self):
        respuesta = {"data": {"r0": {"nameWithOwner": "o/a"}, "r1": None},
                     "errors": [{"path": ["r1"], "message": "Could not resolve to a Repository"}]}
        with mock.patch.object(gp, "http", return_value=respuesta):
            nodos, errores = gp.consultar(["o/a", "o/b"], "t")
        self.assertEqual(nodos, {"o/a": {"nameWithOwner": "o/a"}, "o/b": None})
        self.assertEqual(errores, [{"repo": "o/b", "detalle": "Could not resolve to a Repository"}])

    def test_una_consulta_por_token_de_dueno(self):
        llamadas = []

        def http(metodo, url, token, cuerpo=None):
            llamadas.append((token, sorted(set(re.findall(r'owner: "([^"]+)"', cuerpo["query"])))))
            alias = re.findall(r"(r\d+): repository", cuerpo["query"])
            return {"data": {a: {"nameWithOwner": a} for a in alias}}

        with mock.patch.object(gp, "http", http), mock.patch.dict("os.environ", {"GH_TOKEN_ESCALA_AGENCIA": "te"}):
            nodos, errores = gp.consultar(["o/a", "Escala-Agencia/w", "o/b"], "t")
        self.assertEqual(llamadas, [("t", ["o"]), ("te", ["Escala-Agencia"])])
        self.assertEqual(nodos, {"o/a": {"nameWithOwner": "r0"}, "Escala-Agencia/w": {"nameWithOwner": "r1"},
                                 "o/b": {"nameWithOwner": "r2"}})
        self.assertEqual(errores, [])

    def test_token_de_sin_variable_del_dueno_usa_el_comun(self):
        with mock.patch.dict("os.environ", {"GH_TOKEN_ESCALA_AGENCIA": "te"}):
            self.assertEqual(gp.token_de("Escala-Agencia/w", "t"), "te")
            self.assertEqual(gp.token_de("mariomina/x", "t"), "t")

    def test_sin_data_y_con_errores_lanza_fallo(self):
        with mock.patch.object(gp, "http", return_value={"errors": [{"message": "Bad credentials"}]}), \
                self.assertRaises(gp.Fallo):
            gp.consultar(["o/a"], "t")


class Linea(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name) / "pendientes.json"
        self.lanzadas = []

    def tearDown(self):
        self._tmp.cleanup()

    def lanzar(self, ruta, ahora):
        self.lanzadas.append(ruta)

    def linea(self):
        return gp.linea(self.cache, AHORA, self.lanzar)

    def test_sin_cache_lanza_el_refresco_y_no_espera(self):
        self.assertEqual(self.linea(), "GitHub: sin datos (primera consulta en curso)")
        self.assertEqual(self.lanzadas, [self.cache])

    def test_nada_espera(self):
        gp.guardar_cache(gp.analizar({"o/a": repo()}, [], AHORA - timedelta(minutes=3)), self.cache)
        self.assertEqual(self.linea(), "GitHub: nada espera tu decisión · hace 3 min")
        self.assertEqual(self.lanzadas, [])

    def test_decisiones_y_cache_caducada(self):
        nodos = {"mariomina/.github": repo([dependabot(1, "6", "7"), dependabot(2, "4", "5")]),
                 "Escala-Agencia/agencia-web": repo([pr(2, "chore: release", "release-please--branches--main",
                                               "github-actions", ci="SUCCESS")])}
        gp.guardar_cache(gp.analizar(nodos, [], AHORA - timedelta(minutes=30)), self.cache)
        self.assertEqual(self.linea(), "GitHub: 2 esperan tu decisión: Dependabot mayor (.github#1, .github#2) · "
                                       "1 se fusionan solas · hace 30 min")
        self.assertEqual(self.lanzadas, [self.cache])

    def test_sin_token_o_sin_red(self):
        with mock.patch.object(gp, "obtener_token", return_value=None):
            gp.refrescar(self.cache, AHORA)
        self.assertEqual(self.linea(), "GitHub: sin datos (sin token)")
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.object(gp, "recoger", side_effect=urllib.error.URLError("dns")):
            gp.refrescar(self.cache, AHORA)
        self.assertEqual(self.linea(), "GitHub: sin datos (sin red: dns)")

    def test_cache_corrupta_no_falla(self):
        self.cache.write_text("{no es json")
        self.assertEqual(self.linea(), "GitHub: sin datos (primera consulta en curso)")

    def test_refresco_en_curso_no_se_lanza_dos_veces(self):
        with mock.patch.object(gp.subprocess, "Popen") as popen:
            self.assertTrue(gp.lanzar_refresco(self.cache, datetime.now(timezone.utc)))
            self.assertFalse(gp.lanzar_refresco(self.cache, datetime.now(timezone.utc)))
        self.assertEqual(popen.call_count, 1)
        self.assertIn("--refrescar", popen.call_args.args[0])
        self.assertTrue(popen.call_args.kwargs["start_new_session"])
        self.assertEqual(popen.call_args.kwargs["stdout"], gp.subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs["stderr"], gp.subprocess.DEVNULL)

    def test_hermes_solo_en_el_primer_turno(self):
        gp.guardar_cache(gp.analizar({"o/a": repo()}, [], AHORA), self.cache)
        kw = {"ruta": self.cache, "ahora": AHORA, "lanzar": self.lanzar}
        self.assertEqual(gp.hermes(json.dumps({"extra": {"is_first_turn": True}}), **kw),
                         {"context": "GitHub: nada espera tu decisión · hace 0 min"})
        self.assertEqual(gp.hermes(json.dumps({"extra": {"is_first_turn": False}}), **kw), {})
        self.assertEqual(gp.hermes("no es json", **kw), {})


def nodo_metricas(prs=(), commits=()):
    """prs: (título, autor, fusionador, hace); commits: (estado o None, hace)."""
    return {"pullRequests": {"nodes": [{"title": t, "mergedAt": iso(h), "author": {"login": a},
                                        "mergedBy": {"login": f}} for t, a, f, h in prs]},
            "defaultBranchRef": {"target": {"history": {"nodes": [
                {"committedDate": iso(h), "statusCheckRollup": {"state": e} if e else None} for e, h in commits]}}}}


class Metricas(unittest.TestCase):
    """mariomina/mario-home#22: reverts, CI rojo en la rama principal y fusionadas por bots."""

    def test_cuenta_por_ventana(self):
        d = timedelta(days=1)
        nodos = {"o/a": nodo_metricas(
            prs=[("feat: algo", "mariomina", "mariomina", 2 * d),
                 ("chore(main): release 1.0.0", "app/mariomina-automatizacion", "mariomina-automatizacion", 3 * d),
                 ("chore: Bump x from 1.0 to 1.1", "dependabot[bot]", "mariomina", 4 * d),
                 ('Revert "feat: algo"', "mariomina", "mariomina", 5 * d),
                 ("revert: quitar algo", "mariomina", "mariomina", 10 * d),
                 ("feat: vieja", "mariomina", "mariomina", 40 * d)],
            commits=[("SUCCESS", d), ("FAILURE", 2 * d), (None, 3 * d), ("ERROR", 20 * d), ("SUCCESS", 40 * d)]),
                 "o/sin": None}
        m = gp.metricas(nodos, AHORA)
        self.assertEqual(m["7"], {"fusionadas": 4, "por_bots": 1, "reverts": 1, "ci_rojo": 1, "commits_con_ci": 2})
        self.assertEqual(m["28"], {"fusionadas": 5, "por_bots": 1, "reverts": 2, "ci_rojo": 2, "commits_con_ci": 3})

    def test_linea_y_resumen(self):
        m = {"fusionadas": 12, "por_bots": 5, "reverts": 0, "ci_rojo": 1, "commits_con_ci": 20}
        self.assertEqual(gp.linea_metricas(m), "7 d: 12 fusionadas (5 por bots) · 0 reverts · CI rojo 1/20")
        estado = gp.analizar({"o/a": repo()}, [], AHORA)
        estado["metricas"] = {"7": m, "28": m}
        self.assertIn("· 7 d: 12 fusionadas (5 por bots) · 0 reverts · CI rojo 1/20 · hace 0 min",
                      gp.resumen(estado, AHORA))
        self.assertIn("Métricas: 7 d: 12 fusionadas", gp.tabla(estado, AHORA))
        self.assertIn("28 d: 12 fusionadas", gp.tabla(estado, AHORA))
        self.assertEqual(gp.linea_metricas(None), "")

    def test_un_fallo_de_metricas_no_tumba_recoger(self):
        with mock.patch.object(gp, "repos", return_value=["o/a"]), \
                mock.patch.object(gp, "consultar", return_value=({"o/a": repo()}, [])), \
                mock.patch.object(gp, "workflows_desactivados", return_value=[]), \
                mock.patch.object(gp, "consultar_metricas", side_effect=TimeoutError("lento")), \
                mock.patch.object(gp, "freno", return_value=None), \
                mock.patch.dict("os.environ", {}):
            estado = gp.recoger("t", AHORA)
        self.assertNotIn("metricas", estado)
        self.assertEqual(estado["errores"], [{"repo": "métricas", "detalle": "TimeoutError: lento"}])

    def test_una_consulta_por_token_desde_la_ventana_mayor(self):
        llamadas = []

        def http(metodo, url, token, cuerpo=None):
            llamadas.append((token, re.findall(r'owner: "([^"]+)"', cuerpo["query"]),
                             re.search(r'since: "([^"]+)"', cuerpo["query"]).group(1)))
            return {"data": {a: {} for a in re.findall(r"(m\d+): repository", cuerpo["query"])}}

        with mock.patch.object(gp, "http", http), mock.patch.dict("os.environ", {"GH_TOKEN_E": "te"}):
            nodos = gp.consultar_metricas(["o/a", "E/w"], "t", AHORA)
        self.assertEqual(llamadas, [("t", ["o"], "2026-10-17T20:00:00Z"), ("te", ["E"], "2026-10-17T20:00:00Z")])
        self.assertEqual(nodos, {"o/a": {}, "E/w": {}})


class Freno(unittest.TestCase):
    """mariomina/mario-home#41: un issue abierto «FRENO: …» en mario-home pausa toda fusión automática."""

    def test_detecta_el_issue_y_usa_el_token_de_mariomina(self):
        vistos = []

        def http(metodo, url, token, cuerpo=None):
            vistos.append((url, token))
            return [{"title": "FRENO: nada"} | {"pull_request": {}}, {"title": "FRENO: main roto"}]

        with mock.patch.object(gp, "http", http), mock.patch.dict("os.environ", {"GH_TOKEN_MARIOMINA": "th"}):
            self.assertEqual(gp.freno("t"), "FRENO: main roto")  # una PR con ese título no cuenta
        self.assertEqual(vistos, [(f"{gp.API}/repos/mariomina/mario-home/issues?state=open&per_page=100", "th")])

    def test_sin_red_es_fallo(self):
        with mock.patch.object(gp, "http", side_effect=urllib.error.URLError("x")), self.assertRaises(gp.Fallo):
            gp.freno("t")

    def test_barrido_con_freno_no_fusiona_y_la_linea_lo_dice(self):
        estado = gp.analizar({"o/a": repo([dependabot(3, "5.1", "5.2")])}, [], AHORA)
        estado["freno"] = "FRENO: main roto"
        llamadas = []
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.object(gp, "recoger", return_value=estado), \
                mock.patch.object(gp, "freno", return_value="FRENO: main roto"), \
                mock.patch.object(gp, "http", lambda *a, **k: llamadas.append(a)), \
                mock.patch.object(gp, "log_publico", return_value=False), \
                mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(gp.main(["--fusionar"]), 0)
        self.assertEqual(llamadas, [])
        self.assertIn("No se fusiona nada: freno activo: FRENO: main roto", out.getvalue())
        self.assertTrue(gp.resumen(estado, AHORA).startswith("GitHub: FRENO activo, no se fusiona nada (FRENO: main roto)"))


class Paginacion(unittest.TestCase):
    def test_pagina_commits_y_prs_solo_mientras_hace_falta(self):
        desde = "2026-10-17T20:00:00Z"
        nodo = {"defaultBranchRef": {"target": {"history": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "c1"}, "nodes": [{"committedDate": "x1"}]}}},
                "pullRequests": {"pageInfo": {"hasPreviousPage": True, "startCursor": "p1"},
                                 "nodes": [{"updatedAt": "2026-11-01T00:00:00Z"}]}}
        respuestas = [
            {"data": {"repository": {"defaultBranchRef": {"target": {"history": {
                "pageInfo": {"hasNextPage": False, "endCursor": "c2"}, "nodes": [{"committedDate": "x2"}]}}}}}},
            {"data": {"repository": {"pullRequests": {"pageInfo": {"hasPreviousPage": True, "startCursor": "p2"},
                                                      "nodes": [{"updatedAt": "2026-10-01T00:00:00Z"}]}}}}]
        consultas = []

        def http(metodo, url, token, cuerpo=None):
            consultas.append(cuerpo["query"])
            return respuestas.pop(0)

        with mock.patch.object(gp, "http", http):
            gp._completar("o/a", nodo, "t", desde)
        self.assertEqual([c["committedDate"] for c in nodo["defaultBranchRef"]["target"]["history"]["nodes"]], ["x1", "x2"])
        self.assertEqual(len(nodo["pullRequests"]["nodes"]), 2)  # para: la página nueva ya es anterior a la ventana
        self.assertIn('after: "c1"', consultas[0])
        self.assertIn('before: "p1"', consultas[1])


class WorkflowsDesactivados(unittest.TestCase):
    def test_avisa_solo_de_los_desactivados_por_inactividad(self):
        def http(metodo, url, token, cuerpo=None):
            if "/o/sin/" in url:
                raise urllib.error.HTTPError(url, 404, "x", {}, io.BytesIO(b"{}"))
            return {"workflows": [
                {"path": ".github/workflows/mantenimiento.yml", "state": "disabled_inactivity"},
                {"path": ".github/workflows/pr.yml", "state": "active"},
                {"path": ".github/workflows/viejo.yml", "state": "disabled_manually"}]}

        with mock.patch.object(gp, "http", http):
            avisos = gp.workflows_desactivados(["o/a", "o/sin"], "t")
        self.assertEqual(avisos, [{"repo": "o/a", "tipo": "workflow-desactivado", "detalle":
                                   "mantenimiento.yml: 60 días sin actividad; gh workflow enable mantenimiento.yml -R o/a"}])


def error_http(codigo, mensaje):
    return urllib.error.HTTPError("u", codigo, "x", {}, io.BytesIO(json.dumps({"message": mensaje}).encode()))


def lectura(ci=None, estado="OPEN", fusionada=False, sha="s1"):
    """Respuesta GraphQL de estado_pr_version."""
    commit = {"statusCheckRollup": {"state": ci} if ci else None}
    return {"data": {"repository": {"pullRequest": {"state": estado, "merged": fusionada, "headRefOid": sha,
                                                    "commits": {"nodes": [{"commit": commit}]}}}}}


class FusionarVersion(unittest.TestCase):
    """`--fusionar-version`: espera el CI de la PR de versión y la fusiona solo en verde (mariomina/.github#28)."""

    issues = []  # issues abiertos de mario-home (freno)

    def correr(self, respuestas, prs='[{"number": 8}]'):
        """respuestas: {número: [respuesta o excepción por llamada (lectura GraphQL o PUT), en orden]}."""
        llamadas, esperas = [], []

        def http(metodo, url, token, cuerpo=None):
            if url.endswith("/issues?state=open&per_page=100"):
                return self.issues
            if metodo == "POST":
                numero = cuerpo["variables"]["pr"]
                llamadas.append(("LEER", numero, None))
            else:
                numero = int(url.split("/pulls/")[1].split("/")[0])
                llamadas.append((metodo, numero, cuerpo))
            r = respuestas[numero].pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with tempfile.TemporaryDirectory() as d, mock.patch.object(gp, "http", http), \
                mock.patch("builtins.print"):
            salida = Path(d) / "out"
            codigo = gp.fusionar_version(prs, "o/r", "t", str(salida), esperas.append)
            return codigo, salida.read_text(), llamadas, esperas

    def test_espera_al_ci_y_fusiona_en_verde_con_el_sha_revisado(self):
        codigo, salida, llamadas, esperas = self.correr(
            {8: [lectura(), lectura("PENDING"), lectura("SUCCESS", sha="s2"), {"merged": True}]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [15, 15]))
        self.assertEqual(llamadas[-1], ("PUT", 8, {"merge_method": "squash", "sha": "s2"}))

    def test_ci_rojo_no_fusiona_y_sale_con_1(self):
        codigo, salida, llamadas, _ = self.correr({8: [lectura("PENDING"), lectura("FAILURE")]})
        self.assertEqual((codigo, salida), (1, "fusionadas=0\n"))
        self.assertNotIn("PUT", [m for m, _, _ in llamadas])

    def test_sin_ci_tras_2_min_no_fusiona(self):
        codigo, salida, llamadas, esperas = self.correr({8: [lectura() for _ in range(9)]})
        self.assertEqual((codigo, salida), (1, "fusionadas=0\n"))
        self.assertEqual(len(esperas), 8)  # 8 × 15 s = 2 min
        self.assertEqual({m for m, _, _ in llamadas}, {"LEER"})

    def test_ci_en_curso_al_acabar_el_plazo_lo_deja_al_barrido(self):
        codigo, salida, llamadas, esperas = self.correr({8: [lectura("PENDING") for _ in range(41)]})
        self.assertEqual((codigo, salida, len(esperas)), (0, "fusionadas=0\n", 40))  # 40 × 15 s = 10 min

    def test_prueba_el_siguiente_metodo_si_el_repo_no_lo_permite(self):
        codigo, salida, llamadas, _ = self.correr(
            {8: [lectura("SUCCESS"), error_http(405, "Squash merges are not allowed on this repository."),
                 {"merged": True}]})
        self.assertEqual((codigo, salida), (0, "fusionadas=1\n"))
        self.assertEqual([c["merge_method"] for m, _, c in llamadas if m == "PUT"], ["squash", "merge"])

    def test_cabeza_cambiada_vuelve_a_leer_y_detecta_ya_fusionada(self):
        codigo, salida, llamadas, esperas = self.correr(
            {8: [lectura("SUCCESS"), error_http(409, "Head branch was modified"), lectura(fusionada=True)]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [15]))

    def test_un_put_que_llego_aunque_dio_timeout_cuenta_como_fusionada(self):
        codigo, salida, _, esperas = self.correr(
            {8: [lectura("SUCCESS"), TimeoutError("timed out"), lectura(fusionada=True)]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [15]))

    def test_ningun_metodo_permitido_falla(self):
        no = [error_http(405, f"{m} merges are not allowed") for m in ("Merge", "Squash", "Rebase")]
        codigo, salida, llamadas, esperas = self.correr({8: [lectura("SUCCESS")] + no})
        self.assertEqual((codigo, salida, esperas), (1, "fusionadas=0\n", []))

    def test_freno_activo_no_fusiona_nada_y_sale_con_0(self):
        self.issues = [{"title": "feat: otra cosa"}, {"title": "FRENO: main roto", "number": 9}]
        codigo, salida, llamadas, _ = self.correr({8: [lectura("SUCCESS"), {"merged": True}]})
        self.assertEqual((codigo, salida, llamadas), (0, "fusionadas=0\n", []))

    def test_freno_sin_comprobar_no_fusiona(self):
        with mock.patch.object(gp, "freno", side_effect=gp.Fallo("no se puede comprobar el freno (URLError)")):
            codigo, salida, llamadas, _ = self.correr({8: [lectura("SUCCESS"), {"merged": True}]})
        self.assertEqual((codigo, salida, llamadas), (0, "fusionadas=0\n", []))

    def test_cerrada_sin_fusionar_falla_y_sigue_con_las_demas(self):
        codigo, salida, llamadas, _ = self.correr(
            {8: [lectura(estado="CLOSED")], 9: [lectura("SUCCESS"), {"merged": True}]},
            prs='[{"number": 8}, {"number": 9}]')
        self.assertEqual((codigo, salida), (1, "fusionadas=1\n"))
        self.assertEqual(llamadas[-1][:2], ("PUT", 9))

    def test_main_lee_prs_y_escribe_github_output(self):
        with tempfile.TemporaryDirectory() as d:
            salida = Path(d) / "out"
            entorno = {"GITHUB_REPOSITORY": "o/r", "PRS": '[{"number": 8}]', "GITHUB_OUTPUT": str(salida)}
            with mock.patch.object(gp, "obtener_token", return_value="t"), mock.patch.dict("os.environ", entorno), \
                    mock.patch.object(gp, "fusionar_pr_version", return_value="merge") as fusionar, \
                    mock.patch.object(gp, "freno", return_value=None), \
                    mock.patch.object(gp.time, "sleep"), mock.patch("builtins.print"):
                self.assertEqual(gp.main(["--fusionar-version"]), 0)
            fusionar.assert_called_once()
            self.assertEqual(fusionar.call_args.args[:3], ("o/r", 8, "t"))
            self.assertEqual(salida.read_text(), "fusionadas=1\n")

    def test_main_sin_repo_sale_con_1(self):
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": ""}), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(gp.main(["--fusionar-version"]), 1)


class LogPublico(unittest.TestCase):
    def test_solo_en_actions_y_si_el_repo_no_es_privado(self):
        def http_privado(privado):
            return lambda metodo, url, token, cuerpo=None: {"private": privado}

        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "", "GITHUB_REPOSITORY": "o/r"}):
            self.assertFalse(gp.log_publico("t"))
        with mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "o/r"}):
            with mock.patch.object(gp, "http", http_privado(True)):
                self.assertFalse(gp.log_publico("t"))
            with mock.patch.object(gp, "http", http_privado(False)):
                self.assertTrue(gp.log_publico("t"))
            with mock.patch.object(gp, "http", side_effect=urllib.error.URLError("dns")):
                self.assertTrue(gp.log_publico("t"))  # sin saberlo, público

    def test_main_fusionar_en_log_publico_no_nombra_repos_ni_titulos(self):
        nodos = {"o/secreto": repo([pr(2, "chore: release cliente-acme", "release-please--branches--main",
                                       "github-actions", ci="SUCCESS", edad=timedelta(hours=2))],
                                   issues=[(7, 0)], ramas=[("feat/cliente-acme", timedelta(days=30))]),
                 "o/otro": repo([dependabot(3, "5", "7")])}
        estado = gp.analizar(nodos, [], AHORA)
        salida = io.StringIO()
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.object(gp, "recoger", return_value=estado), \
                mock.patch.object(gp, "log_publico", return_value=True), \
                mock.patch.object(gp, "http", return_value={"merged": True}), \
                mock.patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), mock.patch("sys.stdout", salida):
            self.assertEqual(gp.main(["--fusionar"]), 0)
        texto = salida.getvalue()
        for prohibido in ("o/secreto", "o/otro", "acme", "#2", "#3", "#7", "Bump"):
            self.assertNotIn(prohibido, texto)
        self.assertIn("1 fusionadas · 1 esperan decisión", texto)

    def test_fusionar_discreto_no_nombra_la_pr_ni_el_motivo_del_error(self):
        estado = gp.analizar({"o/secreto": repo([version(3), version(4)])},
                             [], AHORA)
        respuestas = [urllib.error.HTTPError("u", 409, "x", {}, io.BytesIO(b'{"message": "rama cliente-acme"}')),
                      urllib.error.URLError("conexión a o/secreto")]

        def http(metodo, url, token, cuerpo=None):
            raise respuestas.pop(0)

        salida = io.StringIO()
        with mock.patch.object(gp, "http", http), mock.patch("sys.stdout", salida):
            gp.fusionar(estado, "t", discreto=True)
        self.assertEqual(salida.getvalue(), "Error al fusionar una PR: HTTP 409\nError al fusionar una PR: URLError\n")

    def test_error_de_recoger_en_log_publico_solo_da_el_tipo(self):
        error = io.StringIO()
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.object(gp, "log_publico", return_value=True), \
                mock.patch.object(gp, "recoger", side_effect=gp.Fallo("no se puede leer o/secreto")), \
                mock.patch("sys.stderr", error):
            self.assertEqual(gp.main([]), 1)
        self.assertEqual(error.getvalue(), "github_pendientes: Fallo\n")


if __name__ == "__main__":
    unittest.main()
