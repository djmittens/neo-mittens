import { tool } from "@opencode-ai/plugin"

const CONFIG_PATH = `${process.env.HOME}/.config/opencode/jira-credentials.json`

interface TeamDefaults {
  label?: string
  scrum_team_field?: string
  scrum_team_value?: string
  scrum_team_option_id?: string
  epic_link_field?: string
  sprint_field?: string
}

interface JiraConfig {
  base_url: string
  pat: string
  project?: string
  board_id?: number
  team_defaults?: TeamDefaults
}

let _cachedConfig: JiraConfig | null = null

/**
 * Load Jira config from ~/.config/opencode/jira-credentials.json
 */
async function loadConfig(): Promise<JiraConfig> {
  if (_cachedConfig) return _cachedConfig

  try {
    const file = Bun.file(CONFIG_PATH)
    const content = await file.json()
    if (!content.pat) {
      throw new Error("Missing 'pat' field in config")
    }
    _cachedConfig = {
      base_url: content.base_url || "https://jira.creditkarma.com",
      pat: content.pat,
      project: content.project || "FAB",
      board_id: content.board_id || 1990,
      team_defaults: content.team_defaults || {},
    }
    return _cachedConfig
  } catch (err: any) {
    if (err?.code === "ENOENT" || err?.message?.includes("No such file")) {
      throw new Error(
        `Jira credentials file not found at ${CONFIG_PATH}\n\n` +
          "Create it with:\n\n" +
          `  cat > ${CONFIG_PATH} << 'EOF'\n` +
          "  {\n" +
          '    "pat": "your-personal-access-token",\n' +
          '    "base_url": "https://jira.creditkarma.com",\n' +
          '    "project": "FAB",\n' +
          '    "board_id": 1990\n' +
          "  }\n" +
          "  EOF\n" +
          `  chmod 600 ${CONFIG_PATH}\n\n` +
          "To create a PAT:\n" +
          "1. Go to https://jira.creditkarma.com/secure/ViewProfile.jspa\n" +
          "2. Click 'Personal Access Tokens' in the left sidebar\n" +
          "3. Click 'Create token', give it a name, and copy the value"
      )
    }
    throw new Error(`Failed to read Jira config at ${CONFIG_PATH}: ${err?.message}`)
  }
}

function getBaseUrl(): string {
  return _cachedConfig?.base_url || "https://jira.creditkarma.com"
}

function getApiUrl(): string {
  return `${getBaseUrl()}/rest/api/2`
}

function getAgileApiUrl(): string {
  return `${getBaseUrl()}/rest/agile/1.0`
}

function getDefaultProject(): string {
  return _cachedConfig?.project || "FAB"
}

function getDefaultBoardId(): number {
  return _cachedConfig?.board_id || 1990
}

function getTeamDefaults(): TeamDefaults {
  return _cachedConfig?.team_defaults || {}
}

/**
 * Make authenticated request to Jira REST API
 */
async function jiraApi(
  endpoint: string,
  options: RequestInit = {},
  baseUrl?: string
): Promise<any> {
  const config = await loadConfig()
  const resolvedBase = baseUrl || getApiUrl()

  const headers: Record<string, string> = {
    Authorization: `Bearer ${config.pat}`,
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(options.headers as Record<string, string>),
  }

  const url = endpoint.startsWith("http") ? endpoint : `${resolvedBase}${endpoint}`

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Jira API error (${response.status}): ${error}`)
  }

  // Some endpoints return 204 No Content
  if (response.status === 204) {
    return { success: true }
  }

  return response.json()
}

/**
 * Format an issue for display
 */
function formatIssue(issue: any, verbose = false): string {
  const fields = issue.fields || {}
  const key = issue.key
  const summary = fields.summary || "No summary"
  const status = fields.status?.name || "Unknown"
  const assignee = fields.assignee?.displayName || "Unassigned"
  const reporter = fields.reporter?.displayName || "Unknown"
  const priority = fields.priority?.name || "None"
  const type = fields.issuetype?.name || "Unknown"
  const created = fields.created ? new Date(fields.created).toLocaleDateString() : "Unknown"
  const updated = fields.updated ? new Date(fields.updated).toLocaleDateString() : "Unknown"
  const labels = fields.labels?.length > 0 ? fields.labels.join(", ") : "None"
  const components = fields.components?.length > 0
    ? fields.components.map((c: any) => c.name).join(", ")
    : "None"
  const sprint = fields.sprint?.name || (fields.customfield_10007?.[0]?.name) || "None"
  const storyPoints = fields.story_points || fields.customfield_10004 || "N/A"
  const link = `${getBaseUrl()}/browse/${key}`

  let result = `### [${key}](${link}) — ${summary}
- **Type:** ${type} | **Status:** ${status} | **Priority:** ${priority}
- **Assignee:** ${assignee} | **Reporter:** ${reporter}
- **Labels:** ${labels} | **Components:** ${components}
- **Sprint:** ${sprint} | **Story Points:** ${storyPoints}
- **Created:** ${created} | **Updated:** ${updated}`

  if (verbose && fields.description) {
    result += `\n\n**Description:**\n${fields.description}`
  }

  if (verbose && fields.comment?.comments?.length > 0) {
    result += `\n\n**Comments (${fields.comment.comments.length}):**`
    for (const comment of fields.comment.comments.slice(-5)) {
      const author = comment.author?.displayName || "Unknown"
      const date = new Date(comment.created).toLocaleDateString()
      result += `\n\n> **${author}** (${date}):\n> ${comment.body?.replace(/\n/g, "\n> ")}`
    }
  }

  return result
}

// ─── Issue Operations ────────────────────────────────────────────────

export const get_issue = tool({
  description: `Get detailed information about a Jira issue by its key (e.g., FAB-1234).
  
Returns issue details including summary, status, assignee, description, and recent comments.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
    include_comments: tool.schema
      .boolean()
      .optional()
      .default(true)
      .describe("Include comments (default: true)"),
  },
  async execute(args) {
    const { issue_key, include_comments = true } = args

    const fields = [
      "summary", "status", "assignee", "reporter", "priority",
      "issuetype", "description", "labels", "components", "created",
      "updated", "sprint", "story_points", "fixVersions", "parent",
      "subtasks", "issuelinks",
      "customfield_10004", // story points (common)
      "customfield_10007", // sprint (common)
    ]

    if (include_comments) {
      fields.push("comment")
    }

    const params = new URLSearchParams({
      fields: fields.join(","),
    })

    const data = await jiraApi(`/issue/${issue_key}?${params}`)

    let result = formatIssue(data, true)

    // Show subtasks
    if (data.fields?.subtasks?.length > 0) {
      result += `\n\n**Subtasks:**`
      for (const sub of data.fields.subtasks) {
        result += `\n- [${sub.key}] ${sub.fields?.summary} (${sub.fields?.status?.name})`
      }
    }

    // Show linked issues
    if (data.fields?.issuelinks?.length > 0) {
      result += `\n\n**Linked Issues:**`
      for (const link of data.fields.issuelinks) {
        if (link.outwardIssue) {
          result += `\n- ${link.type?.outward}: [${link.outwardIssue.key}] ${link.outwardIssue.fields?.summary}`
        }
        if (link.inwardIssue) {
          result += `\n- ${link.type?.inward}: [${link.inwardIssue.key}] ${link.inwardIssue.fields?.summary}`
        }
      }
    }

    // Show parent (for subtasks / sub-tasks of epics)
    if (data.fields?.parent) {
      result += `\n\n**Parent:** [${data.fields.parent.key}] ${data.fields.parent.fields?.summary}`
    }

    return result
  },
})

export const search = tool({
  description: `Search Jira issues using JQL (Jira Query Language).
  
Examples:
- "project = FAB AND status = 'In Progress'" — all in-progress FAB issues
- "assignee = currentUser() AND sprint in openSprints()" — my sprint work
- "project = FAB AND created >= -7d" — issues created in last 7 days
- "project = FAB AND type = Bug AND status != Done" — open bugs
- "text ~ 'search term'" — full-text search`,
  args: {
    jql: tool.schema.string().describe("JQL query string"),
    max_results: tool.schema
      .number()
      .optional()
      .default(20)
      .describe("Maximum results to return (default: 20, max: 50)"),
    fields: tool.schema
      .string()
      .optional()
      .describe("Comma-separated field names to include (default: key fields)"),
  },
  async execute(args) {
    const { jql, max_results = 20, fields } = args

    const defaultFields = [
      "summary", "status", "assignee", "priority", "issuetype",
      "labels", "created", "updated", "reporter",
      "customfield_10004", "customfield_10007",
    ]

    const body = {
      jql,
      maxResults: Math.min(max_results, 50),
      fields: fields ? fields.split(",").map((f: string) => f.trim()) : defaultFields,
    }

    const data = await jiraApi("/search", {
      method: "POST",
      body: JSON.stringify(body),
    })

    if (!data.issues || data.issues.length === 0) {
      return `No issues found for JQL: \`${jql}\``
    }

    const results = data.issues.map((issue: any) => formatIssue(issue, false)).join("\n\n")

    return `## Jira Search Results (${data.total} total, showing ${data.issues.length})\n\n**JQL:** \`${jql}\`\n\n${results}`
  },
})

export const create_issue = tool({
  description: `Create a new Jira issue with team defaults automatically applied.
  
Automatically sets:
- Label: AppPlatformData
- Scrum Team: Portals
- Epic link (if provided)

To make the issue appear on the board, also use jira_add_to_sprint after creation.

Supported issue types: Story, Bug, Task, Sub-task, Epic.
For sub-tasks, provide the parent issue key.`,
  args: {
    project: tool.schema
      .string()
      .optional()
      .describe("Project key (default: from config, typically FAB)"),
    type: tool.schema
      .enum(["Story", "Bug", "Task", "Sub-task", "Epic"])
      .describe("Issue type"),
    summary: tool.schema.string().describe("Issue title/summary"),
    description: tool.schema
      .string()
      .optional()
      .describe("Issue description (Jira wiki markup supported)"),
    assignee: tool.schema
      .string()
      .optional()
      .describe("Assignee username"),
    priority: tool.schema
      .enum(["Blocker", "Major", "Normal", "Minor", "Trivial"])
      .optional()
      .describe("Priority level"),
    labels: tool.schema
      .string()
      .optional()
      .describe("Additional comma-separated labels (team label is always added)"),
    components: tool.schema
      .string()
      .optional()
      .describe("Comma-separated component names"),
    parent: tool.schema
      .string()
      .optional()
      .describe("Parent issue key (required for Sub-task type)"),
    epic_link: tool.schema
      .string()
      .optional()
      .describe("Epic issue key to link to (e.g., FAB-11437)"),
    story_points: tool.schema
      .number()
      .optional()
      .describe("Story point estimate"),
    skip_team_defaults: tool.schema
      .boolean()
      .optional()
      .default(false)
      .describe("Skip auto-applying team defaults (label, scrum team)"),
  },
  async execute(args) {
    const config = await loadConfig()
    const td = getTeamDefaults()
    const {
      project, type, summary, description, assignee,
      priority, labels, components, parent, epic_link, story_points,
      skip_team_defaults = false,
    } = args

    const fields: Record<string, any> = {
      project: { key: project || getDefaultProject() },
      issuetype: { name: type },
      summary,
    }

    // Build labels: start with team default, add any extras
    const labelSet = new Set<string>()
    if (!skip_team_defaults && td.label) {
      labelSet.add(td.label)
    }
    if (labels) {
      labels.split(",").map((l: string) => l.trim()).filter(Boolean).forEach((l) => labelSet.add(l))
    }
    if (labelSet.size > 0) {
      fields.labels = Array.from(labelSet)
    }

    // Set Scrum Team
    if (!skip_team_defaults && td.scrum_team_field && td.scrum_team_option_id) {
      fields[td.scrum_team_field] = { id: td.scrum_team_option_id }
    }

    // Set Epic Link
    if (epic_link && td.epic_link_field) {
      fields[td.epic_link_field] = epic_link
    }

    if (description) fields.description = description
    if (assignee) fields.assignee = { name: assignee }
    if (priority) fields.priority = { name: priority }
    if (components) {
      fields.components = components.split(",").map((c: string) => ({ name: c.trim() }))
    }
    if (parent) fields.parent = { key: parent }
    if (story_points !== undefined) fields.customfield_10004 = story_points

    const data = await jiraApi("/issue", {
      method: "POST",
      body: JSON.stringify({ fields }),
    })

    const applied: string[] = []
    if (!skip_team_defaults && td.label) applied.push(`label: ${td.label}`)
    if (!skip_team_defaults && td.scrum_team_field) applied.push(`scrum team: ${td.scrum_team_value}`)
    if (epic_link) applied.push(`epic: ${epic_link}`)

    let result = `Issue created: **[${data.key}](${getBaseUrl()}/browse/${data.key})** — ${summary}`
    if (applied.length > 0) {
      result += `\n\nTeam defaults applied: ${applied.join(", ")}`
    }
    result += `\n\nTo add to the current sprint: use \`jira_add_to_sprint(issue_key: "${data.key}")\``

    return result
  },
})

export const update_issue = tool({
  description: `Update an existing Jira issue's fields.
  
Can update summary, description, assignee, priority, labels, components, and story points.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
    summary: tool.schema.string().optional().describe("New summary/title"),
    description: tool.schema.string().optional().describe("New description"),
    assignee: tool.schema.string().optional().describe("New assignee username (use '' to unassign)"),
    priority: tool.schema
      .enum(["Blocker", "Major", "Normal", "Minor", "Trivial"])
      .optional()
      .describe("New priority"),
    labels: tool.schema
      .string()
      .optional()
      .describe("Comma-separated labels (replaces all labels)"),
    components: tool.schema
      .string()
      .optional()
      .describe("Comma-separated component names (replaces all components)"),
    story_points: tool.schema.number().optional().describe("Story point estimate"),
  },
  async execute(args) {
    const { issue_key, summary, description, assignee, priority, labels, components, story_points } = args

    const fields: Record<string, any> = {}

    if (summary !== undefined) fields.summary = summary
    if (description !== undefined) fields.description = description
    if (assignee !== undefined) {
      fields.assignee = assignee === "" ? null : { name: assignee }
    }
    if (priority) fields.priority = { name: priority }
    if (labels !== undefined) fields.labels = labels.split(",").map((l: string) => l.trim()).filter(Boolean)
    if (components !== undefined) {
      fields.components = components.split(",").map((c: string) => ({ name: c.trim() })).filter((c: any) => c.name)
    }
    if (story_points !== undefined) fields.customfield_10004 = story_points

    if (Object.keys(fields).length === 0) {
      return "No fields to update. Provide at least one field to change."
    }

    await jiraApi(`/issue/${issue_key}`, {
      method: "PUT",
      body: JSON.stringify({ fields }),
    })

    return `Issue **${issue_key}** updated successfully.\n\nUpdated fields: ${Object.keys(fields).join(", ")}`
  },
})

export const transition_issue = tool({
  description: `Transition a Jira issue to a new status (e.g., "In Progress", "Done", "To Do").
  
First fetches available transitions for the issue, then applies the matching one.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
    status: tool.schema.string().describe("Target status name (e.g., 'In Progress', 'Done', 'To Do')"),
    comment: tool.schema
      .string()
      .optional()
      .describe("Optional comment to add with the transition"),
  },
  async execute(args) {
    const { issue_key, status, comment } = args

    // Get available transitions
    const transitions = await jiraApi(`/issue/${issue_key}/transitions`)

    const match = transitions.transitions?.find(
      (t: any) => t.name.toLowerCase() === status.toLowerCase() ||
        t.to?.name?.toLowerCase() === status.toLowerCase()
    )

    if (!match) {
      const available = transitions.transitions
        ?.map((t: any) => `"${t.name}" -> ${t.to?.name}`)
        .join(", ")
      return `Cannot transition to "${status}". Available transitions: ${available}`
    }

    const body: any = {
      transition: { id: match.id },
    }

    if (comment) {
      body.update = {
        comment: [{ add: { body: comment } }],
      }
    }

    await jiraApi(`/issue/${issue_key}/transitions`, {
      method: "POST",
      body: JSON.stringify(body),
    })

    return `Issue **${issue_key}** transitioned to **${match.to?.name || status}**${comment ? " with comment" : ""}.`
  },
})

export const add_comment = tool({
  description: `Add a comment to a Jira issue.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
    body: tool.schema.string().describe("Comment text (Jira wiki markup supported)"),
  },
  async execute(args) {
    const { issue_key, body } = args

    const data = await jiraApi(`/issue/${issue_key}/comment`, {
      method: "POST",
      body: JSON.stringify({ body }),
    })

    return `Comment added to **${issue_key}** by ${data.author?.displayName || "you"}.`
  },
})

export const assign_issue = tool({
  description: `Assign a Jira issue to a user, or unassign it.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
    assignee: tool.schema
      .string()
      .describe("Username to assign to (use '-1' for automatic, or '' to unassign)"),
  },
  async execute(args) {
    const { issue_key, assignee } = args

    const name = assignee === "" ? null : assignee === "-1" ? "-1" : assignee

    await jiraApi(`/issue/${issue_key}/assignee`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    })

    if (name === null) {
      return `Issue **${issue_key}** unassigned.`
    }
    return `Issue **${issue_key}** assigned to **${assignee}**.`
  },
})

// ─── Board & Sprint Operations ───────────────────────────────────────

export const add_to_sprint = tool({
  description: `Add an issue to a sprint. If no sprint ID is provided, automatically finds the active sprint for the team board.
  
This is required for issues to appear on the team board. Use after creating an issue.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
    sprint_id: tool.schema
      .number()
      .optional()
      .describe("Sprint ID. If omitted, uses the current active sprint for the team board."),
  },
  async execute(args) {
    const config = await loadConfig()
    let { issue_key, sprint_id } = args

    // If no sprint ID, find the active sprint
    if (!sprint_id) {
      const boardId = getDefaultBoardId()
      const params = new URLSearchParams({ state: "active" })
      const data = await jiraApi(`/board/${boardId}/sprint?${params}`, {}, getAgileApiUrl())

      if (!data.values || data.values.length === 0) {
        return `No active sprint found for board ${boardId}. Please provide a sprint_id manually.`
      }

      sprint_id = data.values[0].id
    }

    await jiraApi(`/sprint/${sprint_id}/issue`, {
      method: "POST",
      body: JSON.stringify({ issues: [issue_key] }),
    }, getAgileApiUrl())

    return `Issue **${issue_key}** added to sprint ${sprint_id}.`
  },
})

export const get_board = tool({
  description: `Get information about a Jira Agile board.
  
Returns board configuration and details. Default board ID is 1990 (FAB team board).`,
  args: {
    board_id: tool.schema
      .number()
      .optional()
      .default(1990)
      .describe("Board ID (default: 1990 — FAB team board)"),
  },
  async execute(args) {
    const { board_id = 1990 } = args

    const data = await jiraApi(`/board/${board_id}`, {}, getAgileApiUrl())

    return `## Board: ${data.name}
- **ID:** ${data.id}
- **Type:** ${data.type}
- **Project:** ${data.location?.projectKey || "N/A"} — ${data.location?.displayName || "N/A"}`
  },
})

export const get_sprints = tool({
  description: `List sprints for a board. Returns active, future, and optionally closed sprints.
  
Default board ID is 1990 (FAB team board).`,
  args: {
    board_id: tool.schema
      .number()
      .optional()
      .default(1990)
      .describe("Board ID (default: 1990)"),
    state: tool.schema
      .enum(["active", "future", "closed", "active,future", "active,future,closed"])
      .optional()
      .default("active,future")
      .describe("Sprint states to include (default: active,future)"),
  },
  async execute(args) {
    const { board_id = 1990, state = "active,future" } = args

    const params = new URLSearchParams({ state })
    const data = await jiraApi(`/board/${board_id}/sprint?${params}`, {}, getAgileApiUrl())

    if (!data.values || data.values.length === 0) {
      return "No sprints found."
    }

    const sprints = data.values.map((s: any) => {
      const start = s.startDate ? new Date(s.startDate).toLocaleDateString() : "N/A"
      const end = s.endDate ? new Date(s.endDate).toLocaleDateString() : "N/A"
      return `### Sprint: ${s.name}
- **ID:** ${s.id} | **State:** ${s.state}
- **Start:** ${start} | **End:** ${end}
- **Goal:** ${s.goal || "None"}`
    }).join("\n\n")

    return `## Sprints for Board ${board_id}\n\n${sprints}`
  },
})

export const get_sprint_issues = tool({
  description: `Get all issues in a specific sprint.
  
Use get_sprints first to find the sprint ID.`,
  args: {
    sprint_id: tool.schema.number().describe("Sprint ID"),
    max_results: tool.schema
      .number()
      .optional()
      .default(50)
      .describe("Maximum results (default: 50)"),
  },
  async execute(args) {
    const { sprint_id, max_results = 50 } = args

    const params = new URLSearchParams({
      maxResults: String(Math.min(max_results, 50)),
      fields: "summary,status,assignee,priority,issuetype,labels,customfield_10004,customfield_10007",
    })

    const data = await jiraApi(`/sprint/${sprint_id}/issue?${params}`, {}, getAgileApiUrl())

    if (!data.issues || data.issues.length === 0) {
      return `No issues found in sprint ${sprint_id}.`
    }

    // Group by status
    const byStatus: Record<string, any[]> = {}
    for (const issue of data.issues) {
      const status = issue.fields?.status?.name || "Unknown"
      if (!byStatus[status]) byStatus[status] = []
      byStatus[status].push(issue)
    }

    let result = `## Sprint Issues (${data.total} total)\n`

    for (const [status, issues] of Object.entries(byStatus)) {
      result += `\n### ${status} (${issues.length})\n\n`
      for (const issue of issues) {
        result += formatIssue(issue, false) + "\n\n"
      }
    }

    return result
  },
})

export const get_backlog = tool({
  description: `Get backlog issues for a board (issues not in any active/future sprint).
  
Default board ID is 1990 (FAB team board).`,
  args: {
    board_id: tool.schema
      .number()
      .optional()
      .default(1990)
      .describe("Board ID (default: 1990)"),
    max_results: tool.schema
      .number()
      .optional()
      .default(30)
      .describe("Maximum results (default: 30)"),
  },
  async execute(args) {
    const { board_id = 1990, max_results = 30 } = args

    const params = new URLSearchParams({
      maxResults: String(Math.min(max_results, 50)),
      fields: "summary,status,assignee,priority,issuetype,labels,customfield_10004",
    })

    const data = await jiraApi(`/board/${board_id}/backlog?${params}`, {}, getAgileApiUrl())

    if (!data.issues || data.issues.length === 0) {
      return "Backlog is empty."
    }

    const results = data.issues.map((issue: any) => formatIssue(issue, false)).join("\n\n")

    return `## Backlog (${data.total} total, showing ${data.issues.length})\n\n${results}`
  },
})

// ─── User & Metadata ────────────────────────────────────────────────

export const get_myself = tool({
  description: `Get information about the currently authenticated Jira user.
  
Returns your username, display name, email, and other account details.`,
  args: {},
  async execute() {
    const data = await jiraApi("/myself")

    return `## Authenticated User
- **Username:** ${data.name}
- **Display Name:** ${data.displayName}
- **Email:** ${data.emailAddress}
- **Active:** ${data.active}
- **Timezone:** ${data.timeZone}`
  },
})

export const get_project = tool({
  description: `Get information about a Jira project including issue types, components, and versions.`,
  args: {
    project_key: tool.schema
      .string()
      .optional()
      .default("FAB")
      .describe("Project key (default: FAB)"),
  },
  async execute(args) {
    const { project_key = "FAB" } = args

    const data = await jiraApi(`/project/${project_key}`)

    const issueTypes = data.issueTypes
      ?.map((t: any) => t.name)
      .join(", ") || "None"
    const components = data.components
      ?.map((c: any) => c.name)
      .join(", ") || "None"
    const versions = data.versions
      ?.map((v: any) => `${v.name} (${v.released ? "released" : v.archived ? "archived" : "unreleased"})`)
      .join(", ") || "None"

    return `## Project: ${data.name} (${data.key})
- **Lead:** ${data.lead?.displayName || "Unknown"}
- **Description:** ${data.description || "None"}
- **Issue Types:** ${issueTypes}
- **Components:** ${components}
- **Versions:** ${versions}
- **URL:** ${getBaseUrl()}/browse/${data.key}`
  },
})

export const list_transitions = tool({
  description: `List available status transitions for a Jira issue.
  
Shows what statuses the issue can be moved to from its current state.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key (e.g., FAB-1234)"),
  },
  async execute(args) {
    const { issue_key } = args

    const data = await jiraApi(`/issue/${issue_key}/transitions`)

    if (!data.transitions || data.transitions.length === 0) {
      return `No transitions available for ${issue_key}.`
    }

    const transitions = data.transitions
      .map((t: any) => `- **${t.name}** -> ${t.to?.name} (ID: ${t.id})`)
      .join("\n")

    return `## Available Transitions for ${issue_key}\n\n${transitions}`
  },
})

export const discover_fields = tool({
  description: `Inspect all non-empty custom fields on a Jira issue. Useful for finding custom field IDs.`,
  args: {
    issue_key: tool.schema.string().describe("The issue key to inspect (e.g., FAB-11438)"),
    filter: tool.schema
      .string()
      .optional()
      .describe("Optional text to filter field values by (case-insensitive)"),
  },
  async execute(args) {
    const { issue_key, filter } = args

    const data = await jiraApi(`/issue/${issue_key}`)
    const fields = data.fields || {}

    const results: string[] = []
    for (const [key, val] of Object.entries(fields)) {
      if (val === null || val === undefined) continue
      if (!key.startsWith("customfield_")) continue

      const valStr = JSON.stringify(val)
      if (filter && !valStr.toLowerCase().includes(filter.toLowerCase())) continue

      // Truncate very long values
      const display = valStr.length > 200 ? valStr.slice(0, 200) + "..." : valStr
      results.push(`**${key}:** ${display}`)
    }

    if (results.length === 0) {
      return `No ${filter ? "matching " : ""}custom fields with values found on ${issue_key}.`
    }

    return `## Custom Fields on ${issue_key}${filter ? ` (filter: "${filter}")` : ""}\n\n${results.join("\n\n")}`
  },
})

export const link_issues = tool({
  description: `Create a link between two Jira issues.
  
Common link types: "blocks", "is blocked by", "relates to", "duplicates", "is duplicated by", "clones", "is cloned by".`,
  args: {
    type: tool.schema.string().describe("Link type name (e.g., 'blocks', 'relates to')"),
    inward_issue: tool.schema.string().describe("Inward issue key (e.g., FAB-1234)"),
    outward_issue: tool.schema.string().describe("Outward issue key (e.g., FAB-5678)"),
    comment: tool.schema.string().optional().describe("Optional comment for the link"),
  },
  async execute(args) {
    const { type, inward_issue, outward_issue, comment } = args

    const body: any = {
      type: { name: type },
      inwardIssue: { key: inward_issue },
      outwardIssue: { key: outward_issue },
    }

    if (comment) {
      body.comment = { body: comment }
    }

    await jiraApi("/issueLink", {
      method: "POST",
      body: JSON.stringify(body),
    })

    return `Link created: **${inward_issue}** ${type} **${outward_issue}**`
  },
})
