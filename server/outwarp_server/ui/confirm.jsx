// Themed replacement for window.confirm so destructive actions match the design.
// useConfirmState returns [confirm, dialogElement]; render the element inside the
// themed tree and `await confirm({...})` resolves to a boolean.

const ConfirmDialog = ({ title, message, confirmLabel, cancelLabel, danger, onResult }) => {
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onResult(false);
      else if (e.key === "Enter") onResult(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onResult]);
  return (
    <div className="ow-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onResult(false); }}>
      <div className="ow-modal" role="dialog" aria-modal="true">
        {title && <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{title}</div>}
        <div style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.55 }}>{message}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
          <window.Btn kind="ghost" size="md" onClick={() => onResult(false)}>{cancelLabel}</window.Btn>
          <window.Btn kind={danger ? "danger" : "primary"} size="md" onClick={() => onResult(true)}>{confirmLabel}</window.Btn>
        </div>
      </div>
    </div>
  );
};

function useConfirmState() {
  const [pending, setPending] = React.useState(null);
  const confirm = React.useCallback((opts) => new Promise((resolve) => {
    setPending({ ...opts, resolve });
  }), []);
  const dialog = pending
    ? <ConfirmDialog {...pending} onResult={(val) => { pending.resolve(val); setPending(null); }}/>
    : null;
  return [confirm, dialog];
}

window.ConfirmDialog = ConfirmDialog;
window.useConfirmState = useConfirmState;
