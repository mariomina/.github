"""Tests del filtro global (mariomina/mario-2-cerebro#276). Ejecutar: python3 -m unittest discover -s scripts/tests"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RUTA = Path(__file__).resolve().parents[1] / "filtro_global.py"
spec = importlib.util.spec_from_file_location("filtro_global", RUTA)
filtro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(filtro)

REGLA = "Ningún push, PR, merge ni cambio en main sin aprobación explícita de Mario."
LINEA_148 = ("- **Skill compartida:** carpeta en `skills/<categoría>/<id>/` con su `SKILL.md`, cuyo `name` es `<id>` y es "
             "único en todo el repo. Después, `python3 -I entorno/conectar_arneses.py`. Una skill se mueve aquí cuando la "
             "usan 2 repos. Excepción: `sistema/verify-mario-home`, la verificación de este repo, vive aquí para que "
             "todos los arneses la lean sin carpeta de arnés (decisión 2 de `docs/investigaciones/sistema-objetivo.md`). "
             "Una categoría nueva nace cuando la piden 2 skills, con su `DESCRIPTION.md`.")


def home_md(punteros):
    lineas = "\n".join(f"- **{n}**: `~/Documentos/Mario/{n}`. Si falta: `git clone git@github.com:o/{n}.git`."
                       for n in punteros)
    return f"# home\n\ntipo-repo: home\nautonomia: 0\n\n## Reglas globales\n\n- {REGLA}\n\n## Otros repos\n\n{lineas}\n"


class FiltroGlobal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.casa = Path(self._tmp.name)
        self.proy = self.casa / "Documentos" / "Mario"
        self.proy.mkdir(parents=True)
        self.parches = [mock.patch.object(filtro.Path, "home", return_value=self.casa),
                        mock.patch.object(filtro, "PROYECTOS", self.proy)]
        for p in self.parches:
            p.start()

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self._tmp.cleanup()

    def repo(self, nombre, agents=None):
        d = self.proy / nombre
        (d / ".git").mkdir(parents=True)
        if agents is not None:
            (d / "AGENTS.md").write_text(agents, encoding="utf-8")
        return d

    def correr(self):
        return filtro.modo_completo(str(self.proy / "mario-home"), remoto=False)

    def reglas(self, r):
        return sorted((v["repo"], v["regla"]) for v in r["violaciones"])

    def test_todo_en_orden(self):
        self.repo("mario-home", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: producto\nautonomia: 0\n\nComandos propios.\n")
        r = self.correr()
        self.assertTrue(r["valido"], r)
        self.assertEqual(r["reglas_globales"], 1)

    def test_regla_duplicada(self):
        self.repo("mario-home", home_md(["a"]))
        self.repo("a", f"# a\n\ntipo-repo: producto\nautonomia: 0\n\n- {REGLA}\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "duplicado-de-global")])

    def test_duplicado_reformulado(self):
        self.repo("mario-home", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: producto\nautonomia: 0\n\n- Ningún push, PR, merge ni cambio en `main` sin aprobación explícita de Mario\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "duplicado-de-global")])

    def test_excepcion_a_regla_global(self):
        self.repo("mario-home", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: producto\nautonomia: 0\n\n- Excepción: aquí no aplica la regla global de aprobación.\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "excepcion-a-global")])

    def test_excepcion_a_regla_del_home_no_es_global(self):
        """#56: línea 133 del primer commit de mariomina/mario-home#148, fuera de «Reglas globales»."""
        self.repo("mario-home", home_md([]) + "\n## Cómo añadir contenido\n\n" + LINEA_148 + "\n")
        r = self.correr()
        self.assertTrue(r["valido"], r["violaciones"])

    def test_excepcion_en_reglas_globales_del_home(self):
        self.repo("mario-home", home_md([]).replace(f"- {REGLA}\n", f"- {REGLA}\n- Excepción: en mario-home no aplica.\n"))
        self.assertEqual([(v["repo"], v["regla"], v["linea"]) for v in self.correr()["violaciones"]],
                         [("mario-home", "excepcion-a-global", 9)])

    def test_sin_agents_md_y_sin_tipo(self):
        self.repo("mario-home", home_md(["a", "b"]))
        self.repo("a")
        self.repo("b", "# b\n\nSin tipo.\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "sin-agents-md"), ("o/b", "sin-tipo-repo")])

    def test_autonomia(self):
        self.repo("mario-home", home_md(["a", "b", "c", "d"]).replace("autonomia: 0", "autonomia: 1"))
        self.repo("a", "# a\n\ntipo-repo: producto\nautonomia: 2\n")
        self.repo("b", "# b\n\ntipo-repo: producto\nautonomia: alta\n")
        self.repo("c", "# c\n\ntipo-repo: producto\n")
        self.repo("d", "# d\n\ntipo-repo: home\nautonomia: 0\n")
        self.assertEqual(self.reglas(self.correr()), [("mario-home", "autonomia-fija-en-0"), ("o/b", "autonomia-invalida"),
                                                      ("o/c", "sin-autonomia")])

    def test_tipo_desconocido(self):
        self.repo("mario-home", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: libreria\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "sin-tipo-repo")])

    def test_agente_fuera_de_proyectos(self):
        """mario-home#8: un agente guardado como repo (tipo `agente`) en `~/.hermes`, fuera de Proyectos."""
        self.repo("mario-home", home_md([]) + "- **mario-hermes**: `~/.hermes`. Si falta: "
                                              "`git clone git@github.com:o/mario-hermes.git ~/.hermes`.\n")
        (self.casa / ".hermes").mkdir()
        (self.casa / ".hermes" / "AGENTS.md").write_text("# h\n\ntipo-repo: agente\nautonomia: 0\n", encoding="utf-8")
        r = self.correr()
        self.assertTrue(r["valido"], r["violaciones"])
        self.assertEqual(r["repos"], [{"repo": "o/mario-hermes", "tipo": "agente"}])

    def test_cascada_por_home_hijo(self):
        self.repo("mario-home", home_md(["agencia"]))
        self.repo("agencia", home_md(["cliente-x"]).replace("# home", "# agencia"))
        self.repo("cliente-x", f"# x\n\ntipo-repo: cliente\nautonomia: 0\n\n- {REGLA}\n")
        r = self.correr()
        self.assertEqual([x["repo"] for x in r["repos"]], ["o/agencia", "o/cliente-x"])
        self.assertIn(("o/cliente-x", "duplicado-de-global"), self.reglas(r))

    def test_puntero_con_otra_ruta_en_la_descripcion(self):
        """mariomina/.github#48: la ruta del repo es la que sigue a la descripción, no la primera entre comillas."""
        claude = ("- **mario-claude** (infraestructura de Claude Code, CLI y app: versión de configuración y métricas "
                  "de uso; nunca es `~/.claude`): `~/Documentos/Mario/mario-claude`. Si falta: `git clone "
                  "git@github.com:mariomina/mario-claude.git ~/Documentos/Mario/mario-claude`.\n")
        hermes = ("- **mario-hermes** (agente Hermes: su perfil por defecto como distribución; Hermes exige "
                  "`~/.hermes`, y `~/Documentos/Mario/mario-hermes` es un symlink a esa carpeta): `~/.hermes`. "
                  "Si falta (Hermes recién instalado): `git -C ~/.hermes init && git -C ~/.hermes remote add origin "
                  "git@github.com:mariomina/mario-hermes.git`.\n")
        self.assertEqual(filtro.punteros(home_md([]) + claude + hermes),
                         [(str(self.proy / "mario-claude"), "mariomina/mario-claude"),
                          (str(self.casa / ".hermes"), "mariomina/mario-hermes")])
        self.repo("mario-home", home_md([]) + claude)
        self.repo("mario-claude", "# c\n\ntipo-repo: agente\nautonomia: 0\n")
        r = self.correr()
        self.assertTrue(r["valido"], r["violaciones"])
        self.assertEqual(r["avisos"], [])

    def test_puntero_con_placeholder_se_salta(self):
        self.repo("mario-home", home_md(["a"]) + "- **cliente**: `~/Documentos/Mario/cliente-<slug>`.\n")
        self.repo("a", "# a\n\ntipo-repo: web\nautonomia: 0\n")
        self.assertTrue(self.correr()["valido"])

    def test_repo_sin_puntero_es_aviso(self):
        self.repo("mario-home", home_md([]))
        self.repo("suelto", "# s\n\ntipo-repo: web\nautonomia: 0\n")
        r = self.correr()
        self.assertTrue(r["valido"])
        self.assertEqual([a["repo"] for a in r["avisos"]], ["suelto"])

    def test_carpeta_de_grupo(self):
        """mariomina/.github#24: los repos de una carpeta de grupo (mario-agencia/) cuentan para el aviso."""
        self.repo("mario-home", home_md([]) + "- **agencia-home**: `~/Documentos/Mario/mario-agencia/agencia-home`. "
                                              "Si falta: `git clone git@github.com:e/agencia-home.git`.\n")
        self.repo("mario-agencia/agencia-home", "# h\n\ntipo-repo: home\nautonomia: 0\n\n## Otros repos\n\n")
        self.repo("mario-agencia/agencia-web", "# w\n\ntipo-repo: web\nautonomia: 0\n")
        (self.proy / "mario-agencia" / "notas").mkdir()
        r = self.correr()
        self.assertTrue(r["valido"], r["violaciones"])
        self.assertEqual([a["repo"] for a in r["avisos"]], ["agencia-web"])

    def test_token_por_dueno(self):
        with mock.patch.dict("os.environ", {"GH_TOKEN": "t", "GH_TOKEN_ESCALA_AGENCIA": "te"}):
            self.assertEqual(filtro.token("Escala-Agencia/agencia-web"), "te")
            self.assertEqual(filtro.token("mariomina/mario-home"), "t")

    def test_nombres_de_punta_a_punta(self):
        """mariomina/.github#55: --nombres lee los documentos del árbol git de cada repo apuntado."""
        import subprocess
        self.repo("mario-home", home_md(["a"]))
        a = self.repo("a", "# a\n\ntipo-repo: producto\nautonomia: 0\n\nReglas: `home-mario/AGENTS.md`.\n")
        (a / ".git").rmdir()
        subprocess.run(["git", "init", "-q", str(a)], check=True)
        subprocess.run(["git", "-C", str(a), "add", "AGENTS.md"], check=True)
        r = filtro.modo_completo(str(self.proy / "mario-home"), remoto=False, nombres=True)
        self.assertEqual([(v["repo"], v["regla"], v["detalle"]) for v in r["violaciones"]],
                         [("o/a", "nombre-repo", "home-mario")])
        self.assertTrue(filtro.modo_completo(str(self.proy / "mario-home"), remoto=False)["valido"])

    def test_modo_repo(self):
        d = self.repo("a", "# a\n\nSin tipo.\n")
        self.assertEqual([v["regla"] for v in filtro.modo_repo(str(d))["violaciones"]], ["sin-tipo-repo"])
        (d / "AGENTS.md").write_text("# a\n\ntipo-repo: vault\nautonomia: 0\n", encoding="utf-8")
        self.assertTrue(filtro.modo_repo(str(d))["valido"])


PR_YML = "name: pr\non:\n  pull_request:\njobs:\n  pr:\n    runs-on: x\n  ci:\n    uses: o/.github/.github/workflows/ci-python.yml@v1\n"
CI_PYTHON = "name: ci-python\non:\n  workflow_call:\njobs:\n  ci:\n    name: ci\n    runs-on: x\n"


class Nombres(unittest.TestCase):
    """--nombres con los desfases reales de mariomina/mario-home#134 y #138 (mariomina/.github#55)."""

    def violaciones(self, documentos, workflows=None):
        repos = {"o/.github": {"textos": {".github/workflows/ci-python.yml": CI_PYTHON}},
                 "o/mario-home": {"textos": {".github/workflows/pr.yml": PR_YML, **(workflows or {})}},
                 "o/a": {"textos": documentos}}
        violaciones = []
        filtro.revisar_nombres(repos, {"mario-github", "mario-agencia"}, violaciones)
        return [(v["archivo"], v["linea"], v["regla"], v["detalle"]) for v in violaciones]

    def test_desfases_reales_fallan(self):
        documentos = {
            "AGENTS.md": "# a\n\nReglas globales: `home-mario/AGENTS.md` y `home-agencia/AGENTS.md`.\n",
            "CONTRIBUTING.md": "4. **Una PR por rama**, con título convencional (lo comprueba `pr-titulo`).\n",
            "docs/branch_protection.md": "Checks obligatorios: `pr-titulo / pr-titulo` y `ci / ci`.\n",
            "README.md": "Clon: `git clone git@github.com:o/home-mario.git`.\n"}
        self.assertEqual(self.violaciones(documentos, {".github/workflows/x.yml": "on:\n  push:\njobs:\n  ci:\n"}), [
            ("AGENTS.md", 3, "nombre-repo", "home-mario"),
            ("AGENTS.md", 3, "nombre-repo", "home-agencia"),
            ("CONTRIBUTING.md", 1, "nombre-check", "pr-titulo"),
            ("README.md", 1, "nombre-repo", "o/home-mario"),
            ("docs/branch_protection.md", 1, "nombre-check", "pr-titulo / pr-titulo")])

    def test_documentos_corregidos_pasan(self):
        documentos = {
            "AGENTS.md": "# a\n\nReglas globales: `mario-home/AGENTS.md`; carpeta `mario-agencia/`, `mario-github`.\n",
            "CONTRIBUTING.md": "4. **Una PR por rama**, con título convencional (lo comprueba `pr`).\n",
            "docs/branch_protection.md": "Checks: `pr / pr`, `ci / ci` y el check `ci-python`.\n",
            "README.md": "Clon: `git clone git@github.com:o/mario-home.git`; `o/.github`; ver `o/a#12`.\n"}
        self.assertEqual(self.violaciones(documentos), [])

    def test_lo_que_no_se_mira(self):
        documentos = {
            "AGENTS.md": "Marcadores: `mario-<arnés>/ajustes/`, `o/mario-<producto>`, `agencia-cliente-<slug>`.\n"
                         "Prosa: home-mario y los widgets home-screen; ruta `clients/mario-mina/x.md`.\n",
            "docs/investigaciones/vieja.md": "`home-mario` y el check `pr-titulo`.\n",
            "CHANGELOG.md": "`home-mario`\n",
            "src/notas.md": "`home-mario`\n"}
        self.assertEqual(self.violaciones(documentos), [])

    def test_check_sin_llamador_de_pull_request(self):
        """`ci / ci` existe solo mientras un workflow con pull_request llama al reutilizable."""
        sin_llamador = PR_YML.replace("  ci:\n    uses: o/.github/.github/workflows/ci-python.yml@v1\n", "")
        self.assertEqual(self.violaciones({"README.md": "Check `ci / ci`.\n"},
                                          {".github/workflows/pr.yml": sin_llamador}),
                         [("README.md", 1, "nombre-check", "ci / ci")])


if __name__ == "__main__":
    unittest.main()
