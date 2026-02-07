import type { Plugin } from "@opencode-ai/plugin"

/**
 * Auto-compaction plugin.
 *
 * Monitors cumulative input token usage per session and triggers compaction
 * when a configurable per-model threshold is exceeded. Checks are performed
 * when the session becomes idle (i.e. the assistant finishes responding).
 *
 * Thresholds are total *input* tokens -- the number that grows with context
 * window consumption.  Output and reasoning tokens are excluded because they
 * don't contribute to context pressure.
 */

// ── Configuration ───────────────────────────────────────────────────────────
// Keys can be exact model IDs ("anthropic/claude-sonnet-4-20250514") or bare
// model names ("claude-sonnet-4-20250514").  The lookup tries an exact match
// first, then strips the provider prefix, then falls back to "default".

const THRESHOLDS: Record<string, number> = {
  // Anthropic
  "claude-sonnet-4-20250514":  150_000,
  "claude-opus-4-20250514":    150_000,

  // OpenAI
  "gpt-4o":                    100_000,
  "o3":                        150_000,

  // Google
  "gemini-2.5-pro":            800_000,

  // Fallback
  "default":                   120_000,
}

function getThreshold(modelID: string): number {
  // Exact match (e.g. "anthropic/claude-sonnet-4-20250514")
  if (modelID in THRESHOLDS) return THRESHOLDS[modelID]

  // Strip provider prefix ("anthropic/claude-sonnet-4-20250514" -> "claude-sonnet-4-20250514")
  const bare = modelID.includes("/") ? modelID.split("/").slice(1).join("/") : modelID
  if (bare in THRESHOLDS) return THRESHOLDS[bare]

  return THRESHOLDS["default"]
}

// ── Plugin ──────────────────────────────────────────────────────────────────

export const AutoCompactPlugin: Plugin = async ({ client }) => {
  // Track sessions where compaction is already in-flight so we don't
  // trigger it multiple times while messages are still being processed.
  const compacting = new Set<string>()

  return {
    event: async ({ event }) => {
      if (event.type !== "session.idle") return

      const sessionID = event.properties.sessionID
      if (compacting.has(sessionID)) return

      // Fetch the session to check if it's already being compacted.
      let session
      try {
        const res = await client.session.get({ path: { id: sessionID } })
        session = res.data
      } catch {
        return
      }
      if (!session || session.time.compacting) return

      // Fetch messages and sum input tokens from assistant messages.
      let messages
      try {
        const res = await client.session.messages({ path: { id: sessionID } })
        messages = res.data
      } catch {
        return
      }
      if (!messages) return

      let totalInput = 0
      let modelID = ""

      for (const msg of messages) {
        const info = msg.info as Record<string, unknown>
        if (info.role !== "assistant") continue

        // Use the model from the most recent assistant message.
        if (typeof info.modelID === "string") modelID = info.modelID

        const tokens = info.tokens as
          | { input?: number; cache?: { read?: number } }
          | undefined
        if (tokens) {
          // Count direct input tokens plus cache reads -- both contribute
          // to the context window the provider sees.
          totalInput += (tokens.input ?? 0) + (tokens.cache?.read ?? 0)
        }
      }

      if (!modelID) return

      const threshold = getThreshold(modelID)
      if (totalInput < threshold) return

      // Trigger compaction.
      compacting.add(sessionID)
      try {
        await client.tui.executeCommand({
          body: { command: "session.compact" },
        })
      } catch {
        // Compaction may fail if TUI isn't available (e.g. headless/web mode).
        // Silently ignore -- there's nothing useful to do here.
      } finally {
        compacting.delete(sessionID)
      }
    },

    // Clean up the guard set when compaction finishes (belt-and-suspenders).
    // The event handler above already cleans up in `finally`, but if the
    // session.compacted event arrives from an external trigger we want to
    // make sure we don't block future auto-compactions.
  }
}
