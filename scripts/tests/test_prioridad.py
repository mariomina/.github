"""Tests de prioridad.py (mariomina/mario-home#239): un caso real por regla y el orden dentro del nivel. Sin red."""
import importlib.util
import unittest
from pathlib import Path

RUTA = Path(__file__).resolve().parents[1] / "prioridad.py"
spec = importlib.util.spec_from_file_location("prioridad", RUTA)
pr_ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr_)

E, Contexto = pr_.Elemento, pr_.Contexto
PASO = "Paso 4"


def e(id_, titulo, creado="2026-11-01T00:00:00Z", **kw):
    if "etiquetas" in kw:
        kw["etiquetas"] = frozenset(kw["etiquetas"])
    if "bloquea" in kw:
        kw["bloquea"] = frozenset(kw["bloquea"])
    return E(id=id_, titulo=titulo, creado=creado, **kw)


def nivel(elemento, ctx=None):
    p = pr_.prioridad(elemento, ctx)
    return p.nivel, p.motivo


class Niveles(unittest.TestCase):
    def test_ci_rojo_en_la_rama_principal_es_p0_si_el_elemento_es_de_ci(self):
        self.assertEqual(nivel(e("a", "fix(ci): test_desplegar falla en main", ci_rojo=True)),
                         ("P0", "CI rojo en la rama principal"))
        self.assertEqual(nivel(e("b", "Tests rojos", etiquetas={"area/ci"}, ci_rojo=True))[0], "P0")
        # Con el CI en verde, el mismo elemento no es P0.
        self.assertEqual(nivel(e("c", "fix(ci): test_desplegar falla en main", tipo="PullRequest"))[0], "P1")
        # Con el CI rojo, un elemento que no es de CI tampoco.
        self.assertEqual(nivel(e("d", "docs: glosario", ci_rojo=True))[0], "P2")

    def test_freno_es_p0(self):
        self.assertEqual(nivel(e("a", "FRENO: fusiones con CI rojo")), ("P0", "issue FRENO:"))
        self.assertEqual(nivel(e("b", "Runbook del FRENO: revisar"))[0], "P2")

    def test_seguridad_es_p0(self):
        self.assertEqual(nivel(e("a", "fix(seguridad): .env legible por el agente")), ("P0", "seguridad"))
        self.assertEqual(nivel(e("b", "Token en el log", etiquetas={"security"}))[0], "P0")
        self.assertEqual(nivel(e("c", "Bump x: CVE-2026-1234"))[0], "P0")
        # Nombrar SECURITY.md no es un fallo de seguridad.
        self.assertEqual(nivel(e("d", "docs: SECURITY.md en español"))[0], "P2")

    def test_regresion_es_p0(self):
        self.assertEqual(nivel(e("a", "Regresión: la línea GitHub ya no sale", tipo_issue="Bug")), ("P0", "regresión"))
        self.assertEqual(nivel(e("b", "La línea GitHub no sale", etiquetas={"regresión"}))[0], "P0")
        # «regresión» en una tarea (tests de regresión) no es P0.
        self.assertEqual(nivel(e("c", "Tests de regresión del filtro", tipo_issue="Tarea"))[0], "P2")

    def test_issue_del_paso_actual_es_p1(self):
        cola = e("207", "Cola de agentes", paso=PASO, tipo_issue="Tarea")
        self.assertEqual(nivel(cola, pr_.contexto([cola], PASO)), ("P1", "paso actual del plan"))
        self.assertEqual(nivel(cola, pr_.contexto([cola], "Paso 5"))[0], "P2")
        self.assertEqual(nivel(cola)[0], "P2")  # sin paso actual, la regla no aplica

    def test_issue_que_bloquea_otra_del_paso_actual_es_p1(self):
        paso = e("232", "Núcleo de la cola", paso=PASO)
        hermes = e("227", "Forma de delegate_task en Hermes", bloquea={"232"})
        ajena = e("94", "Nota del vault", bloquea={"999"})
        ctx = pr_.contexto([paso, hermes, ajena], PASO)
        self.assertEqual(nivel(hermes, ctx), ("P1", "bloquea el paso actual"))
        self.assertEqual(nivel(ajena, ctx)[0], "P2")

    def test_bug_en_uso_es_p1(self):
        self.assertEqual(nivel(e("228", "test_desplegar con TMPDIR en un perfil de Hermes", tipo_issue="Bug")),
                         ("P1", "Bug en uso"))
        self.assertEqual(nivel(e("p", "fix(frontera): heredoc", tipo="PullRequest"))[0], "P1")
        # mariomina/mario-2-cerebro#356: una issue de bug sin tipo, con título convencional `fix`.
        self.assertEqual(nivel(e("356", "fix(pko): escapar la comilla de la ruta"))[0], "P1")
        self.assertEqual(nivel(e("i", "Arreglar la cola", tipo_issue="Tarea"))[0], "P2")

    def test_el_resto_es_p2(self):
        self.assertEqual(nivel(e("85", "Observabilidad del sistema", tipo_issue="Épica")), ("P2", "el resto"))

    def test_gana_la_primera_regla(self):
        self.assertEqual(nivel(e("a", "Regresión del paso", tipo_issue="Bug", paso=PASO),
                               Contexto(PASO, frozenset({"a"})))[0], "P0")


class Orden(unittest.TestCase):
    def claves(self, *elementos, paso=None):
        return [x.id for x, _ in pr_.ordenar(list(elementos), paso)]

    def test_el_nivel_va_antes_que_todo(self):
        self.assertEqual(self.claves(e("p2", "Nota", creado="2020-01-01T00:00:00Z"),
                                     e("p1", "Algo roto", tipo_issue="Bug"),
                                     e("p0", "FRENO: parar")), ["p0", "p1", "p2"])

    def test_lo_que_bloquea_mas_va_primero(self):
        self.assertEqual(self.claves(e("a", "Uno"), e("b", "Dos", bloquea={"x"}), e("c", "Tres", bloquea={"x", "y"})),
                         ["c", "b", "a"])

    def test_verificacion_antes_que_funciones(self):
        self.assertEqual(self.claves(e("f", "feat: cola nueva"), e("v", "test: casos de la cola")), ["v", "f"])

    def test_restar_antes_que_añadir(self):
        self.assertEqual(self.claves(e("f", "feat: campo nuevo"), e("r", "Quitar el campo viejo")), ["r", "f"])

    def test_lo_mas_arriesgado_primero(self):
        self.assertEqual(self.claves(e("s", "Uno", tamano="S"), e("n", "Dos"), e("l", "Tres", tamano="L")),
                         ["l", "n", "s"])

    def test_el_error_mas_frecuente_primero(self):
        self.assertEqual(self.claves(e("a", "Uno", frecuencia=1), e("b", "Dos", frecuencia=3)), ["b", "a"])

    def test_lo_mas_antiguo_primero(self):
        self.assertEqual(self.claves(e("n", "Nuevo", creado="2026-11-20T00:00:00Z"),
                                     e("v", "Viejo", creado="2026-10-01T00:00:00Z")), ["v", "n"])

    def test_los_criterios_van_en_su_orden(self):
        # Bloquear gana a verificar; verificar gana a restar; restar gana a riesgo; riesgo gana a frecuencia.
        self.assertEqual(self.claves(e("v", "test: x"), e("b", "feat: y", bloquea={"z"})), ["b", "v"])
        self.assertEqual(self.claves(e("r", "Quitar x"), e("v", "test: y")), ["v", "r"])
        self.assertEqual(self.claves(e("l", "feat: x", tamano="L"), e("r", "Quitar y")), ["r", "l"])
        self.assertEqual(self.claves(e("f", "feat: x", frecuencia=9), e("l", "feat: y", tamano="L")), ["l", "f"])


class Entradas(unittest.TestCase):
    def test_paso_actual_de_la_descripcion_del_project(self):
        self.assertEqual(pr_.paso_actual("Trabajo del sistema · Paso actual: Paso 4"), "Paso 4")
        self.assertEqual(pr_.paso_actual("Paso actual: 2c\nOtra línea"), "2c")
        self.assertIsNone(pr_.paso_actual("Trabajo del sistema de Mario"))
        self.assertIsNone(pr_.paso_actual(None))

    def test_motivo_en_el_cuerpo(self):
        self.assertTrue(pr_.tiene_motivo("## Objetivo\nx\n\nMotivo de prioridad: lo pide un cliente"))
        self.assertTrue(pr_.tiene_motivo("**Motivo de prioridad:** urgente"))
        self.assertFalse(pr_.tiene_motivo("Motivo de prioridad:"))
        self.assertFalse(pr_.tiene_motivo(None))

    def test_desde_graphql(self):
        contenido = {"__typename": "Issue", "id": "I1", "title": "Algo roto", "createdAt": "2026-11-01T00:00:00Z",
                     "issueType": {"name": "Bug"}, "labels": {"nodes": [{"name": "area/ci"}]},
                     "blocking": {"nodes": [{"id": "I2", "state": "OPEN"}, {"id": "I3", "state": "CLOSED"}]},
                     "reactions": {"totalCount": 2}}
        item = {"prioridad": {"name": "P2"}, "paso": {"name": PASO}, "tamano": {"name": "L"}}
        x = pr_.desde_graphql(contenido, item, ci_rojo=True)
        self.assertEqual((x.id, x.tipo, x.tipo_issue, x.etiquetas, x.paso, x.bloquea, x.tamano, x.frecuencia, x.ci_rojo),
                         ("I1", "Issue", "Bug", frozenset({"area/ci"}), PASO, frozenset({"I2"}), "L", 2, True))
        vacio = pr_.desde_graphql({"__typename": "PullRequest", "id": "P1", "title": "t", "createdAt": "c"})
        self.assertEqual((vacio.tipo, vacio.paso, vacio.bloquea, vacio.frecuencia), ("PullRequest", None, frozenset(), 0))


if __name__ == "__main__":
    unittest.main()
