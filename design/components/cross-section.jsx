// Shoreline cross-section — editorial schematic, NOT a cartoon scene.
// Side profile: bathymetry curve, water column, surf zone, beach face,
// with hairline annotations and labeled sample/measurement columns.
// Inspired by oceanographic field-guide diagrams.

function ShorelineCrossSection({ band = 'Low', height = 360 }) {
  const W = 1200, H = height;
  const tok = RISK_TOKEN[band];

  // Bathymetry: deep water on the LEFT, beach face on the RIGHT.
  // Y values are measured from the surface line at y = surfaceY.
  const surfaceY = H * 0.30;
  const beachStart = W * 0.62;        // where bathy meets sea level
  const dryStart   = W * 0.74;        // where wet sand turns dry
  const seaFloor = (x) => {
    if (x <= 0) return surfaceY + H * 0.55;
    if (x >= beachStart) {
      // Beach face above sea level
      const t = (x - beachStart) / (W - beachStart);
      return surfaceY - t * H * 0.15;
    }
    // Concave-up bathymetry
    const t = x / beachStart;
    const depth = H * (0.55 - 0.55 * Math.pow(t, 1.6));
    return surfaceY + depth;
  };

  // Build floor path
  const floorPts = [];
  for (let x = 0; x <= W; x += 8) floorPts.push([x, seaFloor(x)]);
  const floorPath = floorPts.map((p, i) =>
    (i === 0 ? 'M ' : 'L ') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const seaPath = `${floorPath} L ${W} ${surfaceY} L 0 ${surfaceY} Z`;
  const sandPath = `${floorPath} L ${W} ${H} L 0 ${H} Z`;

  // Annotation columns — vertical sample stations
  const stations = [
    { id: 'A', x: W * 0.10, label: 'Offshore',     sub: 'buoy 46221' },
    { id: 'B', x: W * 0.34, label: 'Mid-shelf',    sub: 'CDIP nearshore' },
    { id: 'C', x: W * 0.52, label: 'Surf zone',    sub: 'culture sample' },
    { id: 'D', x: W * 0.68, label: 'Swash',        sub: 'tide gauge' },
  ];

  // Surf-zone particulate density
  const partCount = { Low: 8, Moderate: 22, High: 50, 'Very High': 90 }[band];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H}
      preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id="cs-water" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#cdd9de" stopOpacity="0.7"/>
          <stop offset="1" stopColor="#a4b8c2" stopOpacity="0.5"/>
        </linearGradient>
        <pattern id="cs-sand" x="0" y="0" width="6" height="6" patternUnits="userSpaceOnUse">
          <rect width="6" height="6" fill="#e9dfc6"/>
          <circle cx="2" cy="2" r="0.45" fill="#bfa97a" opacity="0.55"/>
          <circle cx="5" cy="4" r="0.35" fill="#bfa97a" opacity="0.4"/>
        </pattern>
      </defs>

      {/* Air column (just bg color, no clutter) */}
      <rect x="0" y="0" width={W} height={surfaceY} fill="var(--sl-bone)"/>

      {/* Water body */}
      <path d={seaPath} fill="url(#cs-water)"/>

      {/* Sand body */}
      <path d={sandPath} fill="url(#cs-sand)"/>

      {/* Hairline grid — depth ticks on the left */}
      {[1, 2, 3, 4].map(i => {
        const y = surfaceY + (H * 0.55 / 4) * i;
        const depth = i * 5; // m
        return (
          <g key={i}>
            <line x1="0" y1={y} x2={W} y2={y}
              stroke="#0b4266" strokeWidth="0.35" strokeDasharray="2 4" opacity="0.18"/>
            <text x="14" y={y - 4} fontFamily="var(--sl-mono)" fontSize="9"
              fill="var(--sl-muted)" letterSpacing="0.1em">−{depth}m</text>
          </g>
        );
      })}

      {/* Sea-surface line (datum) */}
      <line x1="0" y1={surfaceY} x2={W} y2={surfaceY}
        stroke="var(--sl-navy)" strokeWidth="0.9" opacity="0.55"/>
      <text x={W - 14} y={surfaceY - 6} textAnchor="end"
        fontFamily="var(--sl-mono)" fontSize="9" letterSpacing="0.18em"
        fill="var(--sl-navy)" opacity="0.7">
        MEAN SEA LEVEL · 0M
      </text>

      {/* Subtle wave on the surface, no cartoon foam */}
      <path d={(() => {
        let p = `M 0 ${surfaceY}`;
        for (let x = 0; x <= W * 0.62; x += 12) {
          const amp = x < W * 0.4 ? 1.2 : 1.8;
          const y = surfaceY + Math.sin(x / 28) * amp;
          p += ` L ${x} ${y.toFixed(1)}`;
        }
        return p;
      })()} stroke="var(--sl-navy)" strokeWidth="0.7" fill="none" opacity="0.4"/>

      {/* Surf-zone shading (subtle vertical band, ~ where waves break) */}
      <rect x={W * 0.46} y={surfaceY} width={W * 0.16} height={H * 0.55}
        fill={tok.c} opacity="0.06"/>
      <line x1={W * 0.46} y1={surfaceY - 8} x2={W * 0.46} y2={H - 30}
        stroke={tok.c} strokeWidth="0.5" strokeDasharray="2 3" opacity="0.6"/>
      <line x1={W * 0.62} y1={surfaceY - 8} x2={W * 0.62} y2={H - 30}
        stroke={tok.c} strokeWidth="0.5" strokeDasharray="2 3" opacity="0.6"/>
      <text x={W * 0.54} y={surfaceY - 14} textAnchor="middle"
        fontFamily="var(--sl-mono)" fontSize="9" letterSpacing="0.18em"
        fill={tok.c}>SURF ZONE</text>

      {/* Particulate density inside the water (band-driven) */}
      <g>
        {[...Array(partCount)].map((_, i) => {
          const seed = (i * 9301 + 49297) % 233280 / 233280;
          const seed2 = (i * 1597 + 51749) % 233280 / 233280;
          const x = W * 0.05 + seed * W * 0.55;
          const yMin = surfaceY + 6;
          const yMax = seaFloor(x) - 4;
          const y = yMin + seed2 * (yMax - yMin);
          if (y >= yMax) return null;
          return <circle key={i} cx={x} cy={y} r={0.9} fill={tok.c} opacity="0.55"/>;
        })}
      </g>

      {/* Sea floor profile line — crisp */}
      <path d={floorPath} stroke="var(--sl-navy-ink)" strokeWidth="1.2" fill="none"/>

      {/* Beach face — dry sand color above water */}
      <path d={`M ${beachStart} ${surfaceY}
        L ${W} ${seaFloor(W)} L ${W} ${surfaceY} Z`}
        fill="#d9c49a" opacity="0.55"/>

      {/* Annotation: stations with vertical lines and label boxes ABOVE */}
      {stations.map((st, i) => {
        const x = st.x;
        const yFloor = seaFloor(x);
        const yTop = 22;
        return (
          <g key={st.id}>
            {/* dashed vertical guide */}
            <line x1={x} y1={surfaceY} x2={x} y2={yFloor}
              stroke="var(--sl-navy)" strokeWidth="0.7"
              strokeDasharray="2 3" opacity="0.55"/>
            {/* Tick on surface */}
            <line x1={x - 4} y1={surfaceY} x2={x + 4} y2={surfaceY}
              stroke="var(--sl-navy)" strokeWidth="1.1"/>
            {/* Sample marker on floor */}
            <circle cx={x} cy={yFloor} r="3" fill="var(--sl-bone)"
              stroke="var(--sl-navy-ink)" strokeWidth="1"/>
            {/* Label box above */}
            <line x1={x} y1={yTop + 14} x2={x} y2={surfaceY}
              stroke="var(--sl-muted)" strokeWidth="0.5" opacity="0.7"/>
            <text x={x} y={yTop} textAnchor="middle"
              fontFamily="var(--sl-mono)" fontSize="10" fontWeight="500"
              letterSpacing="0.18em" fill="var(--sl-navy-ink)">
              {st.id} · {st.label.toUpperCase()}
            </text>
            <text x={x} y={yTop + 12} textAnchor="middle"
              fontFamily="var(--sl-mono)" fontSize="8.5"
              letterSpacing="0.1em" fill="var(--sl-muted)">
              {st.sub}
            </text>
          </g>
        );
      })}

      {/* Title block bottom-left */}
      <g transform={`translate(28 ${H - 36})`}>
        <text fontFamily="var(--sl-mono)" fontSize="9" letterSpacing="0.20em"
          fill="var(--sl-muted)">FIG. 02 · SHORELINE PROFILE</text>
        <text y="14" fontFamily="var(--sl-display)" fontSize="14" fontWeight="500"
          fill="var(--sl-navy-ink)">
          What the model "sees" when it forecasts a beach.
        </text>
      </g>

      {/* Scale marker bottom-right */}
      <g transform={`translate(${W - 160} ${H - 28})`}>
        <line x1="0" y1="0" x2="100" y2="0" stroke="var(--sl-navy-ink)" strokeWidth="1.2"/>
        <line x1="0" y1="-3" x2="0" y2="3" stroke="var(--sl-navy-ink)" strokeWidth="1.2"/>
        <line x1="50" y1="-2" x2="50" y2="2" stroke="var(--sl-navy-ink)" strokeWidth="1"/>
        <line x1="100" y1="-3" x2="100" y2="3" stroke="var(--sl-navy-ink)" strokeWidth="1.2"/>
        <text x="0" y="14" fontFamily="var(--sl-mono)" fontSize="9"
          letterSpacing="0.12em" fill="var(--sl-muted)">
          0 ······ 50M ······ 100M (HORIZONTAL, NOT TO SCALE)
        </text>
      </g>
    </svg>
  );
}

Object.assign(window, { ShorelineCrossSection });
