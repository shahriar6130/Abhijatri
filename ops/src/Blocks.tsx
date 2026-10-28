import type { Block, Lang, SeriesBlock, StatBlock, StatusBlock, TableBlock } from './types';
import { formatValue, seriesPaths } from './format';

/**
 * Renders any panel from the four block types of System-Monitoring-Dashboard 6.2, so a new backend
 * panel appears without a frontend change.
 */
export function BlockList({ blocks, lang }: { blocks: Block[]; lang: Lang }) {
  const stats = blocks.filter((b): b is StatBlock | StatusBlock => b.type === 'stat' || b.type === 'status');
  const rest = blocks.filter((b) => b.type === 'series' || b.type === 'table');
  return (
    <>
      {stats.length > 0 && (
        <div className="stats">
          {stats.map((block) => (block.type === 'stat' ? <Stat key={block.key} block={block} lang={lang} /> : <Status key={block.key} block={block} lang={lang} />))}
        </div>
      )}
      {rest.map((block) =>
        block.type === 'series' ? (
          <Series key={block.key} block={block} lang={lang} />
        ) : (
          <Table key={block.key} block={block as TableBlock} lang={lang} />
        ),
      )}
    </>
  );
}

function Stat({ block, lang }: { block: StatBlock; lang: Lang }) {
  return (
    <div className={`stat level-${block.level}`} title={block.hint?.[lang]}>
      <span className="stat-label">{block.label[lang]}</span>
      <span className="stat-value">
        {formatValue(block.value, lang)}
        {block.limit !== undefined && <span className="stat-limit"> / {formatValue(block.limit, lang)}</span>}
      </span>
    </div>
  );
}

function Status({ block, lang }: { block: StatusBlock; lang: Lang }) {
  return (
    <div className={`stat level-${block.level}`}>
      <span className="stat-label">{block.label[lang]}</span>
      <span className="status-value">
        <span className="dot" aria-hidden="true" />
        {block.value}
      </span>
    </div>
  );
}

const WIDTH = 600;
const HEIGHT = 120;

function Series({ block, lang }: { block: SeriesBlock; lang: Lang }) {
  const segments = seriesPaths(block.points, WIDTH, HEIGHT);
  const known = block.points.filter((p) => p.value !== null);
  const total = known.reduce((sum, p) => sum + (p.value ?? 0), 0);
  const first = block.points[0]?.date;
  const last = block.points[block.points.length - 1]?.date;
  return (
    <figure className="series">
      <figcaption>
        <span>{block.label[lang]}</span>
        <span className="muted">
          {lang === 'bn' ? 'মোট' : 'Sum'} {formatValue(known.length ? total : null, lang)} ·{' '}
          {formatValue(block.points.length - known.length, lang)} {lang === 'bn' ? 'দিনের তথ্য নেই' : 'days without data'}
        </span>
      </figcaption>
      <svg viewBox={`-4 -4 ${WIDTH + 8} ${HEIGHT + 8}`} role="img" aria-label={block.label[lang]} preserveAspectRatio="none">
        <line x1="0" y1={HEIGHT} x2={WIDTH} y2={HEIGHT} className="axis" />
        {segments.map((points) =>
          points.includes(' ') ? (
            <polyline key={points} points={points} className="line" />
          ) : (
            <circle key={points} cx={points.split(',')[0]} cy={points.split(',')[1]} r="3" className="point" />
          ),
        )}
      </svg>
      <div className="series-axis muted">
        <span>{first}</span>
        <span>{last}</span>
      </div>
    </figure>
  );
}

/** Table column keys from the providers; an unknown key is shown as sent. */
const COLUMN_LABELS: Record<string, Record<Lang, string>> = {
  status: { bn: 'অবস্থা', en: 'Status' },
  count: { bn: 'সংখ্যা', en: 'Count' },
  route: { bn: 'রুট', en: 'Route' },
  role: { bn: 'ভূমিকা', en: 'Role' },
  accounts: { bn: 'অ্যাকাউন্ট', en: 'Accounts' },
};

export const columnLabel = (column: string, lang: Lang): string => COLUMN_LABELS[column]?.[lang] ?? column;

function Table({ block, lang }: { block: TableBlock; lang: Lang }) {
  return (
    <div className="table-wrap">
      <h4>{block.label[lang]}</h4>
      {block.rows.length === 0 ? (
        <p className="muted">{lang === 'bn' ? 'কিছু নেই' : 'None'}</p>
      ) : (
        <table>
          <thead>
            <tr>
              {block.columns.map((column) => (
                <th key={column}>{columnLabel(column, lang)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, index) => (
              <tr key={index}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{formatValue(cell, lang)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
