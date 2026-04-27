import React from 'react';

export function Skeleton({ 
  className = "", 
  style = {} 
}: { 
  className?: string, 
  style?: React.CSSProperties 
}) {
  return (
    <div 
      className={`animate-pulse ${className}`} 
      style={{
        backgroundColor: 'var(--sl-line-soft)',
        borderRadius: 8,
        ...style
      }} 
    />
  );
}

export function SkeletonCard() {
  return (
    <div style={{ padding: 24, background: 'var(--sl-bone)', borderRadius: 18, border: '1px solid var(--sl-line)' }}>
      <Skeleton style={{ width: '40%', height: 14, marginBottom: 12 }} />
      <Skeleton style={{ width: '80%', height: 32, marginBottom: 20 }} />
      <Skeleton style={{ width: '100%', height: 64, marginBottom: 24 }} />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
        <Skeleton style={{ height: 40 }} />
        <Skeleton style={{ height: 40 }} />
        <Skeleton style={{ height: 40 }} />
      </div>
    </div>
  );
}
