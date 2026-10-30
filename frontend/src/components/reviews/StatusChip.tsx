import React from 'react';
import { Ban, CheckCircle2, Clock, EyeOff, FilePenLine, Trash2, Undo2, XCircle, type LucideIcon } from 'lucide-react';
import { useLanguage } from '../../context/LanguageContext';
import type { ReviewStatus } from '../../types';
import { STATUS_LABEL } from './reviewLabels';

const ICON: Record<ReviewStatus, LucideIcon> = {
  PENDING: Clock,
  UNDER_REVIEW: Clock,
  CHANGES_REQUESTED: FilePenLine,
  PUBLISHED: CheckCircle2,
  HIDDEN: EyeOff,
  REJECTED: XCircle,
  WITHDRAWN: Undo2,
  DELETED: Trash2,
};

const TONE: Record<ReviewStatus, string> = {
  PENDING: 'bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200',
  UNDER_REVIEW: 'bg-amber-50 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200',
  CHANGES_REQUESTED: 'bg-orange-50 text-orange-900 dark:bg-orange-950/40 dark:text-orange-200',
  PUBLISHED: 'bg-emerald-50 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200',
  HIDDEN: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-200',
  REJECTED: 'bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-200',
  WITHDRAWN: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  DELETED: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
};

/** A review status as an icon plus words: colour is never the only signal (WCAG 1.4.1). */
export const StatusChip: React.FC<{ status: ReviewStatus }> = ({ status }) => {
  const { t } = useLanguage();
  const Icon = ICON[status] ?? Ban;
  return (
    <span data-status={status} className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold ${TONE[status] ?? ''}`}>
      <Icon size={13} aria-hidden="true" />
      {t(...STATUS_LABEL[status])}
    </span>
  );
};
