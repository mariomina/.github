# .github de mariomina

tipo-repo: producto

Valores por defecto de GitHub (formularios, plantilla de PR, CONTRIBUTING, SECURITY) y workflows reutilizables que llaman todos los repos de Mario. Las reglas de trabajo son las de `home-mario/AGENTS.md`; aquí solo lo propio de este repo.

## Reglas propias

- Un cambio en `.github/workflows/` afecta a todos los repos que lo llaman: los llamadores usan `@v1`, que se mueve solo al publicar una versión (release-please + `release.yml`). Un cambio que rompa la interfaz de un workflow es `feat!:` (versión mayor).
- `scripts/filtro_global.py` es la única implementación del filtro global; `scripts/proyectos_sync.py`, la de las automatizaciones de Projects; `scripts/github_pendientes.py`, la del barrido de mantenimiento (qué se fusiona solo, qué espera a Mario y qué se avisa). Solo biblioteca estándar.
- Probar un script en local antes del push: `python3 -B -m unittest discover -s scripts/tests`, `python3 -I scripts/filtro_global.py`, `python3 -I scripts/proyectos_sync.py mariomina --dry-run` y `python3 -I scripts/github_pendientes.py` (sin `--fusionar`: solo lee).
