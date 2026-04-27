"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getBeaches, getForecast, preferredForecastDate, type BeachSummary, type ForecastRecord } from "@/lib/api";
import { RISK_COPY, RISK_TOKEN, DropRow, SeverityBar } from "@/components/Risk";

function mToFt(m: number | null | undefined) {
  if (m == null) return "—";
  return (m * 3.281).toFixed(1) + " ft";
}

export default function BeachSharePage() {
  const { id } = useParams();
  const [beach, setBeach] = useState<BeachSummary | null>(null);
  const [forecast, setForecast] = useState<ForecastRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!id) { setNotFound(true); setLoading(false); return; }
    const bid = Array.isArray(id) ? id[0] : id;

    const date = preferredForecastDate();
    Promise.all([
      getBeaches().then((bs) => bs.find((b) => b.id === bid) ?? null),
      getForecast(bid, date).catch(() => null),
    ]).then(([b, f]) => {
      if (!b) setNotFound(true);
      setBeach(b);
      setForecast(f);
    }).finally(() => setLoading(false));
  }, [id]);

  if (loading) return (
    <div style={{ height: "100dvh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--sl-muted)", background: "var(--sl-ecru)" }}>
      Loading predictive model...
    </div>
  );

  if (notFound || !beach) return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12, background: "var(--sl-ecru)" }}>
      <p style={{ fontSize: 16, color: "var(--sl-muted)", fontFamily: "var(--font-mono)" }}>[404] Station not found.</p>
      <a href="/" style={{ color: "var(--sl-navy)", fontWeight: 600, fontFamily: "var(--font-mono)", fontSize: 12, textTransform: "uppercase" }}>← Return to index</a>
    </div>
  );

  const band = forecast?.risk_band ?? "Moderate";
  const tok = RISK_TOKEN[band] ?? RISK_TOKEN.Moderate;
  const copy = RISK_COPY[band] ?? RISK_COPY.Moderate;
  const env = forecast?.environmental_summary;

  const conditions = [
    { l: 'Surf',  v: mToFt(env?.wave_height_m), s: env?.dominant_period_s ? `${Math.round(env.dominant_period_s)}s` : '—' },
    { l: 'Water', v: env?.water_temperature_c != null ? `${Math.round(env.water_temperature_c * 9/5 + 32)}°F` : '—', s: 'mild' },
    { l: 'Wind',  v: env?.wind_speed_mps != null ? `${Math.round(env.wind_speed_mps * 2.237)} mph` : '—', s: 'WSW' },
    { l: 'UV',    v: env?.uv_index != null ? String(Math.round(env.uv_index)) : '—', s: (env?.uv_index ?? 0) >= 7 ? 'high' : 'moderate' },
  ];

  return (
    <main className="page-shell animate-fade" style={{ paddingTop: 64 }}>
      <div style={{ display: 'flex', gap: 64, alignItems: 'flex-start' }}>
        {/* Left Column — 28% width Technical Brief */}
        <div style={{ flex: '0 0 340px' }}>
          <div className="eyebrow">Technical BRIEF · Share surface</div>
          <h1 style={{ fontSize: 48, lineHeight: 1.0, marginBottom: 12 }}>
            {beach.name}
          </h1>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.1em', color: 'var(--sl-muted)', textTransform: 'uppercase', marginBottom: 40 }}>
            {beach.county} County · {beach.geometry?.latitude.toFixed(3)}°N {Math.abs(beach.geometry?.longitude || 0).toFixed(3)}°W
          </div>

          <div className="panel" style={{ padding: 24, background: tok.bg, borderColor: tok.c }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: tok.ink }}>{band.toUpperCase()}</div>
              <DropRow band={band} size={14}/>
            </div>
            <div style={{ fontFamily: 'var(--font-heading)', fontSize: 48, color: tok.ink, lineHeight: 0.9, marginBottom: 16 }}>{copy.head}</div>
            <div style={{ fontSize: 14, color: tok.ink, opacity: 0.85, lineHeight: 1.5, marginBottom: 24 }}>{copy.sub}</div>
            <SeverityBar band={band} width="100%" height={6}/>
            <div style={{ marginTop: 24, paddingTop: 16, borderTop: `1px dashed ${tok.c}`, display: 'flex', justifyContent: 'space-between', fontSize: 10, fontFamily: 'var(--font-mono)', color: tok.ink, opacity: 0.7 }}>
              <div>ENT: {copy.cfu}</div>
              <div>P_EXCEED: {forecast ? Math.round(forecast.p_exceed * 100) : '--'}%</div>
            </div>
          </div>

          <div style={{ marginTop: 40 }}>
            <div className="eyebrow">Forecast Identity</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--sl-muted)', lineHeight: 1.6 }}>
              URL: shorelife.app/b/{beach.id}<br/>
              MODEL: {forecast?.model_version || 'v1.4'}<br/>
              GEN: {forecast ? new Date(forecast.forecast_generated_at).toLocaleTimeString() : '--'}
            </div>
          </div>
        </div>

        {/* Right Column — iOS Mock & Conditions */}
        <div style={{ flex: 1 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: 48 }}>
            <div className="panel" style={{ background: 'var(--sl-ecru-deep)', padding: 12, borderRadius: 44, border: 'none' }}>
              <PhoneMock beach={beach} band={band} tok={tok} copy={copy} p={forecast ? Math.round(forecast.p_exceed * 100) : 0} conditions={conditions} />
            </div>

            <div>
              <div className="eyebrow">Environmental Context</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 32 }}>
                {conditions.map(c => (
                  <div key={c.l} className="card" style={{ padding: 20 }}>
                    <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)', textTransform: 'uppercase', marginBottom: 8 }}>{c.l}</div>
                    <div style={{ fontSize: 24, fontFamily: 'var(--font-heading)' }}>{c.v}</div>
                    <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--sl-muted)', marginTop: 4 }}>{c.s}</div>
                  </div>
                ))}
              </div>

              {forecast && forecast.top_drivers.length > 0 && (
                <>
                  <div className="eyebrow">Model Attribution</div>
                  <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
                    {forecast.top_drivers.map((d, i) => (
                      <div key={i} style={{ padding: '16px 20px', borderBottom: i < forecast.top_drivers.length - 1 ? '1px solid var(--border-soft)' : 'none', display: 'flex', gap: 16, alignItems: 'center' }}>
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: tok.c, fontWeight: 700 }}>0{i+1}</span>
                        <span style={{ fontSize: 14, color: 'var(--sl-ink)' }}>{d}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

function PhoneMock({ beach, band, tok, copy, p, conditions }: any) {
  return (
    <div style={{ width: '100%', borderRadius: 36, background: '#1a2730', padding: 8, boxShadow: '0 30px 80px rgba(11,66,102,0.2)' }}>
      <div style={{ borderRadius: 30, background: 'var(--sl-ecru)', overflow: 'hidden', position: 'relative', height: 600 }}>
        {/* Status bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 22px 8px', fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: 'var(--sl-ink)' }}>
          <span>9:41</span>
          <span>● ●</span>
        </div>

        {/* Hero band */}
        <div style={{ background: tok.c, padding: '24px 22px 32px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 700, letterSpacing: '0.2em', color: 'rgba(255,255,255,0.8)' }}>SHORELIFE</div>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 52, color: '#fff', lineHeight: 1, marginTop: 24, letterSpacing: '-0.02em' }}>{copy.head}</div>
          <div style={{ fontSize: 13, color: 'rgba(255,255,255,0.9)', marginTop: 8, lineHeight: 1.5 }}>{copy.sub}</div>
          <div style={{ marginTop: 24, fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, color: 'rgba(255,255,255,0.9)', letterSpacing: '0.05em' }}>{beach.name.toUpperCase()}</div>
        </div>

        {/* Technical Data Card */}
        <div style={{ padding: 16 }}>
          <div style={{ background: 'var(--sl-bone)', borderRadius: 16, padding: 20, border: '1px solid var(--sl-line-soft)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ color: 'var(--sl-muted)', fontSize: 9, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 700 }}>Risk Signal</div>
                <div style={{ fontSize: 20, fontWeight: 500, color: 'var(--sl-navy)', marginTop: 4 }}>{band}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 32, color: tok.ink, lineHeight: 1, fontFamily: 'var(--font-heading)' }}>{p}%</div>
                <div style={{ color: 'var(--sl-muted)', fontSize: 9, marginTop: 4, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 700 }}>EXCEEDANCE</div>
              </div>
            </div>
            <div style={{ marginTop: 16 }}><SeverityBar band={band} width="100%" height={5}/></div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 12 }}>
            {conditions.slice(0, 4).map((c: any) => (
              <div key={c.l} style={{ background: 'var(--sl-bone)', borderRadius: 12, border: '1px solid var(--sl-line-soft)', padding: 12 }}>
                <div style={{ color: 'var(--sl-muted)', fontSize: 8, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 700 }}>{c.l}</div>
                <div style={{ fontSize: 16, fontWeight: 500, color: 'var(--sl-navy)', marginTop: 2 }}>{c.v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: 20, background: 'linear-gradient(to top, var(--sl-ecru) 80%, transparent)' }}>
          <div style={{ background: 'var(--sl-navy)', borderRadius: 14, padding: '14px', textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--sl-bone)' }}>Get the Shorelife app</div>
          </div>
        </div>
      </div>
    </div>
  );
}
