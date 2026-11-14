# .github de mariomina

Valores por defecto de GitHub para los repos de `mariomina` que no tienen los suyos ([docs](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/creating-a-default-community-health-file)). Es público porque GitHub lo exige.

| Ruta | Qué hereda cada repo |
|---|---|
| `.github/ISSUE_TEMPLATE/` | 4 formularios: Épica, Tarea, Bug, Mejora |
| `.github/pull_request_template.md` | Plantilla de PR |
| `CONTRIBUTING.md` · `SECURITY.md` | Forma de contribuir y aviso de seguridad |
| `.github/workflows/` | Workflows reutilizables (`ci-python`, `pr-titulo`, `release-please`): no se heredan, se llaman con `uses: mariomina/.github/.github/workflows/<archivo>@main` |

Un repo que tenga su propia carpeta `.github/ISSUE_TEMPLATE/` deja de heredar los formularios. Los repos nuevos nacen de [`plantilla-repo`](https://github.com/mariomina/plantilla-repo).
