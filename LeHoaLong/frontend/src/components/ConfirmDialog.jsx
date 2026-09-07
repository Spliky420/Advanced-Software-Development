import { useEffect, useRef } from 'react'
import { BusyButton } from './common'

// A modal confirmation. Deleting a goal takes its plan and its whole
// contribution history with it, so it is not something to do on one click.
export default function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Delete',
  busy = false,
  onConfirm,
  onCancel,
}) {
  const cancelRef = useRef(null)

  useEffect(() => {
    // Focus lands on Cancel, not Confirm: a stray Enter should not destroy
    // anything. Escape closes, as a dialog is expected to.
    cancelRef.current?.focus()
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onCancel()}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title">
        <h2 id="confirm-title">{title}</h2>
        <div>{message}</div>
        <div className="modal__actions">
          <button type="button" ref={cancelRef} className="btn btn--secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <BusyButton className="btn btn--danger" busy={busy} busyLabel="Deleting..." onClick={onConfirm}>
            {confirmLabel}
          </BusyButton>
        </div>
      </div>
    </div>
  )
}
