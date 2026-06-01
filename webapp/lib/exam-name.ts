export function formatExamDisplayName(value?: string | null): string {
  const raw = (value || "").trim()
  if (!raw) return "Đề thi"

  const normalized = raw.replace(/[-\s]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase()
  const numberedExam = normalized.match(/^de_so_(\d+)$/)
  if (numberedExam) {
    return `Đề số ${Number(numberedExam[1])}`
  }

  if (["de", "de_thi", "exam"].includes(normalized)) {
    return "Đề thi"
  }

  return raw
}
