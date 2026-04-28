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
    <div style={{ height: "100dvh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--sl-muted)" }}>
      Loading…
    </div>
  );

  if (notFound || !beach) return (
    <div style={{ height: "100dvh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
      <p style={{ fontSize: 16, color: "var(--sl-muted)" }}>Beach not found.</p>
      <a href="/" style={{ color: "var(--sl-navy)", fontWeight: 600 }}>← Go to Shorelife</a>
    </div>
  );

  const band = forecast?.risk_band ?? "Moderate";
  const tok = RISK_TOKEN[band] ?? RISK_TOKEN.Moderate;
  const copy = RISK_COPY[band] ?? RISK_COPY.Moderate;
  const env = forecast?.environmental_summary;

  const conditions = [
    { l: 'Surf',  v: mToFt(env?.wave_height_m), s: env?.dominant_period_s ? `@ ${Math.round(env.dominant_period_s)}s` : '—' },
    { l: 'Water', v: env?.water_temperature_c != null ? `${Math.round(env.water_temperature_c * 9/5 + 32)}°F` : '—', s: 'mild' },
    { l: 'Wind',  v: env?.wind_speed_mps != null ? `${Math.round(env.wind_speed_mps * 2.237)} mph` : '—', s: 'WSW' },
    { l: 'UV',    v: env?.uv_index != null ? String(Math.round(env.uv_index)) : '—', s: (env?.uv_index ?? 0) >= 7 ? 'high' : 'moderate' },
  ];

  return (
    <div style={{ padding: '48px 64px 64px' }}>
      <div style={{ padding: '48px 0 24px' }}>
        <div style={{ color: 'var(--sl-sun-deep)', margin: '0 0 10px', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--font-mono)' }}>Beach · share preview</div>
        <h1 style={{ fontSize: 64, margin: '12px 0 12px', color: 'var(--sl-navy-ink)', fontFamily: 'var(--font-heading)', fontWeight: 400, letterSpacing: '-0.02em' }}>
          {beach.name}
        </h1>
        <div style={{ display: 'flex', gap: 24, alignItems: 'baseline',
          fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em',
          color: 'var(--sl-muted)', textTransform: 'uppercase' }}>
          <span>{beach.county} County</span>
          <span>·</span>
          <span>{beach.region ?? 'CA'}</span>
          <span>·</span>
          <span>{beach.geometry?.latitude?.toFixed(3)}°N · {Math.abs(beach.geometry?.longitude || 0).toFixed(3)}°W</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 48, alignItems: 'start' }}>
        {/* LEFT — full beach detail */}
        <div>
          {/* Big risk hero card */}
          <div style={{
            background: tok.bg, border: `1px solid ${tok.c}`, borderRadius: 18,
            padding: '36px 40px', position: 'relative', overflow: 'hidden',
          }}>
            {/* Tide-line texture */}
            <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.18 }}
              viewBox="0 0 600 320" preserveAspectRatio="none">
              {[60, 90, 130, 180, 240].map((y, i) => (
                <path key={i} d={`M 0 ${y} C 150 ${y - 6}, 300 ${y + 8}, 450 ${y - 4} S 600 ${y}, 600 ${y}`}
                  stroke={tok.ink} strokeWidth="1" fill="none" opacity={1 - i*0.15}/>
              ))}
            </svg>
            <div style={{ position: 'relative' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <DropRow band={band} size={18}/>
                <div style={{ color: tok.ink, fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', fontWeight: 600 }}>{band.toUpperCase()} · TODAY</div>
              </div>
              <div style={{ fontSize: 120, lineHeight: 0.85, color: tok.ink, marginTop: 20, marginBottom: 16, fontFamily: 'var(--font-heading)', fontWeight: 400, letterSpacing: '-0.04em' }}>
                {copy.head}
              </div>
              <div style={{ fontSize: 17, color: tok.ink, opacity: 0.85, lineHeight: 1.5, maxWidth: 460, fontFamily: 'var(--font-mono)' }}>
                {copy.sub}
              </div>
              <div style={{ marginTop: 28, paddingTop: 20,
                borderTop: `1px dashed ${tok.c}`,
                display: 'flex', justifyContent: 'space-between' }}>
                <div>
                  <div style={{ color: tok.ink, opacity: 0.7, fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600 }}>Enterococcus</div>
                  <div style={{ fontSize: 18, color: tok.ink, marginTop: 4, fontFamily: 'var(--font-mono)' }}>{copy.cfu}</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ color: tok.ink, opacity: 0.7, fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600 }}>Exceed chance</div>
                  <div style={{ fontSize: 36, color: tok.ink, marginTop: 4, lineHeight: 1, fontFamily: 'var(--font-heading)' }}>
                    {forecast ? Math.round(forecast.p_exceed * 100) : '--'}<span style={{ fontSize: 18 }}>%</span>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ color: tok.ink, opacity: 0.7, fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600 }}>Sampled</div>
                  <div style={{ fontSize: 18, color: tok.ink, marginTop: 4, fontFamily: 'var(--font-mono)' }}>2d ago</div>
                </div>
              </div>
              <div style={{ marginTop: 16 }}><SeverityBar band={band} width="100%" height={6}/></div>
            </div>
          </div>

          {/* Conditions strip */}
          <div style={{ marginTop: 24 }}>
            <div style={{ color: 'var(--sl-sun-deep)', margin: '0 0 10px', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--font-mono)' }}>Conditions now</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 14 }}>
              {conditions.map(c => (
                <div key={c.l} style={{
                  background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
                  borderRadius: 12, padding: '18px 20px',
                }}>
                  <div style={{ color: 'var(--sl-muted)', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600 }}>{c.l}</div>
                  <div style={{ fontSize: 28, color: 'var(--sl-navy)', marginTop: 8, fontFamily: 'var(--font-heading)' }}>{c.v}</div>
                  <div style={{ fontSize: 11, color: 'var(--sl-muted)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>{c.s}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Drivers */}
          {forecast && forecast.top_drivers.length > 0 && (
            <div style={{ marginTop: 32 }}>
              <div style={{ color: 'var(--sl-sun-deep)', margin: '0 0 10px', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--font-mono)' }}>What's driving this</div>
              <div style={{ marginTop: 14, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
                borderRadius: 14, overflow: 'hidden' }}>
                {forecast.top_drivers.map((d, i) => (
                  <div key={i} style={{ padding: '16px 20px', display: 'flex', gap: 14,
                    borderTop: i ? '1px solid var(--sl-line-soft)' : 'none' }}>
                    <span style={{ width: 24, height: 24, borderRadius: 6, background: tok.bg,
                      color: tok.ink, display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, flexShrink: 0 }}>
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <p style={{ margin: 0, fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.55, fontFamily: 'var(--font-mono)' }}>{d}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT — phone preview + share metadata */}
        <div>
          <div style={{ color: 'var(--sl-sun-deep)', margin: '0 0 10px', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--font-mono)' }}>iOS share preview</div>
          <div style={{ marginTop: 14, padding: 24, background: 'var(--sl-bone)',
            border: '1px solid var(--sl-line)', borderRadius: 18 }}>
            <PhoneMock beach={beach} band={band} tok={tok} copy={copy} p={forecast ? Math.round(forecast.p_exceed * 100) : 0} conditions={conditions} />
          </div>

          <div style={{ marginTop: 24 }}>
            <div style={{ color: 'var(--sl-sun-deep)', margin: '0 0 10px', fontSize: '0.85rem', textTransform: 'uppercase', letterSpacing: '0.12em', fontFamily: 'var(--font-mono)' }}>Share link metadata</div>
            <div style={{ marginTop: 14, fontFamily: 'var(--font-mono)', fontSize: 12,
              color: 'var(--sl-ink)', background: 'var(--sl-bone)',
              border: '1px solid var(--sl-line)', borderRadius: 12, padding: 16, lineHeight: 1.7 }}>
              <div><span style={{ color: 'var(--sl-muted)' }}>url:</span> kylechoi101.github.io/surf-health/b/{beach.id}</div>
              <div><span style={{ color: 'var(--sl-muted)' }}>og:title:</span> {beach.name} · {copy.head}</div>
              <div><span style={{ color: 'var(--sl-muted)' }}>og:desc:</span> {copy.sub}</div>
              <div><span style={{ color: 'var(--sl-muted)' }}>og:image:</span> /og/{beach.id}-{band.toLowerCase().replace(' ', '-')}.png</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PhoneMock({ beach, band, tok, copy, p, conditions }: any) {
  return (
    <div style={{ width: 340, margin: '0 auto', borderRadius: 38,
      background: '#1a1a1a', padding: 8,
      boxShadow: '0 20px 60px rgba(11,66,102,0.25)' }}>
      <div style={{ borderRadius: 32, background: 'var(--sl-ecru)', overflow: 'hidden',
        position: 'relative', height: 600 }}>
        {/* Status bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 22px 8px',
          fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600, color: 'var(--sl-ink)' }}>
          <span>9:41</span>
          <span>● ●</span>
        </div>

        {/* Hero band */}
        <div style={{ background: tok.c, padding: '20px 22px 24px', position: 'relative', overflow: 'hidden' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600,
            letterSpacing: '0.18em', color: 'rgba(255,255,255,0.85)' }}>SHORELIFE</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'rgba(255,255,255,0.7)',
            letterSpacing: '0.12em', textTransform: 'uppercase', marginTop: 16 }}>
            Can I swim today?
          </div>
          <div style={{ fontFamily: 'var(--font-heading)', fontSize: 48, color: '#fff', lineHeight: 1, marginTop: 4, letterSpacing: '-0.02em' }}>
            {copy.head}
          </div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.92)', marginTop: 6, lineHeight: 1.5, fontFamily: 'var(--font-text)' }}>
            {copy.sub}
          </div>
          <div style={{ marginTop: 18, fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600,
            color: 'rgba(255,255,255,0.9)', letterSpacing: '0.06em' }}>
            {beach.name.toUpperCase()} · {beach.county.toUpperCase()}
          </div>
        </div>

        {/* Risk readout card */}
        <div style={{ padding: '14px 14px 0' }}>
          <div style={{ background: tok.bg, borderRadius: 14, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ color: tok.ink, fontSize: 9, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.1em' }}>Water quality</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: tok.ink, marginTop: 4, fontFamily: 'var(--font-text)' }}>{band}</div>
                <div style={{ fontSize: 11, color: tok.ink, opacity: 0.8, marginTop: 4, fontFamily: 'var(--font-text)' }}>Ent: {copy.cfu}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ fontSize: 28, color: tok.ink, lineHeight: 1, fontFamily: 'var(--font-heading)' }}>
                  {p}<span style={{ fontSize: 14 }}>%</span>
                </div>
                <div style={{ color: tok.ink, opacity: 0.7, fontSize: 9, marginTop: 2, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.1em' }}>EXCEED</div>
              </div>
            </div>
            <div style={{ marginTop: 12 }}><SeverityBar band={band} width="100%" height={5}/></div>
          </div>
        </div>

        {/* Conditions */}
        <div style={{ padding: '14px 14px 0' }}>
          <div style={{ color: 'var(--sl-muted)', fontSize: 9, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.1em' }}>Conditions</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
            {conditions.map((c: any) => (
              <div key={c.l} style={{ background: 'var(--sl-bone)', borderRadius: 10,
                border: '1px solid var(--sl-line)', padding: '10px 12px' }}>
                <div style={{ color: 'var(--sl-muted)', fontSize: 8, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.1em' }}>{c.l}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--sl-navy)', marginTop: 2, fontFamily: 'var(--font-text)' }}>{c.v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div style={{ padding: 14, marginTop: 8 }}>
          <div style={{ background: 'var(--sl-navy)', borderRadius: 14, padding: '14px 16px', textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--sl-bone)', fontFamily: 'var(--font-text)' }}>Get the Shorelife app</div>
            <div style={{ fontSize: 10, color: 'rgba(250,246,238,0.7)', marginTop: 2, fontFamily: 'var(--font-text)' }}>300+ California beaches</div>
          </div>
        </div>
      </div>
    </div>
  );
}
