import { useRef, useState } from "react";
import { de } from "@/i18n/de";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

interface RenameSpeakerDialogProps {
  currentLabel: string;
  onSave: (label: string) => Promise<void>;
  onClose: () => void;
}

/**
 * Give a speaker their name. Reached from the speaker chip in the transcript
 * and from the speaker list in the sidebar — both are places where you notice
 * that "Sprecher 3" is the organist.
 */
export function RenameSpeakerDialog({
  currentLabel,
  onSave,
  onClose,
}: RenameSpeakerDialogProps) {
  const [value, setValue] = useState(currentLabel);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const label = value.trim();

  const save = async () => {
    if (!label || pending) return;
    setPending(true);
    try {
      await onSave(label);
      onClose();
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && !pending && onClose()}
      title={de.transcript.renameSpeaker}
      initialFocusRef={inputRef}
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>
            {de.transcript.cancel}
          </Button>
          <Button disabled={!label || pending} onClick={() => void save()}>
            {de.transcript.save}
          </Button>
        </>
      }
    >
      <label className="mb-1.5 block text-sm text-muted-foreground" htmlFor="speaker-name">
        {de.transcript.speakerName}
      </label>
      <Input
        id="speaker-name"
        ref={inputRef}
        value={value}
        disabled={pending}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            void save();
          }
        }}
      />
    </Dialog>
  );
}
