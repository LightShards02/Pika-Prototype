import React from "react";

interface FileFieldProps {
  label: string;
  value: string;
  field: string;
  placeholder?: string;
  optional?: boolean;
  isDir?: boolean;
  onChange: (v: string) => void;
  onBrowse: (field: string, isDir: boolean) => void;
}

/** A labelled file/dir picker row. */
export function FileField({
  label,
  value,
  field,
  placeholder,
  optional,
  isDir = false,
  onChange,
  onBrowse,
}: FileFieldProps) {
  return (
    <div className="field-row">
      <label className="field-label">
        {label}
        {optional && <span className="optional"> (optional)</span>}
      </label>
      <div className="field-input-group">
        <input
          className="field-input"
          type="text"
          value={value}
          placeholder={placeholder ?? (isDir ? "directory path" : "file path")}
          onChange={(e) => onChange(e.target.value)}
        />
        {value && optional && (
          <button className="icon-btn" title="Clear" onClick={() => onChange("")}>
            ×
          </button>
        )}
        <button className="icon-btn" title="Browse" onClick={() => onBrowse(field, isDir)}>
          …
        </button>
      </div>
    </div>
  );
}

interface CheckboxFieldProps {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}

export function CheckboxField({ label, checked, onChange }: CheckboxFieldProps) {
  return (
    <div className="field-row field-row--inline">
      <label className="field-label field-label--checkbox">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number) => void;
}

export function NumberField({ label, value, min, max, step = 1, onChange }: NumberFieldProps) {
  return (
    <div className="field-row field-row--short">
      <label className="field-label">{label}</label>
      <input
        className="field-input field-input--number"
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

interface TextAreaFieldProps {
  label: string;
  value: string;
  placeholder?: string;
  optional?: boolean;
  onChange: (v: string) => void;
}

export function TextAreaField({ label, value, placeholder, optional, onChange }: TextAreaFieldProps) {
  return (
    <div className="field-row">
      <label className="field-label">
        {label}
        {optional && <span className="optional"> (optional)</span>}
      </label>
      <textarea
        className="field-textarea"
        rows={2}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

interface SectionProps {
  title: string;
  children: React.ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
}

/** Collapsible section card. */
export function Section({ title, children, collapsible = false, defaultOpen = true }: SectionProps) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="section-card">
      <div
        className={`section-header${collapsible ? " section-header--clickable" : ""}`}
        onClick={collapsible ? () => setOpen((o) => !o) : undefined}
      >
        <span className="section-title">{title}</span>
        {collapsible && <span className="section-chevron">{open ? "▲" : "▼"}</span>}
      </div>
      {open && <div className="section-body">{children}</div>}
    </div>
  );
}
