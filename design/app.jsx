// App orchestrator — four pages in a single scrollable doc, page chips at top, Tweaks for risk band

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "heroBand": "Low",
  "showAllPages": true,
  "page": "home"
}/*EDITMODE-END*/;

function App() {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const homeRef = React.useRef(null);
  const shareRef = React.useRef(null);
  const methodRef = React.useRef(null);
  const researchRef = React.useRef(null);

  const scrollTo = (ref) => {
    if (ref.current) {
      window.scrollTo({ top: ref.current.offsetTop - 56, behavior: 'smooth' });
    }
  };

  const pages = [
    { key: 'home',     label: 'Home / Forecast', ref: homeRef,     tag: '01' },
    { key: 'share',    label: 'Beach · Share',   ref: shareRef,    tag: '02' },
    { key: 'method',   label: 'Methodology',     ref: methodRef,   tag: '03' },
    { key: 'research', label: 'Research / Ops',  ref: researchRef, tag: '04' },
  ];

  return (
    <>
      {/* Page navigator */}
      <div className="nav-bar">
        <span className="nav-tag">Shorelife · web redesign · v1.0</span>
        <span className="nav-spacer"/>
        {pages.map(p => (
          <button key={p.key} onClick={() => scrollTo(p.ref)}>
            {p.tag} · {p.label}
          </button>
        ))}
      </div>

      <div ref={homeRef} className="page-frame">
        <span className="page-tag">01 · Home</span>
        <HomePage heroBand={tweaks.heroBand}/>
      </div>

      <div ref={shareRef} className="page-frame">
        <span className="page-tag">02 · Beach · Share link</span>
        <SharePage/>
      </div>

      <div ref={methodRef} className="page-frame">
        <span className="page-tag">03 · Methodology</span>
        <MethodologyPage/>
      </div>

      <div ref={researchRef} className="page-frame">
        <span className="page-tag">04 · Research / Operator</span>
        <ResearchPage/>
      </div>

      {/* Tweaks */}
      <TweaksPanel title="Tweaks">
        <TweakSection title="Hero risk band">
          <TweakRadio
            label="Live state"
            value={tweaks.heroBand}
            onChange={(v) => setTweak('heroBand', v)}
            options={[
              { value: 'Low',       label: 'Low' },
              { value: 'Moderate',  label: 'Mod' },
              { value: 'High',      label: 'High' },
              { value: 'Very High', label: 'V.High' },
            ]}/>
          <p style={{ fontSize: 11, color: 'var(--sl-muted)', margin: '8px 0 0', lineHeight: 1.5 }}>
            Toggles the home hero answer card + cross-section illustration through all four risk states.
          </p>
        </TweakSection>
      </TweaksPanel>
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App/>);
