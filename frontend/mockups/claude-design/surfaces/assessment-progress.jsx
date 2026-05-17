// Surface 2 — Assessment progress with scanner-specific stages

function ProgressStepDone({ label, result }) {
  return (
    <li className="flex items-center gap-3 py-1.5">
      <span className="material-symbols-outlined msym-filled text-tertiary" style={{fontSize: 18}} aria-hidden>check_circle</span>
      <span className="text-sm font-medium text-on-surface">{label}</span>
      {result && <span className="ml-auto text-[10px] font-medium text-on-surface-variant bg-surface-container rounded-full px-2 py-0.5">{result}</span>}
    </li>
  );
}

function ProgressStepRunning({ label, percent, detail }) {
  return (
    <li className="flex flex-col gap-2 rounded-2xl bg-primary-container/30 p-4">
      <div className="flex items-center gap-3">
        <span className="spinner" aria-hidden />
        <span className="text-sm font-semibold text-on-surface">{label}</span>
        <span className="ml-auto text-xs font-bold text-primary tabular-nums">{percent}%</span>
      </div>
      <div className="ml-7 h-1.5 rounded-full bg-surface-container-high overflow-hidden">
        <div className="h-full rounded-full bg-primary transition-all" style={{width: percent + '%'}} />
      </div>
      <p className="ml-7 text-xs text-on-surface-variant">{detail}</p>
    </li>
  );
}

function ProgressStepPending({ label, hint }) {
  return (
    <li className="flex items-center gap-3 py-1.5 pl-[3px]">
      <span className="material-symbols-outlined text-outline-variant" style={{fontSize: 16}} aria-hidden>radio_button_unchecked</span>
      <span className="text-sm text-on-surface-variant/75">{label}</span>
      {hint && <span className="ml-auto text-[10px] text-on-surface-variant/55">{hint}</span>}
    </li>
  );
}

function AssessmentProgressPage() {
  return (
    <div className="bg-surface flex" style={{minHeight: 880}}>
      <SideNav active="dashboard" />
      <main className="flex-1 px-8 py-7">
        <div className="mb-6">
          <p className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Repository</p>
          <h1 className="font-headline text-[32px] font-extrabold text-on-surface tracking-tight leading-tight">galanko / cliff-demo</h1>
        </div>

        {/* Live assessment card */}
        <section className="rounded-3xl bg-surface-container-lowest p-8 mb-5" aria-label="Assessment in progress" role="status" aria-live="polite">
          <div className="flex items-start gap-5 mb-6">
            <div className="grid h-14 w-14 place-items-center rounded-2xl bg-primary-container flex-shrink-0">
              <span className="spinner spinner-lg" aria-hidden />
            </div>
            <div className="flex-1">
              <h2 className="font-headline text-2xl font-extrabold text-on-surface tracking-tight">Assessing your repository</h2>
              <p className="mt-1 text-sm text-on-surface-variant">Usually 2–5 minutes. You can leave this page — progress is saved.</p>
            </div>
            <div className="text-right">
              <p className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Elapsed</p>
              <p className="font-headline text-lg font-bold text-on-surface tabular-nums">01:24</p>
            </div>
          </div>

          {/* Tool pill bar */}
          <div className="flex items-center justify-between gap-4 flex-wrap mb-7 pt-5" style={{boxShadow: 'inset 0 1px 0 rgba(43,52,55,0.06)'}}>
            <span className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">Powered by</span>
            <ToolPillBar tools={[
              { label: 'Trivy 0.52', icon: 'bug_report', state: 'active' },
              { label: 'Semgrep 1.70', icon: 'code', state: 'pending' },
              { label: '15 posture checks', icon: 'rule', state: 'pending' },
            ]} />
          </div>

          {/* Steps */}
          <ul role="list" className="flex flex-col gap-1.5">
            <ProgressStepDone label="Detecting project type" result="npm + Python" />
            <ProgressStepRunning
              label="Scanning dependencies with Trivy"
              percent={42}
              detail="Checking 312 dependencies across npm and pip ecosystems…"
            />
            <ProgressStepPending label="Checking for committed secrets" />
            <ProgressStepPending label="Scanning code with Semgrep" />
            <ProgressStepPending label="Checking repo posture" hint="15 checks" />
            <ProgressStepPending label="Writing plain-language descriptions" />
          </ul>
        </section>

        {/* Previous assessment — kept visible so Alex doesn't feel data vanished */}
        <section className="rounded-3xl bg-surface-container-low p-5 flex items-center gap-4 opacity-80">
          <span className="material-symbols-outlined text-on-surface-variant" style={{fontSize: 20}} aria-hidden>history</span>
          <div className="flex-1">
            <p className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Previous assessment</p>
            <p className="text-sm font-semibold text-on-surface">Grade B · 8 of 10 criteria · 3 days ago</p>
          </div>
          <a href="#" className="text-[11px] font-semibold text-primary hover:underline">View report</a>
        </section>
      </main>
    </div>
  );
}

Object.assign(window, { AssessmentProgressPage });
