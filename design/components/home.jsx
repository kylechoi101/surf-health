// Home screen — shoreline cross-section metaphor, refined.
// Side-view of the beach: sky · horizon · breaking wave · surf zone · wet sand · dry sand.
// No clutter overlays inside the art — annotations live outside the illustration.

// ─── Cross-section illustration (refined) ──────────────────────────────────
function ShorelineCrossSection({ band, beach, width = 390, height = 260, variant = 'A' }) {
  const tok = window.RISK_TOKEN[band];
  const w = width, h = height;

  // Four curated palettes — earthy, considered, no neon.
  const palette = {
    A: { sky1: '#f0e6cf', sky2: '#e4d6b4', sea1: '#3d7aa0', sea2: '#0b4266', deep: '#051d2e',
         foam: '#faf6ee', wetSand: '#b39770', drySand: '#d9c49a', horizon: '#8fa5b8' },
    B: { sky1: '#ede3cc', sky2: '#dfceac', sea1: '#427ea3', sea2: '#0b4266', deep: '#051d2e',
         foam: '#f5f0e4', wetSand: '#a68862', drySand: '#d0bb8e', horizon: '#7d95aa' },
    C: { sky1: '#e7dcc3', sky2: '#d5c39d', sea1: '#316a8d', sea2: '#093a5a', deep: '#04182a',
         foam: '#f1ecdf', wetSand: '#9e8055', drySand: '#c5b080', horizon: '#6f8799' },
    D: { sky1: '#e8cf9f', sky2: '#d2a878', sea1: '#2a5876', sea2: '#0a3654', deep: '#051a2b',
         foam: '#f4e9d2', wetSand: '#8f6f48', drySand: '#b89a6a', horizon: '#a88060' },
  }[variant];

  // Particulate density cues risk — subtly, not as dots floating in empty water.
  const particleCount = { Low: 4, Moderate: 9, High: 16, 'Very High': 26 }[band];
  const horizonY = h * 0.36;
  const beachY = h * 0.62;  // where sand meets water at the shoreline
  const lipX = w * 0.66;    // wave lip position

  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none"
      style={{ display: 'block' }}>
      <defs>
        <linearGradient id={`sky-${variant}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={palette.sky1}/>
          <stop offset="1" stopColor={palette.sky2}/>
        </linearGradient>
        <linearGradient id={`sea-${variant}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={palette.sea1}/>
          <stop offset="0.7" stopColor={palette.sea2}/>
          <stop offset="1" stopColor={palette.deep}/>
        </linearGradient>
        <linearGradient id={`sand-${variant}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={palette.wetSand}/>
          <stop offset="1" stopColor={palette.drySand}/>
        </linearGradient>
        {/* Clip the whole thing to rounded corners for the host */}
        <clipPath id={`clip-${variant}`}>
          <rect x="0" y="0" width={w} height={h}/>
        </clipPath>
      </defs>

      <g clipPath={`url(#clip-${variant})`}>
        {/* SKY */}
        <rect x="0" y="0" width={w} height={horizonY + 2} fill={`url(#sky-${variant})`}/>

        {/* Distant silhouette headland — gives scale, anchors horizon */}
        <path d={`M 0 ${horizonY} L 0 ${horizonY - 8}
                  Q ${w*0.06} ${horizonY - 18}, ${w*0.12} ${horizonY - 10}
                  Q ${w*0.18} ${horizonY - 4}, ${w*0.22} ${horizonY}
                  L 0 ${horizonY} Z`}
          fill={palette.horizon} opacity="0.55"/>

        {/* Horizon atmospheric haze */}
        <rect x="0" y={horizonY - 4} width={w} height="8" fill={palette.sky2} opacity="0.6"/>

        {/* OCEAN — everything between horizon and beach */}
        <rect x="0" y={horizonY} width={w} height={h - horizonY} fill={`url(#sea-${variant})`}/>

        {/* Distant swell — horizontal lines, tighter near horizon (perspective) */}
        {[0, 1, 2, 3, 4].map(i => {
          const y = horizonY + 4 + i*i*1.8;
          const op = 0.5 - i*0.08;
          return <line key={i} x1="0" y1={y} x2={w} y2={y}
            stroke={palette.foam} strokeWidth="0.6" opacity={op}/>;
        })}

        {/* Mid-distance swells — sinusoidal, getting taller toward viewer */}
        {[0.48, 0.53, 0.58].map((yr, i) => {
          const y = h * yr;
          const amp = 2 + i*1.5;
          return (
            <path key={i} d={`M 0 ${y}
              Q ${w*0.15} ${y-amp}, ${w*0.3} ${y}
              T ${w*0.6} ${y}
              T ${w*0.9} ${y}
              T ${w*1.1} ${y}`}
              stroke={palette.foam} strokeWidth={0.8 + i*0.2} fill="none" opacity={0.35 + i*0.1}/>
          );
        })}

        {/* THE BREAKING WAVE — proper anatomy: face, lip, tube, trailing whitewater */}
        {/* Wave face (the back side of the breaking wave, visible from our side view) */}
        <path d={`M ${w*0.35} ${h*0.62}
                 C ${w*0.42} ${h*0.55}, ${w*0.52} ${h*0.48}, ${lipX} ${h*0.42}
                 C ${lipX + w*0.04} ${h*0.40}, ${lipX + w*0.08} ${h*0.44}, ${lipX + w*0.10} ${h*0.50}
                 C ${lipX + w*0.05} ${h*0.56}, ${lipX - w*0.02} ${h*0.60}, ${lipX - w*0.08} ${h*0.60}
                 Z`}
          fill={`url(#sea-${variant})`}/>
        {/* Wave face shadow (gives the wave dimension) */}
        <path d={`M ${w*0.42} ${h*0.60}
                 C ${w*0.48} ${h*0.54}, ${w*0.56} ${h*0.49}, ${lipX - w*0.01} ${h*0.44}
                 L ${lipX - w*0.01} ${h*0.52}
                 C ${w*0.56} ${h*0.56}, ${w*0.48} ${h*0.60}, ${w*0.42} ${h*0.62}
                 Z`}
          fill={palette.deep} opacity="0.25"/>
        {/* The lip — thin foam line along the crest */}
        <path d={`M ${w*0.35} ${h*0.62}
                 C ${w*0.42} ${h*0.55}, ${w*0.52} ${h*0.48}, ${lipX} ${h*0.42}
                 C ${lipX + w*0.04} ${h*0.40}, ${lipX + w*0.07} ${h*0.42}, ${lipX + w*0.08} ${h*0.45}`}
          stroke={palette.foam} strokeWidth="1.8" fill="none" strokeLinecap="round"/>
        {/* Spray at the lip */}
        <g fill={palette.foam} opacity="0.75">
          <circle cx={lipX + w*0.02} cy={h*0.40} r="1.2"/>
          <circle cx={lipX + w*0.05} cy={h*0.39} r="0.8"/>
          <circle cx={lipX + w*0.07} cy={h*0.41} r="0.6"/>
          <circle cx={lipX - w*0.01} cy={h*0.42} r="0.9"/>
        </g>

        {/* SURF ZONE — foamy whitewater between wave and shore */}
        <path d={`M ${w*0.15} ${h*0.65}
                 Q ${w*0.25} ${h*0.63}, ${w*0.35} ${h*0.65}
                 T ${w*0.55} ${h*0.66}
                 T ${w*0.78} ${h*0.64}
                 L ${w*0.78} ${h*0.71}
                 Q ${w*0.55} ${h*0.72}, ${w*0.30} ${h*0.71}
                 T ${w*0.12} ${h*0.70} Z`}
          fill={palette.foam} opacity="0.85"/>
        {/* Foam texture lines */}
        <path d={`M ${w*0.18} ${h*0.67} Q ${w*0.30} ${h*0.66}, ${w*0.42} ${h*0.67} T ${w*0.70} ${h*0.67}`}
          stroke={palette.sea1} strokeWidth="0.5" fill="none" opacity="0.5"/>

        {/* SUBMERGED kelp / particulate — only in water zones, density = risk */}
        {[...Array(particleCount)].map((_, i) => {
          // Deterministic pseudo-random positions within the water area
          const t = (i * 97 + 31) % 1000 / 1000;
          const px = w * (0.08 + t * 0.82);
          const py = h * (0.74 + ((i * 53) % 100) / 100 * 0.18);
          const r = 0.6 + ((i * 17) % 10) / 10 * 1.2;
          // Don't draw on the sand wedge (lower left)
          if (px < w * 0.22 && py > h * 0.82) return null;
          return <circle key={i} cx={px} cy={py} r={r}
            fill={band === 'Low' ? palette.sea1 : tok.c}
            opacity={band === 'Low' ? 0.35 : 0.55}/>;
        })}

        {/* WET SAND — dark, glossy, right where water recedes */}
        <path d={`M 0 ${beachY + 10}
                 C ${w*0.04} ${beachY + 4}, ${w*0.10} ${beachY + 2}, ${w*0.16} ${beachY + 8}
                 C ${w*0.22} ${beachY + 14}, ${w*0.28} ${beachY + 22}, ${w*0.32} ${beachY + 30}
                 L ${w*0.32} ${h}
                 L 0 ${h} Z`}
          fill={palette.wetSand}/>
        {/* Wet-sand sheen — reflection of sky */}
        <path d={`M ${w*0.02} ${beachY + 12}
                 C ${w*0.08} ${beachY + 8}, ${w*0.14} ${beachY + 10}, ${w*0.20} ${beachY + 16}`}
          stroke={palette.sky1} strokeWidth="1.2" fill="none" opacity="0.5" strokeLinecap="round"/>

        {/* DRY SAND — lighter, receding into foreground */}
        <path d={`M 0 ${h*0.78}
                 C ${w*0.06} ${h*0.76}, ${w*0.12} ${h*0.78}, ${w*0.20} ${h*0.84}
                 L ${w*0.20} ${h}
                 L 0 ${h} Z`}
          fill={`url(#sand-${variant})`}/>

        {/* Tideline — where the wave's last reach made dark arcs on the sand */}
        <path d={`M ${w*0.02} ${h*0.84} Q ${w*0.10} ${h*0.82}, ${w*0.18} ${h*0.86}`}
          stroke={palette.wetSand} strokeWidth="0.6" fill="none" opacity="0.7"/>
        <path d={`M ${w*0.04} ${h*0.90} Q ${w*0.12} ${h*0.88}, ${w*0.19} ${h*0.92}`}
          stroke={palette.wetSand} strokeWidth="0.5" fill="none" opacity="0.5"/>

        {/* Sand grain texture — subtle */}
        <g fill={palette.wetSand} opacity="0.4">
          {[...Array(14)].map((_, i) => {
            const px = w * 0.02 + (i * 11) % (w * 0.18);
            const py = h * 0.88 + ((i * 7) % 8);
            return <circle key={i} cx={px} cy={py} r="0.4"/>;
          })}
        </g>

        {/* Subtle sample marker — thin dashed vertical line in the surf, no label */}
        <line x1={w*0.45} y1={h*0.66} x2={w*0.45} y2={h*0.72}
          stroke={palette.foam} strokeWidth="1" strokeDasharray="1.5 2" opacity="0.8"/>
        <circle cx={w*0.45} cy={h*0.66} r="2" fill={palette.foam} stroke={palette.deep} strokeWidth="0.6"/>
      </g>
    </svg>
  );
}

// Shared mini cross-section annotation row — used below the illustration in variants
function CrossSectionLegend({ band }) {
  return (
    <div style={{ display: 'flex', gap: 16, padding: '10px 16px 0',
      fontFamily: 'var(--sl-mono)', fontSize: 9, letterSpacing: '0.1em', color: 'var(--sl-muted)',
      textTransform: 'uppercase' }}>
      <span>◦ SAMPLE IN SURF</span>
      <span style={{ marginLeft: 'auto' }}>← OPEN OCEAN · SHORE →</span>
    </div>
  );
}

// ─── Variant A — "Hero cross-section" ──────────────────────────────────────
function HomeVariantA({ beach, nearby }) {
  const tok = window.RISK_TOKEN[beach.risk];
  const copy = window.RISK_COPY[beach.risk];
  return (
    <div style={{ background: 'var(--sl-ecru)', height: '100%', overflowY: 'auto', paddingBottom: 80 }}>
      <div style={{ padding: '54px 18px 10px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <ShorelifeMark size={24}/>
        <div style={{ flex: 1 }}>
          <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>Your beach · updated 5:02a</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--sl-navy)', marginTop: 1 }}>
            {beach.name}
          </div>
        </div>
        <Icon.chevron style={{ color: 'var(--sl-muted)' }}/>
      </div>

      <div style={{ position: 'relative', margin: '8px 16px 0', borderRadius: 18, overflow: 'hidden',
        border: '1px solid var(--sl-line)' }}>
        <ShorelineCrossSection band={beach.risk} beach={beach} variant="A" height={240}/>
      </div>
      <CrossSectionLegend band={beach.risk}/>

      <div style={{ padding: '12px 20px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <DropRow band={beach.risk} size={16}/>
          <div className="sl-label" style={{ color: tok.ink }}>{beach.risk.toUpperCase()}</div>
        </div>
        <div className="sl-display" style={{ fontSize: 52, color: 'var(--sl-navy)', lineHeight: 0.95 }}>
          {copy.head}
        </div>
        <div style={{ fontSize: 14, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.45, maxWidth: 310 }}>
          {copy.sub} <span style={{ color: 'var(--sl-ink)' }}>
            Last sample 5 days ago · {copy.cfu} CFU/100mL.</span>
        </div>
        <div style={{ marginTop: 14 }}><SeverityBar band={beach.risk} width="100%"/></div>
      </div>

      <div style={{ padding: '22px 20px 0' }}>
        <div className="sl-eyebrow">Conditions now</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 10 }}>
          {[
            { l: 'Surf',  v: `${beach.waveFt}ft`, s: `${beach.period}s` },
            { l: 'Water', v: `${beach.temp}°`,    s: 'F' },
            { l: 'Wind',  v: `${beach.wind}`,     s: 'mph W' },
            { l: 'UV',    v: beach.uv,            s: beach.uv >= 7 ? 'high' : 'mod' },
          ].map(c => (
            <div key={c.l} style={{ padding: '10px 10px', background: 'var(--sl-bone)',
              border: '1px solid var(--sl-line)', borderRadius: 10 }}>
              <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>{c.l}</div>
              <div className="sl-mono" style={{ fontSize: 18, color: 'var(--sl-ink)', marginTop: 2 }}>{c.v}</div>
              <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)' }}>{c.s}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '22px 20px 0' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div className="sl-eyebrow">Nearby</div>
          <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-navy)' }}>VIEW MAP →</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
          {nearby.slice(0,4).map(b => (
            <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 12px', background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
              borderRadius: 10 }}>
              <DropRow band={b.risk} size={11}/>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div>
                <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)', marginTop: 1 }}>
                  {b.dist} MI · {b.waveFt}FT · {b.temp}°
                </div>
              </div>
              <SeverityBar band={b.risk} width={50}/>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Variant B — Answer-first + strip ──────────────────────────────────────
function HomeVariantB({ beach, nearby }) {
  const tok = window.RISK_TOKEN[beach.risk];
  const copy = window.RISK_COPY[beach.risk];
  return (
    <div style={{ background: 'var(--sl-ecru)', height: '100%', overflowY: 'auto', paddingBottom: 80 }}>
      <div style={{ padding: '54px 18px 10px', display: 'flex', alignItems: 'center', gap: 10 }}>
        <ShorelifeMark size={22}/>
        <div style={{ flex: 1, fontSize: 15, fontWeight: 600, color: 'var(--sl-navy)',
          fontFamily: 'var(--sl-display)' }}>shorelife</div>
        <Icon.search style={{ color: 'var(--sl-muted)' }}/>
      </div>

      <div style={{ padding: '4px 20px 0' }}>
        <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>
          {beach.name} · {beach.county.toUpperCase()}
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', marginTop: 4 }}>
          <div className="sl-display" style={{ fontSize: 64, color: tok.ink, lineHeight: 0.9 }}>
            {copy.head}
          </div>
          <DropRow band={beach.risk} size={18}/>
        </div>
        <div style={{ fontSize: 13, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.45 }}>
          {copy.sub}
        </div>
      </div>

      <div style={{ margin: '18px 16px 0', borderRadius: 12, overflow: 'hidden',
        border: '1px solid var(--sl-line)' }}>
        <ShorelineCrossSection band={beach.risk} beach={beach} variant="B" height={130}/>
      </div>

      <div style={{ padding: '20px 20px 0' }}>
        <div className="sl-eyebrow">Reading</div>
        <div style={{ background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
          borderRadius: 12, marginTop: 10, overflow: 'hidden' }}>
          {[
            ['Enterococcus', copy.cfu + ' CFU/100mL'],
            ['Sample date', 'Apr 18 · 5 days ago'],
            ['7-day trend', beach.risk === 'Low' ? 'Stable' : 'Rising'],
            ['Advisory',    beach.risk === 'Very High' ? 'Active · County' : 'None'],
          ].map(([l, v], i) => (
            <div key={l} style={{ display: 'flex', justifyContent: 'space-between',
              padding: '11px 14px', borderTop: i ? '1px solid var(--sl-line-soft)' : 'none' }}>
              <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>{l}</div>
              <div className="sl-mono" style={{ fontSize: 12, color: 'var(--sl-ink)' }}>{v}</div>
            </div>
          ))}
        </div>
      </div>

      <div style={{ padding: '22px 20px 0' }}>
        <div className="sl-eyebrow">Nearby</div>
        <div style={{ marginTop: 10 }}>
          {nearby.slice(0,5).map((b, i) => (
            <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 10,
              padding: '9px 0', borderTop: i ? '1px dashed var(--sl-line)' : '1px solid var(--sl-line)',
              borderBottom: i === 4 ? '1px solid var(--sl-line)' : 'none' }}>
              <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)', width: 34 }}>
                {b.dist}MI
              </div>
              <div style={{ flex: 1, fontSize: 13, fontWeight: 500 }}>{b.name}</div>
              <SeverityBar band={b.risk} width={46}/>
              <DropRow band={b.risk} size={10}/>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Variant C — Full-bleed diagrammatic ───────────────────────────────────
function HomeVariantC({ beach, nearby }) {
  const tok = window.RISK_TOKEN[beach.risk];
  const copy = window.RISK_COPY[beach.risk];
  return (
    <div style={{ background: 'var(--sl-ecru)', height: '100%', overflowY: 'auto', paddingBottom: 80 }}>
      <div style={{ position: 'relative', height: 380 }}>
        <ShorelineCrossSection band={beach.risk} beach={beach} variant="C" height={380}/>
        <div style={{ position: 'absolute', top: 54, left: 20, right: 20, display: 'flex',
          justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <ShorelifeMark size={22} ink="#f4efe6" sand="#e8dfcc" water="#4dd5a8"/>
            <div className="sl-label" style={{ color: '#f4efe6' }}>{beach.county.toUpperCase()}</div>
          </div>
          <div style={{ padding: '4px 10px', background: 'rgba(244,239,230,0.92)',
            border: '1px solid var(--sl-line)', borderRadius: 999 }} className="sl-mono" >
            <span style={{ fontSize: 10, color: 'var(--sl-muted)' }}>5:02A</span>
          </div>
        </div>
        <div style={{ position: 'absolute', left: 20, top: 92, display: 'flex', alignItems: 'center',
          gap: 6, padding: '5px 10px', background: 'rgba(244,239,230,0.92)',
          border: '1px solid var(--sl-line)', borderRadius: 999, fontSize: 12, fontWeight: 500,
          color: 'var(--sl-navy)' }}>
          <Icon.location style={{ width: 12, height: 12 }}/>
          {beach.name}
        </div>
      </div>

      <div style={{ margin: '-80px 16px 0', position: 'relative', padding: 22,
        background: 'var(--sl-bone)', border: '1px solid var(--sl-line)', borderRadius: 18,
        boxShadow: '0 -6px 24px rgba(11,66,102,0.05)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div className="sl-label" style={{ color: tok.ink }}>{beach.risk.toUpperCase()}</div>
          <DropRow band={beach.risk} size={16}/>
        </div>
        <div className="sl-display" style={{ fontSize: 54, color: 'var(--sl-navy)', lineHeight: 0.95 }}>
          {copy.head}
        </div>
        <div style={{ fontSize: 13, color: 'var(--sl-muted)', marginTop: 8, lineHeight: 1.45 }}>
          {copy.sub}
        </div>
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px dashed var(--sl-line)',
          display: 'flex', justifyContent: 'space-between' }}>
          <div>
            <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>Enterococcus</div>
            <div className="sl-mono" style={{ fontSize: 14, marginTop: 2 }}>{copy.cfu}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="sl-label" style={{ color: 'var(--sl-muted)' }}>Surf · UV</div>
            <div className="sl-mono" style={{ fontSize: 14, marginTop: 2 }}>{beach.waveFt}ft · {beach.uv}</div>
          </div>
        </div>
      </div>

      <div style={{ padding: '22px 20px 0' }}>
        <div className="sl-eyebrow">Nearby shoreline</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 10 }}>
          {nearby.slice(0,3).map(b => (
            <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 12px', background: 'var(--sl-bone)', border: '1px solid var(--sl-line)',
              borderRadius: 10 }}>
              <DropRow band={b.risk} size={11}/>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div>
                <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)', marginTop: 1 }}>
                  {b.dist} MI
                </div>
              </div>
              <SeverityBar band={b.risk} width={50}/>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Variant D — Field guide ───────────────────────────────────────────────
function HomeVariantD({ beach, nearby }) {
  const tok = window.RISK_TOKEN[beach.risk];
  const copy = window.RISK_COPY[beach.risk];
  return (
    <div style={{ background: 'var(--sl-ecru)', height: '100%', overflowY: 'auto', paddingBottom: 80 }}>
      <div style={{ padding: '54px 20px 16px', background: 'var(--sl-navy)', color: 'var(--sl-ecru)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <ShorelifeMark size={20} ink="#f4efe6" sand="#c9b997" water="#4dd5a8"/>
          <div style={{ flex: 1, fontFamily: 'var(--sl-display)', fontSize: 16, fontWeight: 500 }}>
            shorelife
          </div>
          <div className="sl-mono" style={{ fontSize: 10, opacity: 0.7 }}>APR 24 · 5:02A</div>
        </div>
        <div className="sl-label" style={{ color: '#c99b2d', opacity: 0.9 }}>
          SHORELINE REPORT · {beach.county.toUpperCase()}
        </div>
        <div style={{ fontSize: 18, fontFamily: 'var(--sl-display)', fontWeight: 500, marginTop: 4 }}>
          {beach.name}
        </div>
      </div>

      <div style={{ position: 'relative', borderBottom: '1px solid var(--sl-line)' }}>
        <ShorelineCrossSection band={beach.risk} beach={beach} variant="D" height={220} width={390}/>
        <div style={{ position: 'absolute', left: 16, top: 12, display: 'flex', alignItems: 'center', gap: 6,
          padding: '3px 8px', background: 'rgba(244,239,230,0.92)', border: '1px solid var(--sl-line)',
          borderRadius: 4, fontFamily: 'var(--sl-mono)', fontSize: 9, letterSpacing: '0.08em',
          color: 'var(--sl-ink)', textTransform: 'uppercase' }}>
          SWELL · {beach.waveFt}FT @ {beach.period}S
        </div>
        <div style={{ position: 'absolute', left: 16, bottom: 12, display: 'flex', alignItems: 'center', gap: 6,
          padding: '3px 8px', background: 'rgba(244,239,230,0.92)', border: '1px solid var(--sl-line)',
          borderRadius: 4, fontFamily: 'var(--sl-mono)', fontSize: 9, letterSpacing: '0.08em',
          color: 'var(--sl-ink)', textTransform: 'uppercase' }}>
          SAND · DRY/WET LINE
        </div>
      </div>

      <div style={{ padding: '20px 20px 0' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div>
            <div className="sl-label" style={{ color: tok.ink }}>§ {beach.risk.toUpperCase()}</div>
            <div className="sl-display" style={{ fontSize: 56, color: 'var(--sl-navy)',
              lineHeight: 0.95, marginTop: 2 }}>{copy.head}</div>
          </div>
          <DropRow band={beach.risk} size={18}/>
        </div>
        <div style={{ fontSize: 13, color: 'var(--sl-muted)', marginTop: 10, lineHeight: 1.5,
          paddingBottom: 14, borderBottom: '1px solid var(--sl-line)' }}>
          {copy.sub} Enterococcus <span className="sl-mono" style={{ color: tok.ink }}>{copy.cfu}</span> — sampled 5 days ago.
        </div>
      </div>

      <div style={{ padding: '18px 20px 0' }}>
        <div className="sl-eyebrow">Also along this coast</div>
        <div style={{ marginTop: 10 }}>
          {nearby.slice(0,4).map((b, i) => (
            <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 12,
              padding: '10px 0', borderTop: i ? '1px dashed var(--sl-line)' : 'none' }}>
              <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)',
                width: 26, textAlign: 'right' }}>{String(i+1).padStart(2,'0')}</div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{b.name}</div>
                <div className="sl-mono" style={{ fontSize: 10, color: 'var(--sl-muted)', marginTop: 1 }}>
                  {b.dist} MI · {b.risk.toUpperCase()}
                </div>
              </div>
              <DropRow band={b.risk} size={11}/>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ShorelineCrossSection, HomeVariantA, HomeVariantB, HomeVariantC, HomeVariantD });
