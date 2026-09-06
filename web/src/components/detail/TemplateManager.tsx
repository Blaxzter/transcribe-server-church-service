import { useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  Copy,
  Download,
  FileUp,
  Loader2,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { api, type Template } from "@/lib/api";
import { de } from "@/i18n/de";
import { cn, formatBytes } from "@/lib/utils";
import { placeholderToken } from "@/components/detail/exportLabels";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tooltip } from "@/components/ui/tooltip";
import { useToast } from "@/components/ui/toast";

interface TemplateManagerProps {
  templates: Template[];
  /** Placeholder names the server can fill, in the order it lists them. */
  fields: string[];
  onTemplatesChange: (templates: Template[]) => void;
  onBack: () => void;
}

/**
 * Upload, rename and delete Word templates, and explain which placeholders a
 * template may use. Lives inside the export dialog so the person setting up an
 * export never has to leave it.
 */
export function TemplateManager({
  templates,
  fields,
  onTemplatesChange,
  onBack,
}: TemplateManagerProps) {
  const { toast } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<Template | null>(null);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const created = await api.uploadTemplate(file);
      onTemplatesChange([...templates, created].sort(byName));
      toast({ title: de.toast.templateUploaded, variant: "success" });
    } catch (error) {
      toast({
        title: de.toast.templateUploadFailed,
        description: error instanceof Error ? error.message : undefined,
        variant: "destructive",
      });
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const remove = async (template: Template) => {
    try {
      await api.deleteTemplate(template.id);
      onTemplatesChange(templates.filter((entry) => entry.id !== template.id));
      toast({ title: de.toast.templateDeleted });
    } catch {
      toast({ title: de.toast.templateDeleteFailed, variant: "destructive" });
    }
  };

  const rename = async (template: Template, name: string) => {
    const updated = await api.renameTemplate(template.id, name);
    onTemplatesChange(
      templates.map((entry) => (entry.id === template.id ? updated : entry)).sort(byName),
    );
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft />
          {de.templates.back}
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
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
          {uploading ? de.templates.uploading : de.templates.upload}
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">{de.templates.description}</p>

      {templates.length === 0 ? (
        <div className="rounded-md border border-dashed border-border px-4 py-6 text-center">
          <p className="text-sm font-medium">{de.templates.empty}</p>
          <p className="mt-1 text-xs text-muted-foreground">{de.templates.emptyHint}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {templates.map((template) => (
            <TemplateRow
              key={template.id}
              template={template}
              onRename={(name) => rename(template, name)}
              onDelete={() => setDeleting(template)}
            />
          ))}
        </ul>
      )}

      <section className="rounded-md bg-muted/60 p-4">
        <h4 className="text-sm font-semibold">{de.templates.fieldsTitle}</h4>
        <p className="mt-1 text-xs text-muted-foreground">{de.templates.fieldsHint}</p>
        <ul className="mt-3 divide-y divide-border/70">
          {fields.map((field) => (
            <FieldRow key={field} name={field} />
          ))}
        </ul>
      </section>

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={de.templates.deleteTitle}
        description={de.templates.deleteDescription}
        confirmLabel={de.templates.delete}
        destructive
        onConfirm={async () => {
          if (deleting) await remove(deleting);
        }}
      />
    </div>
  );
}

function byName(a: Template, b: Template): number {
  return a.name.localeCompare(b.name, "de");
}

function TemplateRow({
  template,
  onRename,
  onDelete,
}: {
  template: Template;
  onRename: (name: string) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(template.name);
  const [saving, setSaving] = useState(false);
  const name = draft.trim();

  const commit = async () => {
    if (!name || saving) return;
    if (name === template.name) {
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

  const unknown = new Set(template.unknown_placeholders);

  return (
    <li className="rounded-md border border-border px-3 py-2.5">
      <div className="flex items-center gap-2">
        {editing ? (
          <>
            <Input
              value={draft}
              autoFocus
              disabled={saving}
              aria-label={de.templates.name}
              className="h-8 flex-1"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  void commit();
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  setDraft(template.name);
                  setEditing(false);
                }
              }}
            />
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label={de.templates.save}
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
                setDraft(template.name);
                setEditing(false);
              }}
            >
              <X />
            </Button>
          </>
        ) : (
          <>
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{template.name}</span>
            <Tooltip label={de.templates.rename} side="left">
              <Button
                size="icon-sm"
                variant="ghost"
                aria-label={de.templates.rename}
                onClick={() => setEditing(true)}
              >
                <Pencil />
              </Button>
            </Tooltip>
            <Tooltip label={de.templates.download} side="left">
              <a
                href={api.templateFileUrl(template.id)}
                download={template.filename}
                aria-label={de.templates.download}
                className={buttonVariants({ variant: "ghost", size: "icon-sm" })}
              >
                <Download />
              </a>
            </Tooltip>
            <Tooltip label={de.templates.delete} side="left">
              <Button
                size="icon-sm"
                variant="ghost"
                className="text-destructive"
                aria-label={de.templates.delete}
                onClick={onDelete}
              >
                <Trash2 />
              </Button>
            </Tooltip>
          </>
        )}
      </div>
      <p className="mt-0.5 truncate text-xs text-muted-foreground">
        {template.filename}
        {template.size_bytes ? ` · ${formatBytes(template.size_bytes)}` : ""}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {template.placeholders.length === 0 ? (
          <span className="text-xs text-warning">{de.templates.placeholdersNone}</span>
        ) : (
          template.placeholders.map((placeholder) => (
            <Badge
              key={placeholder}
              variant={unknown.has(placeholder) ? "warning" : "default"}
              title={unknown.has(placeholder) ? de.templates.unknownPlaceholder : undefined}
              className="font-mono"
            >
              {placeholderToken(placeholder)}
            </Badge>
          ))
        )}
      </div>
    </li>
  );
}

function FieldRow({ name }: { name: string }) {
  const { toast } = useToast();
  const token = placeholderToken(name);
  const description = de.templates.fields[name] ?? "";

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(token);
      toast({ title: de.toast.copied, variant: "success" });
    } catch {
      toast({ title: de.toast.copyFailed, variant: "destructive" });
    }
  };

  return (
    <li className="flex items-center gap-3 py-1.5">
      <code className={cn("shrink-0 rounded bg-card px-1.5 py-0.5 font-mono text-xs")}>
        {token}
      </code>
      <span className="min-w-0 flex-1 text-xs text-muted-foreground">{description}</span>
      <Button
        size="icon-sm"
        variant="ghost"
        aria-label={de.templates.copyField}
        onClick={() => void copy()}
      >
        <Copy />
      </Button>
    </li>
  );
}
