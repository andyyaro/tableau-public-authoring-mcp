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
`confirm_publish: true`, defaults `overwrite` to `false`, supports `dry_run`, and
refuses to act unless the intended workbook is the frontmost document.

## Reporting

This is a local-only tool with no network listener. It makes exactly one outbound
request type: an HTTPS GET to `public.tableau.com` to verify a published URL.
