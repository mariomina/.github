"""Tests del filtro global (mariomina/2-cerebro#276). Ejecutar: python3 -m unittest discover -s scripts/tests"""
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


def home_md(punteros):
    lineas = "\n".join(f"- **{n}**: `~/Documentos/Proyectos/{n}`. Si falta: `git clone git@github.com:o/{n}.git`."
                       for n in punteros)
    return f"# home\n\ntipo-repo: home\n\n## Reglas globales\n\n- {REGLA}\n\n## Otros repos\n\n{lineas}\n"


class FiltroGlobal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.casa = Path(self._tmp.name)
        self.proy = self.casa / "Documentos" / "Proyectos"
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
        return filtro.modo_completo(str(self.proy / "home-mario"), remoto=False)

    def reglas(self, r):
        return sorted((v["repo"], v["regla"]) for v in r["violaciones"])

    def test_todo_en_orden(self):
        self.repo("home-mario", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: producto\n\nComandos propios.\n")
        r = self.correr()
        self.assertTrue(r["valido"], r)
        self.assertEqual(r["reglas_globales"], 1)

    def test_regla_duplicada(self):
        self.repo("home-mario", home_md(["a"]))
        self.repo("a", f"# a\n\ntipo-repo: producto\n\n- {REGLA}\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "duplicado-de-global")])

    def test_duplicado_reformulado(self):
        self.repo("home-mario", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: producto\n\n- Ningún push, PR, merge ni cambio en `main` sin aprobación explícita de Mario\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "duplicado-de-global")])

    def test_excepcion_a_regla_global(self):
        self.repo("home-mario", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: producto\n\n- Excepción: aquí no aplica la regla global de aprobación.\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "excepcion-a-global")])

    def test_sin_agents_md_y_sin_tipo(self):
        self.repo("home-mario", home_md(["a", "b"]))
        self.repo("a")
        self.repo("b", "# b\n\nSin tipo.\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "sin-agents-md"), ("o/b", "sin-tipo-repo")])

    def test_tipo_desconocido(self):
        self.repo("home-mario", home_md(["a"]))
        self.repo("a", "# a\n\ntipo-repo: libreria\n")
        self.assertEqual(self.reglas(self.correr()), [("o/a", "sin-tipo-repo")])

    def test_agente_fuera_de_proyectos(self):
        """home-mario#8: un agente guardado como repo (tipo `agente`) en `~/.hermes`, fuera de Proyectos."""
        self.repo("home-mario", home_md([]) + "- **hermes-mario**: `~/.hermes`. Si falta: "
                                              "`git clone git@github.com:o/hermes-mario.git ~/.hermes`.\n")
        (self.casa / ".hermes").mkdir()
        (self.casa / ".hermes" / "AGENTS.md").write_text("# h\n\ntipo-repo: agente\n", encoding="utf-8")
        r = self.correr()
        self.assertTrue(r["valido"], r["violaciones"])
        self.assertEqual(r["repos"], [{"repo": "o/hermes-mario", "tipo": "agente"}])

    def test_cascada_por_home_hijo(self):
        self.repo("home-mario", home_md(["agencia"]))
        self.repo("agencia", home_md(["cliente-x"]).replace("# home", "# agencia"))
        self.repo("cliente-x", f"# x\n\ntipo-repo: cliente\n\n- {REGLA}\n")
        r = self.correr()
        self.assertEqual([x["repo"] for x in r["repos"]], ["o/agencia", "o/cliente-x"])
        self.assertIn(("o/cliente-x", "duplicado-de-global"), self.reglas(r))

    def test_puntero_con_placeholder_se_salta(self):
        self.repo("home-mario", home_md(["a"]) + "- **cliente**: `~/Documentos/Proyectos/cliente-<slug>`.\n")
        self.repo("a", "# a\n\ntipo-repo: web\n")
        self.assertTrue(self.correr()["valido"])

    def test_repo_sin_puntero_es_aviso(self):
        self.repo("home-mario", home_md([]))
        self.repo("suelto", "# s\n\ntipo-repo: web\n")
        r = self.correr()
        self.assertTrue(r["valido"])
        self.assertEqual([a["repo"] for a in r["avisos"]], ["suelto"])

    def test_modo_repo(self):
        d = self.repo("a", "# a\n\nSin tipo.\n")
        self.assertEqual([v["regla"] for v in filtro.modo_repo(str(d))["violaciones"]], ["sin-tipo-repo"])
        (d / "AGENTS.md").write_text("# a\n\ntipo-repo: vault\n", encoding="utf-8")
        self.assertTrue(filtro.modo_repo(str(d))["valido"])


if __name__ == "__main__":
    unittest.main()
