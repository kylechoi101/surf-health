import React, { useId } from 'react';

export function ShorelifeMark({
  size = 40,
  ocean = 'var(--sl-navy)',
  sand = 'var(--sl-sun)',
  coast = 'var(--sl-bone)',
  showFrame = false,
}: {
  size?: number;
  ocean?: string;
  sand?: string;
  coast?: string;
  showFrame?: boolean;
}) {
  const uid = useId();
  const cId = `sl-coast-${uid}`;
  const rId = `sl-ring-${uid}`;
  const SCURVE = 'M 50 4 C 12 18 12 38 50 50 C 88 62 88 82 50 96';

  const OCEAN = `M 0 0 L 50 0
                 C 12 18 12 38 50 50
                 C 88 62 88 82 50 96
                 L 50 100 L 0 100 Z`;
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

      <g clipPath={`url(#${rId})`}>
        <path d={OCEAN} fill={ocean}/>
        <path d={SAND}  fill={sand}/>
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

export function ShorelifeWordmark({ size = 30, ink = 'var(--sl-navy)' }: { size?: number, ink?: string }) {
  return (
    <span style={{ fontFamily: 'var(--font-heading)', fontSize: size, fontWeight: 500,
      color: ink, letterSpacing: '-0.025em', lineHeight: 0.9 }}>
      shorelife
    </span>
  );
}

export function LockupHorizontal({ size = 32, ink = 'var(--sl-navy)', subtitle }: { size?: number, ink?: string, subtitle?: string }) {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: size * 0.55 }}>
      <ShorelifeMark size={size * 1.15} ocean={ink}/>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <ShorelifeWordmark size={size} ink={ink}/>
        {subtitle && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fontWeight: 500,
            letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--sl-muted)' }}>
            {subtitle}
          </span>
        )}
      </div>
    </div>
  );
}
