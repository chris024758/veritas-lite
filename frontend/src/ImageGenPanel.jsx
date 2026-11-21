import { useState } from "react";
import { assetUrl, generateImage } from "./api.js";

export default function ImageGenPanel() {
  const [description, setDescription] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const prompt = description.trim();
    if (!prompt || busy) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await generateImage(prompt);
      if (!response?.image_url) throw new Error(response?.note || response?.detail || "The backend returned no image.");
      setResult(response);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="image-gen-panel">
      <p className="muted">Describe a scene to create an illustration. Generated images are not evidence.</p>
      <form onSubmit={submit}>
        <label htmlFor="image-description">Scene description</label>
        <textarea id="image-description" value={description} onChange={(e) => setDescription(e.target.value)}
          placeholder="A white scooter outside a shop at night" rows={3} required />
        <button type="submit" className="primary" disabled={busy || !description.trim()}>
          {busy ? "Generating…" : "Generate image"}
        </button>
      </form>
      {busy && <p className="muted" role="status">Generating an image; this may take a minute.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <figure className="image-gen-result">
          <img src={assetUrl(result.image_url)} alt={result.placeholder ? "Image generation placeholder" : description} />
          <figcaption>{result.placeholder ? "Placeholder — no image was generated. " : "Generated illustration. "}{result.note}</figcaption>
        </figure>
      )}
    </div>
  );
}
