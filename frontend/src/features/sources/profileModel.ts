import type { Profile, SourceSchema } from "../../api";

export const numberText = (value: number) => value.toLocaleString("ru-RU");
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

export function profileModel(schema: SourceSchema, profile: Profile) {
  const fields: ProfileField[] = schema.objects.flatMap((object) =>
    object.fields.map((field) => ({
      name: field.name,
      type: field.inferred_type,
      identifier: field.is_identifier_candidate,
      stats: profile.columns[field.name],
    })),
  );
  const counts = schema.objects.map((object) => object.row_count);
  const totalRows =
    counts.length && counts.every((count) => count !== null)
      ? counts.reduce<number>((sum, count) => sum + (count ?? 0), 0)
      : null;
  const profiled = fields.filter((field) => field.stats !== undefined);
  const filled = profiled.reduce(
    (sum, field) => sum + field.stats!.sample_non_null_count,
    0,
  );
  const missing = profiled.reduce(
    (sum, field) => sum + field.stats!.sample_null_count,
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
    totalRows,
    filled,
    missing,
    profiledCount: profiled.length,
    completeness: ratio(filled, filled + missing),
    types: [...typeCounts].map(([label, count]) => ({ label, count })),
    missingFields: profiled
      .filter((field) => field.stats!.sample_null_count > 0)
      .sort((a, b) => b.stats!.sample_null_count - a.stats!.sample_null_count),
  };
}
export type ProfileModel = ReturnType<typeof profileModel>;

export function sampleDescription(profile: Profile) {
  const count = profile.sample_size;
  const noun =
    count % 10 === 1 && count % 100 !== 11
      ? "строка"
      : [2, 3, 4].includes(count % 10) && ![12, 13, 14].includes(count % 100)
        ? "строки"
        : "строк";
  return `Выборка: ${numberText(count)} ${noun} · до ${numberText(profile.sample_limit)} первых строк`;
}
