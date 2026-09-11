export type WorkbenchMode = "ask" | "plan" | "agent" | "run";

export type MessageKind =
  | "user_text"
  | "ask"
  | "ask_text"
  | "clarify"
  | "clarification"
  | "plan_ready"
  | "executing"
  | "result"
  | "mode_notice"
  | "plan_card"
  | "step_status"
  | "error"
  | "design_card"
  | "kb_write";

export interface WorkbenchMessage {
  kind: MessageKind;
  text: string;
  payload: Record<string, unknown>;
}

export interface WorkbenchPlanStep {
  step_id: string;
  skill_name: string;
  side_effects: {
    network: boolean;
    filesystem_write: boolean;
    local_state_change: boolean;
    heavy_compute: boolean;
    description: string;
  };
  needs_confirm: boolean;
  status: string;
  summary?: string;
}

export interface WorkbenchPlanCard {
  plan_id: string;
  steps: WorkbenchPlanStep[];
  plan_md: string;
  confirmable: boolean;
  needs_confirm: boolean;
}

export interface WorkbenchSidebarSlot {
  name: string;
  value: unknown;
  source: string;
  confirmed: boolean;
}

export interface WorkbenchSidebar {
  active_intent: { job?: string; flags?: Record<string, unknown> } | null;
  slots: WorkbenchSidebarSlot[];
  missing: string[];
  env_summary: Record<string, unknown>;
  current_plan_id: string;
  clarify_round: number;
  design?: Record<string, unknown> | null;
  trial_queue?: Array<Record<string, unknown>>;
}

export interface WorkbenchArtifact {
  type: "data_table" | "chart" | "strategy_code" | "backtest_report" | "plan";
  run_id: string;
  title: string;
  export_path: string;
  preview: Record<string, unknown>;
  warnings: string[];
}

export interface WorkbenchState {
  mode: WorkbenchMode;
  session_id: string;
  messages: WorkbenchMessage[];
  plan_card: WorkbenchPlanCard | null;
  sidebar: WorkbenchSidebar;
  artifacts: WorkbenchArtifact[];
  execution: { status: string; steps: Array<Record<string, unknown>> };
  error: { code?: string; message?: string } | null;
  run_id: string;
  sources: string[];
}

export const WORKBENCH_STATE_KEYS = [
  "mode",
  "session_id",
  "messages",
  "plan_card",
  "sidebar",
  "artifacts",
  "execution",
  "error",
  "run_id",
  "sources",
] as const;
