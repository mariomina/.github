"""El escaneo de secretos ve exactamente lo que añade la PR, en su archivo y línea del head (mariomina/.github#80)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secretos  # noqa: E402

# Forma de los items de GET /repos/{dueño}/{repo}/pulls/{n}/files.
ITEMS = [
    {
        "filename": "config.py",
        "status": "modified",
        "patch": (
            "@@ -1,3 +1,4 @@\n"
            " import os\n"
            '-TOKEN = os.environ["TOKEN"]\n'
            '+TOKEN = "nuevo"\n'
            "+++ contenido que empieza como una cabecera\n"
            " \n"
            "@@ -10,2 +11,2 @@ def f():\n"
            " x = 1\n"
            "-y = 2\n"
            "+y = 3\r con retorno de carro\n"
            "\\ No newline at end of file"
        ),
    },
    {"filename": "viejo.txt", "status": "removed", "patch": '@@ -1 +0,0 @@\n-clave = "vieja"'},
    {"filename": "con espacio/café x.md", "status": "added", "patch": "@@ -0,0 +1 @@\n+hola"},
    {"filename": "imagen.png", "status": "added"},
    {"filename": ".gitleaks.toml", "status": "added", "patch": "@@ -0,0 +1 @@\n+[allowlist]"},
]


class Añadidas(unittest.TestCase):
    def test_solo_lineas_añadidas_con_su_numero_del_head(self):
        archivos, sin_patch = secretos.añadidas(ITEMS)
        self.assertEqual(
            archivos,
            {
                "config.py": {2: 'TOKEN = "nuevo"', 3: "++ contenido que empieza como una cabecera", 12: "y = 3\r con retorno de carro"},
                "con espacio/café x.md": {1: "hola"},
                ".gitleaks.toml": {1: "[allowlist]"},
            },
        )
        self.assertEqual(sin_patch, 1)

    def test_ruta_fuera_del_repo_falla(self):
        with self.assertRaises(ValueError):
            secretos.añadidas([{"filename": "../fuera", "status": "added", "patch": "@@ -0,0 +1 @@\n+x"}])

    def test_escribe_cada_linea_en_su_numero_bajo_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            raiz = Path(tmp)
            secretos.escribir(secretos.añadidas(ITEMS)[0], raiz / "head")
            lineas = (raiz / "head" / "config.py").read_bytes().decode("utf-8").split("\n")
            self.assertEqual(lineas[1], 'TOKEN = "nuevo"')
            self.assertEqual(lineas[11], "y = 3\r con retorno de carro")
            self.assertTrue((raiz / "head" / "con espacio" / "café x.md").exists())
            self.assertFalse((raiz / "head" / "viejo.txt").exists())
            # La configuración que añade la PR no queda donde gitleaks la cargaría (la raíz que escanea).
            self.assertEqual([p.name for p in raiz.iterdir()], ["head"])


if __name__ == "__main__":
    unittest.main()
