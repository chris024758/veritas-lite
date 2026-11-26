# Security review and deployment

The review covered authentication, authorization, CORS and CSRF, rate limits, private file delivery, input limits, and dependency advisories. [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)

| Finding | Applied control |
| --- | --- |
| The login screen accepted any input and API routes accepted anonymous requests | Server-side authentication uses salted scrypt password hashes, eight-hour sessions, and HttpOnly, SameSite=Strict cookies. Logout revokes the token. Production requires HTTPS and uses a Secure cookie. |
| Case IDs and file URLs gave callers access across accounts | Each case has one owner. Case reads and writes, interviews, reports, subjects, and evidence inherit that owner. Newly generated images are associated with the requesting account. |
| Broad CORS and no write-origin validation | Credentialed CORS uses a list of exact browser origins, methods, and headers. The server rejects writes from unapproved origins. |
| Unbounded requests and costly anonymous operations | SQLite shares per-IP limits across API workers. The limit is 8 sign-in attempts and 180 API requests per minute per IP, plus 60 sign-ins per minute globally and 20 expensive operations per minute per account. The server caps bodies and checks uploaded image signatures. |
| Evidence files could be served without authorization or committed to Git | Uploads and generated files are served through authenticated routes, with private responses marked no-store. Earlier Git commits still contain the three previously tracked uploads. |

## Run the demo locally

From the `backend` directory, install the requirements, run `python seed.py`, then run `uvicorn main:app --port 8018 --no-proxy-headers`. From the `frontend` directory, run `npm ci` and `npm run dev`. Open `http://localhost:5173` and use the requested `demo123` demo credentials.

Seeding assigns the three sample cases to `demo123`. For an existing database, seeding can claim matching fixtures. If a matching case has private ownership, interview history, or changed evidence or personal details, seeding stops. Use a fresh `VERITAS_DB` for the demo and keep the original database for private cases. To create a private account and give it an unassigned case, run `python security.py investigator --case CASE_ID` in `backend` and enter a unique password when prompted. Repeat `--case` to assign several cases.

## Deploy over HTTPS

- Set `VERITAS_ENV=production` and set `VERITAS_ALLOWED_ORIGINS` to the exact HTTPS frontend origin or origins. Serve the frontend and proxy the API paths through the same HTTPS origin, or build with `VITE_API_URL` pointing to an HTTPS API on the same site.
- Configure the edge to enforce HTTPS and the expected hostnames, limit request sizes and connection concurrency, and trust forwarded headers only from the reverse proxy. Keep SQLite, uploads, and generated files in private storage outside the frontend document root.
- Production disables sign-in to `demo123` by default. To expose a public demo, set `VERITAS_ENABLE_DEMO=1` on a separate deployment with its own synthetic database, files, and provider credentials and quotas. Everyone using the shared login can see changes made in that demo.
- Review which case and evidence data may be sent to Gemini, Groq, Cloudflare, or routing providers. Verify provider terms, access logs, storage encryption, and retention against your organization’s requirements.

The repository review covered application controls. TLS, proxy settings, infrastructure controls, and organizational policies require deployment-level verification.
