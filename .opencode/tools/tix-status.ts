import { tool } from "@opencode-ai/plugin"
import { existsSync } from "fs"
import { readFile } from "fs/promises"
import { execSync } from "child_process"

export default tool({
  description: `Show tix status for the current repository.
  
Reports: task counts, pending tasks, open issues, and current branch.`,
  args: {},
  async execute(args, context) {
    // Check if tix is available
    try {
      execSync("which tix", { stdio: "pipe" })
    } catch {
      return "tix not found in PATH. Build with: cd app/tix && make build && make install"
    }

    // Check if initialized
    if (!existsSync(".tix")) {
      return "tix not initialized. Run `tix init` first."
    }

    // Run tix query for full state
    try {
      const queryOutput = execSync("tix query", {
        encoding: "utf-8",
        timeout: 5000,
      }).trim()

      const state = JSON.parse(queryOutput)
      const results: string[] = ["## tix Status", ""]

      // Branch info
      if (state.meta) {
        results.push(`**Branch:** ${state.meta.branch} (${state.meta.commit})`)
      }

      // Task counts
      const pendingTasks = state.tasks?.pending?.length || 0
      const doneTasks = state.tasks?.done?.length || 0
      results.push(`**Tasks:** ${pendingTasks} pending, ${doneTasks} done`)

      // List pending tasks
      if (pendingTasks > 0) {
        results.push("", "### Pending Tasks")
        for (const task of state.tasks.pending.slice(0, 10)) {
          const prio = task.priority && task.priority !== "none" 
            ? ` [${task.priority.toUpperCase()}]` 
            : ""
          results.push(`- ${task.id}: ${task.name}${prio}`)
        }
        if (pendingTasks > 10) {
          results.push(`- ... and ${pendingTasks - 10} more`)
        }
      }

      // Issues
      const issues = state.issues?.length || 0
      if (issues > 0) {
        results.push("", "### Open Issues")
        for (const issue of state.issues.slice(0, 5)) {
          results.push(`- ${issue.id}: ${issue.name}`)
        }
      }

      // Notes
      const notes = state.notes?.length || 0
      if (notes > 0) {
        results.push(`**Notes:** ${notes}`)
      }

      return results.join("\n")
    } catch (e: any) {
      return `tix query failed: ${e.message}`
    }
  },
})
