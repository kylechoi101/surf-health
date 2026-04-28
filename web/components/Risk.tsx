export const RISK_ORDER = ['Low', 'Moderate', 'High', 'Very High'] as const;

export type RiskBand = typeof RISK_ORDER[number];

export const RISK_COPY: Record<string, { head: string; sub: string; cfu: string; drops: number }> = {
  'Low':       { head: 'Below standard.', sub: 'Conditions favor swimming.',         cfu: '< 35 CFU/100mL',  drops: 1 },
  'Moderate':  { head: 'Caution.',         sub: 'Avoid swallowing water.',            cfu: '35–104',          drops: 2 },
  'High':      { head: 'Warning.',         sub: 'Avoid water contact.',               cfu: '104–320',         drops: 3 },
  'Very High': { head: 'Closure level.',   sub: 'Check posted county advisory.',      cfu: '> 320',           drops: 3 },
};

export const RISK_TOKEN: Record<string, { c: string; bg: string; ink: string }> = {
  'Low':       { c: 'var(--sl-risk-low)',  bg: 'var(--sl-risk-low-bg)',  ink: 'var(--sl-risk-low-ink)' },
  'Moderate':  { c: 'var(--sl-risk-mod)',  bg: 'var(--sl-risk-mod-bg)',  ink: 'var(--sl-risk-mod-ink)' },
  'High':      { c: 'var(--sl-risk-high)', bg: 'var(--sl-risk-high-bg)', ink: 'var(--sl-risk-high-ink)' },
  'Very High': { c: 'var(--sl-risk-vh)',   bg: 'var(--sl-risk-vh-bg)',   ink: 'var(--sl-risk-vh-ink)' },
};

function getBandColorName(band: string) {
  return band === 'Very High' ? 'vh' : band === 'High' ? 'high' : band === 'Moderate' ? 'mod' : 'low';
}

export function DropRow({ band, size = 14 }: { band: string, size?: number }) {
  const d = RISK_COPY[band]?.drops || 2;
  const color = `var(--sl-risk-${getBandColorName(band)})`;
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

export function SeverityBar({ band, width = '140px', height = 6 }: { band: string, width?: number | string, height?: number }) {
  const idx = RISK_ORDER.indexOf(band as any);
  return (
    <div 
      role="img" 
      aria-label={`Risk level ${idx + 1} of 4: ${band}`}
      style={{ display: 'flex', gap: 3, width }}
    >
      {RISK_ORDER.map((b, i) => {
        const on = i <= idx;
        const c = `var(--sl-risk-${getBandColorName(b)})`;
        return <div key={b} className="animate-fill" style={{
          flex: 1, height, borderRadius: 2,
          background: on ? c : 'var(--sl-sand)',
          opacity: on ? (i === idx ? 1 : 0.55) : 1,
          animationDelay: `${i * 0.1}s`,
        }}/>;
      })}
    </div>
  );
}

export function RiskChip({ band, ageHours }: { band: string, ageHours?: number }) {
  const tok = RISK_TOKEN[band] || RISK_TOKEN['Moderate'];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px 4px 8px', borderRadius: 999,
      background: tok.bg, color: tok.ink,
      border: `1px solid ${tok.c}`,
      fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 500,
      letterSpacing: '0.10em', textTransform: 'uppercase',
    }}>
      <DropRow band={band} size={10}/>
      <span>{band}{ageHours !== undefined && ageHours > 24 ? ` · ${Math.floor(ageHours/24)}d` : ''}</span>
    </span>
  );
}
