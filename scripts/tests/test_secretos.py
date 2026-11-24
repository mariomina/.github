"""El escaneo de secretos ve exactamente lo que añade la PR, en su archivo y línea del head (mariomina/.github#80)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secretos  # noqa: E402

DIFF = """\
diff --git a/config.py b/config.py
index 1111111..2222222 100644
--- a/config.py
+++ b/config.py
@@ -1,3 +1,4 @@
 import os
-TOKEN = os.environ["TOKEN"]
+TOKEN = "nuevo"
+++ contenido que empieza como una cabecera

@@ -10,2 +11,2 @@ def f():
 x = 1
-y = 2
+y = 3
\\ No newline at end of file
diff --git a/viejo.txt b/viejo.txt
deleted file mode 100644
--- a/viejo.txt
+++ /dev/null
@@ -1 +0,0 @@
-clave = "vieja"
diff --git "a/caf\\303\\251.md" "b/caf\\303\\251.md"
new file mode 100644
--- /dev/null
+++ "b/caf\\303\\251.md"
@@ -0,0 +1 @@
+hola
"""


class Añadidas(unittest.TestCase):
    def test_solo_lineas_añadidas_con_su_numero_del_head(self):
        self.assertEqual(
            secretos.añadidas(DIFF),
            {
                "config.py": {2: 'TOKEN = "nuevo"', 3: "++ contenido que empieza como una cabecera", 12: "y = 3"},
                "café.md": {1: "hola"},
            },
        )

    def test_ruta_fuera_del_repo_falla(self):
        with self.assertRaises(ValueError):
            secretos.añadidas("diff --git a/x b/x\n--- a/x\n+++ b/../fuera\n@@ -0,0 +1 @@\n+x\n")

    def test_escribe_cada_linea_en_su_numero(self):
        with tempfile.TemporaryDirectory() as tmp:
            secretos.escribir(secretos.añadidas(DIFF), Path(tmp))
            lineas = Path(tmp, "config.py").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lineas[1], 'TOKEN = "nuevo"')
            self.assertEqual(lineas[11], "y = 3")
            self.assertEqual(len(lineas), 12)
            self.assertTrue(Path(tmp, "café.md").exists())
            self.assertFalse(Path(tmp, "viejo.txt").exists())


if __name__ == "__main__":
    unittest.main()
