import React from 'react';
import Link from 'next/link';

// Use standard Tailwind components instead of old RiskComponents
const RISK_ORDER = ['Low', 'Moderate', 'High', 'Very High'];
const RISK_COPY: Record<string, any> = {
  'Low': { head: 'Below standard', sub: 'Lower modeled exceedance risk.', cfu: '< 35' },
  'Moderate': { head: 'Moderate', sub: 'Elevated modeled risk.', cfu: '35–104' },
  'High': { head: 'High risk', sub: 'Avoid water contact and check advisories.', cfu: '104–320' },
  'Very High': { head: 'Closure level', sub: 'Check posted county advisory.', cfu: '> 320' },
};

function RiskChip({ band }: { band: string }) {
  const c = {
    'Low': 'bg-emerald-500/10 text-emerald-600',
    'Moderate': 'bg-amber-500/10 text-amber-600',
    'High': 'bg-rose-500/10 text-rose-600',
    'Very High': 'bg-red-500/20 text-red-700 font-bold',
  }[band] || 'bg-muted text-muted-foreground';
  return (
    <span className={`inline-block font-mono text-[10px] uppercase tracking-widest px-2.5 py-1 rounded-full ${c}`}>
      {band}
    </span>
  );
}

const BAND_DETAIL: Record<string, { threshold: string; action: string; 'regulatory reference': string }> = {
  Low: {
    threshold: 'Predicted exceedance probability < 15 %',
    action: 'Lower modeled exceedance risk, but still check county advisories and posted warnings.',
    'regulatory reference': 'Below EPA STV (104 CFU/100mL) and state action threshold.',
  },
  Moderate: {
    threshold: 'Predicted exceedance probability 15–35 %',
    action: 'Avoid swallowing water; rinse thoroughly after exit.',
    'regulatory reference': 'Elevated but below the single-sample violation threshold.',
  },
  High: {
    threshold: 'Predicted exceedance probability 35–65 %',
    action: 'Avoid water contact and check county advisories, especially for sensitive groups.',
    'regulatory reference': 'Exceeds 104 CFU/100mL with high probability; county may post advisory.',
  },
  'Very High': {
    threshold: 'Predicted exceedance probability > 65 %',
    action: 'Check posted county advisory before entering the water.',
    'regulatory reference': 'Model predicts likely ≥ 320 CFU/100mL; corresponds to CDPH closure threshold.',
  },
};

export default function LabelsPage() {
  return (
    <main className="min-h-screen bg-background pt-32 pb-24">
      <article className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="mb-4">
          <Link href="/research" className="font-mono text-[11px] text-muted-foreground hover:text-foreground transition-colors tracking-widest">
            ← Research
          </Link>
        </div>

        <div className="text-primary text-sm tracking-widest uppercase font-medium mb-4">
          Research · Labels
        </div>
        <h1 className="text-5xl md:text-7xl font-light mb-8 text-foreground text-balance">
          How risk bands<br/>are defined.
        </h1>
        <p className="text-xl text-muted-foreground leading-relaxed max-w-3xl mb-24">
          Each beach is assigned one of four risk bands derived from the model&apos;s calibrated
          exceedance probability — the chance that enterococcus exceeds the EPA single-sample
          threshold of 104 CFU/100mL on a given day.
        </p>

        {/* Threshold logic */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 01</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">Thresholds</div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              From probability to label.
            </h2>
            <div className="grid sm:grid-cols-2 gap-8">
              {[
                ['EPA STV', 'The single-sample threshold for enterococcus in marine waters is 104 CFU/100mL (EPA Recreational Water Quality Criteria, 2012). Exceeding this value does not guarantee illness but indicates elevated risk.'],
                ['Calibrated probability', 'The model outputs a calibrated p_exceed — the estimated probability that the true concentration will exceed 104 CFU/100mL on the forecast day, given environmental covariates.'],
                ['Band cut-points', 'Cut-points (15 %, 35 %, 65 %) are tuned so false negatives (missed High/Very High days) are penalised more heavily than false positives in the loss function, providing a conservative public-health posture.'],
                ['County advisories', 'Shorelife bands are forecasts; official CDPH/county advisories are posted after a confirmed sample violation. A Very High forecast does not replace a posted advisory.'],
              ].map(([h, b]) => (
                <div key={h} className="pt-6 border-t border-border/50">
                  <h3 className="text-lg font-medium mb-3 text-foreground">{h}</h3>
                  <p className="text-sm text-muted-foreground leading-relaxed">{b}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Band definitions */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50 mb-24">
          <aside>
            <div className="text-primary font-medium tracking-widest text-sm uppercase mb-2">§ 02</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">Band Definitions</div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              Four levels, calibrated for public health.
            </h2>
            <div className="bg-muted/30 border border-border/50 rounded-2xl overflow-hidden overflow-x-auto">
              <div className="grid grid-cols-[140px_1fr_1.5fr_1.5fr] p-4 border-b border-border/50 font-mono text-[10px] uppercase tracking-widest text-muted-foreground font-semibold min-w-[700px]">
                <span>Band</span><span>Guidance</span><span>Probability gate</span><span>Action</span>
              </div>
              {RISK_ORDER.map((band, i, arr) => {
                const c = RISK_COPY[band];
                const d = BAND_DETAIL[band];
                return (
                  <div key={band} className={`grid grid-cols-[140px_1fr_1.5fr_1.5fr] gap-4 p-5 items-start min-w-[700px] ${i < arr.length - 1 ? 'border-b border-border/50' : ''}`}>
                    <div>
                      <RiskChip band={band} />
                    </div>
                    <div>
                      <div className="text-lg font-light text-foreground mb-1">{c.head}</div>
                      <div className="text-sm text-muted-foreground leading-relaxed">{c.sub}</div>
                      <div className="font-mono text-[10px] text-muted-foreground mt-2 uppercase tracking-widest">{c.cfu} CFU/100mL</div>
                    </div>
                    <div className="font-mono text-xs text-foreground leading-relaxed">{d.threshold}</div>
                    <div className="text-sm text-muted-foreground leading-relaxed">{d.action}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Legal / statutory note */}
        <div className="grid md:grid-cols-[200px_1fr] gap-12 pt-12 border-t border-border/50">
          <aside>
            <div className="text-red-500 font-medium tracking-widest text-sm uppercase mb-2">§ 03</div>
            <div className="text-xs text-muted-foreground tracking-wider uppercase">Legal Basis</div>
          </aside>
          <div>
            <h2 className="text-3xl font-light mb-8 text-foreground">
              What the model can and cannot do.
            </h2>
            <ul className="space-y-6">
              {[
                'Shorelife forecasts are probabilistic estimates, not certified sample results.',
                'Official beach closures and advisories are issued by county environmental health agencies under California AB 411.',
                'A Low band forecast does not guarantee safe water. Localised events (sewage spills, storm runoff) can override model predictions.',
                'The model is trained exclusively on marine enterococcus (culture-based, MPN/IDEXX). Freshwater E. coli and other analytes are outside its scope.',
                'For confirmed regulatory status, always consult the current county health advisory for the specific beach.',
              ].map((li, i) => (
                <li key={i} className="flex gap-4 pt-6 border-t border-dashed border-border/50 text-base text-muted-foreground leading-relaxed">
                  <span className="text-xs font-mono text-muted-foreground pt-1">0{i + 1}</span>
                  <span>{li}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

      </article>
    </main>
  );
}
