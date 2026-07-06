import { useCallback, useEffect, useState } from "react";

// ============================================================================
// Deal Pipeline CRM — client-side store (localStorage).
// Tracks which listings the user is pursuing and their deal state. No backend
// yet, so state persists in the browser; swap the storage layer for an API
// later without touching the UI.
// ============================================================================

export interface Stage {
  id: string;
  label: string;
  defaultProbability: number; // 0-100
  tone: "ink" | "accent" | "warn" | "pos" | "neg";
}

/** Acquisition funnel. Terminal outcomes (won/passed/lost) live in `TERMINAL`. */
export const STAGES: Stage[] = [
  { id: "sourced", label: "Sourced", defaultProbability: 5, tone: "ink" },
  { id: "contacted", label: "Contacted", defaultProbability: 10, tone: "ink" },
  { id: "nda_cim", label: "NDA / CIM", defaultProbability: 20, tone: "accent" },
  { id: "analysis", label: "Analysis", defaultProbability: 30, tone: "accent" },
  { id: "loi", label: "LOI", defaultProbability: 45, tone: "warn" },
  { id: "diligence", label: "Due Diligence", defaultProbability: 60, tone: "warn" },
  { id: "financing", label: "Financing & Legal", defaultProbability: 75, tone: "pos" },
  { id: "closing", label: "Closing", defaultProbability: 90, tone: "pos" },
  { id: "closed", label: "Closed — Won", defaultProbability: 100, tone: "pos" },
];

export const TERMINAL: Stage[] = [
  { id: "passed", label: "Passed", defaultProbability: 0, tone: "neg" },
  { id: "lost", label: "Lost", defaultProbability: 0, tone: "neg" },
];

export const ALL_STAGES = [...STAGES, ...TERMINAL];

export function stageById(id: string): Stage | undefined {
  return ALL_STAGES.find((s) => s.id === id);
}

export type Priority = "High" | "Medium" | "Low";

export interface PipelineEntry {
  listingId: string;
  stage: string;
  priority: Priority;
  probability: number; // 0-100, overrideable
  nextAction: string;
  nextActionDate: string; // ISO date or ""
  notes: string;
  addedAt: number; // epoch ms
}

type Store = Record<string, PipelineEntry>;
const KEY = "acq_pipeline_v1";

function read(): Store {
  if (typeof window === "undefined") return {};
  try {
    return JSON.parse(window.localStorage.getItem(KEY) || "{}") as Store;
  } catch {
    return {};
  }
}

function write(store: Store) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(store));
  // notify listeners in the same tab (storage event only fires cross-tab)
  window.dispatchEvent(new Event("acq_pipeline_change"));
}

/** React hook exposing the pipeline store with live updates. */
export function usePipeline() {
  const [store, setStore] = useState<Store>({});

  useEffect(() => {
    setStore(read());
    const sync = () => setStore(read());
    window.addEventListener("acq_pipeline_change", sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener("acq_pipeline_change", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  const add = useCallback((listingId: string) => {
    const s = read();
    if (s[listingId]) return;
    s[listingId] = {
      listingId,
      stage: "sourced",
      priority: "Medium",
      probability: 5,
      nextAction: "",
      nextActionDate: "",
      notes: "",
      addedAt: Date.now(),
    };
    write(s);
  }, []);

  const remove = useCallback((listingId: string) => {
    const s = read();
    delete s[listingId];
    write(s);
  }, []);

  const update = useCallback((listingId: string, patch: Partial<PipelineEntry>) => {
    const s = read();
    if (!s[listingId]) return;
    s[listingId] = { ...s[listingId], ...patch };
    write(s);
  }, []);

  const setStage = useCallback((listingId: string, stage: string) => {
    const s = read();
    if (!s[listingId]) return;
    const st = stageById(stage);
    // Move stage; snap probability to the stage default unless user customized.
    s[listingId] = { ...s[listingId], stage, probability: st ? st.defaultProbability : s[listingId].probability };
    write(s);
  }, []);

  return {
    entries: Object.values(store),
    store,
    isTracked: (id: string) => !!store[id],
    add,
    remove,
    update,
    setStage,
  };
}
