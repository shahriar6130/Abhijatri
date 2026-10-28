/** The panel format of System-Monitoring-Dashboard 6.2 (backend/app/ops/registry.py). */

export type Lang = 'bn' | 'en';
export type Localized = Record<Lang, string>;
export type Level = 'ok' | 'warn' | 'critical';
export type PanelStatus = 'ok' | 'degraded' | 'unavailable';

export interface StatBlock {
  type: 'stat';
  key: string;
  label: Localized;
  value: number | null;
  limit?: number;
  level: Level;
  hint?: Localized;
}

export interface SeriesBlock {
  type: 'series';
  key: string;
  label: Localized;
  points: { date: string; value: number | null }[];
}

export interface TableBlock {
  type: 'table';
  key: string;
  label: Localized;
  columns: string[];
  rows: (string | number | null)[][];
}

export interface StatusBlock {
  type: 'status';
  key: string;
  label: Localized;
  value: string;
  level: Level;
}

export type Block = StatBlock | SeriesBlock | TableBlock | StatusBlock;

export interface PanelData {
  id: string;
  version: number;
  title: Localized;
  status: PanelStatus;
  generated_at: string;
  refresh_seconds: number;
  sources: { name: string; fresh_at: string | null }[];
  blocks: Block[];
  notes: Localized[];
}

/** One row of GET /ops/panels: the layout is built from this (System-Monitoring-Dashboard 5). */
export interface CatalogueEntry {
  id: string;
  title: Localized;
  version: number;
  refresh_seconds: number;
  permission: string;
  sources: string[];
  owner: string;
}

export interface Overview {
  generated_at: string;
  days: number;
  panels: PanelData[];
}

export type Days = 7 | 30 | 90;
