// Adapted from Uiverse.io by andrew-manzyk: recoloured red and white, the hue-rotate swapped
// for a brightness pulse so it stays red, and a per-instance mask id so loaders can coexist.
import { useId } from "react";

export default function VeritasLoader({ size = 1, label }) {
  const maskId = `veritas-clip-${useId().replace(/:/g, "")}`;
  return (
    <span className="vloader-wrap" role="status" aria-label={label ?? "Working"}>
      <span className="vloader" style={{ "--size": size }}>
        <svg width="100" height="100" viewBox="0 0 100 100" aria-hidden="true">
          <defs>
            <mask id={maskId} className="vloader-mask">
              <polygon points="0,0 100,0 100,100 0,100" fill="black" />
              <polygon points="25,25 75,25 50,75" fill="white" />
              <polygon points="50,25 75,75 25,75" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
              <polygon points="35,35 65,35 50,65" fill="white" />
            </mask>
          </defs>
        </svg>
        <span className="vloader-box" style={{ mask: `url(#${maskId})`, WebkitMask: `url(#${maskId})` }} />
      </span>
    </span>
  );
}
