import { ImageResponse } from "next/og";

export const runtime = "edge";

export const alt = "Shorelife — California beach health forecasts";
export const size = {
  width: 1200,
  height: 630,
};

export const contentType = "image/png";

export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          background: "#faf6ee",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Background Texture - stylized coastlines */}
        <div style={{ position: "absolute", inset: 0, display: "flex", opacity: 0.1 }}>
          <svg width="1200" height="630" viewBox="0 0 1200 630">
            {[100, 200, 300, 400, 500].map((y) => (
              <path
                key={y}
                d={`M 0 ${y} Q 300 ${y - 40} 600 ${y} T 1200 ${y}`}
                stroke="#0b4266"
                strokeWidth="2"
                fill="none"
              />
            ))}
          </svg>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 60 }}>
          {/* Logo Mark */}
          <div style={{ display: "flex" }}>
            <svg width="240" height="240" viewBox="0 0 100 100">
              <circle cx="50" cy="50" r="48" fill="none" />
              <g clipPath="circle(48% at 50% 50%)">
                <path d="M 0 0 L 50 0 C 12 18 12 38 50 50 C 88 62 88 82 50 96 L 50 100 L 0 100 Z" fill="#0b4266" />
                <path d="M 50 0 L 100 0 L 100 100 L 50 100 C 88 82 88 62 50 50 C 12 38 12 18 50 0 Z" fill="#d99a2b" />
                <path d="M 50 4 C 12 18 12 38 50 50 C 88 62 88 82 50 96" stroke="#faf6ee" strokeWidth="2.4" fill="none" strokeLinecap="round" />
              </g>
            </svg>
          </div>

          <div style={{ display: "flex", flexDirection: "column" }}>
            <div
              style={{
                fontSize: 140,
                fontFamily: "serif",
                fontWeight: 500,
                color: "#0b4266",
                lineHeight: 1,
                letterSpacing: "-0.04em",
              }}
            >
              shorelife
            </div>
            <div
              style={{
                fontSize: 32,
                fontFamily: "monospace",
                color: "#5e6b73",
                letterSpacing: "0.2em",
                textTransform: "uppercase",
                marginTop: 20,
              }}
            >
              California Water Quality
            </div>
          </div>
        </div>

        <div
          style={{
            position: "absolute",
            bottom: 60,
            fontSize: 24,
            fontFamily: "sans-serif",
            color: "#1a2730",
            background: "#d8efe4",
            padding: "10px 24px",
            borderRadius: 100,
            display: "flex",
            alignItems: "center",
            gap: 12,
            border: "1px solid #2b9e79",
          }}
        >
          Daily bacteria + surf health forecasts
        </div>
      </div>
    ),
    {
      ...size,
    }
  );
}
