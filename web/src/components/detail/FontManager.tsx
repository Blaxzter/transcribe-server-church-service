import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Download, FileUp, Loader2, Pencil, Trash2, X } from "lucide-react";
import { api, type Font } from "@/lib/api";
import { de } from "@/i18n/de";
import { formatBytes } from "@/lib/utils";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";

interface FontManagerProps {
  fonts: Font[];
  onFontsChange: (fonts: Font[]) => void;
  onBack: () => void;
}

/**
 * Upload, rename and delete the fonts the built-in Word layout can use. Each
 * row previews itself in its own font, which is the only way to tell two
 * uploads apart at a glance.
 */
export function FontManager({ fonts, onFontsChange, onBack }: FontManagerProps) {
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<Font | null>(null);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const created = await api.uploadFont(file);
      onFontsChange([...fonts, created].sort(byName));
      toast({ title: de.toast.fontUploaded, variant: "success" });
    } catch (error) {
      toast({
        title: de.toast.fontUploadFailed,
        description: error instanceof Error ? error.message : undefined,
        variant: "destructive",
      });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (font: Font) => {
    try {
      await api.deleteFont(font.id);
      onFontsChange(fonts.filter((entry) => entry.id !== font.id));
      toast({ title: de.toast.fontDeleted });
    } catch {
      toast({ title: de.toast.fontDeleteFailed, variant: "destructive" });
    }
  };

  const rename = async (font: Font, name: string) => {
    const updated = await api.renameFont(font.id, name);
    onFontsChange(fonts.map((entry) => (entry.id === font.id ? updated : entry)).sort(byName));
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft />
          {de.fonts.back}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".ttf,.otf,font/ttf,font/otf"
          className="hidden"
          onChange={(event) => void upload(event.target.files?.[0])}
        />
        <Button
          size="sm"
          className="ml-auto"
          disabled={uploading}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? <Loader2 className="animate-spin" /> : <FileUp />}
          {uploading ? de.fonts.uploading : de.fonts.upload}
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">{de.fonts.description}</p>

      {fonts.length === 0 ? (
        <div className="rounded-md border border-dashed border-border px-4 py-6 text-center">
          <p className="text-sm font-medium">{de.fonts.empty}</p>
          <p className="mt-1 text-xs text-muted-foreground">{de.fonts.emptyHint}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {fonts.map((font) => (
            <FontRow
              key={font.id}
              font={font}
              onRename={(name) => rename(font, name)}
              onDelete={() => setDeleting(font)}
            />
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={de.fonts.deleteTitle}
        description={de.fonts.deleteDescription}
        confirmLabel={de.fonts.delete}
        destructive
        onConfirm={async () => {
          if (deleting) await remove(deleting);
        }}
      />
    </div>
  );
}

function byName(a: Font, b: Font): number {
  return a.name.localeCompare(b.name, "de");
}

/**
 * Loads a stored font into the page so a sample can be set in it. The family
 * is namespaced by id: two uploads may well call themselves the same thing.
 */
function useLoadedFont(font: Font): string | null {
  const family = `transkript-font-${font.id}`;
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (typeof FontFace === "undefined") return;
    let cancelled = false;
    const face = new FontFace(family, `url(${api.fontFileUrl(font.id)})`);
    face
      .load()
      .then((loaded) => {
        if (cancelled) return;
        document.fonts.add(loaded);
        setReady(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      setReady(false);
    };
  }, [family, font.id]);

  return ready ? family : null;
}

function FontRow({
  font,
  onRename,
  onDelete,
}: {
  font: Font;
  onRename: (name: string) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(font.name);
  const [saving, setSaving] = useState(false);
  const family = useLoadedFont(font);
  const name = draft.trim();

  const commit = async () => {
    if (!name || saving) return;
    if (name === font.name) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onRename(name);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="rounded-md border border-border px-3 py-2.5">
      <div className="flex items-center gap-2">
        {editing ? (
          <>
            <Input
              value={draft}
              autoFocus
              disabled={saving}
              aria-label={de.fonts.name}
              className="h-8 flex-1"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void commit();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setDraft(font.name);
                  setEditing(false);
                }
              }}
            />
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label={de.fonts.save}
              disabled={!name || saving}
              onClick={() => void commit()}
            >
              {saving ? <Loader2 className="animate-spin" /> : <Check />}
            </Button>
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label={de.common.cancel}
              disabled={saving}
              onClick={() => {
                setDraft(font.name);
                setEditing(false);
              }}
            >
              <X />
            </Button>
          </>
        ) : (
          <>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{font.name}</span>
            <Tooltip label={de.fonts.rename} side="left">
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={de.fonts.rename}
                onClick={() => setEditing(true)}
              >
                <Pencil />
              </Button>
            </Tooltip>
            <Tooltip label={de.fonts.download} side="left">
              <a
                href={api.fontFileUrl(font.id)}
                download={font.filename}
                aria-label={de.fonts.download}
                className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
              >
                <Download />
              </a>
            </Tooltip>
            <Tooltip label={de.fonts.delete} side="left">
              <Button
                size="icon-sm"
                variant="ghost"
                className="text-destructive"
                aria-label={de.fonts.delete}
                onClick={onDelete}
              >
                <Trash2 />
              </Button>
            </Tooltip>
          </>
        )}
      </div>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">
        {font.family}
        {font.size_bytes ? ` · ${formatBytes(font.size_bytes)}` : ""}
      </p>
      <p
        className="mt-2 truncate text-lg"
        style={family ? { fontFamily: `"${family}"` } : undefined}
      >
        {de.fonts.sample}
      </p>
    </li>
  );
}
