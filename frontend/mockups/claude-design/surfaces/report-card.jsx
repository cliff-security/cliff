// Surface 1 — Report card with grouped posture (2 variations)
// Variation A: single tall card, 4 stacked groups (matches brief default)
// Variation B: 2×2 grid of category cards (more scannable)

// ─── Posture row primitives ───
function PostureRowPass({ label }) {
  return (
    <li className="flex items-center gap-2.5 py-1.5">
      <span className="material-symbols-outlined msym-filled text-tertiary" style={{fontSize: 18}} aria-hidden>check_circle</span>
      <span className="text-sm font-medium text-on-surface">{label}</span>
    </li>
  );
}

function PostureRowAdvisory({ label }) {
  return (
    <li className="flex items-center gap-2.5 py-1.5">
      <span className="material-symbols-outlined text-on-surface-variant" style={{fontSize: 18}} aria-hidden>info</span>
      <span className="text-sm text-on-surface-variant flex-1">{label}</span>
      <span className="text-[10px] font-medium text-on-surface-variant bg-surface-container-high rounded-full px-2 py-0.5">advisory</span>
    </li>
  );
}

function PostureRowFail({ title, body, cta, ctaIcon = 'auto_fix_high' }) {
  return (
    <li className="flex flex-col gap-3 rounded-2xl bg-primary-container/30 p-4">
      <div className="flex items-start gap-2.5">
        <span className="material-symbols-outlined msym-filled text-error flex-shrink-0" style={{fontSize: 18, marginTop: 1}} aria-hidden>cancel</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-on-surface">{title}</p>
          <p className="mt-1 text-[13px] leading-relaxed text-on-surface-variant">{body}</p>
        </div>
      </div>
      {cta && (
        <div className="ml-7">
          <PillButton icon={ctaIcon} size="sm">{cta}</PillButton>
        </div>
      )}
    </li>
  );
}

function PostureRowDone({ label, prHref = '#' }) {
  return (
    <li className="flex items-center gap-2.5 py-1.5">
      <span className="material-symbols-outlined msym-filled text-tertiary" style={{fontSize: 18}} aria-hidden>check_circle</span>
      <span className="text-sm font-medium text-on-surface flex-1">{label}</span>
      <a href={prHref} className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline">
        Draft PR
        <span className="material-symbols-outlined" style={{fontSize: 13}} aria-hidden>open_in_new</span>
      </a>
    </li>
  );
}

// ─── Category header with progress rail ───
function CategoryHeader({ title, done, total }) {
  const pct = (done / total) * 100;
  return (
    <div className="mb-2.5 flex items-baseline justify-between gap-3">
      <h4 className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">{title}</h4>
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-on-surface-variant tabular-nums">{done} of {total}</span>
        <div className="h-1.5 w-20 rounded-full bg-surface-container-high overflow-hidden">
          <div className="h-full rounded-full bg-primary" style={{width: pct + '%'}} />
        </div>
      </div>
    </div>
  );
}

// ─── Hero (editorial split: ring + narrative + scanner chips as third row) ───
function ReportCardHero() {
  return (
    <section className="rounded-3xl bg-surface-container-lowest p-7">
      <div className="flex flex-col items-start gap-7 md:flex-row md:items-center">
        <GradeRing grade="B" percent={80} size={120} sub="8 of 10" />
        <div className="flex-1">
          <p className="text-[11px] font-bold uppercase tracking-wider text-primary">Security grade</p>
          <h2 className="mt-1.5 font-headline text-[28px] font-extrabold text-on-surface leading-[1.1] tracking-tight">Nearly there.</h2>
          <p className="mt-2 text-[15px] text-on-surface-variant max-w-md leading-relaxed">
            Two checks left to reach Grade A. Both are fixable by an Cliff agent.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1.5 text-right">
          <span className="text-[10px] font-bold uppercase tracking-wider text-on-surface-variant">Last assessed</span>
          <span className="text-sm font-semibold text-on-surface">2 minutes ago</span>
          <button className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-surface-container-high px-3 py-1.5 text-[11px] font-semibold text-on-surface-variant hover:bg-surface-container-highest transition-colors">
            <span className="material-symbols-outlined" style={{fontSize: 13}} aria-hidden>refresh</span>
            Re-assess
          </button>
        </div>
      </div>
      {/* Scanner chip row — branded trust signal */}
      <div className="mt-6 pt-5 flex items-center justify-between gap-4 flex-wrap" style={{boxShadow: 'inset 0 1px 0 rgba(43,52,55,0.06)'}}>
        <div className="flex items-center gap-2.5">
          <span className="material-symbols-outlined text-on-surface-variant" style={{fontSize: 16}} aria-hidden>verified</span>
          <span className="text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant">Scanned by</span>
        </div>
        <ToolPillBar size="sm" tools={[
          { label: 'Trivy 0.52', icon: 'bug_report', state: 'done', result: '7 findings' },
          { label: 'Semgrep 1.70', icon: 'code', state: 'done', result: '3 findings' },
          { label: '15 posture checks', icon: 'rule', state: 'done', result: '12 pass' },
        ]} />
      </div>
    </section>
  );
}

// ─── Vulnerabilities card ───
function VulnsCard() {
  return (
    <section className="flex flex-col gap-4 rounded-3xl bg-surface-container-lowest p-6">
      <header>
        <h3 className="font-headline text-[17px] font-bold text-on-surface">Vulnerabilities</h3>
        <p className="text-sm text-on-surface-variant mt-0.5">10 findings waiting to be solved</p>
      </header>
      <div className="grid grid-cols-4 gap-2.5">
        {[
          {k:'Critical', v: 0, color: 'text-on-surface-variant'},
          {k:'High',     v: 2, color: 'text-error'},
          {k:'Medium',   v: 5, color: 'text-tertiary'},
          {k:'Low',      v: 3, color: 'text-on-surface-variant'},
        ].map(s => (
          <div key={s.k} className="rounded-2xl bg-surface-container-low p-3">
            <p className={cx('font-headline text-[26px] font-extrabold leading-none tabular-nums', s.color)}>{s.v}</p>
            <p className="mt-1.5 text-[11px] font-medium text-on-surface-variant">{s.k}</p>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 text-[11px] text-on-surface-variant">
        <span className="material-symbols-outlined" style={{fontSize: 13}} aria-hidden>code</span>
        <span>3 are code issues from Semgrep · may need manual review</span>
      </div>
      <PillButton icon="play_arrow">Start fixing</PillButton>
    </section>
  );
}

// ─── Completion progress card (10 criteria, matches Surface 5) ───
function CompletionCard() {
  return (
    <section className="rounded-3xl bg-surface-container-lowest p-6 flex flex-col gap-4">
      <header className="flex items-baseline justify-between">
        <h3 className="font-headline text-[17px] font-bold text-on-surface">Completion progress</h3>
        <span className="font-headline text-sm font-bold text-primary tabular-nums">8/10</span>
      </header>
      {/* Bar with 10 ticks */}
      <div className="relative h-2.5">
        <div className="absolute inset-0 rounded-full bg-surface-container-high overflow-hidden">
          <div className="h-full rounded-full bg-primary transition-all" style={{width: '80%'}} />
        </div>
        <div className="absolute inset-0 flex justify-between px-[1px]">
          {Array.from({length: 11}).map((_, i) => (
            <span key={i} className="w-px h-full bg-surface-container-lowest/60" />
          ))}
        </div>
      </div>
      <p className="text-[13px] text-on-surface-variant">
        2 criteria remaining: <span className="text-on-surface font-medium">pin CI actions to SHA</span>, <span className="text-on-surface font-medium">add code owners</span>.
      </p>
    </section>
  );
}

// ─── VARIATION A — single tall card with stacked groups ───
function PostureCardStacked() {
  return (
    <section className="flex flex-col gap-6 rounded-3xl bg-surface-container-lowest p-6" aria-label="Repository posture checks">
      <header className="flex items-baseline justify-between">
        <div>
          <h3 className="font-headline text-[17px] font-bold text-on-surface">Repo posture</h3>
          <p className="text-sm text-on-surface-variant mt-0.5">12 of 15 checks pass · 3 advisory</p>
        </div>
      </header>

      {/* CI supply chain */}
      <div>
        <CategoryHeader title="CI supply chain" done={1} total={2} />
        <ul role="list" className="flex flex-col gap-1">
          <PostureRowPass label="Trusted action sources" />
          <PostureRowFail
            title="Actions not pinned to SHA"
            body="3 actions reference mutable tags (e.g. actions/checkout@v4). Pinning to a commit SHA prevents a compromised maintainer from pushing malicious code under the same tag."
            cta="Pin actions to SHA"
            ctaIcon="auto_fix_high"
          />
          <PostureRowAdvisory label="Workflow trigger scope" />
        </ul>
      </div>

      {/* Collaborator hygiene */}
      <div>
        <CategoryHeader title="Collaborator hygiene" done={2} total={2} />
        <ul role="list" className="flex flex-col gap-1">
          <PostureRowPass label="No stale collaborators" />
          <PostureRowAdvisory label="Broad team permissions" />
          <PostureRowPass label="Default branch permissions" />
        </ul>
      </div>

      {/* Code integrity */}
      <div>
        <CategoryHeader title="Code integrity" done={3} total={4} />
        <ul role="list" className="flex flex-col gap-1">
          <PostureRowPass label="Secret scanning enabled" />
          <PostureRowFail
            title="Code owners file missing"
            body="No CODEOWNERS file found. We can generate one based on your git blame history — you review and merge."
            cta="Generate code owners"
          />
          <PostureRowAdvisory label="Signed commits" />
          <PostureRowDone label="Dependabot configured" />
          <PostureRowPass label="No committed secrets" />
        </ul>
      </div>

      {/* Repo configuration */}
      <div>
        <CategoryHeader title="Repo configuration" done={4} total={4} />
        <ul role="list" className="flex flex-col gap-1">
          <PostureRowPass label="Branch protection enabled" />
          <PostureRowDone label="SECURITY.md exists" />
          <PostureRowPass label="No secrets in code (regex)" />
          <PostureRowPass label="Lockfile integrity" />
        </ul>
      </div>
    </section>
  );
}

// ─── VARIATION B — 2×2 grid of category cards ───
function PostureCardGrid() {
  return (
    <section className="flex flex-col gap-4" aria-label="Repository posture checks">
      <header className="flex items-baseline justify-between px-1">
        <div>
          <h3 className="font-headline text-[17px] font-bold text-on-surface">Repo posture</h3>
          <p className="text-sm text-on-surface-variant mt-0.5">12 of 15 checks pass · 3 advisory</p>
        </div>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* CI supply chain */}
        <div className="rounded-3xl bg-surface-container-lowest p-5 flex flex-col gap-3">
          <CategoryHeader title="CI supply chain" done={1} total={2} />
          <ul role="list" className="flex flex-col gap-1">
            <PostureRowPass label="Trusted action sources" />
            <PostureRowFail
              title="Actions not pinned to SHA"
              body="3 actions reference mutable tags. Pin to commit SHAs."
              cta="Pin actions to SHA"
              ctaIcon="auto_fix_high"
            />
            <PostureRowAdvisory label="Workflow trigger scope" />
          </ul>
        </div>

        {/* Collaborator hygiene */}
        <div className="rounded-3xl bg-surface-container-lowest p-5 flex flex-col gap-3">
          <CategoryHeader title="Collaborator hygiene" done={2} total={2} />
          <ul role="list" className="flex flex-col gap-1">
            <PostureRowPass label="No stale collaborators" />
            <PostureRowAdvisory label="Broad team permissions" />
            <PostureRowPass label="Default branch permissions" />
          </ul>
        </div>

        {/* Code integrity */}
        <div className="rounded-3xl bg-surface-container-lowest p-5 flex flex-col gap-3">
          <CategoryHeader title="Code integrity" done={3} total={4} />
          <ul role="list" className="flex flex-col gap-1">
            <PostureRowPass label="Secret scanning enabled" />
            <PostureRowFail
              title="Code owners file missing"
              body="No CODEOWNERS file found. We can draft one from git blame."
              cta="Generate code owners"
            />
            <PostureRowAdvisory label="Signed commits" />
            <PostureRowDone label="Dependabot configured" />
            <PostureRowPass label="No committed secrets" />
          </ul>
        </div>

        {/* Repo configuration */}
        <div className="rounded-3xl bg-surface-container-lowest p-5 flex flex-col gap-3">
          <CategoryHeader title="Repo configuration" done={4} total={4} />
          <ul role="list" className="flex flex-col gap-1">
            <PostureRowPass label="Branch protection enabled" />
            <PostureRowDone label="SECURITY.md exists" />
            <PostureRowPass label="No secrets in code (regex)" />
            <PostureRowPass label="Lockfile integrity" />
          </ul>
        </div>
      </div>
    </section>
  );
}

// ─── Page wrapper ───
function ReportCardPage({ variation = 'A' }) {
  return (
    <div className="bg-surface flex" style={{minHeight: 1100}}>
      <SideNav active="dashboard" />
      <main className="flex-1 px-8 py-7 overflow-hidden">
        <div className="flex items-baseline justify-between mb-6">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-on-surface-variant">Repository</p>
            <h1 className="font-headline text-[32px] font-extrabold text-on-surface tracking-tight leading-tight">galanko / cliff-demo</h1>
          </div>
        </div>

        <div className="flex flex-col gap-5">
          <ReportCardHero />
          <CompletionCard />
          <div className="grid grid-cols-1 lg:grid-cols-[380px_1fr] gap-5">
            <VulnsCard />
            {variation === 'A' ? <PostureCardStacked /> : <PostureCardGrid />}
          </div>
        </div>
      </main>
    </div>
  );
}

Object.assign(window, { ReportCardPage, PostureRowPass, PostureRowAdvisory, PostureRowFail, PostureRowDone, CategoryHeader });
