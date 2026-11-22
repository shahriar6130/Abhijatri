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
  CHANGES_REQUESTED: 'bg-amber-100 text-amber-950 dark:bg-amber-950/60 dark:text-amber-100',
  PUBLISHED: 'bg-primary/10 text-foreground',
  HIDDEN: 'bg-muted text-foreground',
  REJECTED: 'bg-red-50 text-red-900 dark:bg-red-950/40 dark:text-red-200',
  WITHDRAWN: 'bg-muted text-muted-foreground',
  DELETED: 'bg-muted text-muted-foreground',
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
