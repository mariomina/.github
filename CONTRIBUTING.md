# Contribuir

1. **Issue primero.** Todo cambio parte de un issue (Épica, Tarea, Bug o Mejora). Una tarea grande va como sub-issue de su épica; las dependencias, como «bloqueado por».
2. **Una rama por issue**, desde `main`: `feat/<n>-<slug>`, `fix/<n>-<slug>`, `docs/<n>-<slug>`, `chore/<n>-<slug>` o `experiment/<slug>`.
3. **Commits pequeños** con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) (`feat:`, `fix:`, `docs:`, `chore:`…).
4. **Una PR por rama**, con `Closes #<n>` y título convencional (lo comprueba `pr-titulo`).
5. **CI en verde** antes de fusionar. La rama se borra al fusionar.
6. **Versiones y changelog** los genera release-please desde los commits: no se edita un `CHANGELOG.md` a mano.

Etiquetas: solo `area/<x>`. El tipo va en el formulario del issue y la prioridad, en el campo del proyecto.
