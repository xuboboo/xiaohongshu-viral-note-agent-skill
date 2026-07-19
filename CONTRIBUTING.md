# Contributing to Xiaohongshu Viral Note Agent Skill

Thank you for your interest in contributing! This project exists because of the passion and contributions from people like you.

## How to Contribute

### Reporting Issues

- Use the GitHub Issues tracker for bugs and feature requests
- Include as much detail as possible: steps to reproduce, expected behavior, actual behavior
- For security-related issues, please see [SECURITY.md](SECURITY.md)

### Suggesting Features

- Open an Issue with the "enhancement" label
- Describe the use case and why it would benefit the community

### Submitting Code

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run the tests (`pytest`)
5. Run linting (`ruff check .`)
6. Commit your changes (`git commit -m 'feat: add amazing feature'`)
7. Push to your branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

### Code Style

- Follow PEP 8 for Python code
- Use type hints for all function signatures
- Write docstrings for public functions and classes
- Keep functions focused and small

### Testing

- Write tests for new features and bug fixes
- Ensure all tests pass before submitting
- Aim for meaningful coverage, not just high numbers

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format:

- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation changes
- `refactor:` for code refactoring
- `test:` for adding tests
- `chore:` for maintenance tasks

## Development Setup

```bash
git clone https://github.com/xuboboo/xiaohongshu-viral-note-agent-skill.git
cd xiaohongshu-viral-note-agent-skill
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e '.[dev,enterprise,ml,vision]'
```

## Questions?

Open an Issue for general questions or discussions.