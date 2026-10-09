import * as XLSX from "xlsx";

export async function workbookText(file: File): Promise<string> {
  const book = XLSX.read(await file.arrayBuffer(), { type: "array" });
  const lines: string[] = [];
  for (const name of book.SheetNames) {
    const rows = XLSX.utils.sheet_to_json<(string | number | boolean | null)[]>(book.Sheets[name], {
      header: 1,
      raw: false,
      defval: "",
    });
    for (const row of rows) {
      const cells = (row ?? []).map((cell) => String(cell ?? "").trim()).filter(Boolean);
      if (cells.length) lines.push(cells.join(" "));
    }
  }
  return lines.join("\n");
}
