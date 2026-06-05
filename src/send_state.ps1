# ClaudeLamp — Hook-to-state forwarder
# Called automatically by Claude Code hooks; no manual invocation needed.
#
# Maps Claude Code hook event names → traffic-light colours,
# then POSTs the state to the local ClaudeLamp HTTP server.
#
# Usage (internal): powershell -File send_state.ps1 -Event <EventName>
# Port override:     $env:CLAUDELAMP_PORT=23336

param(
    [Parameter(Mandatory=$true)]
    [string]$Event
)

$Port = if ($env:CLAUDELAMP_PORT) { $env:CLAUDELAMP_PORT } else { "23335" }
$ServerUrl = "http://127.0.0.1:${Port}"

# ── Event → state map ─────────────────────────────────────
$StateMap = @{
    "SessionStart"        = "green"
    "UserPromptSubmit"    = "yellow"
    "PreToolUse"          = "red"
    "PostToolUse"         = "red"
    "PostToolUseFailure"  = "red"
    "Stop"                = "green"
    "StopFailure"         = "red"
    "SubagentStart"       = "red"
    "SubagentStop"        = "green"
    "PreCompact"          = "yellow"
    "PostCompact"         = "yellow"
    "PermissionRequest"   = "yellow"
    "Notification"        = "yellow"
}

# ── Special: SessionEnd → shutdown the lamp ───────────────
if ($Event -eq "SessionEnd") {
    try {
        Invoke-RestMethod -Uri "$ServerUrl/shutdown" `
            -Method Post `
            -TimeoutSec 3 `
            -ErrorAction SilentlyContinue | Out-Null
    } catch {
        # Server may already be down — ignore
    }
    exit 0
}

$State = $StateMap[$Event]
if (-not $State) {
    exit 0  # Unknown event — ignore silently
}

# ── POST state update ─────────────────────────────────────
try {
    $body = @{ state = $State } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri "$ServerUrl/state" `
        -Method Post `
        -Body $body `
        -ContentType "application/json; charset=utf-8" `
        -TimeoutSec 3 `
        -ErrorAction SilentlyContinue | Out-Null
} catch {
    # ClaudeLamp not running — ignore
}

exit 0
