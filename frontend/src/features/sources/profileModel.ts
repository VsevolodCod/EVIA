import type { Profile, SourceSchema } from "../../api";

export const numberText = (value: number) => value.toLocaleString("ru-RU");
export function rowsText(count: number) {
  const remainder = Math.abs(count) % 100;
  const lastDigit = remainder % 10;
  const noun = remainder > 10 && remainder < 20
    ? "строк"
    : lastDigit === 1
      ? "строка"
      : lastDigit > 1 && lastDigit < 5
        ? "строки"
        : "строк";
  return `${numberText(count)} ${noun}`;
}
export const percentText = (value: number | null) =>
  value === null
    ? "—"
    : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
export const ratio = (part: number, total: number) =>
  total > 0 ? (part / total) * 100 : null;
export const typeNames: Record<string, string> = {
  string: "Текст",
  integer: "Целое число",
  number: "Число",
  float: "Число",
  boolean: "Да / нет",
  date: "Дата",
  datetime: "Дата и время",
  unknown: "Не определён",
};
export const typeLabel = (type: string) => typeNames[type] ?? type;
export type ProfileField = {
  name: string;
  type: string;
  identifier: boolean;
  stats?: Profile["columns"][string];
};

export type ExactColumnProfile = Extract<Profile, { coverage: "full" }>["columns"][string];

export function hasExactStats(
  stats: Profile["columns"][string],
): stats is ExactColumnProfile {
  return "non_null_count" in stats;
}

export function profileModel(schema: SourceSchema, profile: Profile) {
  const fields: ProfileField[] = schema.objects.flatMap((object) =>
    object.fields.map((field) => {
      const stats = profile.columns[field.name];
      return {
        name: field.name,
        type: field.inferred_type,
        identifier: stats && hasExactStats(stats)
          ? stats.is_identifier_candidate
          : field.is_identifier_candidate,
        stats,
      };
    }),
  );
  const counts = schema.objects.map((object) => object.row_count);
  const totalRows =
    counts.length && counts.every((count) => count !== null)
      ? counts.reduce<number>((sum, count) => sum + (count ?? 0), 0)
      : null;
  const profiled = fields.filter((field) => field.stats !== undefined);
  const exact = profile.coverage === "full";
  const filled = profiled.reduce(
    (sum, field) => sum + (exact ? (field.stats! as ExactColumnProfile).non_null_count : field.stats!.sample_non_null_count),
    0,
  );
  const missing = profiled.reduce(
    (sum, field) => sum + (exact ? (field.stats! as ExactColumnProfile).null_count : field.stats!.sample_null_count),
    0,
  );
  const typeCounts = new Map<string, number>();
  fields.forEach((field) =>
    typeCounts.set(
      typeLabel(field.type),
      (typeCounts.get(typeLabel(field.type)) ?? 0) + 1,
    ),
  );
  return {
    fields,
    coverage: profile.coverage,
    totalRows,
    filled,
    missing,
    profiledCount: profiled.length,
    completeness: ratio(filled, filled + missing),
    types: [...typeCounts].map(([label, count]) => ({ label, count })),
    missingFields: profiled
      .filter((field) => exact
        ? (field.stats! as ExactColumnProfile).null_count > 0
        : field.stats!.sample_null_count > 0)
      .sort((a, b) => exact
        ? (b.stats! as ExactColumnProfile).null_count - (a.stats! as ExactColumnProfile).null_count
        : b.stats!.sample_null_count - a.stats!.sample_null_count),
  };
}
export type ProfileModel = ReturnType<typeof profileModel>;

export function sampleDescription(profile: Profile) {
  return `Выборка: ${rowsText(profile.sample_size)} · до ${numberText(profile.sample_limit)} первых строк`;
}
