// Shorelife logo system
// Vertical lockup. No sun. The wave curl meeting the sand line FORMS the S.
// Realistic beach scene, calm and graphic.

// ─── The mark ──────────────────────────────────────────────────────────────
// The S is built from: top curve = cresting wave, bottom curve = wet-sand shoreline receding.
// Where wave meets sand, the two curves connect into a single "S" form.
// No sun. Just wave, water, sand.
function ShorelifeMark({ size = 96, ink = '#0b4266', sand = '#c9b997', water = '#4dd5a8',
                        style = 'default' }) {
  const s = size;
  // 'default': tall vertical mark. 'stamp': square tile with rounded corners (app-icon ready).
  const isStamp = style === 'stamp';
  const tileBg = isStamp ? ink : 'transparent';
  const waveInk = isStamp ? '#faf6ee' : ink;
  const sandInk = isStamp ? sand : sand;

  // viewBox is portrait for vertical orientation.
  return (
    <svg width={s} height={s * 1.2} viewBox="0 0 80 96" style={{ display: 'block' }}>
      {isStamp && <rect width="80" height="96" rx="18" fill={tileBg}/>}

      {/* Top-right: cresting wave — upper curl of the S */}
      {/* Shape: wave peaks in upper-right, curls back and down toward middle-left */}
      <path d="M 10 26
               C 10 14, 22 8, 38 8
               C 54 8, 66 18, 70 30
               C 68 28, 62 26, 56 28
               C 48 30, 42 36, 38 44
               L 10 44
               Z"
        fill={waveInk}/>
      {/* Wave lip highlight */}
      <path d="M 18 20 C 26 14, 40 12, 54 18"
        stroke={isStamp ? water : '#faf6ee'} strokeWidth="1.2" fill="none" strokeLinecap="round" opacity={isStamp ? 0.9 : 0.6}/>

      {/* Water band — thin strip below the wave, where surf meets shore */}
      <path d="M 10 44 L 70 44 L 70 48 C 50 50, 30 50, 10 48 Z"
        fill={waveInk} opacity={isStamp ? 0.5 : 0.35}/>

      {/* Bottom-left: wet sand curl — lower curl of the S */}
      {/* Shape: sand sweeps from lower-left up and around to middle-right */}
      <path d="M 70 54
               C 58 52, 46 54, 38 60
               C 30 66, 24 76, 22 84
               C 20 90, 16 88, 10 88
               L 10 96
               L 70 96
               Z"
        fill={sandInk}/>
      {/* Sand grain texture */}
      <g fill={isStamp ? ink : '#a89569'} opacity={isStamp ? 0.25 : 0.5}>
        <circle cx="30" cy="78" r="0.6"/>
        <circle cx="38" cy="82" r="0.5"/>
        <circle cx="48" cy="78" r="0.6"/>
        <circle cx="58" cy="82" r="0.5"/>
        <circle cx="26" cy="86" r="0.6"/>
        <circle cx="44" cy="88" r="0.5"/>
        <circle cx="54" cy="86" r="0.5"/>
        <circle cx="64" cy="88" r="0.6"/>
      </g>
      {/* Tideline — where wet sand meets dry */}
      <path d="M 12 86 C 24 84, 40 89, 58 85 C 64 84, 68 85, 70 86"
        stroke={isStamp ? '#faf6ee' : ink} strokeWidth="0.8" fill="none" strokeLinecap="round" opacity="0.35"/>
    </svg>
  );
}

// ─── The wordmark — plain, clean Fraunces. No sun-dot hackery. ─────────────
function ShorelifeWordmark({ size = 42, ink = '#0b4266', weight = 500 }) {
  return (
    <div style={{ fontFamily: 'var(--sl-display)', fontSize: size, fontWeight: weight,
      color: ink, letterSpacing: '-0.025em', lineHeight: 1 }}>
      shorelife
    </div>
  );
}

// ─── Lockups — vertical is primary ─────────────────────────────────────────
function LockupVertical({ ink = '#0b4266', sand = '#c9b997', water = '#4dd5a8', size = 42,
                         tagline = true }) {
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', gap: size * 0.35 }}>
      <ShorelifeMark size={size * 1.8} ink={ink} sand={sand} water={water}/>
      <ShorelifeWordmark size={size} ink={ink}/>
      {tagline && (
        <div style={{ fontFamily: 'var(--sl-mono)', fontSize: size * 0.22, letterSpacing: '0.2em',
          textTransform: 'uppercase', color: ink, opacity: 0.65 }}>
          California water quality
        </div>
      )}
    </div>
  );
}

// Keep horizontal as a secondary treatment (nav-bar use case)
function LockupHorizontal({ ink = '#0b4266', sand = '#c9b997', water = '#4dd5a8', size = 32 }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.4 }}>
      <ShorelifeMark size={size * 1.1} ink={ink} sand={sand} water={water}/>
      <ShorelifeWordmark size={size} ink={ink}/>
    </div>
  );
}

// Canvas app-icon cell
function AppIconCell({ bg, ink = '#0b4266', sand = '#c9b997', water = '#4dd5a8', label }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 180, height: 180, borderRadius: 40, background: bg, overflow: 'hidden',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        boxShadow: '0 8px 24px rgba(11,66,102,0.12), inset 0 1px 0 rgba(255,255,255,0.3)' }}>
        <svg width="180" height="180" viewBox="0 0 80 96" preserveAspectRatio="xMidYMid slice">
          <path d="M 10 26 C 10 14, 22 8, 38 8 C 54 8, 66 18, 70 30
                   C 68 28, 62 26, 56 28 C 48 30, 42 36, 38 44 L 10 44 Z"
            fill={ink}/>
          <path d="M 18 20 C 26 14, 40 12, 54 18"
            stroke={water} strokeWidth="1.2" fill="none" strokeLinecap="round" opacity="0.8"/>
          <path d="M 10 44 L 70 44 L 70 48 C 50 50, 30 50, 10 48 Z"
            fill={ink} opacity="0.45"/>
          <path d="M 70 54 C 58 52, 46 54, 38 60 C 30 66, 24 76, 22 84
                   C 20 90, 16 88, 10 88 L 10 96 L 70 96 Z"
            fill={sand}/>
          <path d="M 12 86 C 24 84, 40 89, 58 85 C 64 84, 68 85, 70 86"
            stroke={ink} strokeWidth="0.8" fill="none" strokeLinecap="round" opacity="0.3"/>
        </svg>
      </div>
      {/* 40px reference */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ width: 40, height: 40, borderRadius: 9, background: bg, overflow: 'hidden',
          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <svg width="40" height="40" viewBox="0 0 80 96" preserveAspectRatio="xMidYMid slice">
            <path d="M 10 26 C 10 14, 22 8, 38 8 C 54 8, 66 18, 70 30
                     C 68 28, 62 26, 56 28 C 48 30, 42 36, 38 44 L 10 44 Z" fill={ink}/>
            <path d="M 10 44 L 70 44 L 70 48 C 50 50, 30 50, 10 48 Z" fill={ink} opacity="0.45"/>
            <path d="M 70 54 C 58 52, 46 54, 38 60 C 30 66, 24 76, 22 84
                     C 20 90, 16 88, 10 88 L 10 96 L 70 96 Z" fill={sand}/>
          </svg>
        </div>
        <div style={{ fontFamily: 'var(--sl-mono)', fontSize: 10, letterSpacing: '0.12em',
          textTransform: 'uppercase', color: '#5e6b73' }}>
          {label}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ShorelifeMark, ShorelifeWordmark, LockupVertical, LockupHorizontal, AppIconCell });
