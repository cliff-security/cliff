// Shared chrome + atoms for PRD-0003 surfaces.
// All surfaces sit inside the Cliff app shell: fixed left rail + main content area.

const cx = (...xs) => xs.filter(Boolean).join(' ');

// ─── Side nav (PRD-0004 inherited pattern, w-20, no top bar) ───
function SideNav({ active = 'dashboard' }) {
  const items = [
    { id: 'dashboard', icon: 'dashboard', label: 'Dashboard' },
    { id: 'findings', icon: 'bug_report', label: 'Findings' },
    { id: 'history', icon: 'history', label: 'History' },
    { id: 'integrations', icon: 'extension', label: 'Integrations' },
  ];
  return (
    <nav className="w-20 bg-surface-container-low flex flex-col items-center py-6 gap-5 flex-shrink-0">
      <div className="w-10 h-10 rounded-xl bg-surface-container-lowest flex items-center justify-center shadow-sm mb-1">
        <span className="font-headline text-lg font-extrabold text-primary">O</span>
      </div>
      {items.map(it => {
        const isActive = it.id === active;
        return (
          <div key={it.id} className="flex flex-col items-center gap-1">
            <div className={cx(
              'w-10 h-10 rounded-xl flex items-center justify-center transition-colors',
              isActive ? 'bg-primary-container/55' : 'hover:bg-surface-container-high'
            )}>
              <span className={cx('material-symbols-outlined', isActive ? 'text-primary' : 'text-on-surface-variant')} style={{fontSize:20}} aria-hidden>{it.icon}</span>
            </div>
            <span className={cx('text-[10px]', isActive ? 'font-semibold text-primary' : 'text-on-surface-variant')}>{it.label}</span>
          </div>
        );
      })}
      <div className="flex-1" />
      <div className="flex flex-col items-center gap-1">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center hover:bg-surface-container-high transition-colors">
          <span className="material-symbols-outlined text-on-surface-variant" style={{fontSize:20}} aria-hidden>settings</span>
        </div>
        <span className="text-[10px] text-on-surface-variant">Settings</span>
      </div>
    </nav>
  );
}

// ─── Tool pill row — the brand trust signal ───
// states: 'pending' | 'active' | 'done' | 'skipped'
function ToolPillBar({ tools, size = 'md' }) {
  const padding = size === 'sm' ? 'px-2.5 py-1 text-[11px]' : 'px-3 py-1.5 text-xs';
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {tools.map((t, i) => {
        const base = 'inline-flex items-center gap-1.5 rounded-full font-semibold transition-colors';
        let cls = '';
        let icon = t.icon;
        if (t.state === 'active')  cls = 'bg-primary-container text-on-primary-container animate-pulse-subtle';
        else if (t.state === 'done') { cls = 'bg-tertiary-container/60 text-on-tertiary-container'; icon = 'check_circle'; }
        else if (t.state === 'skipped') cls = 'bg-surface-container-high text-on-surface-variant/70 line-through';
        else cls = 'bg-surface-container-high text-on-surface-variant';

        return (
          <span key={i} className={cx(base, cls, padding)}>
            <span className={cx('material-symbols-outlined', t.state === 'done' ? 'msym-filled' : '')} style={{fontSize: size === 'sm' ? 13 : 14}} aria-hidden>{icon}</span>
            <span>{t.label}</span>
            {t.result && <span className="ml-1 font-medium opacity-70">· {t.result}</span>}
          </span>
        );
      })}
    </div>
  );
}

// ─── Pill button (primary CTA) ───
function PillButton({ children, icon, variant = 'primary', size = 'md' }) {
  const sz = size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm';
  const v = variant === 'primary'
    ? 'bg-primary text-on-primary hover:bg-primary-dim shadow-sm'
    : variant === 'ghost'
      ? 'bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest'
      : 'bg-surface-container text-on-surface hover:bg-surface-container-high';
  return (
    <button className={cx('inline-flex items-center gap-1.5 rounded-full font-semibold active:scale-[0.97] transition-all', sz, v)}>
      {icon && <span className="material-symbols-outlined" style={{fontSize: 16}} aria-hidden>{icon}</span>}
      <span>{children}</span>
    </button>
  );
}

// ─── Severity chip ───
function SeverityChip({ kind, count }) {
  const palette = {
    critical: 'bg-error-container/40 text-on-error-container',
    high:     'bg-error-container/25 text-on-error-container',
    medium:   'bg-tertiary-container/45 text-on-tertiary-container',
    low:      'bg-surface-container-high text-on-surface-variant',
    code:     'bg-primary-container/45 text-on-primary-container',
  };
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold', palette[kind] || palette.low)}>
      <span className="font-bold tabular-nums">{count}</span>
      <span className="capitalize opacity-80">{kind}</span>
    </span>
  );
}

// ─── Browser frame chrome ───
function BrowserChrome({ url }) {
  return (
    <div className="flex items-center gap-2 px-3.5 py-2.5 bg-surface-container">
      <span className="w-2.5 h-2.5 rounded-full bg-[#f57a7a]" />
      <span className="w-2.5 h-2.5 rounded-full bg-[#f5c767]" />
      <span className="w-2.5 h-2.5 rounded-full bg-[#7ecb7a]" />
      <span className="ml-3 text-[11px] text-on-surface-variant font-mono">{url}</span>
    </div>
  );
}

// ─── Mini grade ring (used in summaries) ───
function GradeRing({ grade, percent, size = 96, sub }) {
  return (
    <div className="relative flex-shrink-0" style={{width: size, height: size}}>
      <div className="absolute inset-0 rounded-full grade-ring" style={{['--p']: percent + '%'}} />
      <div className="absolute rounded-full bg-surface-container-lowest flex flex-col items-center justify-center" style={{inset: size*0.08}}>
        <span className="font-headline font-extrabold text-primary leading-none" style={{fontSize: size*0.42}}>{grade}</span>
        {sub && <span className="text-[10px] font-semibold text-on-surface-variant mt-0.5">{sub}</span>}
      </div>
    </div>
  );
}

Object.assign(window, { cx, SideNav, ToolPillBar, PillButton, SeverityChip, BrowserChrome, GradeRing });
