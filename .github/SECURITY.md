# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Murphy, please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Instead, please open a new [GitHub security advisory](https://github.com/ProsusAI/Murphy/security/advisories/new).

Please include as much of the following information as you can:

- The type of issue (e.g., command injection, credential exposure, XSS)
- Full paths of source file(s) related to the issue
- Step-by-step instructions to reproduce the issue
- Impact of the issue, including how an attacker might exploit it

## Scope

Murphy runs a browser automation agent that navigates real websites. Security considerations include:

- **Credential handling**: Murphy may handle authentication credentials during `--auth` flows
- **Browser session isolation**: Test execution runs in browser sessions that may retain cookies/state
- **LLM API keys**: API keys for LLM providers are required and should be kept secure
- **Output files**: Evaluation reports may contain screenshots or page content from tested sites

## Best Practices

- Never commit `.env` files or API keys to the repository
- Use `--no-auth` for public sites to skip credential handling
- Review `murphy/output/` contents before sharing — reports may contain sensitive page data
- Run Murphy in isolated environments (Docker) when evaluating untrusted sites
