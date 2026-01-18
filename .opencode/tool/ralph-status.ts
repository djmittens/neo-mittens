import { tool } from "@opencode-ai/plugin"
import { existsSync } from "fs"
import { readdir } from "fs/promises"

export default tool({
  description: `Show Ralph status for the current repository.
  
Reports: initialization state, spec count, task counts, and latest log.`,
  args: {},
  async execute(args, context) {
    const ralphDir = ".ralph"
    const specsDir = `${ralphDir}/specs`
    const planFile = `${ralphDir}/IMPLEMENTATION_PLAN.md`
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

    // Count tasks
    if (existsSync(planFile)) {
      const content = await Bun.file(planFile).text()
      const pending = (content.match(/^- \[ \]/gm) || []).length
      const completed = (content.match(/^- \[x\]/gim) || []).length
      results.push(`**Tasks:** ${pending} pending, ${completed} completed`)
    } else {
      results.push("**Tasks:** No implementation plan yet")
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
