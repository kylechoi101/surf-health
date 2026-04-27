"use client";
import { useEffect, useState } from "react";
import { getBeaches, getForecast, preferredForecastDate, type BeachSummary, type ForecastRecord } from "@/lib/api";

const RISK_COLORS: Record<string, { bg: string; ink: string; fill: string }> = {
  Low:         { bg: "#dcfce7", ink: "#175d43", fill: "#10b981" },
  Moderate:    { bg: "#fef3c7", ink: "#6d4a05", fill: "#f59e0b" },
  High:        { bg: "#ffedd5", ink: "#7a2d15", fill: "#fb923c" },
  "Very High": { bg: "#fee2e2", ink: "#561611", fill: "#f87171" },
};

const RISK_HEAD: Record<string, string> = {
  Low: "Clean.", Moderate: "Watch.", High: "Elevated.", "Very High": "Unsafe.",
};

const RISK_SUB: Record<string, string> = {
  Low: "Swim, surf, dunk under.",
  Moderate: "Okay — just don't swallow.",
  High: "Stay out if you're sensitive.",
  "Very High": "County advisory — stay out.",
};

function mToFt(m: number | null | undefined) {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + " ft";
}

export default function BeachSharePage() {
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("id");
    if (!id) { setNotFound(true); setLoading(false); return; }

    const date = preferredForecastDate();
    Promise.all([
      getBeaches().then((bs) => bs.find((b) => b.id === id) ?? null),
      getForecast(id, date).catch(() => null),
    ]).then(([b, f]) => {
      if (!b) setNotFound(true);
      setBeach(b);
      setForecast(f);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div style={{ height: "100dvh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "system-ui, sans-serif", color: "#64748b" }}>
      Loading…
    </div>
  );

  if (notFound || !beach) return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", fontFamily: "system-ui, sans-serif", gap: 12 }}>
      <p style={{ fontSize: 16, color: "#64748b" }}>Beach not found.</p>
      <a href="/" style={{ color: "#0b4266", fontWeight: 600 }}>← Go to Shorelife</a>
    </div>
  );

  const band = forecast?.risk_band ?? "Moderate";
  const c = RISK_COLORS[band] ?? RISK_COLORS.Moderate;
  const env = forecast?.environmental_summary;

  return (
    <div style={{ minHeight: "100dvh", fontFamily: "system-ui, -apple-system, sans-serif", backgroundColor: "#f2f4f7" }}>
      {/* Hero */}
      <div style={{ backgroundColor: c.fill, padding: "32px 24px 28px", position: "relative", overflow: "hidden" }}>
        {/* Decorative circles */}
        <div style={{ position: "absolute", top: -20, right: -20, width: 120, height: 120, borderRadius: 60, backgroundColor: "rgba(255,255,255,0.12)" }} />
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 24, backgroundColor: "rgba(255,255,255,0.08)", borderRadius: "60px 60px 0 0" }} />

        <a href="/" style={{ display: "inline-block", color: "rgba(255,255,255,0.8)", fontSize: 12, fontWeight: 800, letterSpacing: 3, textDecoration: "none", marginBottom: 24 }}>
          SHORELIFE
        </a>
        <p style={{ color: "rgba(255,255,255,0.8)", fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1.2, margin: 0 }}>
          Can I swim today?
        </p>
        <h1 style={{ color: "#fff", fontSize: 52, fontWeight: 700, margin: "4px 0 8px", lineHeight: 1 }}>
          {RISK_HEAD[band]}
        </h1>
        <p style={{ color: "rgba(255,255,255,0.9)", fontSize: 15, margin: "0 0 20px", lineHeight: 1.5 }}>
          {RISK_SUB[band]}
        </p>
        <p style={{ color: "rgba(255,255,255,0.75)", fontSize: 13, fontWeight: 600, margin: 0 }}>
          {beach.name} · {beach.county} County
        </p>
      </div>

      {/* Risk card */}
      <div style={{ padding: "16px 16px 0" }}>
        <div style={{ backgroundColor: c.bg, borderRadius: 18, padding: 18 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <p style={{ color: c.ink, fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: 1, margin: "0 0 4px" }}>Water quality</p>
              <p style={{ color: c.ink, fontSize: 22, fontWeight: 700, margin: "0 0 4px" }}>{band}</p>
              <p style={{ color: c.ink, fontSize: 13, margin: 0, opacity: 0.85 }}>Enterococcus: {
                band === "Low" ? "< 35 CFU/100mL" :
                band === "Moderate" ? "35–104 CFU/100mL" :
                band === "High" ? "104–320 CFU/100mL" : "> 320 CFU/100mL"
              }</p>
            </div>
            {forecast && (
              <div style={{ textAlign: "right" }}>
                <p style={{ color: c.ink, fontSize: 32, fontWeight: 700, margin: 0, lineHeight: 1 }}>{Math.round(forecast.p_exceed * 100)}<span style={{ fontSize: 16 }}>%</span></p>
                <p style={{ color: c.ink, fontSize: 10, fontWeight: 600, margin: "4px 0 0", opacity: 0.75 }}>exceed chance</p>
              </div>
            )}
          </div>
          {/* Severity bar */}
          <div style={{ display: "flex", gap: 4, marginTop: 16 }}>
            {(["Low", "Moderate", "High", "Very High"] as const).map((b, i) => {
              const idx = ["Low", "Moderate", "High", "Very High"].indexOf(band);
              const on = i <= idx;
              return (
                <div key={b} style={{ flex: 1, height: 7, borderRadius: 4, backgroundColor: on ? RISK_COLORS[b].fill : "#e2e8f0", opacity: on ? (i === idx ? 1 : 0.45) : 1 }} />
              );
            })}
          </div>
        </div>
      </div>

      {/* Conditions */}
      {env && (
        <div style={{ padding: "16px 16px 0" }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 1, margin: "0 0 10px" }}>Conditions</p>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {[
              { icon: "🌊", label: "Surf", val: mToFt(env.wave_height_m) },
              { icon: "🌡", label: "Water temp", val: env.water_temperature_c != null ? `${Math.round(env.water_temperature_c * 9/5 + 32)}°F` : "—" },
              { icon: "💨", label: "Wind", val: env.wind_speed_mps != null ? `${Math.round(env.wind_speed_mps * 2.237)} mph` : "—" },
              { icon: "☀️", label: "UV", val: env.uv_index != null ? String(Math.round(env.uv_index)) : "—" },
            ].map(({ icon, label, val }) => (
              <div key={label} style={{ backgroundColor: "#fff", borderRadius: 14, padding: 14, border: "1px solid #e5e7eb" }}>
                <p style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5, margin: "0 0 6px" }}>{icon} {label}</p>
                <p style={{ fontSize: 20, fontWeight: 700, color: "#0f172a", margin: 0 }}>{val}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Drivers */}
      {forecast && forecast.top_drivers.length > 0 && (
        <div style={{ padding: "16px 16px 0" }}>
          <p style={{ fontSize: 10, fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: 1, margin: "0 0 10px" }}>What&apos;s driving this</p>
          <div style={{ backgroundColor: "#fff", borderRadius: 18, border: "1px solid #e5e7eb", overflow: "hidden" }}>
            {forecast.top_drivers.map((d, i) => (
              <div key={i} style={{ padding: "12px 16px", borderTop: i ? "1px solid #f1f5f9" : "none", display: "flex", gap: 10, alignItems: "flex-start" }}>
                <div style={{ width: 22, height: 22, borderRadius: 6, backgroundColor: band === "Low" ? "#dcfce7" : "#fee2e2", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: band === "Low" ? "#15803d" : "#b91c1c", flexShrink: 0 }}>
                  {band === "Low" ? "✓" : "!"}
                </div>
                <p style={{ margin: 0, fontSize: 13, fontWeight: 500, color: "#0f172a", lineHeight: 1.5 }}>{d}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* App CTA */}
      <div style={{ padding: 16, marginTop: 8 }}>
        <div style={{ backgroundColor: "#0b4266", borderRadius: 18, padding: 20, textAlign: "center" }}>
          <p style={{ color: "#fff", fontSize: 16, fontWeight: 700, margin: "0 0 6px" }}>Get the Shorelife app</p>
          <p style={{ color: "rgba(255,255,255,0.75)", fontSize: 13, margin: "0 0 16px" }}>Daily forecasts for 300+ California beaches.</p>
          <a href="https://apps.apple.com/app/shorelife/id0000000000" style={{ display: "inline-block", backgroundColor: "#fff", color: "#0b4266", fontSize: 14, fontWeight: 700, padding: "12px 28px", borderRadius: 12, textDecoration: "none" }}>
            Download on iOS
          </a>
        </div>
      </div>

      <p style={{ textAlign: "center", fontSize: 11, color: "#94a3b8", padding: "0 16px 24px", lineHeight: 1.6 }}>
        This is a model forecast, not an official lab result. Treat it as advisory. · <a href="/methodology/" style={{ color: "#64748b" }}>Methodology</a>
      </p>
    </div>
  );
}
