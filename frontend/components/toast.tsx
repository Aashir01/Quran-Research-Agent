"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";

type Toast = { id: number; message: string; kind: "ok" | "err" };
type Api = { toast: (message: string, kind?: "ok" | "err") => void };

const ToastContext = createContext<Api>({ toast: () => {} });

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);

  const toast = useCallback((message: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((current) => [...current, { id, message, kind }]);
    setTimeout(() => setItems((current) => current.filter((t) => t.id !== id)), 3600);
  }, []);

  const value = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* aria-live so a screen reader hears the confirmation it can't see. */}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast ${item.kind === "err" ? "err" : ""}`}>
            <span className="dot" />
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
