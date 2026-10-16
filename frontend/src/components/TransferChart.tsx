import { useState } from "react";
import type { TransferLine } from "../api";

const TOTAL_COLOR = "#0f766e";
const DELTA_POS = "#c2410c";
const DELTA_NEG = "#64748b";
const WIDTH = 720;
const HEIGHT = 280;
const PAD = { top: 16, right: 48, bottom: 32, left: 48 };

function labelIndexes(count: number) {
  if (count <= 8) return Array.from({ length: count }, (_, index) => index);
  const step = Math.ceil(count / 7);
  const indexes: number[] = [];
  for (let index = 0; index < count; index += step) indexes.push(index);
  if (indexes[indexes.length - 1] !== count - 1) indexes.push(count - 1);
  return indexes;
}

function niceBounds(values: number[]) {
  let min = Math.min(0, ...values);
  let max = Math.max(0, ...values);
  if (min === max) max = min + 1;
  const rough = Math.max(1, (max - min) / 4);
  const power = 10 ** Math.floor(Math.log10(rough));
  const error = rough / power;
  const factor = error >= 7.5 ? 10 : error >= 3.5 ? 5 : error >= 1.5 ? 2 : 1;
  const step = Math.max(1, factor * power);
  min = Math.floor(min / step) * step;
  max = Math.ceil(max / step) * step;
  if (min === max) max += step;
  return { min, max, step };
}

function ticksFor(bounds: { min: number; max: number; step: number }) {
  const ticks: number[] = [];
  for (let tick = bounds.min; tick <= bounds.max + 0.001; tick += bounds.step) ticks.push(tick);
  return ticks;
}

function pickLine(lines: TransferLine[], kind: string) {
  return lines.find((line) => line.kind === kind) ?? null;
}

export default function TransferChart({
  dates,
  lines,
  start,
  end,
}: {
  dates: string[];
  lines: TransferLine[];
  start: string;
  end: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const totalLine = pickLine(lines, "total");
  const deltaLine = pickLine(lines, "delta");
  const totalValues = (totalLine?.values ?? []).filter((value): value is number => value != null);
  const deltaValues = (deltaLine?.values ?? []).filter((value): value is number => value != null);
  const hasTotal = totalValues.length > 0;
  const hasDelta = deltaValues.length > 0;
  const hasPoint = hasTotal || hasDelta;

  const totalBounds = niceBounds(hasTotal ? totalValues : [0]);
  const deltaBounds = niceBounds(hasDelta ? deltaValues : [0]);
  const totalTicks = ticksFor(totalBounds);
  const deltaTicks = ticksFor(deltaBounds);

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const xAt = (index: number) => PAD.left + (dates.length <= 1 ? plotW / 2 : (index / (dates.length - 1)) * plotW);
  const yLeft = (value: number) => PAD.top + ((totalBounds.max - value) / (totalBounds.max - totalBounds.min || 1)) * plotH;
  const yRight = (value: number) => PAD.top + ((deltaBounds.max - value) / (deltaBounds.max - deltaBounds.min || 1)) * plotH;
  const zeroY = yRight(0);
  const barW = Math.max(4, Math.min(28, (plotW / Math.max(dates.length, 1)) * 0.55));

  const totalSegments: number[][] = [];
  if (totalLine) {
    let current: number[] = [];
    totalLine.values.forEach((value, index) => {
      if (value == null) {
        if (current.length) totalSegments.push(current);
        current = [];
        return;
      }
      current.push(index);
    });
    if (current.length) totalSegments.push(current);
  }

  return (
    <section className="mt-4 rounded-2xl border border-line bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">转存趋势</h2>
          <p className="mt-1 h-10 text-[13px] leading-5 text-ink/55">
            实线为转存总量（左轴），柱为日增量（右轴）。缺日表数据的日期留空。
          </p>
        </div>
        <p className="shrink-0 pt-1 text-[13px] text-ink/45">
          {start} 至 {end}
        </p>
      </div>
      <div className="relative mt-3 aspect-[720/280]">
        {!hasPoint ? (
          <p className="flex h-full items-center justify-center text-sm text-ink/45">
            {lines.length === 0 ? "还没有网盘账号。" : "这段日期还没有可绘制的转存日统计。"}
          </p>
        ) : (
          <>
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              className="h-full w-full"
              role="img"
              aria-label="转存趋势双轴图"
              onMouseLeave={() => setHover(null)}
              onMouseMove={(event) => {
                const svg = event.currentTarget;
                const point = svg.createSVGPoint();
                point.x = event.clientX;
                point.y = event.clientY;
                const matrix = svg.getScreenCTM();
                if (!matrix || dates.length === 0) return;
                const local = point.matrixTransform(matrix.inverse());
                if (dates.length === 1) {
                  setHover(0);
                  return;
                }
                const ratio = (local.x - PAD.left) / plotW;
                const index = Math.round(Math.min(1, Math.max(0, ratio)) * (dates.length - 1));
                setHover(index);
              }}
            >
              {totalTicks.map((tick) => (
                <g key={`l-${tick}`}>
                  <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yLeft(tick)} y2={yLeft(tick)} stroke="#e7e5e4" />
                  <text x={PAD.left - 8} y={yLeft(tick) + 4} textAnchor="end" fill="#0f766e" fontSize="11">
                    {String(tick)}
                  </text>
                </g>
              ))}
              {deltaTicks.map((tick) => (
                <text key={`r-${tick}`} x={WIDTH - PAD.right + 8} y={yRight(tick) + 4} textAnchor="start" fill="#c2410c" fontSize="11">
                  {String(tick)}
                </text>
              ))}
              {hasDelta ? (
                <line x1={PAD.left} x2={WIDTH - PAD.right} y1={zeroY} y2={zeroY} stroke="#d6d3d1" strokeDasharray="4 3" />
              ) : null}

              {deltaLine
                ? deltaLine.values.map((value, index) => {
                    if (value == null) return null;
                    const y = yRight(value);
                    const top = Math.min(y, zeroY);
                    const height = Math.max(1, Math.abs(y - zeroY));
                    return (
                      <rect
                        key={`bar-${index}`}
                        x={xAt(index) - barW / 2}
                        y={top}
                        width={barW}
                        height={height}
                        rx="2"
                        fill={value >= 0 ? DELTA_POS : DELTA_NEG}
                        opacity={hover == null || hover === index ? 0.85 : 0.3}
                      />
                    );
                  })
                : null}

              {totalLine
                ? totalSegments.map((segment) =>
                    segment.length > 1 ? (
                      <polyline
                        key={`seg-${segment[0]}`}
                        fill="none"
                        stroke={TOTAL_COLOR}
                        strokeWidth="2"
                        points={segment.map((index) => `${xAt(index)},${yLeft(totalLine.values[index] as number)}`).join(" ")}
                      />
                    ) : null,
                  )
                : null}
              {totalLine
                ? totalLine.values.map((value, index) =>
                    value == null ? null : <circle key={`pt-${index}`} cx={xAt(index)} cy={yLeft(value)} r="3.5" fill={TOTAL_COLOR} />,
                  )
                : null}

              {labelIndexes(dates.length).map((index) => (
                <text key={dates[index]} x={xAt(index)} y={HEIGHT - 8} textAnchor="middle" fill="#78716c" fontSize="11">
                  {dates[index].slice(5)}
                </text>
              ))}
              {hover != null ? (
                <line x1={xAt(hover)} x2={xAt(hover)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke="#a8a29e" strokeDasharray="3 3" />
              ) : null}
            </svg>
            {hover != null ? (
              <div
                className="pointer-events-none absolute top-2 z-10 min-w-36 rounded-xl border border-line bg-white px-3 py-2 text-[12px]"
                style={{ left: `min(${((xAt(hover) / WIDTH) * 100).toFixed(2)}%, calc(100% - 10rem))` }}
              >
                <p className="font-medium">{dates[hover]}</p>
                <ul className="mt-1 space-y-1">
                  <li className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5 text-ink/70">
                      <span className="inline-block h-2 w-2 rounded-full" style={{ background: TOTAL_COLOR }} />
                      转存总量
                    </span>
                    <span>{totalLine?.values[hover] == null ? "暂无" : totalLine.values[hover]}</span>
                  </li>
                  <li className="flex items-center justify-between gap-3">
                    <span className="flex items-center gap-1.5 text-ink/70">
                      <span className="inline-block h-2 w-2 rounded-sm" style={{ background: DELTA_POS }} />
                      日增量
                    </span>
                    <span>
                      {deltaLine?.values[hover] == null
                        ? "暂无"
                        : (deltaLine.values[hover] as number) > 0
                          ? `+${deltaLine.values[hover]}`
                          : deltaLine.values[hover]}
                    </span>
                  </li>
                </ul>
              </div>
            ) : null}
          </>
        )}
      </div>
      {hasPoint ? (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[13px] text-ink/70">
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-0.5 w-4" style={{ background: TOTAL_COLOR }} />
            转存总量（左轴）
          </li>
          <li className="flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-3 rounded-sm" style={{ background: DELTA_POS }} />
            日增量（右轴）
          </li>
        </ul>
      ) : null}
    </section>
  );
}
