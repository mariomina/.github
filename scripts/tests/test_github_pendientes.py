"""Tests de github_pendientes.py (mariomina/2-cerebro#280), sin red. Ejecutar: python3 -m unittest discover -s scripts/tests"""
import importlib.util
import io
import json
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
               "github-actions", edad=timedelta(minutes=30)),
            dependabot(3, "5.1", "5.2"),
            dependabot(4, "5.1", "5.2", ci="PENDING"),
            dependabot(5, "5.1", "5.2", ci=None),
            dependabot(6, "5.1", "5.2", ci="FAILURE"),
            dependabot(7, "5", "7"),
            pr(8, "chore: Bump the x group with 2 updates", "dependabot/npm/g", "dependabot[bot]", ci="SUCCESS"),
            pr(9, "feat: algo", "feat/9-algo"),
            pr(10, "feat: borrador", "feat/10-b", borrador=True),
        ])}
        estado = gp.analizar(nodos, [], AHORA)
        self.assertEqual(acciones(estado), {
            ("o/a", 1): ("version", "esperar"), ("o/a", 2): ("version", "fusionar"),
            ("o/a", 3): ("dependabot-menor", "fusionar"), ("o/a", 4): ("dependabot-menor", "esperar"),
            ("o/a", 5): ("dependabot-menor", "decision"), ("o/a", 6): ("dependabot-menor", "decision"),
            ("o/a", 7): ("dependabot-mayor", "decision"), ("o/a", 8): ("dependabot-mayor", "decision"),
            ("o/a", 9): ("trabajo", "decision"), ("o/a", 10): ("trabajo", "borrador")})

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
        version = [("mariomina/home-mario", 1, "main"), ("mariomina/2-cerebro", 278, "master--components--sistema"),
                   ("mariomina/2-cerebro", 279, "master--components--pkm"), ("mariomina/copy-os", 16, "main"),
                   ("Escala-Agencia/web", 2, "main")]
        nodos = {}
        for r, n, rama in version:
            nodos.setdefault(r, repo())["pullRequests"]["nodes"].append(
                pr(n, "chore: release", f"release-please--branches--{rama}", "github-actions", edad=timedelta(hours=1)))
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

    def test_repo_sin_acceso_es_error(self):
        estado = gp.analizar({"o/a": None}, [], AHORA)
        self.assertEqual(estado["errores"], [{"repo": "o/a", "detalle": "sin acceso o no existe"}])


class Repos(unittest.TestCase):
    def test_cascada_por_home_repos(self):
        filtro = gp.cargar_filtro()
        textos = {
            gp.HOME_REPO: "tipo-repo: home\n\n## Otros repos\n\n"
                          "- **a**: `~/Documentos/Proyectos/a`. `git clone git@github.com:o/a.git`.\n"
                          "- **ag**: `~/Documentos/Proyectos/ag`. `git clone git@github.com:e/ag.git`.\n"
                          "- **x**: `~/Documentos/Proyectos/x-<slug>`.\n",
            "o/a": "tipo-repo: producto\n",
            "e/ag": "tipo-repo: home\n\n## Otros repos\n\n"
                    "- **w**: `~/Documentos/Proyectos/w`. `git clone git@github.com:e/w.git`.\n"
                    "- **a**: `~/Documentos/Proyectos/a`. `git clone git@github.com:o/a.git`.\n",
        }
        with mock.patch.object(filtro, "leer_remoto", side_effect=textos.get):
            self.assertEqual(gp.repos(filtro), [gp.HOME_REPO, "o/a", "e/ag", "e/w"])

    def test_sin_agents_md_de_home(self):
        filtro = gp.cargar_filtro()
        with mock.patch.object(filtro, "leer_remoto", return_value=None), self.assertRaises(gp.Fallo):
            gp.repos(filtro)


class Fusion(unittest.TestCase):
    def test_fusiona_con_sha_y_metodo_y_sigue_tras_un_error(self):
        nodos = {"o/a": repo([dependabot(3, "5.1", "5.2"), dependabot(7, "5", "7")], merge=False),
                 "o/b": repo([pr(2, "chore: release", "release-please--branches--main", "github-actions",
                                 edad=timedelta(hours=1))])}
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
            ("PUT", f"{gp.API}/repos/o/b/pulls/2/merge", {"merge_method": "merge", "sha": "sha2"})])
        self.assertEqual([(h["repo"], h["numero"]) for h in hechas], [("o/b", 2)])
        self.assertEqual(errores, [{"repo": "o/a", "detalle": "#3: HTTP 405 not mergeable"}])

    def test_main_fusionar_registra_las_fusionadas_y_sale_con_1_si_alguna_falla(self):
        nodos = {"o/a": repo([dependabot(3, "5.1", "5.2")]),
                 "o/b": repo([pr(2, "chore: release", "release-please--branches--main", "github-actions")])}
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
                 "Escala-Agencia/web": repo([pr(2, "chore: release", "release-please--branches--main",
                                               "github-actions")])}
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


class FusionarVersion(unittest.TestCase):
    """`--fusionar-version`: el paso del job reutilizable release-please (antes JavaScript sin tests)."""

    def correr(self, respuestas, prs='[{"number": 8}]'):
        """respuestas: {número: [respuesta o excepción por llamada PUT/GET, en orden]}."""
        llamadas, esperas = [], []

        def http(metodo, url, token, cuerpo=None):
            numero = int(url.split("/pulls/")[1].split("/")[0])
            llamadas.append((metodo, numero, (cuerpo or {}).get("merge_method")))
            r = respuestas[numero].pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with tempfile.TemporaryDirectory() as d, mock.patch.object(gp, "http", http), \
                mock.patch("builtins.print"):
            salida = Path(d) / "out"
            codigo = gp.fusionar_version(prs, "o/r", "t", str(salida), esperas.append)
            return codigo, salida.read_text(), llamadas, esperas

    def test_fusiona_con_merge_y_espera_antes_de_la_segunda_pasada(self):
        codigo, salida, llamadas, esperas = self.correr({8: [{"merged": True}]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [10]))
        self.assertEqual(llamadas, [("PUT", 8, "merge")])

    def test_prueba_el_siguiente_metodo_si_el_repo_no_lo_permite(self):
        codigo, salida, llamadas, _ = self.correr(
            {8: [error_http(405, "Merge commits are not allowed on this repository."), {"merged": True}]})
        self.assertEqual((codigo, salida), (0, "fusionadas=1\n"))
        self.assertEqual(llamadas, [("PUT", 8, "merge"), ("PUT", 8, "squash")])

    def test_reintenta_mientras_no_es_fusionable_y_detecta_ya_fusionada(self):
        no_aun = lambda: error_http(405, "Pull Request is not mergeable")  # noqa: E731 - un cuerpo por respuesta
        codigo, salida, llamadas, esperas = self.correr(
            {8: [no_aun(), {"merged": False}, no_aun(), {"merged": True}]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [5, 10]))
        self.assertEqual([m for m, _, _ in llamadas], ["PUT", "GET", "PUT", "GET"])

    def test_tras_4_intentos_falla_pero_escribe_fusionadas_y_sigue_con_las_demas(self):
        respuestas = [r for _ in range(4) for r in (error_http(409, "Head branch was modified"), {"merged": False})]
        codigo, salida, llamadas, esperas = self.correr(
            {8: respuestas, 9: [{"merged": True}]}, prs='[{"number": 8}, {"number": 9}]')
        self.assertEqual((codigo, salida), (1, "fusionadas=1\n"))
        self.assertEqual(esperas, [5, 5, 5, 10])
        self.assertEqual(llamadas[-1], ("PUT", 9, "merge"))

    def test_ningun_metodo_permitido_falla_sin_reintentar(self):
        no = [error_http(405, f"{m} merges are not allowed") for m in ("Merge", "Squash", "Rebase")]
        codigo, salida, llamadas, esperas = self.correr({8: no + [{"merged": False}]})
        self.assertEqual((codigo, salida, esperas), (1, "fusionadas=0\n", []))
        self.assertEqual(llamadas, [("PUT", 8, "merge"), ("PUT", 8, "squash"), ("PUT", 8, "rebase"), ("GET", 8, None)])

    def test_un_error_de_red_se_comprueba_con_el_get_y_se_reintenta(self):
        codigo, salida, llamadas, esperas = self.correr(
            {8: [TimeoutError("timed out"), {"merged": False}, {"merged": True}]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [5, 10]))
        self.assertEqual([m for m, _, _ in llamadas], ["PUT", "GET", "PUT"])

    def test_un_put_que_llego_aunque_dio_timeout_cuenta_como_fusionada(self):
        codigo, salida, _, esperas = self.correr({8: [TimeoutError("timed out"), {"merged": True}]})
        self.assertEqual((codigo, salida, esperas), (0, "fusionadas=1\n", [10]))

    def test_main_lee_prs_y_escribe_github_output(self):
        with tempfile.TemporaryDirectory() as d:
            salida = Path(d) / "out"
            entorno = {"GITHUB_REPOSITORY": "o/r", "PRS": '[{"number": 8}]', "GITHUB_OUTPUT": str(salida)}
            with mock.patch.object(gp, "obtener_token", return_value="t"), mock.patch.dict("os.environ", entorno), \
                    mock.patch.object(gp, "fusionar_pr_version", return_value="merge") as fusionar, \
                    mock.patch.object(gp.time, "sleep"), mock.patch("builtins.print"):
                self.assertEqual(gp.main(["--fusionar-version"]), 0)
            fusionar.assert_called_once()
            self.assertEqual(fusionar.call_args.args[:3], ("o/r", 8, "t"))
            self.assertEqual(salida.read_text(), "fusionadas=1\n")

    def test_main_sin_repo_sale_con_1(self):
        with mock.patch.object(gp, "obtener_token", return_value="t"), \
                mock.patch.dict("os.environ", {"GITHUB_REPOSITORY": ""}), mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(gp.main(["--fusionar-version"]), 1)


if __name__ == "__main__":
    unittest.main()
