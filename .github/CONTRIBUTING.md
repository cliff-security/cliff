# Contributing to Cliff

Thank you for your interest in contributing to Cliff!

## Getting Started

1. Fork the repository
2. Clone with submodules: `git clone --recurse-submodules <your-fork-url>`
3. Follow the [development setup guide](../docs/guides/development-setup.md)
4. Create a branch for your work: `git checkout -b feat/your-feature`

## Development Workflow

1. Check the [ROADMAP.md](../ROADMAP.md) for current priorities
2. Pick an issue or propose a new one
3. Write code following the conventions below
4. Submit a pull request

## Conventions

### Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `refactor:` — code change that neither fixes a bug nor adds a feature
- `test:` — adding or updating tests
- `chore:` — maintenance, dependencies, CI

### Code Style

- **Python:** Use ruff for linting and formatting. Strict type hints. Pydantic models for data structures.
- **TypeScript:** ESLint + Prettier. Strict mode enabled.

### Architecture Decisions

Significant decisions are recorded as ADRs in `docs/adr/`. If your contribution involves an architectural change:

1. Create a new ADR using the template in `docs/adr/README.md`
2. Set status to `Proposed`
3. Include it in your pull request for discussion

### Adapters

All external integrations go through adapter interfaces. See `docs/architecture/adapter-interfaces.md`. New adapters must:

1. Implement the relevant interface
2. Include a mock/fixture provider for testing
3. Not break existing adapters

### Agent Output Rule

Every agent result must persist into both the chat timeline AND the SidebarState. Agent output must never live only as chat text.

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Reference the related issue if one exists
- Include a description of what changed and why
- Add tests for new functionality
- Ensure existing tests pass

## Reporting Issues

Use GitHub Issues. Please include:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Environment details (OS, Docker version, browser)

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0 License](../LICENSE).
