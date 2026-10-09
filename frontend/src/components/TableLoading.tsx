export default function TableLoading({ colSpan }: { colSpan: number }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-10 text-center text-sm text-ink/45">
        <span className="inline-flex items-center gap-2">
          <span className="loading-spin" aria-hidden="true" />
          正在加载
        </span>
      </td>
    </tr>
  );
}
