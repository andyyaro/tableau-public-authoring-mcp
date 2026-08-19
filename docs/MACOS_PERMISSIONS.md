# macOS Permissions

The authoring server needs three things from macOS. It never modifies TCC
databases; grant everything through the standard system prompts.

| Permission | Why | Where |
|---|---|---|
| **Accessibility** | read Tableau's menu geometry | System Settings > Privacy & Security > Accessibility |
| **Screen Recording** | capture validation screenshots | System Settings > Privacy & Security > Screen Recording |
| **Automation** (Apple Events) | talk to System Events | prompted on first use |

Grant them to the process that *runs* the server (Terminal, iTerm, or Claude Code),
not to Tableau.

## Check

```bash
osascript -e 'tell application "System Events" to return name of first process'   # Automation
osascript -e 'tell application "System Events" to tell process "Finder" to return count of windows'  # Accessibility
screencapture -x /tmp/t.png && echo ok                                            # Screen Recording
```

Or call the `get_tableau_public_app_status` tool, which reports
`accessibility_ok` plus a remediation note.

## Note on CGEvent

Posting synthetic HID events (`CGEventPost`) - required because Tableau is a Qt app
that ignores Accessibility clicks - is itself gated by Accessibility permission.
