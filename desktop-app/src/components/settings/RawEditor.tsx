interface RawEditorProps {
  value: string;
  onChange: (value: string) => void;
}

export const RawEditor = ({ value, onChange }: RawEditorProps) => {
  return (
    <div className="flex-1 h-full bg-white">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-full p-6 font-mono text-[13px] leading-relaxed bg-transparent border-none resize-none focus:outline-none text-text-primary"
        spellCheck={false}
        placeholder="# Paste or edit your YAML config here..."
      />
    </div>
  );
};
