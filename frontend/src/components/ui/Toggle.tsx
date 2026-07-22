export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-3">
      <span className="relative inline-flex h-[26px] w-[46px] shrink-0 items-center rounded-full bg-white/15 transition-colors has-[:checked]:bg-primary">
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-[23px]' : 'translate-x-1'}`}
        />
        <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      </span>
      {label && <span className="text-sm text-white">{label}</span>}
    </label>
  )
}
