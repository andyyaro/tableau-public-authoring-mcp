"""Detect name collisions on Tableau Public *before* an irreversible publish.

WHY THIS EXISTS
---------------
``publish_to_tableau_public`` accepts an ``overwrite`` flag, but until this module
nothing ever checked whether a workbook of that name was already live on the
user's profile: the flag was decorative. Publishing to Tableau Public is
irreversible and world-visible, and Tableau's own "Save to Tableau Public" flow
matches an existing workbook **by name** and replaces it without a diff, without
a version history, and without a way to get the old one back. Silently
clobbering somebody's published work is the worst failure this server can have,
so the check is a hard precondition (same posture as
``publisher.assert_target_frontmost``).

HOW THE LOOKUP WORKS
--------------------
Tableau Public has no supported REST API, but the profile page is backed by a
public, unauthenticated JSON endpoint. The exact URL validated during
development, against a real Tableau Public profile on
2026-07-27, was::

    https://public.tableau.com/public/apis/workbooks?profileName=<profile>&start=0&count=50&visibility=NON_HIDDEN

It returned HTTP 200 and a body shaped like::

    {"contents": [{"workbookRepoUrl": "...", "title": "...",
                   "defaultViewName": "...", "viewCount": 4,
                   "numberOfFavorites": 0, "authorDisplayName": "...",
                   "authorProfileName": "...", "defaultViewRepoUrl": "..."}],
     "startIndex": 0, "nextIndex": -1, "next": -1, "current": 0}

Empirically confirmed behaviour of that endpoint:

* ``count`` is capped at 50 - ``count=100`` returns
  ``{"error": {"message": "must be less than or equal to 50"}}``.
* ``nextIndex`` is the offset of the next page, or ``-1`` on the last page.
  Reading past the end returns ``contents: []`` and ``nextIndex: -1``.
* An unknown profile returns HTTP 404 with
  ``{"error": {"message": "No entity found!"}}``.

This server deliberately does **not** call the separate ``tableau-public``
reader MCP to do this. A publish-safety precondition must not depend on another
server being installed, configured, and reachable, so the request is issued
directly with ``urllib.request`` (stdlib only - no new dependencies).

FAIL-CLOSED POLICY
------------------
If the lookup cannot complete - DNS failure, timeout, 5xx, unparseable body,
unknown profile - we do **not** know whether a collision exists, so we must not
say "safe". ``assert_safe_to_publish`` returns ``(False, ...)`` in that case and
says so in the message. The only thing that turns a blocked publish into an
allowed one is the user explicitly passing ``overwrite=True``, which is informed
consent to replace whatever is there.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

WORKBOOKS_ENDPOINT = "https://public.tableau.com/public/apis/workbooks"
PROFILE_URL_TEMPLATE = "https://public.tableau.com/app/profile/{profile}"
VIZ_URL_TEMPLATE = "https://public.tableau.com/app/profile/{profile}/viz/{workbook}/{view}"

# The endpoint rejects count > 50 outright, so 50 is both the maximum and the
# fewest round-trips we can make.
PAGE_SIZE = 50
# Defence against a malformed ``nextIndex`` looping us forever. 50 pages is
# 2,500 workbooks, far beyond any real Tableau Public profile.
MAX_PAGES = 50
VISIBILITY = "NON_HIDDEN"
USER_AGENT = "tableau-public-authoring/0.1"


class ProfileLookupError(RuntimeError):
    """Raised when the published-workbook list cannot be determined.

    Never means "no collision" - it means "unknown", which callers must treat as
    unsafe. Message is written to be surfaced to the user verbatim.
    """


@dataclass
class PublishedWorkbook:
    """One workbook already live on a Tableau Public profile."""

    title: str
    repo_url: str
    default_view_name: str
    view_count: int
    direct_url: str
    author_profile_name: str = ""
    default_view_repo_url: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "repo_url": self.repo_url,
            "default_view_name": self.default_view_name,
            "view_count": self.view_count,
            "direct_url": self.direct_url,
            "author_profile_name": self.author_profile_name,
            "default_view_repo_url": self.default_view_repo_url,
        }


@dataclass
class CollisionResult:
    """Outcome of comparing a proposed name against everything already published."""

    collides: bool
    matched_title: str | None
    matched_url: str | None
    checked_count: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "collides": self.collides,
            "matched_title": self.matched_title,
            "matched_url": self.matched_url,
            "checked_count": self.checked_count,
            "reason": self.reason,
        }


def normalize_workbook_name(name: str) -> str:
    """Reproduce the title -> ``workbookRepoUrl`` transformation Tableau applies.

    DETERMINED EMPIRICALLY, not from documentation. 566 real ``title`` /
    ``workbookRepoUrl`` pairs were fetched from live Tableau Public profiles and
    the rule below reproduces 412 of them exactly. Every one of the remaining
    154 is a workbook whose *title* was edited after publishing (the repo URL is
    frozen at first publish): they differ by letter case, by an appended tag such
    as ``" | #VOTD"``, or by a fixed typo (``Balitmore`` -> ``Baltimore``). No
    residual disagreement looked like a gap in the character rule.

    VERIFIED transformations (each backed by at least one live pair):

    ===========================================  =========================================
    title                                        workbookRepoUrl
    ===========================================  =========================================
    ``Card A -  Visuals1``                       ``CardA-Visuals1``
    ``AGA datathon visualizations - USAspend…``  ``AGAdatathonvisualizations-USAspend…``
    ``Quarterly_Sales_Review``                   ``Quarterly_Sales_Review``
    ``Comet_DataRevelations_2019.1``             ``Comet_DataRevelations_2019_1``
    ``2.9 SuperStore Demo``                      ``2_9SuperStoreDemo``
    ``It's Groundhog Day...again``               ``ItsGroundhogDay___again``
    ``NATO Military Spending … as a % of GDP``   ``NATOMilitarySpending…asaofGDP``
    ``Question #7 - Wheel of Time … (book 10)``  ``Question7-WheelofTime…book10``
    ``…売上実績ダッシュボード For Tableau 9.0 …``       ``ForTableau9_0Roadshow…``
    ``Beyoncé's Grammys``                        ``BeyoncesGrammys``
    ===========================================  =========================================

    So the rule is:

    1. ``.`` becomes ``_``.
    2. ``-`` and ``_`` are kept as-is.
    3. ASCII letters and digits are kept; **case is preserved**.
    4. Everything else is deleted - whitespace, ``&``, ``#``, ``%``, ``(``,
       ``)``, ``:``, ``|``, ``,``, ``!``, ``?``, apostrophes (straight and
       curly), ``®``, and non-ASCII scripts such as Japanese.
    5. Accented Latin letters fold to their base letter first (``é`` ->
       ``e``), which is why the input is NFKD-normalised before filtering.

    INFERRED, NOT CONFIRMED: step 5 rests on the single ``Beyoncé's Grammys``
    pair, so NFKD is the best-supported explanation rather than a proven one -
    it is also strictly better than plain stripping across the corpus (412 vs
    411 exact matches) and never made a pair worse. Length truncation was not
    observed and is not modelled; the longest title seen round-tripped intact.
    """
    folded = unicodedata.normalize("NFKD", name)
    out: list[str] = []
    for ch in folded:
        if ch == ".":
            out.append("_")
        elif ch in "-_":
            out.append(ch)
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
    return "".join(out)


def _strip_uniquifier(repo_url: str) -> str:
    """Drop the ``_<timestamp>`` suffix Tableau sometimes appends to a repo URL.

    Observed on live profiles, e.g. ``Findings by Entity Type FY2023-2024`` ->
    ``FindingsbyEntityTypeFY2023-2024_17687247871180`` (an epoch-milliseconds
    stamp), while sibling workbooks on the same profile carry no suffix at all.
    Because we cannot predict which of the two Tableau will do, we compare
    against the stripped base as well. That biases toward *false positives* on
    purpose: a spurious warning costs the user one ``overwrite=True``, a missed
    collision costs them a published workbook.
    """
    head, sep, tail = repo_url.rpartition("_")
    if sep and len(tail) >= 10 and tail.isdigit():
        return head
    return repo_url


def _build_page_url(profile: str, start: int) -> str:
    query = urllib.parse.urlencode(
        {
            "profileName": profile,
            "start": start,
            "count": PAGE_SIZE,
            "visibility": VISIBILITY,
        }
    )
    return f"{WORKBOOKS_ENDPOINT}?{query}"


def _profile_from_url(url: str) -> str:
    """Best-effort extraction of ``profileName`` from a request URL, for messages."""
    query = urllib.parse.urlparse(url).query
    values = urllib.parse.parse_qs(query).get("profileName") or []
    return values[0] if values else "(unknown)"


def _fetch_json(url: str, *, timeout: int) -> dict:
    """GET a JSON document over https, or raise ``ProfileLookupError``."""
    if not url.startswith("https://"):
        raise ValueError(f"only https URLs may be requested, got: {url!r}")
    req = urllib.request.Request(  # noqa: S310 - scheme is asserted https above
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            who = _profile_from_url(url)
            raise ProfileLookupError(
                f"Tableau Public has no profile named {who!r} (HTTP 404). Check the "
                f"profile name, or open {PROFILE_URL_TEMPLATE.format(profile=who)} in a "
                f"browser to confirm it exists."
            ) from exc
        raise ProfileLookupError(
            f"Tableau Public returned HTTP {exc.code} for the published-workbook list. "
            f"Cannot determine whether this name is already taken."
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProfileLookupError(
            f"could not reach Tableau Public to list already-published workbooks: {exc}"
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProfileLookupError(
            "Tableau Public returned a response that is not JSON; the endpoint may have "
            "changed. Cannot determine whether this name is already taken."
        ) from exc

    if not isinstance(payload, dict):
        raise ProfileLookupError(
            f"unexpected response shape from Tableau Public: {type(payload).__name__}"
        )
    if "error" in payload:
        detail = payload["error"]
        message = detail.get("message") if isinstance(detail, dict) else detail
        raise ProfileLookupError(f"Tableau Public rejected the request: {message}")
    return payload


def _parse_workbook(item: dict, *, profile: str) -> PublishedWorkbook | None:
    """Map one ``contents`` entry to a ``PublishedWorkbook``, skipping junk."""
    if not isinstance(item, dict):
        return None
    repo_url = str(item.get("workbookRepoUrl") or "")
    if not repo_url:
        return None
    title = str(item.get("title") or repo_url)
    author = str(item.get("authorProfileName") or profile)
    view_repo = str(item.get("defaultViewRepoUrl") or "")
    view_leaf = view_repo.split("/sheets/")[-1].split("/")[-1] if view_repo else ""
    direct_url = (
        VIZ_URL_TEMPLATE.format(profile=author, workbook=repo_url.split("/")[-1], view=view_leaf)
        if view_leaf
        else PROFILE_URL_TEMPLATE.format(profile=author)
    )
    try:
        view_count = int(item.get("viewCount") or 0)
    except (TypeError, ValueError):
        view_count = 0
    return PublishedWorkbook(
        title=title,
        repo_url=repo_url,
        default_view_name=str(item.get("defaultViewName") or ""),
        view_count=view_count,
        direct_url=direct_url,
        author_profile_name=author,
        default_view_repo_url=view_repo,
    )


def list_published_workbooks(profile: str, *, timeout: int = 25) -> list[PublishedWorkbook]:
    """Every non-hidden workbook currently published under ``profile``.

    Raises ``ProfileLookupError`` rather than returning a partial or empty list
    when the lookup fails, so a caller can never mistake "we could not ask" for
    "nothing is published". That applies to truncation too: an unrecognised
    pagination cursor or a profile larger than the page budget raises instead of
    quietly returning what it managed to read.

    **Known blind spot.** The endpoint is queried with ``visibility=NON_HIDDEN``,
    which is the only visibility value confirmed to work. A workbook the user has
    HIDDEN from their profile still owns its repo URL, and Tableau's save flow
    still matches it by name, so publishing that name would replace the hidden
    workbook without this check ever seeing it. There is no known query parameter
    that includes hidden workbooks, so this cannot currently be closed in code --
    ``assert_safe_to_publish`` says so in its message rather than implying the
    check is exhaustive.
    """
    if not profile or not isinstance(profile, str):
        raise ProfileLookupError("a Tableau Public profile name is required")

    found: list[PublishedWorkbook] = []
    seen: set[str] = set()
    start = 0
    for _ in range(MAX_PAGES):
        payload = _fetch_json(_build_page_url(profile, start), timeout=timeout)
        contents = payload.get("contents")
        if not isinstance(contents, list):
            raise ProfileLookupError(
                "Tableau Public response had no 'contents' list; the endpoint may have "
                "changed. Cannot determine whether this name is already taken."
            )
        for item in contents:
            wb = _parse_workbook(item, profile=profile)
            if wb is not None and wb.repo_url not in seen:
                seen.add(wb.repo_url)
                found.append(wb)

        next_index = payload.get("nextIndex", payload.get("next", -1))
        if not contents:
            break
        if next_index == -1 or (isinstance(next_index, int) and next_index <= start):
            break  # normal end of pagination
        if not isinstance(next_index, int):
            # The endpoint changed shape (e.g. started returning "50" as a string,
            # or switched to a per-page count). Breaking here would hand back a
            # PARTIAL list, and name_collides would then report "no collision"
            # from data it never finished reading -- the exact "we could not ask"
            # vs "nothing is published" confusion this function promises to
            # prevent. Fail closed instead.
            raise ProfileLookupError(
                f"Tableau Public returned an unexpected pagination cursor "
                f"({next_index!r}); the endpoint may have changed. Refusing to report a "
                f"partial workbook list, because it would look like 'no collision'."
            )
        start = next_index
    else:
        # Loop exhausted without breaking: there are more pages than MAX_PAGES.
        raise ProfileLookupError(
            f"profile {profile!r} has more than {MAX_PAGES * PAGE_SIZE} workbooks; the "
            f"listing was truncated, so a name collision cannot be ruled out."
        )
    return found


def name_collides(profile: str, proposed_name: str, *, timeout: int = 25) -> CollisionResult:
    """Would publishing ``proposed_name`` land on top of something already live?

    Compares on BOTH forms, because either can collide on its own:

    * the raw title, as Tableau's save dialog matches it, and
    * ``normalize_workbook_name`` output against ``workbookRepoUrl``, because
      two visually different titles ("Q1 Sales!" and "Q1 Sales") normalise to
      the same repo URL and therefore to the same public address.

    Propagates ``ProfileLookupError`` - an unanswerable question is not a "no".
    """
    published = list_published_workbooks(profile, timeout=timeout)
    proposed_norm = normalize_workbook_name(proposed_name)
    proposed_key = proposed_norm.casefold()

    for wb in published:
        if wb.title == proposed_name:
            return CollisionResult(
                collides=True,
                matched_title=wb.title,
                matched_url=wb.direct_url,
                checked_count=len(published),
                reason=(
                    f"a published workbook already has the exact title {wb.title!r} "
                    f"({wb.view_count} views)"
                ),
            )

    if proposed_norm:
        for wb in published:
            candidates = {
                wb.repo_url,
                _strip_uniquifier(wb.repo_url),
                normalize_workbook_name(wb.title),
            }
            if proposed_key in {c.casefold() for c in candidates if c}:
                return CollisionResult(
                    collides=True,
                    matched_title=wb.title,
                    matched_url=wb.direct_url,
                    checked_count=len(published),
                    reason=(
                        f"{proposed_name!r} normalises to {proposed_norm!r}, which is the "
                        f"public address already used by the published workbook "
                        f"{wb.title!r} (repo URL {wb.repo_url!r}, {wb.view_count} views)"
                    ),
                )

    return CollisionResult(
        collides=False,
        matched_title=None,
        matched_url=None,
        checked_count=len(published),
        reason=(
            f"no published workbook on profile {profile!r} matches {proposed_name!r} "
            f"(or its normalised form {proposed_norm!r}); checked {len(published)} workbooks"
        ),
    )


def assert_safe_to_publish(
    profile: str,
    proposed_name: str,
    *,
    overwrite: bool,
    timeout: int = 25,
) -> tuple[bool, str]:
    """Hard precondition for publishing. ``(False, why)`` means: do not publish.

    ``overwrite=True`` is the user's explicit, informed consent to replace an
    existing workbook, so it always returns ``True`` - including when the lookup
    itself failed, since the user has already accepted the outcome either way.

    With ``overwrite=False`` this fails CLOSED: a lookup that could not complete
    returns ``(False, ...)`` and says plainly that the collision state is
    unknown, because reporting "safe" on a failed check is exactly the mistake
    that loses somebody's published work.
    """
    try:
        result = name_collides(profile, proposed_name, timeout=timeout)
    except ProfileLookupError as exc:
        if overwrite:
            return True, (
                f"could not verify existing workbooks ({exc}), but overwrite=True was "
                f"requested, so publishing proceeds and may replace an existing workbook."
            )
        return False, (
            f"UNABLE TO VERIFY: could not determine whether {proposed_name!r} is already "
            f"published on profile {profile!r} - {exc} "
            f"Refusing to publish, because a failed check is NOT evidence that the name is "
            f"free and publishing is irreversible. Options: (1) retry when the network is "
            f"available, (2) check "
            f"{PROFILE_URL_TEMPLATE.format(profile=profile)} yourself and re-run, or "
            f"(3) pass overwrite=true to publish anyway, accepting that an existing "
            f"workbook of this name would be replaced."
        )

    if not result.collides:
        # State the blind spot rather than implying the check was exhaustive. The
        # listing endpoint only returns NON_HIDDEN workbooks, and a hidden one
        # still owns its name as far as Tableau's save flow is concerned.
        return True, (
            f"{result.reason} Note: workbooks you have HIDDEN from your profile are not "
            f"visible to this check, so a hidden workbook of this name would still be "
            f"replaced."
        )

    if overwrite:
        return True, (
            f"overwrite=True: {result.reason}. The existing workbook at "
            f"{result.matched_url} will be REPLACED."
        )

    return False, (
        f"NAME COLLISION: {result.reason}. It is live at {result.matched_url}. "
        f"Refusing to publish, because Tableau Public would replace it irreversibly and "
        f"there is no version history to restore from. Options: (1) publish under a "
        f"different name, (2) pass overwrite=true to deliberately replace "
        f"{result.matched_title!r}, or (3) delete the existing workbook from "
        f"{PROFILE_URL_TEMPLATE.format(profile=profile)} first."
    )
