import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  LoaderCircle,
  X,
} from "lucide-react";
import type { Mode, Route } from "./types";
export const routeNames: Record<Route, string> = {
  read: "Read first",
  skim: "Skim",
  review: "Needs review",
  later: "For later",
};
export function Logo({ small = false }: { small?: boolean }) {
  return (
    <span className={`brand-symbol ${small ? "small" : ""}`} aria-hidden="true">
      <svg viewBox="0 0 40 40">
        <path d="M20 6c8 0 10 8 0 14C10 14 12 6 20 6Zm14 14c0 8-8 10-14 0 6-10 14-8 14 0ZM20 34c-8 0-10-8 0-14 10 6 8 14 0 14ZM6 20c0-8 8-10 14 0-6 10-14 8-14 0Z" />
      </svg>
    </span>
  );
}
export function ModeBadge({ mode }: { mode: Mode }) {
  return (
    <span className={`mode-badge ${mode}`}>
      <span />
      {mode === "jev"
        ? "Jev · live result"
        : mode === "llm"
          ? "Compatible LLM"
          : "Keyword baseline"}
    </span>
  );
}
export function RouteBadge({ route }: { route: Route }) {
  return (
    <span className={`route-badge ${route}`}>
      <span />
      {routeNames[route]}
    </span>
  );
}
export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span className="spinner" role="status">
      <LoaderCircle size={16} />
      <span>{label}</span>
    </span>
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
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function ErrorPanel({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error-panel" role="alert">
      <CircleAlert size={19} />
      <div>
        <strong>Something needs your attention</strong>
        <p>{message}</p>
        {retry && (
          <button className="text-button" onClick={retry}>
            Try again <ArrowUpRight size={14} />
          </button>
        )}
      </div>
    </div>
  );
}
export function Modal({
  title,
  subtitle,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const dialog = ref.current;
    const previous = document.activeElement as HTMLElement | null;
    dialog?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = overflow;
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return createPortal(
    <dialog
      ref={ref}
      className={`modal ${wide ? "wide" : ""}`}
      onCancel={(e) => {
        e.preventDefault();
        closeRef.current();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const box = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < box.left ||
            e.clientX > box.right ||
            e.clientY < box.top ||
            e.clientY > box.bottom
          )
            closeRef.current();
        }
      }}
      aria-labelledby="modal-title"
    >
      <div className="modal-header">
        <div>
          <span className="eyebrow">YOUR RESEARCH WORKSPACE</span>
          <h2 id="modal-title">{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>,
    document.body,
  );
}
export function Toast({
  message,
  error,
  onClose,
}: {
  message: string;
  error?: boolean;
  onClose: () => void;
}) {
  useEffect(() => {
    const timer = setTimeout(onClose, error ? 10000 : 4500);
    return () => clearTimeout(timer);
  }, [message, error, onClose]);
  return (
    <div
      className={`toast ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {error ? <CircleAlert size={18} /> : <Check size={18} />}
      <span>{message}</span>
      <button onClick={onClose} aria-label="Dismiss notification">
        <X size={16} />
      </button>
    </div>
  );
}
