import {
  AlertCircle,
  Check,
  CheckCheck,
  ChevronRight,
  Loader2,
  X,
} from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { Button } from "./ui/button";
import { cn, jobLabels } from "../lib";
import type { JobStatus } from "../types";

export function Logo() {
  return (
    <svg
      width="29"
      height="29"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M5 9h11m5 0h6M5 16h5m5 0h12M5 23h16"
        stroke="currentColor"
        strokeWidth="2.8"
        strokeLinecap="round"
      />
    </svg>
  );
}
export function Spinner({
  children = "Chargement…",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="loading" role="status">
      <Loader2 className="spin" size={18} />
      {children}
    </div>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: string;
  retry?: () => void;
}) {
  return (
    <div className="notice notice-error" role="alert">
      <AlertCircle size={17} />
      <span>{error}</span>
      {retry && (
        <Button variant="ghost" size="sm" onClick={retry}>
          Réessayer
        </Button>
      )}
    </div>
  );
}
export function Empty({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Status({ status }: { status: JobStatus }) {
  return (
    <span className={cn("status", `status-${status}`)}>
      <span className="status-dot" />
      {jobLabels[status]}
    </span>
  );
}
export function Progress({ value, label }: { value: number; label: string }) {
  return (
    <div
      className="progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(value)}
      aria-label={label}
    >
      <div style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
    </div>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content
          className={cn("modal", wide && "modal-wide")}
          aria-describedby={description ? undefined : undefined}
        >
          <div className="modal-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {description && (
                <Dialog.Description>{description}</Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Fermer">
                <X size={18} />
              </Button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function StepHint() {
  return (
    <div className="step-hint">
      <span>
        <CheckCheck size={14} />
        Choisir un dossier
      </span>
      <ChevronRight size={12} />
      <span>Scanner</span>
      <ChevronRight size={12} />
      <span>Sélectionner</span>
      <ChevronRight size={12} />
      <span>Traduire</span>
    </div>
  );
}
export function Checkmark({ checked }: { checked: boolean }) {
  return checked ? <Check size={14} /> : <X size={14} />;
}
