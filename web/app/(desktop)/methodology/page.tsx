export default function MethodologyPage() {
  return (
    <main className="page-shell">
      <section className="hero compact-hero">
        <div className="hero-copy">
          <p className="eyebrow">Methodology</p>
          <h1>How the forecast is built</h1>
          <p className="hero-lede">
            Surf Health models marine enterococcus risk using official California sample history and
            daily environmental context from nearshore ocean and weather sources.
          </p>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Model design</p>
            <h2>Numerically grounded by default</h2>
          </div>
        </div>
        <div className="value-grid">
          <article>
            <h3>Label policy</h3>
            <p>
              V1 uses culture-based marine enterococcus only. Freshwater E. coli, total coliform,
              fecal coliform, and ddPCR stay in the warehouse but outside the pooled forecast label.
            </p>
          </article>
          <article>
            <h3>Daily forecast</h3>
            <p>
              We train only on observed sample days, then infer unsampled days from sliding-window
              history instead of pseudo-labeling the gaps.
            </p>
          </article>
          <article>
            <h3>Baselines first</h3>
            <p>
              Persistence, logistic/linear, and gradient-boosted tree baselines are mandatory. The
              neural model stays research-only until it clears blocked-time and explicit spatial
              holdout gates.
            </p>
          </article>
          <article>
            <h3>Calibration</h3>
            <p>
              Public-facing bands come from calibrated exceedance probabilities with a stronger
              penalty on false negatives than false positives.
            </p>
          </article>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Limits</p>
            <h2>Important caveats</h2>
          </div>
        </div>
        <ul className="driver-list">
          <li>Forecasts complement official monitoring; they do not replace county advisories.</li>
          <li>Sparse sites may remain in beta mode with wider prediction intervals.</li>
          <li>Heavy storm, sewage, or spill events can outrun any historical statistical model.</li>
          <li>Ollama explanations summarize the forecast; the numeric risk comes from the ML model.</li>
        </ul>
      </section>
    </main>
  );
}
