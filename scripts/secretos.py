"""Escaneo de secretos de una PR: gitleaks sobre las líneas que la PR añade (mariomina/.github#80).

Solo lo que añade la PR, no el árbol entero: un falso positivo que ya estaba en un repo no bloquea cada PR.
Cada archivo se reconstruye con sus líneas añadidas en su número de línea del head (el resto, en blanco), y
gitleaks informa archivo y línea reales. Un secreto de prueba se admite con `gitleaks:allow` en su línea.
Uso: GH_TOKEN=… GITHUB_REPOSITORY=dueño/repo python3 -I scripts/secretos.py <número de PR>
Solo biblioteca estándar.
"""
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

# Fijado por versión y SHA-256 del tarball (gitleaks_<versión>_checksums.txt de la release, igual al `digest`
# del asset en la API). Dependabot no lo ve: se sube a mano.
VERSION = "8.30.1"
SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
URL = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_linux_x64.tar.gz"
RE_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def ruta(cabecera: str) -> str | None:
    """`+++ b/ruta`, `+++ "b/ruta con \\303\\251"` o `+++ /dev/null` (archivo borrado: None)."""
    r = cabecera[4:]
    if r.startswith('"'):
        r = r[1:-1].encode("latin-1").decode("unicode_escape").encode("latin-1").decode("utf-8")
    if r == "/dev/null":
        return None
    p = PurePosixPath(r.removeprefix("b/"))
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"ruta fuera del repo en el diff: {r}")
    return str(p)


def añadidas(diff: str) -> dict[str, dict[int, str]]:
    """Por archivo del head, sus líneas añadidas por número de línea."""
    archivos: dict[str, dict[int, str]] = {}
    actual, en_hunk, n = None, False, 0
    for linea in diff.splitlines():
        if linea.startswith("diff --git "):
            actual, en_hunk = None, False
        elif not en_hunk and linea.startswith("+++ "):
            actual = ruta(linea)
        elif m := RE_HUNK.match(linea):
            en_hunk, n = True, int(m.group(1))
        elif en_hunk and actual is not None:
            if linea.startswith("+"):
                archivos.setdefault(actual, {})[n] = linea[1:]
                n += 1
            elif not linea.startswith(("-", "\\")):
                n += 1
    return archivos


def escribir(archivos: dict[str, dict[int, str]], raiz: Path) -> None:
    for nombre, lineas in archivos.items():
        destino = raiz / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("\n".join(lineas.get(i, "") for i in range(1, max(lineas) + 1)) + "\n", encoding="utf-8")


def descargar(url: str, cabeceras: dict[str, str] | None = None) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=cabeceras or {}), timeout=60) as r:
        return r.read()


def gitleaks(destino: Path) -> Path:
    datos = descargar(URL)
    if hashlib.sha256(datos).hexdigest() != SHA256:
        sys.exit("::error::El tarball de gitleaks no coincide con su SHA-256 fijado")
    with tarfile.open(fileobj=io.BytesIO(datos)) as tar:
        tar.extract("gitleaks", destino, filter="data")
    binario = destino / "gitleaks"
    binario.chmod(0o755)
    return binario


def main(pr: str) -> int:
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    try:
        diff = descargar(
            f"{api}/repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{pr}",
            {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github.diff"},
        ).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        print(f"::error::No se pudo leer el diff de la PR (HTTP {e.code}; 406 = diff demasiado grande para la API)")
        return 1
    archivos = añadidas(diff)
    if not archivos:
        print("La PR no añade líneas de texto")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp, "pr")
        escribir(archivos, raiz)
        binario = gitleaks(Path(tmp))
        rc = subprocess.run([binario, "dir", ".", "-v", "--redact", "--no-banner", "--exit-code", "1"], cwd=raiz).returncode
    if rc:
        print("::error::La PR añade algo que parece un secreto: rótalo y quítalo; si es de prueba, `gitleaks:allow` en su línea")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
