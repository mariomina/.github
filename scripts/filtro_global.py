"""Filtro global de reglas: comprueba que el AGENTS.md de cada repo cumple el reparto global/repo.

Regla (mariomina/2-cerebro#276): una regla vive en home-mario solo si aplica sin excepción a
todos los tipos de repo. Si un repo necesita una excepción, la regla baja de nivel: no se
escribe la excepción.

Modos:
  completo (por defecto)  Lee home-mario/AGENTS.md, recorre sus punteros (y los de cada home
                          repo apuntado, en cascada) y revisa el AGENTS.md de cada repo.
  --remoto                Igual, pero lee cada AGENTS.md por la API de GitHub (CI; necesita GH_TOKEN).
  --repo RUTA             Solo la estructura de un repo: AGENTS.md, tipo-repo y excepciones (PR de cada repo).

Violaciones (salida 1): repo apuntado sin AGENTS.md o sin tipo-repo válido; regla global repetida
en un repo; repo que declara una excepción a una regla global.
Avisos (salida 0): repo con git en ~/Documentos/Proyectos que no está en ningún puntero.
Salida JSON en stdout.
"""
import argparse
import base64
import difflib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

TIPOS = {"vault", "producto", "cliente", "web", "home"}
PROYECTOS = Path.home() / "Documentos" / "Proyectos"
IGNORAR_DIRS = {"worktrees"}
SIMILITUD = 0.9          # dos líneas con ratio >= 0.9 cuentan como la misma regla
MIN_REGLA = 40           # una regla más corta no se compara (evita falsos positivos)
RE_TIPO = re.compile(r"^\s*tipo-repo:\s*([a-z-]+)\s*$", re.M)
RE_RUTA = re.compile(r"`(~/Documentos/Proyectos/[^`]+)`")
RE_CLONE = re.compile(r"git@github\.com:([\w.-]+/[\w.-]+?)\.git")
RE_EXCEPCION = re.compile(
    r"(excepci[oó]n|no aplica|salvo|se ignora|ignora|no rige)[^.\n]{0,80}(regla(s)? global(es)?|home-mario)",
    re.I)


def seccion(texto, titulo):
    """Contenido de una sección '## titulo' hasta el siguiente '## '."""
    m = re.search(rf"^##\s+{re.escape(titulo)}\s*$(.*?)(?=^##\s|\Z)", texto, re.M | re.S)
    return m.group(1) if m else ""


def normalizar(linea):
    linea = re.sub(r"[`*_>#]|\[(.*?)\]\(.*?\)", r"\1", linea)
    return re.sub(r"\s+", " ", linea.strip(" -\t")).lower()


def reglas_globales(texto):
    cuerpo = seccion(texto, "Reglas globales")
    return [normalizar(l) for l in cuerpo.splitlines()
            if l.lstrip().startswith("- ") and len(normalizar(l)) >= MIN_REGLA]


def punteros(texto):
    """[(ruta_local, owner/repo)] de la sección 'Otros repos'; se saltan las rutas con <placeholder>."""
    salida = []
    for linea in seccion(texto, "Otros repos").splitlines():
        ruta = RE_RUTA.search(linea)
        if not ruta or "<" in ruta.group(1):
            continue
        clone = RE_CLONE.search(linea)
        salida.append((ruta.group(1).replace("~", str(Path.home()), 1), clone.group(1) if clone else None))
    return salida


def leer_local(ruta):
    f = Path(ruta) / "AGENTS.md"
    return f.read_text(encoding="utf-8") if f.is_file() else None


def leer_remoto(nombre):
    if not nombre:
        return None
    req = urllib.request.Request(f"https://api.github.com/repos/{nombre}/contents/AGENTS.md",
                                 headers={"Authorization": f"bearer {os.environ['GH_TOKEN']}",
                                          "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return base64.b64decode(json.load(r)["content"]).decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def revisar_estructura(nombre, texto, violaciones):
    if texto is None:
        violaciones.append({"repo": nombre, "regla": "sin-agents-md"})
        return None
    tipo = RE_TIPO.search(texto)
    if not tipo or tipo.group(1) not in TIPOS:
        violaciones.append({"repo": nombre, "regla": "sin-tipo-repo",
                            "detalle": f"falta «tipo-repo: <{'|'.join(sorted(TIPOS))}>»"})
    for n, linea in enumerate(texto.splitlines(), 1):
        if RE_EXCEPCION.search(linea):
            violaciones.append({"repo": nombre, "regla": "excepcion-a-global", "linea": n,
                                "detalle": "la regla global debe bajar de nivel, no exceptuarse"})
    return tipo.group(1) if tipo else None


def revisar_duplicados(nombre, texto, globales, violaciones):
    lineas = [normalizar(l) for l in texto.splitlines() if len(normalizar(l)) >= MIN_REGLA]
    for regla in globales:
        for n, linea in enumerate(lineas, 1):
            if difflib.SequenceMatcher(None, regla, linea).ratio() >= SIMILITUD:
                violaciones.append({"repo": nombre, "regla": "duplicado-de-global",
                                    "detalle": regla[:90]})
                break


def modo_completo(home, remoto):
    violaciones, avisos, repos = [], [], []
    texto_home = leer_local(home)
    if texto_home is None:
        sys.exit(json.dumps({"valido": False, "error": f"no existe {home}/AGENTS.md"}))
    globales = reglas_globales(texto_home)
    revisar_estructura("home-mario", texto_home, violaciones)
    vistos, pendientes = {str(Path(home).resolve())}, list(punteros(texto_home))
    while pendientes:
        ruta, nombre = pendientes.pop(0)
        clave = nombre or ruta
        if clave in vistos or str(Path(ruta).resolve()) in vistos:
            continue
        vistos.update({clave, str(Path(ruta).resolve())})
        texto = leer_remoto(nombre) if remoto else leer_local(ruta)
        etiqueta = nombre or Path(ruta).name
        tipo = revisar_estructura(etiqueta, texto, violaciones)
        repos.append({"repo": etiqueta, "tipo": tipo})
        if texto is None:
            continue
        revisar_duplicados(etiqueta, texto, globales, violaciones)
        if tipo == "home":
            pendientes.extend(punteros(texto))
    if not remoto and PROYECTOS.is_dir():
        for d in sorted(PROYECTOS.iterdir()):
            if d.name in IGNORAR_DIRS or not (d / ".git").exists():
                continue
            if str(d.resolve()) not in vistos:
                avisos.append({"repo": d.name, "regla": "sin-puntero",
                               "detalle": "repo con git que no está en ningún puntero"})
    return {"valido": not violaciones, "reglas_globales": len(globales), "repos": repos,
            "violaciones": violaciones, "avisos": avisos}


def modo_repo(ruta):
    violaciones = []
    revisar_estructura(Path(ruta).resolve().name, leer_local(ruta), violaciones)
    return {"valido": not violaciones, "violaciones": violaciones, "avisos": []}


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--home", default=str(PROYECTOS / "home-mario"))
    p.add_argument("--remoto", action="store_true")
    p.add_argument("--repo")
    a = p.parse_args()
    r = modo_repo(a.repo) if a.repo else modo_completo(a.home, a.remoto)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["valido"] else 1)


if __name__ == "__main__":
    main()
