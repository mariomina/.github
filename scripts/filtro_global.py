"""Filtro global de reglas: comprueba que el AGENTS.md de cada repo cumple el reparto global/repo.

Regla (mariomina/mario-2-cerebro#276): una regla vive en mario-home solo si aplica sin excepción a
todos los tipos de repo. Si un repo necesita una excepción, la regla baja de nivel: no se
escribe la excepción.

Modos:
  completo (por defecto)  Lee mario-home/AGENTS.md, recorre sus punteros (y los de cada home
                          repo apuntado, en cascada) y revisa el AGENTS.md de cada repo.
  --remoto                Igual, pero lee cada AGENTS.md por la API de GitHub (CI; necesita GH_TOKEN).
                          Un token de GitHub App vale para una sola cuenta: GH_TOKEN_<DUEÑO> (p. ej.
                          GH_TOKEN_ESCALA_AGENCIA) manda sobre GH_TOKEN en los repos de ese dueño.
  --repo RUTA             Solo la estructura de un repo: AGENTS.md, tipo-repo y excepciones (PR de cada repo).
  --nombres               Con el modo completo: además, los documentos base de cada repo apuntado (Markdown de la
                          raíz y de docs/, sin docs/investigaciones/ ni CHANGELOG.md) no nombran un repo ni un
                          check que no existe (mariomina/.github#55). El inventario sale de los punteros y de los
                          workflows con pull_request de cada repo: nada que mantener a mano.

Violaciones (salida 1): repo apuntado sin AGENTS.md o sin tipo-repo válido; `autonomia: N` sin declarar, fuera de 0–2,
o distinto de 0 en un home repo o en .github (mariomina/mario-home#19); regla global repetida
en un repo; repo que declara una excepción a una regla global; con --nombres, nombre-repo y nombre-check.
Avisos (salida 0): repo con git en ~/Documentos/Mario (o en una carpeta de grupo sin git, como
mario-agencia/) que no está en ningún puntero.
Salida JSON en stdout.
"""
import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

TIPOS = {"vault", "producto", "cliente", "web", "home", "agente"}
PROYECTOS = Path.home() / "Documentos" / "Mario"
IGNORAR_DIRS = {"worktrees"}
SIMILITUD = 0.9          # dos líneas con ratio >= 0.9 cuentan como la misma regla
MIN_REGLA = 40           # una regla más corta no se compara (evita falsos positivos)
RE_TIPO = re.compile(r"^\s*tipo-repo:\s*([a-z-]+)\s*$", re.M)
RE_AUTONOMIA = re.compile(r"^\s*autonomia:\s*(\S*)\s*$", re.M)  # mariomina/mario-home#19
NIVELES = {"0", "1", "2"}
# puntero: «- **nombre** (descripción): `ruta`»; la ruta, cualquiera bajo ~ (p. ej. ~/.hermes), es la que sigue a la
# descripción, que puede nombrar otras rutas (mariomina/.github#48)
RE_RUTA = re.compile(r"^\s*- \*\*[^*]+\*\*\s*(?:\((?:[^()]|\([^()]*\))*\))?:\s*`(~/[^`]+)`")
RE_CLONE = re.compile(r"git@github\.com:([\w.-]+/[\w.-]+?)\.git")
RE_EXCEPCION = re.compile(
    r"(excepci[oó]n|no aplica|salvo|se ignora|ignora|no rige)[^.\n]{0,80}(regla(s)? global(es)?|mario-home)",
    re.I)
# --nombres (mariomina/.github#55)
RE_CODIGO = re.compile(r"`([^`\n]+)`")
RE_PALABRA_REPO = re.compile(r"(?<![\w.<~/-])((?:mario|agencia|home)-[a-z0-9][\w-]*[a-z0-9])(?![\w<-])")
RE_PAR_CHECK = re.compile(r"^([\w.-]+) / ([\w.-]+)$")
RE_UN_CHECK = re.compile(r"^[a-z][\w-]*$")
RE_ANTES_CHECK = re.compile(r"\b(?:checks?|comprueba|jobs?)\s*$", re.I)


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
        ruta = RE_RUTA.match(linea)
        if not ruta or "<" in ruta.group(1):
            continue
        clone = RE_CLONE.search(linea)
        salida.append((ruta.group(1).replace("~", str(Path.home()), 1), clone.group(1) if clone else None))
    return salida


def leer_local(ruta):
    f = Path(ruta) / "AGENTS.md"
    return f.read_text(encoding="utf-8") if f.is_file() else None


def token(nombre):
    """Token para `owner/repo`: GH_TOKEN_<DUEÑO> si existe, si no GH_TOKEN. Mismo criterio en github_pendientes.py."""
    dueno = re.sub(r"\W", "_", nombre.split("/")[0]).upper()
    return os.environ.get(f"GH_TOKEN_{dueno}") or os.environ["GH_TOKEN"]


def api(nombre, ruta):
    req = urllib.request.Request(f"https://api.github.com/repos/{nombre}/{ruta}",
                                 headers={"Authorization": f"bearer {token(nombre)}",
                                          "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def leer_remoto(nombre, archivo="AGENTS.md"):
    if not nombre:
        return None
    try:
        datos = api(nombre, f"contents/{urllib.parse.quote(archivo)}")
        return base64.b64decode(datos["content"]).decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def archivos_local(ruta):
    r = subprocess.run(["git", "-C", str(ruta), "ls-files"], capture_output=True, text=True)
    return set(r.stdout.splitlines()) if r.returncode == 0 else set()


def archivos_remoto(nombre):
    return {e["path"] for e in api(nombre, "git/trees/HEAD?recursive=1")["tree"] if e["type"] == "blob"}


def revisar_estructura(nombre, texto, violaciones):
    if texto is None:
        violaciones.append({"repo": nombre, "regla": "sin-agents-md"})
        return None
    tipo = RE_TIPO.search(texto)
    if not tipo or tipo.group(1) not in TIPOS:
        violaciones.append({"repo": nombre, "regla": "sin-tipo-repo",
                            "detalle": f"falta «tipo-repo: <{'|'.join(sorted(TIPOS))}>»"})
    autonomia = RE_AUTONOMIA.search(texto)
    if not autonomia and tipo and tipo.group(1) in TIPOS:
        violaciones.append({"repo": nombre, "regla": "sin-autonomia",
                            "detalle": "falta «autonomia: <0|1|2>» junto a tipo-repo"})
    elif autonomia and autonomia.group(1) not in NIVELES:
        violaciones.append({"repo": nombre, "regla": "autonomia-invalida",
                            "detalle": f"«autonomia: {autonomia.group(1)}»: el nivel es 0, 1 o 2"})
    elif autonomia and autonomia.group(1) != "0" and ((tipo and tipo.group(1) == "home")
                                                      or nombre.rstrip("/").endswith("/.github")):
        violaciones.append({"repo": nombre, "regla": "autonomia-fija-en-0",
                            "detalle": "los home repos y .github fijan las reglas: su nivel es siempre 0"})
    # En el home que define las reglas globales, el resto de su texto son reglas de su nivel (#56).
    define_globales = bool(tipo and tipo.group(1) == "home" and seccion(texto, "Reglas globales").strip())
    actual = None
    for n, linea in enumerate(texto.splitlines(), 1):
        if titulo := re.match(r"##\s+(.*?)\s*$", linea):
            actual = titulo.group(1)
        if (not define_globales or actual == "Reglas globales") and RE_EXCEPCION.search(linea):
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


def es_documento(ruta):
    """Documento base: Markdown de la raíz o de docs/, sin investigaciones (fechadas) ni el changelog generado."""
    if not ruta.endswith(".md") or ruta == "CHANGELOG.md":
        return False
    return "/" not in ruta or (ruta.startswith("docs/") and not ruta.startswith("docs/investigaciones/"))


def nombres_de_jobs(texto):
    """Nombre del workflow, id y `name` de cada job: lo que GitHub muestra como check (`workflow / job`)."""
    cabeza, _, jobs = texto.partition("\njobs:")
    return (set(re.findall(r"^name:\s*['\"]?([^'\"\n#]+?)['\"]?\s*$", cabeza, re.M))
            | set(re.findall(r"^  ([\w-]+):\s*$", jobs, re.M))
            | set(re.findall(r"^    name:\s*['\"]?([^'\"\n#]+?)['\"]?\s*$", jobs, re.M)))


def inventario_checks(repos):
    """Checks de PR de todos los repos: workflows con pull_request y los jobs de los reutilizables que llaman."""
    workflows = {f"{nombre}/{ruta}": texto for nombre, r in repos.items()
                 for ruta, texto in r["textos"].items() if ruta.startswith(".github/workflows/")}
    checks = set()
    for texto in workflows.values():
        if "pull_request" not in texto.partition("\njobs:")[0]:
            continue
        checks |= nombres_de_jobs(texto)
        for uso in re.findall(r"uses:\s*([\w.-]+/[\w.-]+/\.github/workflows/[\w.-]+)@", texto):
            checks |= nombres_de_jobs(workflows.get(uso, ""))
    return checks


def revisar_nombres(repos, otros_nombres, violaciones):
    """Nombres de repo y de check que no existen, en el código (`…`) de los documentos base (mariomina/.github#55).

    repos: {nombre: {"textos": {ruta: texto}}}, con los documentos y los workflows de cada repo apuntado.
    otros_nombres: nombres de los punteros sin leer y de las carpetas locales y de grupo (mario-github, mario-agencia).
    Las rutas de archivo no se comprueban: medido el 18-11 sobre los repos apuntados, 120 avisos y ningún nombre
    desfasado que no vieran ya las 2 reglas (rutas de otros repos y del home, etiquetas, prefijos de rama).
    """
    cortos = {n.split("/")[-1] for n in repos} | set(otros_nombres)
    duenos = "|".join(sorted({re.escape(n.split("/")[0]) for n in repos if "/" in n})) or "(?!)"
    re_dueno = re.compile(rf"\b({duenos})"
                          r"/([\w.-]+?)(?:\.git)?(?![\w.<-])")
    checks = inventario_checks(repos)
    for nombre, r in repos.items():
        for ruta, texto in sorted(r["textos"].items()):
            if not es_documento(ruta):
                continue
            for n, linea in enumerate(texto.splitlines(), 1):
                for m in RE_CODIGO.finditer(linea):
                    valor, malos = m.group(1).strip(), []
                    malos += [("nombre-repo", c) for c in RE_PALABRA_REPO.findall(valor) if c not in cortos]
                    malos += [("nombre-repo", f"{d}/{c}") for d, c in re_dueno.findall(valor) if c not in cortos]
                    par = RE_PAR_CHECK.match(valor)
                    if par or (RE_UN_CHECK.match(valor) and RE_ANTES_CHECK.search(linea[:m.start()])):
                        if not set(par.groups() if par else [valor]) <= checks:
                            malos.append(("nombre-check", valor))
                    violaciones.extend({"repo": nombre, "regla": regla, "archivo": ruta, "linea": n, "detalle": d}
                                       for regla, d in malos)


def repos_locales():
    """Repos con git en PROYECTOS y en sus carpetas de grupo (un nivel, carpetas sin git: mario-agencia/)."""
    for d in sorted(PROYECTOS.iterdir()):
        if d.name in IGNORAR_DIRS or not d.is_dir():
            continue
        if (d / ".git").exists():
            yield d
        elif not d.is_symlink():
            yield from (h for h in sorted(d.iterdir())
                        if h.is_dir() and h.name not in IGNORAR_DIRS and (h / ".git").exists())


def cargar(ruta, nombre, remoto):
    """Documentos base y workflows de un repo, para --nombres."""
    if remoto:
        archivos, leer = archivos_remoto(nombre), lambda f: leer_remoto(nombre, f)
    else:
        archivos = archivos_local(ruta)
        def leer(f):
            p = Path(ruta) / f
            return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else None
    textos = {f: leer(f) for f in sorted(archivos)
              if es_documento(f) or (f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")))}
    return {"textos": {f: t for f, t in textos.items() if t is not None}}


def modo_completo(home, remoto, nombres=False):
    violaciones, avisos, repos = [], [], []
    texto_home = leer_local(home)
    if texto_home is None:
        sys.exit(json.dumps({"valido": False, "error": f"no existe {home}/AGENTS.md"}))
    globales = reglas_globales(texto_home)
    revisar_estructura("mario-home", texto_home, violaciones)
    datos = {"mario-home": cargar(home, None, False)} if nombres else {}
    otros = set()  # nombres que existen: el de cada puntero, aunque falte su copia, y las carpetas locales y de grupo
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
        otros |= {etiqueta.split("/")[-1], Path(ruta).name}
        otros |= {p.name for p in Path(ruta).parents if PROYECTOS in p.parents}
        if texto is None:
            continue
        revisar_duplicados(etiqueta, texto, globales, violaciones)
        if nombres and (nombre or not remoto):
            datos[etiqueta] = cargar(ruta, nombre, remoto)
        if tipo == "home":
            pendientes.extend(punteros(texto))
    if nombres:
        revisar_nombres(datos, otros, violaciones)
    if not remoto and PROYECTOS.is_dir():
        for d in repos_locales():
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
    p.add_argument("--home", default=str(PROYECTOS / "mario-home"))
    p.add_argument("--remoto", action="store_true")
    p.add_argument("--repo")
    p.add_argument("--nombres", action="store_true")
    a = p.parse_args()
    r = modo_repo(a.repo) if a.repo else modo_completo(a.home, a.remoto, a.nombres)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r["valido"] else 1)


if __name__ == "__main__":
    main()
