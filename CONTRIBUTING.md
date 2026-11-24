# Contribuir

1. **Issue primero, uno por objetivo.** Todo cambio parte de un issue (Épica, Tarea, Bug o Mejora). Una tarea grande va como sub-issue de su épica; las dependencias, como «bloqueado por». El issue nace configurado: tipo, etiqueta `area/<x>`, épica y los campos del Project `Status`, `Prioridad` y `Tamaño`.
   - **Agentes:** `python3 -I entorno/control.py alta issue` de `mario-home` (mariomina/mario-home#234). Sale con 1 y dice qué falta si no se da un dato o si `area/<x>` no existe en el repo.
   - **Mario:** el formulario del tipo en «New issue», que fija tipo y Project; después, la etiqueta `area/<x>`, la épica y los campos del Project.
   - **Prioridad:** la calcula `scripts/prioridad.py` (`prioridad()`); para poner otra, una línea `Motivo de prioridad: <texto>` en el cuerpo.
2. **Una rama por issue**, desde `main`, con un nombre corto y descriptivo (GitHub flow). Ningún check exige un formato.
3. **Commits pequeños** con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) (`feat:`, `fix:`, `docs:`, `chore:`…).
4. **Una PR por rama**, con título convencional (lo comprueba el check `pr`). Si el objetivo necesita varias PR, las intermedias llevan `Refs #<n>` y la última `Closes #<n>`. La PR hereda la etiqueta `area/<x>` de su issue y entra en el Project: los agentes, con `control.py alta pr`; Mario, a mano.
5. **CI en verde** antes de fusionar. **Solo squash:** una PR es un commit en `main`, con el título de la PR como mensaje; revertir es una sola operación. La rama se borra al fusionar.
6. **Versiones y changelog** los genera release-please desde los commits: no se edita un `CHANGELOG.md` a mano.

## Etiquetas

Solo `area/<x>`, una por issue: la carpeta donde cae el cambio. El tipo va en el formulario del issue y la prioridad, en el campo del Project. Las etiquetas por defecto de GitHub (`bug`, `enhancement`…) no se usan; las `autorelease: *` son de release-please.

| Repo | Áreas | Fuente |
|---|---|---|
| `mario-home` | `skills`, `playbooks`, `workflows`, `agentes`, `automatizaciones`, `conectores`, `hooks`, `entorno`, `docs`, `ci` | Carpetas de primer nivel de `entorno/revisar_skills.py` (`ESTRUCTURA` y `LIBRES`); `ci` = `.github/` |
| `.github` | `scripts`, `acciones`, `plantillas`, `ci` | Carpetas `scripts/` y `acciones/`; `plantillas` = `.github/ISSUE_TEMPLATE/` y los documentos base de la raíz; `ci` = `.github/workflows/` y `dependabot.yml` |

Un repo sin fila usa las carpetas de primer nivel de su raíz, más `ci`. Un área nueva entra aquí por PR y después se crea la etiqueta.
