# .github de mariomina

tipo-repo: producto

Valores por defecto de GitHub (formularios, plantilla de PR, CONTRIBUTING, SECURITY) y workflows reutilizables que llaman todos los repos de Mario. Las reglas de trabajo son las de `home-mario/AGENTS.md`; aquí solo lo propio de este repo.

## Reglas propias

- Un cambio en `.github/workflows/` afecta a todos los repos que lo llaman: los llamadores usan `@v1`, que se mueve solo al publicar una versión (release-please + `release.yml`). Un cambio que rompa la interfaz de un workflow es `feat!:` (versión mayor).
- `scripts/filtro_global.py` es la única implementación del filtro global; `scripts/proyectos_sync.py`, la de las automatizaciones de Projects; `scripts/github_pendientes.py`, la del barrido de mantenimiento (qué se fusiona solo, qué espera a Mario y qué se avisa) y la de la fusión de la PR de versión del reutilizable `release-please` (`--fusionar-version`, que el job lee de `main`, no de `@v1`: su interfaz, el flag y las variables `PRS`, `GITHUB_REPOSITORY`, `GITHUB_OUTPUT` con `fusionadas=N`, cambia solo con compatibilidad hacia atrás). Solo biblioteca estándar.
- Probar un script en local antes del push: `python3 -B -m unittest discover -s scripts/tests`, `python3 -I scripts/filtro_global.py`, `python3 -I scripts/proyectos_sync.py mariomina --dry-run` y `python3 -I scripts/github_pendientes.py` (sin `--fusionar` ni `--fusionar-version`, que fusionan PR de verdad: solo lee).
- El log de un workflow de este repo es público: ninguno imprime nombres, títulos, ramas ni datos de los repos privados. Lo que los necesita se programa en un repo privado (el barrido, en `home-mario`).
- `home-mario/.github/workflows/mantenimiento.yml` ejecuta `scripts/github_pendientes.py --fusionar` de `main` (checkout parcial de ese archivo y de `filtro_global.py`, con el token de Mario): el modo, `GH_TOKEN` y esos dos archivos solo cambian con compatibilidad hacia atrás; si el script importa otro archivo, se añade también a ese checkout.
- Toda acción externa va fijada por SHA completo, con su versión en comentario (`@<sha> # vX.Y.Z`): una etiqueta se puede mover y el código cambiaría sin pasar por aquí. Dependabot actualiza el SHA y el comentario. El repo exige SHA (`sha_pinning_required`).
