# .github de mariomina

Valores por defecto de GitHub para los repos de `mariomina` que no tienen los suyos ([docs](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)). Es público porque GitHub lo exige.

| Ruta | Qué hereda cada repo |
|---|---|
| `.github/ISSUE_TEMPLATE/` | 4 formularios: Épica, Tarea, Bug, Mejora |
| `.github/pull_request_template.md` | Plantilla de PR |
| `CONTRIBUTING.md` · `SECURITY.md` | Forma de contribuir y aviso de seguridad |
| `.github/workflows/` | Workflows reutilizables (`ci-python`, `pr-titulo`, `release-please`): no se heredan, se llaman con `uses: mariomina/.github/.github/workflows/<archivo>@main` |
| `.github/workflows/proyectos.yml` + `scripts/proyectos_sync.py` | Automatizaciones de los Projects de la cuenta y de la org cada 15 min: alta de los issues de los repos enlazados, primer Status al entrar, último al cerrar, archivado a los 14 días. Secreto `PROJECTS_TOKEN` (`gh secret set PROJECTS_TOKEN -R mariomina/.github --body "$(gh auth token)"`; repetir si se renueva el token de `gh`) |

Un repo que tenga su propia carpeta `.github/ISSUE_TEMPLATE/` deja de heredar los formularios. Los repos nuevos nacen de [`plantilla-repo`](https://github.com/mariomina/plantilla-repo).
