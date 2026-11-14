"""Tests de proyectos_sync.py: su log en Actions no nombra proyectos (el repo es público). Sin red."""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

RUTA = Path(__file__).resolve().parents[1] / "proyectos_sync.py"
with mock.patch.dict(os.environ, {"GH_TOKEN": "t"}):
    spec = importlib.util.spec_from_file_location("proyectos_sync", RUTA)
    ps = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ps)


class LogPublico(unittest.TestCase):
    def test_en_actions_el_proyecto_sale_por_numero(self):
        p = {"number": 4, "title": "Cliente — acme", "field": None}
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            self.assertEqual(ps.sincronizar(p, True), "  proyecto 4: sin campo Status, se salta")
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": ""}):
            self.assertIn("Cliente — acme", ps.sincronizar(p, True))


if __name__ == "__main__":
    unittest.main()
