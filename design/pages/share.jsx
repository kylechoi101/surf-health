// Share-link page — /b — phone-frame mock embedded in poster context
// Reused as the social-preview surface

function SharePage() {
  const beach = window.BEACHES.find(b => b.id === 'malibu');
  const band = beach.risk;
  const tok = RISK_TOKEN[band];
  const copy = RISK_COPY[band];

  return (
    <div style={{ padding: '48px 64px 64px' }}>
      <SiteHeader active="Beaches"/>

      <div style={{ padding: '48px 0 24px' }}>
        <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Beach · share preview</div>
        <h1 className="sl-display" style={{ fontSize: 64, margin: '12px 0 12px',
          color: 'var(--sl-navy-ink)' }}>
          {beach.name}
        </h1>
        <div style={{ display: 'flex', gap: 24, alignItems: 'baseline',
          fontFamily: 'var(--sl-mono)', fontSize: 11, letterSpacing: '0.14em',
          color: 'var(--sl-muted)', textTransform: 'uppercase' }}>
          <span>{beach.county} County</span>
          <span>·</span>
          <span>{beach.region}</span>
          <span>·</span>
          <span>{beach.lat.toFixed(3)}°N · {Math.abs(beach.lon).toFixed(3)}°W</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 48,
        alignItems: 'start' }}>

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
                <div className="sl-label" style={{ color: tok.ink }}>{band.toUpperCase()} · TODAY</div>
              </div>
              <div className="sl-display" style={{ fontSize: 120, lineHeight: 0.85,
                color: tok.ink, marginTop: 20, marginBottom: 16 }}>
                {copy.head}
              </div>
              <div style={{ fontSize: 17, color: tok.ink, opacity: 0.85, lineHeight: 1.5,
                maxWidth: 460 }}>
                {copy.sub}
              </div>
              <div style={{ marginTop: 28, paddingTop: 20,
                borderTop: `1px dashed ${tok.c}`,
                display: 'flex', justifyContent: 'space-between' }}>
                <div>
                  <div className="sl-label" style={{ color: tok.ink, opacity: 0.7 }}>Enterococcus</div>
                  <div className="sl-mono" style={{ fontSize: 18, color: tok.ink, marginTop: 4 }}>{copy.cfu}</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div className="sl-label" style={{ color: tok.ink, opacity: 0.7 }}>Exceed chance</div>
                  <div className="sl-display" style={{ fontSize: 36, color: tok.ink, marginTop: 4, lineHeight: 1 }}>
                    {Math.round(beach.p * 100)}<span style={{ fontSize: 18 }}>%</span>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="sl-label" style={{ color: tok.ink, opacity: 0.7 }}>Sampled</div>
                  <div className="sl-mono" style={{ fontSize: 18, color: tok.ink, marginTop: 4 }}>2d ago</div>
                </div>
              </div>
              <div style={{ marginTop: 16 }}><SeverityBar band={band} width="100%" height={6}/></div>
            </div>
          </div>

          {/* Conditions strip */}
          <div style={{ marginTop: 24 }}>
            <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Conditions now</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginTop: 14 }}>
              {[
                { l: 'Surf',  v: `${beach.waveFt}ft`, s: `@ ${beach.period}s` },
                { l: 'Water', v: `${beach.temp}°F`,    s: 'mild' },
                { l: 'Wind',  v: `${beach.wind} mph`,  s: 'WSW' },
                { l: 'UV',    v: beach.uv,             s: beach.uv >= 7 ? 'high' : 'moderate' },
              ].map(c => (
                <div key={c.l} style={{
                  background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
                  borderRadius: 12, padding: '18px 20px',
                }}>
                  <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>{c.l}</div>
                  <div className="sl-display" style={{ fontSize: 28, color: 'var(--sl-navy)', marginTop: 8 }}>{c.v}</div>
                  <div className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)', marginTop: 4 }}>{c.s}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Drivers */}
          <div style={{ marginTop: 32 }}>
            <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>What's driving this</div>
            <div style={{ marginTop: 14, background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
              borderRadius: 14, overflow: 'hidden' }}>
              {[
                'Stable offshore swell, 12s period reduces nearshore mixing',
                'No precipitation in the last 72 hours — runoff risk minimal',
                'Last culture sample 2 days ago: < 35 CFU/100mL',
                'Tide rising through midday; check again at low tide',
              ].map((d, i) => (
                <div key={i} style={{ padding: '16px 20px', display: 'flex', gap: 14,
                  borderTop: i ? '1px solid var(--sl-line-soft)' : 'none' }}>
                  <span style={{ width: 24, height: 24, borderRadius: 6, background: tok.bg,
                    color: tok.ink, display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontFamily: 'var(--sl-mono)', fontSize: 11, fontWeight: 600, flexShrink: 0 }}>
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <p style={{ margin: 0, fontSize: 14, color: 'var(--sl-ink)', lineHeight: 1.55 }}>{d}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT — phone preview + share metadata */}
        <div>
          <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>iOS share preview</div>
          <div style={{ marginTop: 14, padding: 24, background: 'var(--sl-bone)',
            border: '1px solid var(--sl-line)', borderRadius: 18 }}>
            <PhoneMock beach={beach}/>
          </div>

          <div style={{ marginTop: 24 }}>
            <div className="sl-eyebrow" style={{ color: 'var(--sl-sun-deep)' }}>Share link metadata</div>
            <div style={{ marginTop: 14, fontFamily: 'var(--sl-mono)', fontSize: 12,
              color: 'var(--sl-ink)', background: 'var(--sl-bone)',
              border: '1px solid var(--sl-line)', borderRadius: 12, padding: 16, lineHeight: 1.7 }}>
              <div><span style={{ color: 'var(--sl-muted)' }}>url:</span> shorelife.app/b?id=malibu</div>
              <div><span style={{ color: 'var(--sl-muted)' }}>og:title:</span> Malibu Surfrider · {copy.head}</div>
              <div><span style={{ color: 'var(--sl-muted)' }}>og:desc:</span> {copy.sub}</div>
              <div><span style={{ color: 'var(--sl-muted)' }}>og:image:</span> /og/malibu-{band.toLowerCase().replace(' ', '-')}.png</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function PhoneMock({ beach }) {
  const band = beach.risk;
  const tok = RISK_TOKEN[band];
  const copy = RISK_COPY[band];
  return (
    <div style={{ width: 340, margin: '0 auto', borderRadius: 38,
      background: '#1a1a1a', padding: 8,
      boxShadow: '0 20px 60px rgba(11,66,102,0.25)' }}>
      <div style={{ borderRadius: 32, background: 'var(--sl-ecru)', overflow: 'hidden',
        position: 'relative', height: 600 }}>
        {/* Status bar */}
        <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 22px 8px',
          fontFamily: 'var(--sl-mono)', fontSize: 11, fontWeight: 600, color: 'var(--sl-ink)' }}>
          <span>9:41</span>
          <span>● ●</span>
        </div>

        {/* Hero band */}
        <div style={{ background: tok.c, padding: '20px 22px 24px', position: 'relative', overflow: 'hidden' }}>
          <div style={{ fontFamily: 'var(--sl-mono)', fontSize: 9, fontWeight: 600,
            letterSpacing: '0.18em', color: 'rgba(255,255,255,0.85)' }}>SHORELIFE</div>
          <div style={{ fontFamily: 'var(--sl-mono)', fontSize: 9, color: 'rgba(255,255,255,0.7)',
            letterSpacing: '0.12em', textTransform: 'uppercase', marginTop: 16 }}>
            Can I swim today?
          </div>
          <div style={{ fontFamily: 'var(--sl-display)', fontSize: 48, color: '#fff', lineHeight: 1, marginTop: 4 }}>
            {copy.head}
          </div>
          <div style={{ fontSize: 12, color: 'rgba(255,255,255,0.92)', marginTop: 6, lineHeight: 1.5 }}>
            {copy.sub}
          </div>
          <div style={{ marginTop: 18, fontFamily: 'var(--sl-mono)', fontSize: 10, fontWeight: 600,
            color: 'rgba(255,255,255,0.9)', letterSpacing: '0.06em' }}>
            {beach.name.toUpperCase()} · {beach.county.toUpperCase()}
          </div>
        </div>

        {/* Risk readout card */}
        <div style={{ padding: '14px 14px 0' }}>
          <div style={{ background: tok.bg, borderRadius: 14, padding: 16 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div className="sl-label" style={{ color: tok.ink, fontSize: 9 }}>Water quality</div>
                <div style={{ fontSize: 18, fontWeight: 600, color: tok.ink, marginTop: 4 }}>{band}</div>
                <div style={{ fontSize: 11, color: tok.ink, opacity: 0.8, marginTop: 4 }}>Ent: {copy.cfu}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="sl-display" style={{ fontSize: 28, color: tok.ink, lineHeight: 1 }}>
                  {Math.round(beach.p * 100)}<span style={{ fontSize: 14 }}>%</span>
                </div>
                <div className="sl-label" style={{ color: tok.ink, opacity: 0.7, fontSize: 9, marginTop: 2 }}>EXCEED</div>
              </div>
            </div>
            <div style={{ marginTop: 12 }}><SeverityBar band={band} width="100%" height={5}/></div>
          </div>
        </div>

        {/* Conditions */}
        <div style={{ padding: '14px 14px 0' }}>
          <div className="sl-label" style={{ color: 'var(--sl-muted)', fontSize: 9 }}>Conditions</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
            {[
              { l: 'Surf',  v: `${beach.waveFt}ft` },
              { l: 'Water', v: `${beach.temp}°F` },
              { l: 'Wind',  v: `${beach.wind} mph` },
              { l: 'UV',    v: beach.uv },
            ].map(c => (
              <div key={c.l} style={{ background: 'var(--sl-bone)', borderRadius: 10,
                border: '1px solid var(--sl-line)', padding: '10px 12px' }}>
                <div className="sl-label" style={{ color: 'var(--sl-muted)', fontSize: 8 }}>{c.l}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--sl-navy)', marginTop: 2 }}>{c.v}</div>
              </div>
            ))}
          </div>
        </div>

        {/* CTA */}
        <div style={{ padding: 14, marginTop: 8 }}>
          <div style={{ background: 'var(--sl-navy)', borderRadius: 14, padding: '14px 16px', textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--sl-bone)' }}>Get the Shorelife app</div>
            <div style={{ fontSize: 10, color: 'rgba(250,246,238,0.7)', marginTop: 2 }}>300+ California beaches</div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SharePage });
