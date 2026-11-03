export const usd = new Intl.NumberFormat("fr-FR", {
  style: "currency",
  currency: "USD",
  currencyDisplay: "narrowSymbol",
  maximumFractionDigits: 3, // les appels IA coûtent souvent moins d'un centime
});

export const dateTime = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });
export const longDate = new Intl.DateTimeFormat("fr-FR", { dateStyle: "long" });

/** Durée en `m:ss` (pistes audio). */
export function clock(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Titre affiché sans pictogrammes : l'interface n'a pas d'emoji, même quand l'IA en met dans un titre. */
export function plainTitle(title: string): string {
  return title.replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, "").replace(/\s{2,}/g, " ").trim();
}

/** Durée en clair : « 45 s », « 7 min 30 s », « 1 h 48 min ». */
export function durationText(totalSeconds: number): string {
  const seconds = Math.round(totalSeconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h && `${h} h`, m && `${m} min`, s && `${s} s`].filter(Boolean).join(" ") || "0 s";
}
