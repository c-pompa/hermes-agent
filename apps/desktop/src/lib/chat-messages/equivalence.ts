import type { ChatMessage } from './types'

// Compile-time exhaustiveness guards. If a new field is added to ChatMessage
// or a new part type appears in the ChatMessagePart union (e.g. @assistant-ui
// ships one), these fail tsc until someone explicitly classifies it.
//
// COMPARED: fields whose change must trigger a re-render (setMessages).
// IGNORED:  fields that are intentionally not compared — display-only metadata
//           or reference identity the runtime already guarantees.
//   timestamp  — presentation-only (sort/age display), never affects transcript equality
//   attachmentRefs — composer-side metadata; already reconciled in reconcileResumeMessages
//   rowId — durable backend identity; stable for a given row, never changes what's painted
//
// If your new field affects what the user sees in the transcript, add it to
// COMPARED. If it's metadata that shouldn't trigger a re-render, add it to
// IGNORED.
const _chatMessageFieldsExhaustive: {
  [K in Exclude<keyof ChatMessage, (typeof COMPARED_FIELDS)[number] | (typeof IGNORED_FIELDS)[number]>]: never
} = {}

const COMPARED_FIELDS = [
  'id',
  'role',
  'pending',
  'error',
  // Structured failure layer — drives the error card's title and action row,
  // so a change (e.g. resume replay attaching the descriptor) must repaint.
  'errorSurface',
  'hidden',
  'branchGroupId',
  'interim',
  'reactions',
  'timestamp',
  'completedAt',
  // Turn wall-clock duration — stamps the visible "⏱ 38s" badge, so a change
  // must re-render (set once at completion; stable afterwards).
  'durationS'
] as const

const IGNORED_FIELDS = ['attachmentRefs', 'parts', 'rowId'] as const

// Compile-time check: every ChatMessagePart discriminant must be handled by
// chatPartsEquivalent. If @assistant-ui adds a new part type, this fails tsc.
//   text, reasoning      → compared by .text
//   tool-call             → compared by toolCallId/toolName + result presence
//   source, image, file, data, generative-ui, audio, data-* → shallow primitive compare
const _chatMessagePartTypesExhaustive: {
  [T in Exclude<ChatMessage['parts'][number]['type'], (typeof HANDLED_PART_TYPES)[number]>]: never
} = {}

const HANDLED_PART_TYPES = [
  'text',
  'reasoning',
  'tool-call',
  'source',
  'image',
  'file',
  'data',
  'generative-ui',
  'audio'
] as const

// Structural compare WITHOUT JSON.stringify — the only consumer asks "did
// the transcript change, should I call setMessages?", so a slightly
// conservative compare (occasionally false-negative → one extra idempotent
// setMessages) is safe, but a false-POSITIVE (claiming equal when different)
// would skip a needed update.
export function chatPartsEquivalent(aPart: ChatMessage['parts'][number], bPart: ChatMessage['parts'][number]): boolean {
  // Reference equality fast-path
  if (aPart === bPart) {
    return true
  }

  if (aPart.type !== bPart.type) {
    return false
  }

  if (aPart.timestamp !== bPart.timestamp || aPart.completedAt !== bPart.completedAt) {
    return false
  }

  if (aPart.type === 'text' || aPart.type === 'reasoning') {
    return (aPart as { text: string }).text === (bPart as { text: string }).text
  }

  if (aPart.type === 'tool-call') {
    const aCall = aPart as { toolCallId?: string; toolName?: string; result?: unknown }
    const bCall = bPart as { toolCallId?: string; toolName?: string; result?: unknown }

    if (aCall.toolCallId !== bCall.toolCallId || aCall.toolName !== bCall.toolName) {
      return false
    }

    // Compare whether result is present (undefined on both or defined on both)
    const aHasResult = aCall.result !== undefined
    const bHasResult = bCall.result !== undefined

    return aHasResult === bHasResult
  }

  // For all other handled part types (source, image, file, data, generative-ui,
  // audio, data-*), fall back to shallow primitive-key comparison — conservative:
  // if we're not sure, claim not-equal (one extra setMessages is harmless, but
  // skipping an update would break the UI).
  const aPrimitive = aPart as unknown as Record<string, unknown>
  const bPrimitive = bPart as unknown as Record<string, unknown>
  const aKeys = Object.keys(aPrimitive).filter(k => typeof aPrimitive[k] !== 'object' || aPrimitive[k] === null)
  const bKeys = Object.keys(bPrimitive).filter(k => typeof bPrimitive[k] !== 'object' || bPrimitive[k] === null)

  if (aKeys.length !== bKeys.length) {
    return false
  }

  return aKeys.every(k => aPrimitive[k] === bPrimitive[k])
}

export function chatReactionsEquivalent(a: ChatMessage['reactions'], b: ChatMessage['reactions']): boolean {
  const aList = a ?? []
  const bList = b ?? []

  if (aList === bList) {
    return true
  }

  return (
    aList.length === bList.length &&
    aList.every((reaction, index) => reaction.emoji === bList[index].emoji && reaction.author === bList[index].author)
  )
}

export function chatMessagesEquivalent(a: ChatMessage, b: ChatMessage): boolean {
  if (
    a.id !== b.id ||
    a.role !== b.role ||
    a.pending !== b.pending ||
    a.error !== b.error ||
    // Structural compare — the descriptor arrives as a fresh object per
    // resume/replay, so identity comparison would repaint forever.
    (a.errorSurface?.layer ?? null) !== (b.errorSurface?.layer ?? null) ||
    (a.errorSurface?.code ?? null) !== (b.errorSurface?.code ?? null) ||
    (a.errorSurface?.retryable ?? null) !== (b.errorSurface?.retryable ?? null) ||
    a.hidden !== b.hidden ||
    a.branchGroupId !== b.branchGroupId ||
    a.timestamp !== b.timestamp ||
    a.completedAt !== b.completedAt ||
    // Interim gates the action footer, so flipping it must repaint (e.g. a
    // previewed final settling onto a sealed interim bubble restores the bar).
    (a.interim ?? false) !== (b.interim ?? false) ||
    !chatReactionsEquivalent(a.reactions, b.reactions)
  ) {
    return false
  }

  if (a.parts.length !== b.parts.length) {
    return false
  }

  return a.parts.every((part, index) => chatPartsEquivalent(part, b.parts[index]))
}

export function chatMessageArraysEquivalent(a: ChatMessage[], b: ChatMessage[]): boolean {
  // Array-level identity fast-path (same reference)
  if (a === b) {
    return true
  }

  return a.length === b.length && a.every((message, index) => chatMessagesEquivalent(message, b[index]))
}
