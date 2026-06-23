import type { ReactNode } from "react";
import { IconCheck } from "./Icons";

type Status = "pass" | "fail" | "warn" | "skip";

const LABEL: Record<Status, string> = {
  pass: "Pass",
  fail: "Fail",
  warn: "Warn",
  skip: "Skip",
};

export function StatusBadge({ status }: { status: Status }) {
  return <span className={`status-badge status-badge--${status}`}>{LABEL[status]}</span>;
}

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "success" | "danger" | "accent";
}) {
  return (
    <div className={`stat-card stat-card--${tone}`}>
      <span className="stat-card__label">{label}</span>
      <span className="stat-card__value">{value}</span>
      {hint && <span className="stat-card__hint">{hint}</span>}
    </div>
  );
}

export function ProgressRing({ pct, label }: { pct: number; label: string }) {
  const r = 42;
  const c = 2 * Math.PI * r;
  const offset = c - (pct / 100) * c;
  return (
    <div className="progress-ring">
      <svg width="100" height="100" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r={r} className="progress-ring__track" />
        <circle
          cx="50"
          cy="50"
          r={r}
          className="progress-ring__fill"
          strokeDasharray={c}
          strokeDashoffset={offset}
        />
      </svg>
      <div className="progress-ring__center">
        <span className="progress-ring__pct">{Math.round(pct)}%</span>
        <span className="progress-ring__label">{label}</span>
      </div>
    </div>
  );
}

export function PipelineStepper({ activeStep }: { activeStep: number }) {
  const steps = [
    { id: 1, title: "Health", desc: "Verify environment" },
    { id: 2, title: "Configure", desc: "Tune tool params" },
    { id: 3, title: "Demo run", desc: "Sandbox variant call" },
    { id: 4, title: "Results", desc: "Review VCF output" },
    { id: 5, title: "Deploy", desc: "Go live on SN107" },
  ];
  return (
    <div className="pipeline">
      {steps.map((step, i) => (
        <div key={step.id} className="pipeline__item">
          <div
            className={`pipeline__node ${activeStep >= step.id ? "pipeline__node--active" : ""} ${activeStep === step.id ? "pipeline__node--current" : ""}`}
          >
            {activeStep > step.id ? <IconCheck /> : step.id}
          </div>
          <div className="pipeline__text">
            <span className="pipeline__title">{step.title}</span>
            <span className="pipeline__desc">{step.desc}</span>
          </div>
          {i < steps.length - 1 && (
            <div className={`pipeline__line ${activeStep > step.id ? "pipeline__line--active" : ""}`} />
          )}
        </div>
      ))}
    </div>
  );
}

export function TemplateSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="template-select">
      <label className="template-select__label">Variant caller</label>
      <select className="template-select__input" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="gatk">GATK HaplotypeCaller</option>
        <option value="deepvariant">Google DeepVariant</option>
        <option value="bcftools">BCFtools</option>
      </select>
    </div>
  );
}

export function Button({
  children,
  variant = "primary",
  disabled,
  onClick,
  icon,
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  onClick?: () => void;
  icon?: ReactNode;
}) {
  return (
    <button type="button" className={`btn btn--${variant}`} disabled={disabled} onClick={onClick}>
      {icon && <span className="btn__icon">{icon}</span>}
      {children}
    </button>
  );
}
