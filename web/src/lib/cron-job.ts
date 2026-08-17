import type { CronJob, CronJobMutation } from "./api";

export interface CronJobFormState {
  name: string;
  prompt: string;
  schedule: string;
  /** Base delivery target(s); any `discord:<id>` entries are stripped on save. */
  deliver: string;
  /** Picked Discord results channel id (null/"" = no Discord export). */
  discordChannelId: string | null;
  skills: string[];
  provider: string;
  model: string;
  base_url: string;
  script: string;
  no_agent: boolean;
  context_from: string;
  continuity: boolean;
  enabled_toolsets: string[];
  workdir: string;
}

const DISCORD_TARGET_PREFIX = "discord:";
const DEFAULT_DELIVER_TARGET = "local";

/** Split a comma-separated deliver target string into trimmed, non-empty entries. */
export function splitDeliver(deliver: string): string[] {
  return deliver
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

/** The Discord channel id a deliver string posts to (`discord:<id>`), or null. */
export function extractDiscordChannelTarget(deliver: string): string | null {
  for (const entry of splitDeliver(deliver)) {
    if (entry.startsWith(DISCORD_TARGET_PREFIX)) {
      const id = entry.slice(DISCORD_TARGET_PREFIX.length);
      if (id) return id;
    }
  }
  return null;
}

// Compose the stored deliver string from the base target(s) plus the optional
// Discord channel export. Discord output is always additive: non-Discord
// targets pass through untouched, any stale `discord:<id>` entries are dropped
// first, and the picked channel is appended once. An empty base falls back to
// "local" so the result is never an empty/duplicate/comma-dangling string.
export function composeDeliver(
  baseDeliver: string,
  discordChannelId: string | null,
): string {
  const base = splitDeliver(baseDeliver).filter(
    (entry) => !entry.startsWith(DISCORD_TARGET_PREFIX),
  );
  const targets = [...new Set(base.length > 0 ? base : [DEFAULT_DELIVER_TARGET])];
  if (discordChannelId) targets.push(`${DISCORD_TARGET_PREFIX}${discordChannelId}`);
  return targets.join(",");
}

// Client-side mirror of the backend's cron channel naming: lowercase,
// spaces → "-", strip chars outside [a-z0-9_-], collapse dashes, prefix
// "cron-". "LM Studio Release Review & Upgrade Advisor" →
// "cron-lm-studio-release-review-upgrade-advisor".
export function slugifyCronChannelName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
  return `cron-${slug}`;
}

/** Split a comma/newline list (or array) into trimmed, non-empty items. */
export function splitCronList(value: unknown): string[] {
  const items = Array.isArray(value)
    ? value
    : typeof value === "string"
      ? value.split(/[\n,]/)
      : [];
  return items.map((item) => String(item).trim()).filter(Boolean);
}

/** Trim to a non-empty string, or null. Optionally strip trailing slashes
 * (base URLs). Mirrors the backend's `_cron_optional_text`. */
function optionalText(value: string, stripTrailingSlash = false): string | null {
  const text = stripTrailingSlash ? value.trim().replace(/\/+$/, "") : value.trim();
  return text || null;
}

/** Read a stored string field as a plain string ("" when absent). */
function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Build the create/update payload. Optional fields collapse to null so an
 * update explicitly clears them rather than leaving stale values. */
export function buildCronJobPayload(form: CronJobFormState): CronJobMutation {
  // The `continuity` toggle is stored as the reserved "self" entry in
  // context_from (the job's own previous output). Users never type "self" —
  // the checkbox is the surface; strip any hand-typed variant first.
  const contextFrom = splitCronList(form.context_from).filter(
    (item) => item.toLowerCase() !== "self",
  );
  if (form.continuity) contextFrom.push("self");
  const enabledToolsets = form.enabled_toolsets.filter(Boolean);
  return {
    name: form.name.trim(),
    prompt: form.prompt.trim(),
    schedule: form.schedule.trim(),
    deliver: composeDeliver(form.deliver, form.discordChannelId || null),
    skills: form.skills.filter(Boolean),
    provider: optionalText(form.provider),
    model: optionalText(form.model),
    base_url: optionalText(form.base_url, true),
    script: optionalText(form.script),
    no_agent: Boolean(form.no_agent),
    context_from: contextFrom.length > 0 ? contextFrom : null,
    enabled_toolsets: enabledToolsets.length > 0 ? enabledToolsets : null,
    workdir: optionalText(form.workdir),
  };
}

export function cronJobHasExecutionContent(
  job: Pick<CronJobMutation, "prompt" | "skills" | "script">,
): boolean {
  const skills = Array.isArray(job.skills) ? job.skills.filter(Boolean) : [];
  return Boolean(asString(job.prompt).trim() || asString(job.script).trim() || skills.length);
}

export function cronJobFormFromJob(job: CronJob): CronJobFormState {
  const storedRefs = splitCronList(job.context_from);
  // Raw store records carry the reserved "self" entry inside context_from;
  // tool/RPC-formatted records strip it and set an explicit continuity flag.
  const continuity =
    Boolean((job as { continuity?: boolean }).continuity) ||
    storedRefs.some((item) => item.toLowerCase() === "self");
  const externalRefs = storedRefs.filter((item) => item.toLowerCase() !== "self");
  const deliver = asString(job.deliver);
  return {
    name: asString(job.name),
    prompt: asString(job.prompt),
    schedule:
      asString(job.schedule?.expr) ||
      asString(job.schedule?.run_at) ||
      asString(job.schedule_display),
    // Split the stored deliver string: the base target(s) go to the picker, a
    // `discord:<id>` entry (if any) seeds the Discord export toggle.
    deliver: composeDeliver(deliver, null),
    discordChannelId: extractDiscordChannelTarget(deliver),
    skills: Array.isArray(job.skills) ? job.skills.filter(Boolean) : [],
    provider: asString(job.provider),
    model: asString(job.model),
    base_url: asString(job.base_url),
    script: asString(job.script),
    no_agent: Boolean(job.no_agent),
    context_from: externalRefs.join("\n"),
    continuity,
    enabled_toolsets: splitCronList(job.enabled_toolsets),
    workdir: asString(job.workdir),
  };
}
