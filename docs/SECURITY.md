# Security

Full analysis in `docs/architecture/THREAT_MODEL.md`. Summary of what is enforced.

## Credentials

The server **never** reads, types, stores, or logs a credential. Authentication is
entirely delegated to the user's signed-in Tableau desktop session. No Keychain
access. If Tableau shows a sign-in window, the tool stops and hands off.

## Input handling

| Risk | Mitigation | Test |
|---|---|---|
| XML injection | all XML built via `ElementTree` nodes; never string concatenation | `test_xml_metacharacters_are_escaped_not_injected` |
| ZIP slip | every archive entry normalised and verified inside root | `test_safe_archive_name_rejects_zip_slip` |
| Path traversal | absolute-only, `..` rejected, suffix + size checked | `test_resolve_input_file_rejects_bad_paths` |
| Writing to system paths | `/System`, `/usr`, `/bin`, `/sbin` refused | `test_resolve_output_dir_rejects_system_locations` |
| Shell injection | no `shell=True`; AppleScript passed on stdin | code review |
| Machine-data leakage | generated `.twb` scanned for home dir/username/abs paths **before** packaging; build aborts | `test_generated_twb_contains_no_machine_identifiers` |
| Oversized CSV | 64 MB / 200k rows / 256 columns caps | `security/paths.py` |

## Destructive operations

`publish_to_tableau_public` is the only tool with public side effects. It requires
`confirm_publish: true` and `profile`, defaults `overwrite` to `false`, supports
`dry_run`, and refuses to act unless the intended workbook is the frontmost
document. `profile` is required rather than optional because the overwrite check
cannot run without it, and a skipped check used to read as "safe".

## Network

This is a local-only tool with no network listener. It makes **two** kinds of
outbound request, both unauthenticated HTTPS GETs to `public.tableau.com` issued
with stdlib `urllib` under the fixed User-Agent `tableau-public-authoring/0.1`:

| Request | Where | When |
|---|---|---|
| the published viz URL | `publisher.verify_url` | `verify_published_workbook`, and once at the end of a publish |
| `public.tableau.com/public/apis/workbooks?profileName=...` | `WORKBOOKS_ENDPOINT` in `publishing/existing.py`, fetched by `list_published_workbooks` | **before** every publish, for overwrite protection; then **polled every 5s for up to 300s after Save** while the new workbook's URL is resolved (`publisher._await_published_url`) |

The profile-workbooks endpoint is the second request type, and it is not
incidental: a single publish hits it for the collision check and then once every
5s until the workbook appears or `wait_timeout` (300s) elapses — up to ~60 further
polls, each of which pages through the profile 50 workbooks at a time. The only
user-supplied value it carries is the profile name. Both call sites reject any URL
that is not `https://` (`publisher.verify_url`, `existing._fetch_json`), so
neither can be redirected to a plaintext scheme by a crafted argument.

No request carries a credential, cookie, or token — both endpoints are public and
unauthenticated. The server deliberately does not call the separate
`tableau-public` reader MCP for the profile lookup: a publish-safety precondition
must not depend on another server being installed, configured and reachable.
