# Security Policy

## Supported Versions

| Version | Supported          |
|---|---|
| 5.14.x | Yes |
| < 5.14 | No |

## Reporting a Vulnerability

If you discover a security vulnerability within this project, please send an email to [contact@xhspro.com](mailto:contact@xhspro.com). All security vulnerabilities will be promptly addressed.

**Please do not report security vulnerabilities through public GitHub issues.**

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response timeline

- Acknowledgment within 48 hours
- Initial assessment within 1 week
- Fix or mitigation plan within 2 weeks

## Security Best Practices

When deploying this Skill:

1. **Never commit secrets** — Use environment variables or a secrets manager
2. **Use strong `APP_SECRET_KEY`** — At least 32 random bytes
3. **Enable `AUTH_REQUIRED=true`** in production
4. **Use HTTPS** for all external endpoints
5. **Keep dependencies updated** — Run `pip-audit` regularly
6. **Review browser sessions** — `playwright/.auth/` contains encrypted sessions, never commit them
7. **Enterprise mode** — Enable `ENTERPRISE_STRICT_MODE=true` for production deployments

## Authentication

- API access requires Bearer token authentication
- Login requires user QR code confirmation (cannot be bypassed)
- Sessions are encrypted with AES-256-GCM
- Approval tokens are one-time use with HMAC verification

## Data Handling

- Account data is stored locally or in your PostgreSQL instance
- No data is sent to third-party services without explicit configuration
- Browser sessions are encrypted and stored locally
- Audit logs use append-only HMAC-signed hash chains