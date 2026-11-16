# Convenciones

- **Código:** sigue la skill `ddd-fastapi` (`.agents/skills/ddd-fastapi`): contextos acotados con cuatro capas, agregados con comportamiento, value objects inmutables, puertos en el dominio o la aplicación, adaptadores en infraestructura. El código y sus docstrings van en inglés; la documentación del repo, en español.
- **Calidad:** `ruff check`, `mypy --strict` y `pytest` en verde antes de abrir una PR; la CI los corre en cada push y PR a `develop` y `main`.
- **Esquema:** cada cambio de tablas es una migración de Alembic generada con `--autogenerate`, leída antes de aplicarla.
- **Ramas:** `main` y `develop`, con ramas `feature/`, `bugfix/`, `chore/`, `docs/` o `ci/` que se fusionan en `develop` por PR.
- **Commits y PR:** Conventional Commits en inglés, con cuerpo (`feat(assessments): …`).
- **Parches temporales:** se marcan en el código, la configuración, la documentación y los logs, y explican cómo quitarlos.
