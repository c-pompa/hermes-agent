import { describe, expect, it } from 'vitest'

import {
  composeDeliver,
  cronEditorUpdates,
  extractDiscordChannelTarget,
  jobIsScriptOnly,
  parseCronDeliveryTargets,
  slugifyCronChannelName,
  splitDeliver,
  toggleCronDeliveryTarget,
  validateCronEditor
} from './cron-job-model'

describe('jobIsScriptOnly', () => {
  it('is true when no_agent is set and a script is present', () => {
    expect(jobIsScriptOnly({ no_agent: true, script: 'echo hi' })).toBe(true)
  })

  it('is false for agent-backed jobs', () => {
    expect(jobIsScriptOnly({ no_agent: false, script: 'echo hi' })).toBe(false)
    expect(jobIsScriptOnly({ no_agent: true, script: '' })).toBe(false)
    expect(jobIsScriptOnly({ no_agent: true, script: null })).toBe(false)
  })
})

describe('validateCronEditor', () => {
  it('requires prompt and schedule for agent-backed jobs', () => {
    expect(validateCronEditor({ prompt: '', schedule: '', scriptOnlyJob: false })).toBe('prompt_and_schedule')
    expect(validateCronEditor({ prompt: '', schedule: '0 9 * * *', scriptOnlyJob: false })).toBe('prompt')
    expect(validateCronEditor({ prompt: 'go', schedule: '', scriptOnlyJob: false })).toBe('schedule')
  })

  it('allows an empty prompt when editing a script-only job', () => {
    expect(validateCronEditor({ prompt: '', schedule: '0 9 * * 1', scriptOnlyJob: true })).toBe(null)
    expect(validateCronEditor({ prompt: 'optional note', schedule: '0 9 * * 1', scriptOnlyJob: true })).toBe(null)
  })

  it('still requires schedule for script-only jobs', () => {
    expect(validateCronEditor({ prompt: '', schedule: '', scriptOnlyJob: true })).toBe('schedule')
  })
})

describe('cron delivery targets', () => {
  it('parses comma-separated targets and removes duplicates', () => {
    expect(parseCronDeliveryTargets('local, telegram,local')).toEqual(['local', 'telegram'])
  })

  it('falls back to local for an empty stored value', () => {
    expect(parseCronDeliveryTargets('')).toEqual(['local'])
  })

  it('adds a second target in the scheduler comma-separated format', () => {
    expect(toggleCronDeliveryTarget('local', 'origin', true)).toBe('local,origin')
  })

  it('removes one target while keeping the other selection', () => {
    expect(toggleCronDeliveryTarget('local,origin', 'local', false)).toBe('origin')
  })

  it('does not allow the final delivery target to be unchecked', () => {
    expect(toggleCronDeliveryTarget('origin', 'origin', false)).toBe('origin')
  })
})

describe('cronEditorUpdates', () => {
  it('omits prompt when saving a script-only job with an empty prompt', () => {
    expect(
      cronEditorUpdates(
        { deliver: 'local', discordChannelId: null, model: '', name: 'Weekly', prompt: '', provider: '', schedule: '0 9 * * 1' },
        { scriptOnlyJob: true }
      )
    ).toEqual({
      deliver: 'local',
      name: 'Weekly',
      schedule: '0 9 * * 1'
    })
  })

  it('includes prompt when the user typed one on a script-only job', () => {
    expect(
      cronEditorUpdates(
        { deliver: 'email', discordChannelId: null, model: '', name: 'Weekly', prompt: 'note', provider: '', schedule: '0 9 * * 1' },
        { scriptOnlyJob: true }
      ).prompt
    ).toBe('note')
  })

  it('writes the model override for agent jobs', () => {
    const updates = cronEditorUpdates(
      {
        deliver: 'local',
        discordChannelId: null,
        model: 'claude-sonnet-4',
        name: 'Daily',
        prompt: 'go',
        provider: 'anthropic',
        schedule: '0 9 * * *'
      },
      { scriptOnlyJob: false }
    )

    expect(updates.model).toBe('claude-sonnet-4')
    expect(updates.provider).toBe('anthropic')
  })

  it('clears a previous pin when the override is reset to default', () => {
    const updates = cronEditorUpdates(
      { deliver: 'local', discordChannelId: null, model: '', name: 'Daily', prompt: 'go', provider: '', schedule: '0 9 * * *' },
      { scriptOnlyJob: false }
    )

    expect(updates.model).toBe(null)
    expect(updates.provider).toBe(null)
  })

  it('never touches model fields on script-only jobs', () => {
    const updates = cronEditorUpdates(
      { deliver: 'local', discordChannelId: null, model: 'x', name: 'Weekly', prompt: '', provider: 'y', schedule: '0 9 * * 1' },
      { scriptOnlyJob: true }
    )

    expect('model' in updates).toBe(false)
    expect('provider' in updates).toBe(false)
  })

  it('composes the deliver target with the picked Discord channel', () => {
    const updates = cronEditorUpdates(
      {
        deliver: 'local',
        discordChannelId: '123',
        model: '',
        name: 'Daily',
        prompt: 'go',
        provider: '',
        schedule: '0 9 * * *'
      },
      { scriptOnlyJob: false }
    )

    expect(updates.deliver).toBe('local,discord:123')
  })
})

describe('splitDeliver', () => {
  it('splits comma-separated targets and drops empties', () => {
    expect(splitDeliver('local, discord:123 ,,origin')).toEqual(['local', 'discord:123', 'origin'])
    expect(splitDeliver('')).toEqual([])
  })
})

describe('extractDiscordChannelTarget', () => {
  it('returns the channel id from a discord target', () => {
    expect(extractDiscordChannelTarget('local,discord:123')).toBe('123')
    expect(extractDiscordChannelTarget('discord:123')).toBe('123')
  })

  it('returns null when no discord target is present', () => {
    expect(extractDiscordChannelTarget('local,origin')).toBe(null)
    expect(extractDiscordChannelTarget('')).toBe(null)
    expect(extractDiscordChannelTarget('discord:')).toBe(null)
  })
})

describe('composeDeliver', () => {
  it('appends the Discord channel to local', () => {
    expect(composeDeliver('local', '123')).toBe('local,discord:123')
  })

  it('appends the Discord channel to origin', () => {
    expect(composeDeliver('origin', '123')).toBe('origin,discord:123')
  })

  it('strips only the discord target when toggled off', () => {
    expect(composeDeliver('local,discord:123', null)).toBe('local')
    expect(composeDeliver('origin,discord:123', null)).toBe('origin')
  })

  it('replaces a pre-existing discord target instead of duplicating it', () => {
    expect(composeDeliver('local,discord:111', '222')).toBe('local,discord:222')
  })

  it('falls back to local for an empty base', () => {
    expect(composeDeliver('', '123')).toBe('local,discord:123')
    expect(composeDeliver('', null)).toBe('local')
    expect(composeDeliver('discord:123', null)).toBe('local')
  })

  it('never emits duplicate or comma-dangling entries', () => {
    expect(composeDeliver('local,local,', null)).toBe('local')
    expect(composeDeliver('local,,discord:123', '123')).toBe('local,discord:123')
  })

  it('is idempotent', () => {
    const once = composeDeliver('local', '123')

    expect(composeDeliver(once, '123')).toBe(once)
    expect(composeDeliver(composeDeliver(once, '123'), '123')).toBe(once)
  })
})

describe('slugifyCronChannelName', () => {
  it('slugifies a job name into the cron channel name', () => {
    expect(slugifyCronChannelName('LM Studio Release Review & Upgrade Advisor')).toBe(
      'cron-lm-studio-release-review-upgrade-advisor'
    )
  })

  it('collapses dashes and strips unsafe characters', () => {
    expect(slugifyCronChannelName('  Weird   Name!! (v2) ')).toBe('cron-weird-name-v2')
    expect(slugifyCronChannelName('')).toBe('cron-')
  })
})
