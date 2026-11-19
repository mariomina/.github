# Contribuir

1. **Issue primero, uno por objetivo.** Todo cambio parte de un issue (Épica, Tarea, Bug o Mejora). Una tarea grande va como sub-issue de su épica; las dependencias, como «bloqueado por».
2. **Una rama por issue**, desde `main`: `feat/<n>-<slug>`, `fix/<n>-<slug>`, `docs/<n>-<slug>`, `chore/<n>-<slug>` o `experiment/<slug>`.
3. **Commits pequeños** con [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) (`feat:`, `fix:`, `docs:`, `chore:`…).
4. **Una PR por rama**, con título convencional (lo comprueba el check `pr`). Si el objetivo necesita varias PR, las intermedias llevan `Refs #<n>` y la última `Closes #<n>`.
5. **CI en verde** antes de fusionar. **Solo squash:** una PR es un commit en `main`, con el título de la PR como mensaje; revertir es una sola operación. La rama se borra al fusionar.
6. **Versiones y changelog** los genera release-please desde los commits: no se edita un `CHANGELOG.md` a mano.

Etiquetas: solo `area/<x>`. El tipo va en el formulario del issue y la prioridad, en el campo del proyecto.
