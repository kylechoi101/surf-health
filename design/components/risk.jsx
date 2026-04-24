// Risk severity visual system
// Same slot, four outputs. "Beyond color" = layered drop glyphs + compression + type ladder.

const RISK_ORDER = ['Low', 'Moderate', 'High', 'Very High'];
const RISK_COPY = {
  'Low':       { head: 'Clean.',     sub: 'Swim, surf, dunk under.',       cfu: '< 35 CFU',  drops: 1 },
  'Moderate':  { head: 'Watch.',     sub: 'Okay — just don’t swallow.',    cfu: '35–104',    drops: 2 },
  'High':      { head: 'Elevated.',  sub: 'Stay out if you’re sensitive.', cfu: '104–320',   drops: 3 },
  'Very High': { head: 'Unsafe.',    sub: 'County advisory — stay out.',   cfu: '> 320',     drops: 3 },
};
const RISK_TOKEN = {
  'Low':       { c: 'var(--sl-risk-low)',  bg: 'var(--sl-risk-low-bg)',  ink: '#175d43' },
  'Moderate':  { c: 'var(--sl-risk-mod)',  bg: 'var(--sl-risk-mod-bg)',  ink: '#6d4a05' },
  'High':      { c: 'var(--sl-risk-high)', bg: 'var(--sl-risk-high-bg)', ink: '#7a2d15' },
  'Very High': { c: 'var(--sl-risk-vh)',   bg: 'var(--sl-risk-vh-bg)',   ink: '#561611' },
};

// ─── Drop glyph (1–3 drops, filled to severity) ────────────────────────────
function DropRow({ band, size = 14 }) {
  const d = RISK_COPY[band].drops;
  const color = RISK_TOKEN[band].c;
  // Very High: all three filled + dashed ring on last = warning
  const vh = band === 'Very High';
  return (
    <div style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
      {[0,1,2].map(i => {
        const filled = i < d || vh;
        return (
          <svg key={i} width={size} height={size*1.2} viewBox="0 0 12 14">
            <path d="M6 1 C6 1 1.5 6 1.5 9 A4.5 4.5 0 0 0 10.5 9 C10.5 6 6 1 6 1 Z"
              fill={filled ? color : 'none'}
              stroke={color} strokeWidth="1.1" opacity={filled ? 1 : 0.3}/>
            {vh && i === 2 && <path d="M6 5 V8 M6 10 V10.5" stroke="#fff" strokeWidth="1.2" strokeLinecap="round"/>}
          </svg>
        );
      })}
    </div>
  );
}

// ─── Severity bar — 4 slots, fills left-to-right ───────────────────────────
function SeverityBar({ band, width = 140 }) {
  const idx = RISK_ORDER.indexOf(band);
  return (
    <div style={{ display: 'flex', gap: 3, width }}>
      {RISK_ORDER.map((b, i) => {
        const on = i <= idx;
        const { c } = RISK_TOKEN[b];
        return <div key={b} style={{ flex: 1, height: 6, borderRadius: 2,
          background: on ? c : 'var(--sl-sand)',
          opacity: on ? (i === idx ? 1 : 0.55) : 1 }}/>;
      })}
    </div>
  );
}

// ─── A single risk card — same slot, different band ────────────────────────
function RiskCard({ band }) {
  const meta = RISK_COPY[band];
  const tok = RISK_TOKEN[band];
  const idx = RISK_ORDER.indexOf(band);
  // Compression: at high bands the visual gets denser, more bands visible
  return (
    <div className="sl" style={{ width: 280, padding: 22, background: 'var(--sl-bone)',
      border: '1px solid var(--sl-line)', borderRadius: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div className="sl-eyebrow">Water quality · today</div>
          <div className="sl-display" style={{ fontSize: 42, marginTop: 8, color: tok.ink }}>
            {meta.head}
          </div>
        </div>
        <DropRow band={band}/>
      </div>

      <div style={{ fontSize: 13, color: 'var(--sl-muted)', lineHeight: 1.4 }}>{meta.sub}</div>

      <SeverityBar band={band}/>

      <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: 6,
        borderTop: '1px dashed var(--sl-line)', marginTop: 4 }}>
        <div>
          <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>Enterococcus</div>
          <div className="sl-mono" style={{ fontSize: 15, color: 'var(--sl-ink)', marginTop: 2 }}>{meta.cfu}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>Band {idx+1}/4</div>
          <div className="sl-mono" style={{ fontSize: 15, color: tok.ink, marginTop: 2 }}>
            {band.toUpperCase()}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Hero treatment — the huge "answer" as it changes per band ─────────────
function RiskHero({ band }) {
  const meta = RISK_COPY[band];
  const tok = RISK_TOKEN[band];
  const vh = band === 'Very High';
  return (
    <div className="sl" style={{ width: 340, height: 220, borderRadius: 16,
      background: tok.bg, color: tok.ink, padding: 22, position: 'relative', overflow: 'hidden',
      border: `1px solid ${tok.c}`, borderStyle: vh ? 'dashed' : 'solid' }}>
      {/* Tide-line texture — denser as risk grows */}
      <svg viewBox="0 0 340 220" preserveAspectRatio="none"
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.22 }}>
        {[...Array(RISK_ORDER.indexOf(band) + 2)].map((_, i) => (
          <path key={i} d={`M0 ${60 + i*14} C 85 ${54 + i*14}, 170 ${66 + i*14}, 255 ${60 + i*14} S 340 ${58 + i*14}, 340 ${60 + i*14}`}
            stroke={tok.c} strokeWidth="1.2" fill="none"/>
        ))}
      </svg>
      <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <DropRow band={band} size={16}/>
          <div className="sl-label">{band}</div>
        </div>
        <div className="sl-display" style={{
          fontSize: band === 'Very High' ? 68 : band === 'High' ? 62 : band === 'Moderate' ? 56 : 52,
          marginTop: 'auto', fontWeight: 500, lineHeight: 0.95,
        }}>{meta.head}</div>
        <div style={{ fontSize: 13, marginTop: 8, maxWidth: 240 }}>{meta.sub}</div>
      </div>
    </div>
  );
}

// ─── List-item treatment — how a nearby beach shows severity in a list ─────
function RiskListRow({ band, name, dist }) {
  const tok = RISK_TOKEN[band];
  return (
    <div className="sl" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px',
      background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 12, width: 340 }}>
      <DropRow band={band}/>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 500 }}>{name}</div>
        <div className="sl-mono" style={{ fontSize: 11, color: 'var(--sl-muted)', marginTop: 1 }}>
          {dist} mi · {band}
        </div>
      </div>
      <SeverityBar band={band} width={70}/>
    </div>
  );
}

// ─── The full system poster — all four bands laid out ──────────────────────
function RiskSystemPoster() {
  return (
    <div className="sl" style={{ padding: 28, background: 'var(--sl-ecru)', width: 1240 }}>
      <div style={{ marginBottom: 20 }}>
        <div className="sl-eyebrow">03 · Risk vocabulary</div>
        <div className="sl-display" style={{ fontSize: 28, marginTop: 6, color: 'var(--sl-navy)' }}>
          How severity reads, beyond color.
        </div>
        <div style={{ fontSize: 13, color: 'var(--sl-muted)', marginTop: 6, maxWidth: 560, lineHeight: 1.5 }}>
          Color does most of the work, but color alone fails for colorblind users and dark-mode maps.
          So each band also changes: <b>drop glyph count</b>, <b>severity ladder</b>, <b>type scale</b>,
          <b> tide-line density</b>, and <b>copy urgency</b>.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 28 }}>
        {RISK_ORDER.map(b => <div key={b} style={{ display: 'flex', justifyContent: 'center' }}><RiskHero band={b}/></div>)}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 28 }}>
        {RISK_ORDER.map(b => <div key={b} style={{ display: 'flex', justifyContent: 'center' }}><RiskCard band={b}/></div>)}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 10, justifyContent: 'center' }}>
        <RiskListRow band="Low"       name="Malibu Surfrider"   dist="2.4"/>
        <RiskListRow band="Moderate"  name="Venice Beach"       dist="3.2"/>
        <RiskListRow band="High"      name="Santa Monica Pier"  dist="3.8"/>
        <RiskListRow band="Very High" name="Imperial Beach"     dist="9.2"/>
      </div>
    </div>
  );
}

Object.assign(window, { RiskCard, RiskHero, RiskListRow, RiskSystemPoster, DropRow, SeverityBar,
  RISK_ORDER, RISK_COPY, RISK_TOKEN });
