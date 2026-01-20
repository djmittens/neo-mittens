import { tool } from "@opencode-ai/plugin"
import { existsSync } from "fs"
import { readdir, readFile } from "fs/promises"

export default tool({
  description: `Show Ralph status for the current repository.
  
Reports: initialization state, spec count, task counts, and latest log.`,
  args: {},
  async execute(args, context) {
    const ralphDir = "ralph"
    const specsDir = `${ralphDir}/specs`
    const planFile = `${ralphDir}/plan.jsonl`
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

    // Parse plan.jsonl for task counts
    if (existsSync(planFile)) {
      const content = await readFile(planFile, "utf-8")
      const lines = content.trim().split("\n").filter(l => l.trim())
      
      let currentSpec = null
      let pending = 0
      let done = 0
      let issues = 0
      
      for (const line of lines) {
        try {
          const obj = JSON.parse(line)
          if (obj.t === "spec") {
            currentSpec = obj.spec
          } else if (obj.t === "task") {
            if (obj.s === "p") pending++
            else if (obj.s === "d") done++
          } else if (obj.t === "issue") {
            issues++
          }
        } catch (e) {
          // Skip malformed lines
        }
      }
      
      results.push(`**Current spec:** ${currentSpec || "none"}`)
      results.push(`**Tasks:** ${pending} pending, ${done} done`)
      if (issues > 0) {
        results.push(`**Issues:** ${issues}`)
      }
    } else {
      results.push("**Tasks:** No plan yet (run `ralph plan <spec>`)")
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
