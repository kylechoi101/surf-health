// Risk severity vocabulary — same as foundations
const RISK_ORDER = ['Low', 'Moderate', 'High', 'Very High'];
const RISK_COPY = {
  'Low':       { head: 'Clean.',     sub: 'Swim, surf, dunk under.',         cfu: '< 35 CFU/100mL',  drops: 1 },
  'Moderate':  { head: 'Watch.',     sub: 'Okay — just don\u2019t swallow.', cfu: '35\u2013104',      drops: 2 },
  'High':      { head: 'Elevated.',  sub: 'Stay out if you\u2019re sensitive.', cfu: '104\u2013320',  drops: 3 },
  'Very High': { head: 'Unsafe.',    sub: 'County advisory \u00b7 stay out.', cfu: '> 320',           drops: 3 },
};
const RISK_TOKEN = {
  'Low':       { c: 'var(--sl-risk-low)',  bg: 'var(--sl-risk-low-bg)',  ink: 'var(--sl-risk-low-ink)' },
  'Moderate':  { c: 'var(--sl-risk-mod)',  bg: 'var(--sl-risk-mod-bg)',  ink: 'var(--sl-risk-mod-ink)' },
  'High':      { c: 'var(--sl-risk-high)', bg: 'var(--sl-risk-high-bg)', ink: 'var(--sl-risk-high-ink)' },
  'Very High': { c: 'var(--sl-risk-vh)',   bg: 'var(--sl-risk-vh-bg)',   ink: 'var(--sl-risk-vh-ink)' },
};

// Drop glyph (1–3 droplets, filled to severity)
function DropRow({ band, size = 14 }) {
  const d = RISK_COPY[band].drops;
  const color = `var(--sl-risk-${band === 'Very High' ? 'vh' : band === 'High' ? 'high' : band === 'Moderate' ? 'mod' : 'low'})`;
  const vh = band === 'Very High';
  return (
    <span style={{ display: 'inline-flex', gap: 3, alignItems: 'center' }}>
      {[0, 1, 2].map(i => {
        const filled = i < d || vh;
        return (
          <svg key={i} width={size} height={size * 1.2} viewBox="0 0 12 14">
            <path d="M6 1 C6 1 1.5 6 1.5 9 A4.5 4.5 0 0 0 10.5 9 C10.5 6 6 1 6 1 Z"
              fill={filled ? color : 'none'}
              stroke={color} strokeWidth="1.1" opacity={filled ? 1 : 0.3}/>
            {vh && i === 2 && <path d="M6 5 V8 M6 10 V10.5" stroke="#fff" strokeWidth="1.2" strokeLinecap="round"/>}
          </svg>
        );
      })}
    </span>
  );
}

// Severity bar — 4 segmented slots
function SeverityBar({ band, width = 140, height = 6 }) {
  const idx = RISK_ORDER.indexOf(band);
  return (
    <div style={{ display: 'flex', gap: 3, width }}>
      {RISK_ORDER.map((b, i) => {
        const on = i <= idx;
        const c = `var(--sl-risk-${b === 'Very High' ? 'vh' : b === 'High' ? 'high' : b === 'Moderate' ? 'mod' : 'low'})`;
        return <div key={b} style={{
          flex: 1, height, borderRadius: 2,
          background: on ? c : 'var(--sl-sand)',
          opacity: on ? (i === idx ? 1 : 0.55) : 1,
        }}/>;
      })}
    </div>
  );
}

// Pill chip — used in nav, cards
function RiskChip({ band, ageHours }) {
  const tok = RISK_TOKEN[band];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px 4px 8px', borderRadius: 999,
      background: tok.bg, color: tok.ink,
      border: `1px solid ${tok.c}`,
      fontFamily: 'var(--sl-mono)', fontSize: 10, fontWeight: 500,
      letterSpacing: '0.10em', textTransform: 'uppercase',
    }}>
      <DropRow band={band} size={10}/>
      <span>{band}{ageHours !== undefined && ageHours > 24 ? ` · ${Math.floor(ageHours/24)}d` : ''}</span>
    </span>
  );
}

Object.assign(window, { RISK_ORDER, RISK_COPY, RISK_TOKEN, DropRow, SeverityBar, RiskChip });
