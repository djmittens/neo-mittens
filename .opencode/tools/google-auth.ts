/**
 * Shared Google API authentication helper for all google-*.ts opencode tools.
 *
 * Handles:
 * - ADC token acquisition via gcloud
 * - Quota project detection and auto-fix
 * - Scope validation with actionable error messages
 * - Automatic retry after quota project auto-fix
 */

import { readFileSync, existsSync } from "fs"
import { homedir } from "os"
import { join } from "path"

const ALL_SCOPES = [
  "https://www.googleapis.com/auth/documents",
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/drawings",
  "https://www.googleapis.com/auth/spreadsheets",
  "https://www.googleapis.com/auth/cloud-platform",
]

/**
 * Read quota_project_id from the ADC credentials file.
 */
export function getQuotaProject(): string | null {
  const adcPath = join(homedir(), ".config", "gcloud", "application_default_credentials.json")
  if (!existsSync(adcPath)) {
    return null
  }
  try {
    const adc = JSON.parse(readFileSync(adcPath, "utf-8"))
    return adc.quota_project_id || null
  } catch {
    return null
  }
}

/**
 * Get an access token from gcloud ADC.
 */
export async function getAccessToken(): Promise<string> {
  const proc = Bun.spawn(["gcloud", "auth", "application-default", "print-access-token"], {
    stdout: "pipe",
    stderr: "pipe",
  })
  const output = await new Response(proc.stdout).text()
  const exitCode = await proc.exited
  if (exitCode !== 0) {
    const stderr = await new Response(proc.stderr).text()
    throw new Error(
      `Failed to get access token. Is gcloud installed and authenticated?\n\n` +
      `Fix: Run:\n  ${getReauthCommand()}\n\n` +
      `Error: ${stderr}`
    )
  }
  return output.trim()
}

/**
 * Auto-fix: set quota project on ADC credentials file.
 * Tries the preferred personal dev project first, then falls back to gcloud config project.
 */
async function autoSetQuotaProject(): Promise<string | null> {
  // Preferred project — personal dev project with all Google Workspace APIs enabled
  const PREFERRED_PROJECT = "ck-orp-nick-dev"

  // Try preferred project first, then fall back to gcloud config
  let project = PREFERRED_PROJECT
  const configProc = Bun.spawn(["gcloud", "config", "get-value", "project"], {
    stdout: "pipe",
    stderr: "pipe",
  })
  const configProject = (await new Response(configProc.stdout).text()).trim()
  const exitCode = await configProc.exited
  if (!project && (exitCode !== 0 || !configProject || configProject === "(unset)")) {
    return null
  }
  if (!project) {
    project = configProject
  }

  const setProc = Bun.spawn(
    ["gcloud", "auth", "application-default", "set-quota-project", project],
    { stdout: "pipe", stderr: "pipe" }
  )
  const setExit = await setProc.exited
  return setExit === 0 ? project : null
}

function getReauthCommand(): string {
  return `gcloud auth application-default login --scopes=${ALL_SCOPES.join(",")}`
}

function getSetQuotaCommand(project?: string): string {
  return `gcloud auth application-default set-quota-project ${project || "<YOUR_PROJECT_ID>"}`
}

/**
 * Make an authenticated request to a Google API.
 * Handles 403 errors with actionable fix instructions and auto-fix attempts.
 *
 * @param baseUrl - API base URL (e.g., "https://sheets.googleapis.com")
 * @param apiName - Human-readable API name for error messages (e.g., "Google Sheets")
 * @param endpoint - API endpoint path (e.g., "/v4/spreadsheets/...")
 * @param options - fetch RequestInit options
 */
export async function googleApi(
  baseUrl: string,
  apiName: string,
  endpoint: string,
  options: RequestInit = {}
): Promise<any> {
  const token = await getAccessToken()
  let quotaProject = getQuotaProject()

  // If no quota project, try to auto-set it
  if (!quotaProject) {
    quotaProject = await autoSetQuotaProject()
    if (!quotaProject) {
      throw new Error(
        `${apiName} API requires a quota project, but none is set in ADC credentials.\n\n` +
        `Fix: Run these commands:\n` +
        `  ${getReauthCommand()}\n` +
        `  ${getSetQuotaCommand()}\n`
      )
    }
  }

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "x-goog-user-project": quotaProject,
  }

  const response = await fetch(`${baseUrl}${endpoint}`, {
    ...options,
    headers: { ...headers, ...options.headers },
  })

  if (response.ok) {
    const text = await response.text()
    return text ? JSON.parse(text) : {}
  }

  const errorText = await response.text()

  if (response.status === 403) {
    let parsed: any = {}
    try { parsed = JSON.parse(errorText) } catch {}
    const reason = parsed?.error?.details?.[0]?.reason || ""
    const message = parsed?.error?.message || errorText

    // Insufficient scopes — tell the user exactly what to run
    if (reason === "ACCESS_TOKEN_SCOPE_INSUFFICIENT") {
      throw new Error(
        `${apiName} API: insufficient authentication scopes.\n\n` +
        `Fix: Run these commands:\n` +
        `  ${getReauthCommand()}\n` +
        `  ${getSetQuotaCommand(quotaProject)}\n`
      )
    }

    // Missing quota project — try auto-fix and retry
    if (reason === "SERVICE_DISABLED" || message.includes("quota project")) {
      const fixed = await autoSetQuotaProject()
      if (fixed) {
        headers["x-goog-user-project"] = fixed
        const retry = await fetch(`${baseUrl}${endpoint}`, {
          ...options,
          headers: { ...headers, ...options.headers },
        })
        if (retry.ok) {
          const text = await retry.text()
          return text ? JSON.parse(text) : {}
        }
        const retryError = await retry.text()
        throw new Error(`${apiName} API error after auto-fix (${retry.status}): ${retryError}`)
      }

      throw new Error(
        `${apiName} API: quota project required but auto-fix failed.\n\n` +
        `Fix: Run:\n  ${getSetQuotaCommand()}\n`
      )
    }
  }

  throw new Error(`${apiName} API error (${response.status}): ${errorText}`)
}
