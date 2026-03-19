interface SettingsFieldProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

export const SettingsField = ({ label, description, children }: SettingsFieldProps) => {
  return (
    <div className="grid grid-cols-[200px_1fr] gap-4 items-start">
      <div className="pt-2">
        <div className="text-[13px] font-medium text-text-primary">{label}</div>
        {description && (
          <div className="text-[11px] text-text-tertiary mt-0.5 leading-relaxed">{description}</div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
};
