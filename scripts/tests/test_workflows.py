"""Toda acción externa de los workflows de este repo va fijada por SHA completo (AGENTS.md).

`sha_pinning_required` solo rige las ejecuciones de este repo; los reutilizables (ci-python, release-please…)
corren con la política del repo que los llama. Este test cubre todos los archivos publicados. Sin red.
"""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RE_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$")
RE_SHA = re.compile(r"@[0-9a-f]{40}$")
RE_VERSION = re.compile(r"#\s*v\d+\.\d+\.\d+\b")


class AccionesPorSha(unittest.TestCase):
    def test_toda_accion_externa_va_por_sha_con_su_version(self):
        archivos = sorted(WORKFLOWS.glob("*.yml"))
        self.assertTrue(archivos)
        malas = []
        for f in archivos:
            for n, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                m = RE_USES.match(linea)
                if not m or m.group(1).startswith("./"):
                    continue
                if not RE_SHA.search(m.group(1)) or not RE_VERSION.search(m.group(2)):
                    malas.append(f"{f.name}:{n}: {m.group(1)}")
        self.assertEqual(malas, [], "fijar por SHA completo con `# vX.Y.Z` (AGENTS.md)")


if __name__ == "__main__":
    unittest.main()
