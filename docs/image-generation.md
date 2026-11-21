# Image generation

| Setting | Value |
| --- | --- |
| Model | Black Forest Labs FLUX.1 Schnell |
| Model ID | `@cf/black-forest-labs/flux-1-schnell` |
| Inference provider | Cloudflare Workers AI, via its REST API |
| Prompt source | Gemini, using the submitted interview statement |

## Local setup

1. In the Cloudflare dashboard, open **Workers AI → Use REST API**. Copy your account ID and create a Workers AI API token using the dashboard template. [Cloudflare setup guide](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)
2. Add these entries to your existing `backend/.env`:

   ```dotenv
   CLOUDFLARE_ACCOUNT_ID=your_account_id
   CLOUDFLARE_API_TOKEN=your_api_token
   ```

3. Restart the backend. Submit a statement with a visual observation. When the claim finishes checking, the suggested prompt appears under **Image suggestions** near the top of **Findings**.
4. Choose **Generate preview**, then **Approve illustration** or **Discard preview**. Approval saves the illustration with the claim or, when the statement produced a matching case record, with that record.

The backend sends the saved prompt to Cloudflare and serves the resulting JPEG from `/generated/`. The case file only displays approved images, labeled as generated illustrations. Provider or configuration errors appear on the record's review card.

Workers AI has a shared daily free allowance. Check the current limits before relying on it for repeated demos. [Cloudflare pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
