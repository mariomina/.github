# .github de mariomina

Valores por defecto de GitHub para los repos de `mariomina` que no tienen los suyos ([docs](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)). Es público porque GitHub lo exige.

| Ruta | Qué hereda cada repo |
|---|---|
| `.github/ISSUE_TEMPLATE/` | 4 formularios: Épica, Tarea, Bug, Mejora |
| `.github/pull_request_template.md` | Plantilla de PR |
| `CONTRIBUTING.md` · `SECURITY.md` | Forma de contribuir y aviso de seguridad |
| `.github/workflows/` | Workflows reutilizables (`ci-python`, `pr-titulo`, `release-please`): no se heredan, se llaman con `uses: mariomina/.github/.github/workflows/<archivo>@v1` |
| `.github/workflows/proyectos.yml` + `scripts/proyectos_sync.py` | Automatizaciones de los Projects de la cuenta y de la org cada 15 min (el workflow se mantiene vivo solo frente a los 60 días sin actividad; su log solo tiene cuentas): alta de los issues de los repos enlazados, primer Status al entrar, último al cerrar, archivado a los 14 días. Secreto `PROJECTS_TOKEN` (`gh secret set PROJECTS_TOKEN -R mariomina/.github --body "$(gh auth token)"`; repetir si se renueva el token de `gh`) |
| `.github/workflows/agents-md.yml` + `scripts/filtro_global.py` | Filtro global (mariomina/2-cerebro#276): el `AGENTS.md` de cada repo existe, declara `tipo-repo` y no exceptúa reglas globales. En local y en el CI de `home-mario` revisa además los duplicados frente a `home-mario/AGENTS.md` |
| Versiones | release-please + `release.yml`: cada versión mueve el tag `v<major>`. Los repos llaman a los reutilizables con `@v1`. El reutilizable `release-please` fusiona su propia PR de versión (`github_pendientes.py --fusionar-version`) y publica la versión en la misma ejecución (mariomina/2-cerebro#280) |
| `scripts/github_pendientes.py` | Barrido de pendientes de GitHub sobre los repos de los punteros de `home-mario/AGENTS.md`, en cascada (mariomina/2-cerebro#280). Lo programa `home-mario` (`mantenimiento.yml`, cada 3 h), que es privado: el log del barrido nombra repos, PR, ramas y títulos, y aquí sería público (si corre en un repo público, solo imprime cuentas). Fusiona las PR de versión atascadas y las de Dependabot de parche o menor con CI en verde. Dependabot mayor y PR de trabajo esperan a Mario; workflows desactivados, CI rojo en la rama principal, ramas y PR de más de 7 días e issues sin proyecto solo se avisan. En local: `python3 -I scripts/github_pendientes.py` (tabla) o `--linea` (la línea `GitHub:` de la apertura de sesión de Claudian y Hermes, desde la caché `~/.cache/mariomina-github/pendientes.json`) |

Un repo que tenga su propia carpeta `.github/ISSUE_TEMPLATE/` deja de heredar los formularios. Los repos nuevos nacen de [`plantilla-repo`](https://github.com/mariomina/plantilla-repo).
