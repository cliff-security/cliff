// Surface 6 — Shareable summary card (1200×630 social share PNG)

function ShareCardPage() {
  return (
    <div className="bg-surface-container-low flex items-center justify-center p-6" style={{minHeight: 760}}>
      <div className="share-card relative overflow-hidden text-on-primary" style={{width: 1200, height: 630, transform: 'scale(0.55)', transformOrigin: 'center'}}>
        {/* Decorative concentric arcs */}
        <svg className="absolute -right-32 -top-32 opacity-15" width="600" height="600" viewBox="0 0 600 600" aria-hidden>
          <circle cx="300" cy="300" r="120" fill="none" stroke="white" strokeWidth="1.5" />
          <circle cx="300" cy="300" r="200" fill="none" stroke="white" strokeWidth="1.5" />
          <circle cx="300" cy="300" r="280" fill="none" stroke="white" strokeWidth="1.5" />
        </svg>

        <div className="relative h-full flex flex-col p-16">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-2xl bg-on-primary/15 flex items-center justify-center backdrop-blur">
                <span className="font-headline text-2xl font-extrabold text-on-primary">O</span>
              </div>
              <span className="font-headline text-[22px] font-bold tracking-tight text-on-primary">Cliff</span>
            </div>
            <span className="text-[13px] font-semibold uppercase tracking-[0.2em] text-on-primary/70">Secured</span>
          </div>

          {/* Hero */}
          <div className="flex-1 flex items-center gap-12 mt-4">
            {/* Big A */}
            <div className="relative flex-shrink-0">
              <div className="w-48 h-48 rounded-full" style={{background: 'conic-gradient(#ffffff 100%, transparent 0)'}} />
              <div className="absolute inset-3 rounded-full flex flex-col items-center justify-center" style={{background: '#3f33d6'}}>
                <span className="font-headline text-[112px] font-extrabold text-on-primary leading-none">A</span>
                <span className="text-[12px] font-bold uppercase tracking-[0.2em] text-on-primary/75 mt-1">Grade</span>
              </div>
            </div>
            <div className="flex-1">
              <p className="text-[18px] font-semibold uppercase tracking-[0.2em] text-on-primary/70">galanko / cliff-demo</p>
              <h1 className="mt-3 font-headline text-[68px] font-extrabold leading-[0.95] tracking-tight">10 criteria met.</h1>
              <p className="mt-4 font-headline text-[28px] font-bold text-on-primary/80 leading-snug">Vulnerabilities resolved. Posture hardened. CI pinned.</p>
            </div>
          </div>

          {/* Footer — scanned-by + wordmark */}
          <div className="flex items-end justify-between mt-4">
            <div>
              <p className="text-[14px] font-medium text-on-primary/60">
                Scanned by: Trivy 0.52 · Semgrep 1.70 · 15 posture checks
              </p>
              <p className="mt-2 text-[16px] font-semibold text-on-primary/80">cliff.dev / galanko / cliff-demo</p>
            </div>
            <div className="text-right">
              <p className="text-[12px] font-semibold uppercase tracking-[0.2em] text-on-primary/60">Apr 25, 2026</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ShareCardPage });
