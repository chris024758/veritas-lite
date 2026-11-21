# Image generation

| Setting | Value |
| --- | --- |
| Model | Black Forest Labs FLUX.1 Schnell |
| Model ID | `@cf/black-forest-labs/flux-1-schnell` |
| Inference provider | Cloudflare Workers AI, via its REST API |
| Local API | `POST /tools/generate-image` with a JSON `description` |

## Local setup

1. In the Cloudflare dashboard, open **Workers AI → Use REST API**. Copy your account ID and create a Workers AI API token using the dashboard template. [Cloudflare setup guide](https://developers.cloudflare.com/workers-ai/get-started/rest-api/)
2. Add these entries to your existing `backend/.env`:

   ```dotenv
   CLOUDFLARE_ACCOUNT_ID=your_account_id
   CLOUDFLARE_API_TOKEN=your_api_token
   ```

3. Restart the backend. In the frontend, open **Image generator**, enter a description, and select **Generate image**.

The backend sends the description to Cloudflare as the model prompt, saves the returned JPEG in `backend/generated/`, and serves it at `/generated/<filename>.jpg`. If either credential is missing, the panel shows a placeholder. If Cloudflare rejects the request, the panel reports an error.

Workers AI has a shared daily free allowance. Check the current limits before relying on it for repeated demos. [Cloudflare pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
