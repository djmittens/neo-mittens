import { tool } from "@opencode-ai/plugin"
import { existsSync } from "fs"
import { readdir, readFile } from "fs/promises"
import { execSync } from "child_process"

export default tool({
  description: `Show Ralph status for the current repository.
  
Reports: initialization state, spec count, task counts, and latest log.`,
  args: {},
  async execute(args, context) {
    const ralphDir = "ralph"
    const specsDir = `${ralphDir}/specs`
    const stateFile = ".tix/ralph-state.json"
    const logsDir = "build/ralph-logs"

    // Check if initialized
    if (!existsSync(ralphDir)) {
      return "Ralph not initialized. Run `ralph init` or use /ralph-init first."
    }

    const results: string[] = ["## Ralph Status", ""]

    // Count specs
    let specCount = 0
    if (existsSync(specsDir)) {
      const files = await readdir(specsDir)
      specCount = files.filter(f => f.endsWith(".md")).length
    }
    results.push(`**Specs:** ${specCount} files`)

    // Read orchestration state from ralph-state.json
    let stage = "PLAN"
    let spec: string | null = null
    if (existsSync(stateFile)) {
      try {
        const content = await readFile(stateFile, "utf-8")
        const state = JSON.parse(content)
        stage = state.stage || "PLAN"
        spec = state.spec || null
      } catch {
        // Ignore parse errors
      }
    }

    if (spec) {
      results.push(`**Current spec:** ${spec}`)
    }
    results.push(`**Stage:** ${stage}`)

    // Get ticket counts from tix CLI
    try {
      const queryOutput = execSync("tix query", {
        encoding: "utf-8",
        timeout: 5000,
      }).trim()

      const state = JSON.parse(queryOutput)
      const pending = state.tasks?.pending?.length || 0
      const done = state.tasks?.done?.length || 0
      const issues = state.issues?.length || 0

      results.push(`**Tasks:** ${pending} pending, ${done} done`)
      if (issues > 0) {
        results.push(`**Issues:** ${issues}`)
      }
    } catch {
      // tix not available — check if initialized
      if (existsSync(".tix")) {
        results.push("**Tasks:** tix query failed (binary may need building)")
      } else {
        results.push("**Tasks:** No plan yet (run `ralph plan <spec>`)")
      }
    }

    // Find latest log
    if (existsSync(logsDir)) {
      const files = await readdir(logsDir)
      const logs = files.filter(f => f.startsWith("ralph-") && f.endsWith(".log"))
      if (logs.length > 0) {
        logs.sort().reverse()
        results.push(`**Latest log:** ${logsDir}/${logs[0]}`)
      }
    }

    return results.join("\n")
  },
})
