import type { CronJob, CronJobUpdates } from '@/types/hermes'

const asText = (value: unknown): string => (typeof value === 'string' ? value : '')

const DISCORD_TARGET_PREFIX = 'discord:'
const DEFAULT_DELIVER_TARGET = 'local'

/** Split a comma-separated deliver target string into trimmed, non-empty entries. */
export function splitDeliver(deliver: string): string[] {
  return deliver
    .split(',')
    .map(entry => entry.trim())
    .filter(Boolean)
}

/** The Discord channel id a deliver string posts to (`discord:<id>`), or null. */
export function extractDiscordChannelTarget(deliver: string): string | null {
  for (const entry of splitDeliver(deliver)) {
    if (entry.startsWith(DISCORD_TARGET_PREFIX)) {
      const id = entry.slice(DISCORD_TARGET_PREFIX.length)

      if (id) {
        return id
      }
    }
  }

  return null
}

// Compose the stored deliver string from the base target(s) plus the optional
// Discord channel export. Discord output is always additive: non-Discord
// targets pass through untouched, any stale `discord:<id>` entries are dropped
// first, and the picked channel is appended once. An empty base falls back to
// 'local' so the result is never an empty/duplicate/comma-dangling string.
export function composeDeliver(baseDeliver: string, discordChannelId: string | null): string {
  const base = splitDeliver(baseDeliver).filter(entry => !entry.startsWith(DISCORD_TARGET_PREFIX))
  const targets = [...new Set(base.length > 0 ? base : [DEFAULT_DELIVER_TARGET])]

  if (discordChannelId) {
    targets.push(`${DISCORD_TARGET_PREFIX}${discordChannelId}`)
  }

  return targets.join(',')
}

// Client-side mirror of the backend's cron channel naming: lowercase,
// spaces → '-', strip chars outside [a-z0-9_-], collapse dashes, prefix
// 'cron-'. "LM Studio Release Review & Upgrade Advisor" →
// 'cron-lm-studio-release-review-upgrade-advisor'.
export function slugifyCronChannelName(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9_-]/g, '')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')

  return `cron-${slug}`
}

/** Script-only cron jobs run a shell script on schedule with no LLM prompt. */
export function jobIsScriptOnly(job: Pick<CronJob, 'no_agent' | 'script'>): boolean {
  return Boolean(job.no_agent) && Boolean(asText(job.script).trim())
}

export type CronEditorValidationError = 'prompt' | 'prompt_and_schedule' | 'schedule'

export interface CronEditorValidationInput {
  prompt: string
  schedule: string
  scriptOnlyJob: boolean
}

export function validateCronEditor(input: CronEditorValidationInput): CronEditorValidationError | null {
  const trimmedPrompt = input.prompt.trim()
  const trimmedSchedule = input.schedule.trim()

  if (!trimmedSchedule && !trimmedPrompt && !input.scriptOnlyJob) {
    return 'prompt_and_schedule'
  }

  if (!trimmedSchedule) {
    return 'schedule'
  }

  if (!input.scriptOnlyJob && !trimmedPrompt) {
    return 'prompt'
  }

  return null
}

export interface CronEditorSaveValues {
  /** Base delivery target(s); any `discord:<id>` entries are stripped on save. */
  deliver: string
  /** Picked Discord results channel id (null = no Discord export). */
  discordChannelId: null | string
  /** Per-job model override ('' = follow the global default at fire time). */
  model: string
  name: string
  prompt: string
  /** Provider for the model override ('' = none). Always paired with model. */
  provider: string
  schedule: string
}

/** Build the API update payload, preserving an empty prompt on script-only jobs. */
export function cronEditorUpdates(values: CronEditorSaveValues, options: { scriptOnlyJob: boolean }): CronJobUpdates {
  const updates: CronJobUpdates = {
    deliver: composeDeliver(values.deliver, values.discordChannelId),
    name: values.name,
    schedule: values.schedule.trim()
  }

  const trimmedPrompt = values.prompt.trim()

  if (!options.scriptOnlyJob || trimmedPrompt) {
    updates.prompt = trimmedPrompt
  }

  // Script-only jobs never run an agent, so the scheduler ignores model
  // overrides — leave whatever is stored untouched. For agent jobs, always
  // write both axes so resetting to "default" clears a previous pin (the
  // backend normalizes null/'' to "no override").
  if (!options.scriptOnlyJob) {
    updates.model = values.model.trim() || null
    updates.provider = values.provider.trim() || null
  }

  return updates
}
