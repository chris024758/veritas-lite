# Deploy the Veritas-Lite demo on Render

The Render Blueprint on `deployement/sec` builds Vite and serves it with FastAPI on one Free web service. Startup seeds the synthetic case in `/tmp/veritas-demo.db`. Interviews, uploads, and illustrations may disappear when the instance restarts. Use synthetic inputs only.

1. Push `deployement/sec` to the Git remote connected to Render.
2. In Render, create a Blueprint from the repository and select `deployement/sec`, where `render.yaml` lives.
3. Set `VERITAS_DEMO_PASSWORD` to a randomly generated password of at least 24 characters. Set `GEMINI_API_KEY` for typed statement analysis and reports. For live image extraction or generated illustrations, add `GROQ_API_KEY` or both `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` to the service environment.
4. Open the Render URL. Enter username `demo` and the configured password in the browser prompt. Open a case to verify that the frontend can read the seeded database. If needed, start an interview with a synthetic typed statement to verify the Gemini configuration.

The page, API, assets, and report downloads share the same password. `/healthz` is public so Render can check whether the server is running. Typed interviews work without installing Whisper. The deployment accepts one write at a time and up to 12 writes per rolling minute, including AI requests and uploads. Verification can dispatch up to eight tools per statement. These in-memory limits reset when the service restarts.
