// Shorelife mark — disciplined logo for app/header use.
//
// CONCEPT (per kyle): the silhouette IS an "S". The negative-space coastline
// runs through it. Left side = ocean (deep navy). Right side = sand (warm).
// At small sizes (16/24/32px) it MUST read as a confident S; ornament is banned.
//
// Geometry: a square tile, rotated/clipped into a circle. A single sinuous
// S-curve splits it. That's it — no waves, no sun, no grain, no tide-line.
// One sharp coast hairline is the ONLY interior detail.

function ShorelifeMark({
  size = 40,
  ocean = 'var(--sl-navy)',
  sand = 'var(--sl-sun)',           // warm sand-poster mustard reads at small sizes
  coast = 'var(--sl-bone)',         // negative-space hairline — bright against both fills
  showFrame = false,                // off by default; circle is implicit via clipPath
}) {
  const uid = React.useId();
  const cId = `sl-coast-${uid}`;
  const rId = `sl-ring-${uid}`;
  // Coordinate system: 100×100, centered.
  // The S-curve is two cubic beziers stitched. Top-down.
  // Tuned so the curve has muscular shoulders (legible at 16px).
  const SCURVE = 'M 50 4 C 12 18 12 38 50 50 C 88 62 88 82 50 96';

  // Filled "ocean" half: everything LEFT of the curve, bounded by the tile.
  const OCEAN = `M 0 0 L 50 0
                 C 12 18 12 38 50 50
                 C 88 62 88 82 50 96
                 L 50 100 L 0 100 Z`;
  // Filled "sand" half: everything RIGHT of the curve.
  const SAND  = `M 50 0 L 100 0 L 100 100 L 50 100
                 C 88 82 88 62 50 50
                 C 12 38 12 18 50 0 Z`;

  return (
    <svg width={size} height={size} viewBox="0 0 100 100"
      style={{ display: 'block', flexShrink: 0 }}
      shapeRendering="geometricPrecision">
      <defs>
        <clipPath id={rId}>
          <circle cx="50" cy="50" r="48"/>
        </clipPath>
      </defs>

      {/* Everything inside a circular tile so the mark sits on any bg */}
      <g clipPath={`url(#${rId})`}>
        <path d={OCEAN} fill={ocean}/>
        <path d={SAND}  fill={sand}/>
        {/* The coastline — a single negative-space hairline. */}
        <path d={SCURVE} stroke={coast} strokeWidth="2.4"
          fill="none" strokeLinecap="round"/>
      </g>

      {showFrame && (
        <circle cx="50" cy="50" r="48" fill="none"
          stroke={ocean} strokeWidth="1" opacity="0.25"/>
      )}
    </svg>
  );
}

function ShorelifeWordmark({ size = 30, ink = 'var(--sl-navy)' }) {
  return (
    <span style={{ fontFamily: 'var(--sl-display)', fontSize: size, fontWeight: 500,
      color: ink, letterSpacing: '-0.025em', lineHeight: 0.9 }}>
      shorelife
    </span>
  );
}

function LockupHorizontal({ size = 32, ink = 'var(--sl-navy)', subtitle }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.55 }}>
      <ShorelifeMark size={size * 1.15} ocean={ink}/>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <ShorelifeWordmark size={size} ink={ink}/>
        {subtitle && (
          <span style={{ fontFamily: 'var(--sl-mono)', fontSize: 9.5, fontWeight: 500,
            letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { ShorelifeMark, ShorelifeWordmark, LockupHorizontal });
