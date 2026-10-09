import { useState } from "react";
import type { TransferLine } from "../api";

const COLORS = ["#0f766e", "#c2410c", "#1d4ed8", "#a21caf", "#a16207", "#0e7490", "#be123c", "#4d7c0f"];
const WIDTH = 720;
const HEIGHT = 280;
const PAD = { top: 16, right: 16, bottom: 32, left: 48 };

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

export default function TransferChart({
  dates,
  lines,
  mode,
  start,
  end,
}: {
  dates: string[];
  lines: TransferLine[];
  mode: string;
  start: string;
  end: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const numbers = lines.flatMap((line) => line.values.filter((value): value is number => value != null));
  const hasPoint = numbers.length > 0;
  const bounds = niceBounds(hasPoint ? numbers : [0]);
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const xAt = (index: number) => PAD.left + (dates.length <= 1 ? plotW / 2 : (index / (dates.length - 1)) * plotW);
  const yAt = (value: number) => PAD.top + ((bounds.max - value) / (bounds.max - bounds.min || 1)) * plotH;
  const ticks: number[] = [];
  for (let tick = bounds.min; tick <= bounds.max + 0.001; tick += bounds.step) ticks.push(tick);
  const caption =
    mode === "history"
      ? "每个点是当天结束时，该账号全部分享的累计转存。"
      : "每个点是当天相对前一天新增的转存。没有前一天快照的日期留空。";

  return (
    <section className="mt-4 rounded-2xl border border-line bg-white p-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">转存趋势</h2>
          <p className="mt-1 h-10 text-[13px] leading-5 text-ink/55">{caption}</p>
        </div>
        <p className="shrink-0 pt-1 text-[13px] text-ink/45">
          {start} 至 {end}
        </p>
      </div>
      <div className="relative mt-3 aspect-[720/280]">
        {!hasPoint ? (
          <p className="flex h-full items-center justify-center text-sm text-ink/45">
            {lines.length === 0 ? "还没有百度账号。" : "这段日期还没有可绘制的转存快照。"}
          </p>
        ) : (
          <>
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="h-full w-full"
            role="img"
            aria-label="转存趋势折线图"
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
            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={PAD.left} x2={WIDTH - PAD.right} y1={yAt(tick)} y2={yAt(tick)} stroke="#e7e5e4" />
                <text x={PAD.left - 8} y={yAt(tick) + 4} textAnchor="end" fill="#78716c" fontSize="11">
                  {String(tick)}
                </text>
              </g>
            ))}
            {lines.map((line, lineIndex) => {
              const color = COLORS[lineIndex % COLORS.length];
              const segments: number[][] = [];
              let current: number[] = [];
              line.values.forEach((value, index) => {
                if (value == null) {
                  if (current.length) segments.push(current);
                  current = [];
                  return;
                }
                current.push(index);
              });
              if (current.length) segments.push(current);
              return (
                <g key={line.account_id}>
                  {segments.map((segment) =>
                    segment.length > 1 ? (
                      <polyline
                        key={segment[0]}
                        fill="none"
                        stroke={color}
                        strokeWidth="2"
                        points={segment.map((index) => `${xAt(index)},${yAt(line.values[index] as number)}`).join(" ")}
                      />
                    ) : null,
                  )}
                  {line.values.map((value, index) =>
                    value == null ? null : <circle key={index} cx={xAt(index)} cy={yAt(value)} r="3.5" fill={color} />,
                  )}
                </g>
              );
            })}
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
                {lines.map((line, lineIndex) => (
                  <li key={line.account_id} className="flex items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-1.5 text-ink/70">
                      <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: COLORS[lineIndex % COLORS.length] }} />
                      <span className="max-w-28 truncate">{line.account_name}</span>
                    </span>
                    <span>{line.values[hover] == null ? "暂无" : line.values[hover]}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          </>
        )}
      </div>
      {lines.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[13px] text-ink/70">
          {lines.map((line, index) => (
            <li key={line.account_id} className="flex items-center gap-1.5">
              <span className="inline-block h-2 w-2 rounded-full" style={{ background: COLORS[index % COLORS.length] }} />
              {line.account_name}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
