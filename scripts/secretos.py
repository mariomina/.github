"""Escaneo de secretos de una PR: gitleaks sobre las líneas que la PR añade (mariomina/.github#80).

Solo lo que añade la PR, no el árbol entero: un falso positivo que ya estaba en un repo no bloquea cada PR.
Las líneas salen del `patch` de cada archivo del endpoint `pulls/{n}/files` (hasta 3000 archivos; el diff
entero devuelve 406 con más de 300). Cada archivo se reconstruye con sus líneas añadidas en su número de
línea del head (el resto, en blanco), bajo `head/`, y gitleaks informa `head/<archivo>` y la línea real.
Un secreto de prueba se admite con `gitleaks:allow` en su línea. La configuración de gitleaks es siempre la
suya por defecto: un `.gitleaks.toml` o `.gitleaksignore` que añada la PR queda bajo `head/` y no se carga.
Uso: GH_TOKEN=… GITHUB_REPOSITORY=dueño/repo python3 -I scripts/secretos.py <número de PR>
Solo biblioteca estándar.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

# Fijado por versión y SHA-256 del tarball (gitleaks_<versión>_checksums.txt de la release, igual al `digest`
# del asset en la API). Dependabot no lo ve: se sube a mano.
VERSION = "8.30.1"
SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
URL = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_linux_x64.tar.gz"
RE_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
POR_PAGINA, PAGINAS = 100, 30  # el endpoint devuelve como mucho 3000 archivos


def segura(nombre: str) -> str:
    p = PurePosixPath(nombre)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"ruta fuera del repo: {nombre}")
    return str(p)


def lineas_añadidas(patch: str) -> dict[int, str]:
    """Del `patch` de un archivo, sus líneas añadidas por número de línea del head."""
    lineas: dict[int, str] = {}
    n = 0
    for linea in patch.split("\n"):  # no splitlines: \r, \x0b o U+2028 son parte de la línea
        if m := RE_HUNK.match(linea):
            n = int(m.group(1))
        elif linea.startswith("+"):
            lineas[n] = linea[1:]
            n += 1
        elif linea.startswith(" "):
            n += 1
    return lineas


def añadidas(items: list[dict]) -> tuple[dict[str, dict[int, str]], int]:
    """Por archivo del head, sus líneas añadidas; y cuántos archivos no traen `patch` (binarios o enormes)."""
    archivos: dict[str, dict[int, str]] = {}
    sin_patch = 0
    for it in items:
        if it["status"] == "removed":
            continue
        if "patch" not in it:
            sin_patch += 1
        elif lineas := lineas_añadidas(it["patch"]):
            archivos[segura(it["filename"])] = lineas
    return archivos, sin_patch


def escribir(archivos: dict[str, dict[int, str]], raiz: Path) -> None:
    for nombre, lineas in archivos.items():
        destino = raiz / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("\n".join(lineas.get(i, "") for i in range(1, max(lineas) + 1)) + "\n", encoding="utf-8")


def descargar(url: str, cabeceras: dict[str, str] | None = None) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=cabeceras or {}), timeout=60) as r:
        return r.read()


def archivos_de_la_pr(pr: str) -> list[dict]:
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    cabeceras = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}
    items: list[dict] = []
    for pagina in range(1, PAGINAS + 1):
        url = f"{api}/repos/{os.environ['GITHUB_REPOSITORY']}/pulls/{pr}/files?per_page={POR_PAGINA}&page={pagina}"
        lote = json.loads(descargar(url, cabeceras))
        items += lote
        if len(lote) < POR_PAGINA:
            return items
    print(f"::warning::La PR tiene más de {POR_PAGINA * PAGINAS} archivos: la API no da el resto y no se escanea")
    return items


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
    archivos, sin_patch = añadidas(archivos_de_la_pr(pr))
    if sin_patch:
        print(f"::warning::{sin_patch} archivos sin patch en la API (binarios o demasiado grandes): no se escanean")
    if not archivos:
        print("La PR no añade líneas de texto")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp, "pr")  # solo contiene head/: ninguna configuración de la PR queda en su raíz
        escribir(archivos, raiz / "head")
        binario = gitleaks(Path(tmp))
        entorno = {k: v for k, v in os.environ.items() if not k.startswith("GITLEAKS_")}
        orden = [binario, "dir", ".", "-v", "--redact", "--no-banner", "--exit-code", "2"]
        rc = subprocess.run(orden, cwd=raiz, env=entorno).returncode
    if rc == 2:
        print("::error::La PR añade algo que parece un secreto: rótalo y quítalo; si es de prueba, `gitleaks:allow` en su línea")
    elif rc:
        print(f"::error::gitleaks no pudo terminar el escaneo (código {rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
