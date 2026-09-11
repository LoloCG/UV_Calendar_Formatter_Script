# University Calendar Formatter: Data Flow

## Purpose and implementation status

This program converts a University of Valencia (UV) `.ics` calendar into a
more readable calendar, detects timetable changes and collisions, and supports
user-defined subject names. It is a local file-to-file application: the
selected input calendar is read but never modified.

The source-format compatibility work through Stage 5 is implemented. The two
observed UV download channels are detected independently and projected into the
same semantic event model before comparison, collision analysis, reporting, or
generation:

- **calendar-download** (`UXXIAC-GRD`) stores activity and group information in
  a parenthesized `SUMMARY`/`DESCRIPTION` layout and supplies a full
  `LOCATION` value;
- **direct-download** (`SECVIRTUAL UV`) stores subject, activity, and group in
  `SUMMARY`, and stores a compact room/building value in `DESCRIPTION` while
  omitting `LOCATION`.

The current-year fixtures for those channels each contain the same 372
sessions. They now have equal canonical hashes and compare as unchanged even
though their UIDs and source-facing location strings differ.

## End-to-end overview

```text
Selected UV ICS
      |
      v
Read source once
      +----> source metadata and VCALENDAR preamble
      +----> RawCalendarEvent values
      |
      v
Detect and apply an event-shape adapter
      +----> calendar-download adapter
      +----> direct-download adapter
      +----> conservative unknown adapter + diagnostics
      |
      v
Semantic CalendarEventData projection
      +----> canonical activity identity
      +----> canonical building/room identity
      +----> raw/display values and provenance
      |
      v
Conservative location fallback
      +----> unanimous subject/activity evidence in selected calendar
      +----> accepted raw baseline as secondary evidence
      +----> conflict/review diagnostics when inference is unsafe
      |
      +----> canonical comparison with accepted baseline
      +----> collision analysis
      +----> subject catalog and editable output names
      |
      v
User may independently:
      +----> inspect or save reports
      +----> remember exact selected ICS as the next baseline
      +----> generate a formatted ICS and persist subject names
```

Loading and generation never implicitly replace the accepted baseline.
**Remember as baseline** is the only UI action that advances it.

## Components and responsibilities

| Component | Current responsibility |
| --- | --- |
| `main.py` | Resolves portable state and launches `CalendarFormatterApp`. |
| `core/ui/app.py` | Owns the Textual workflow, background work, comparison presentation, subject editing, report actions, baseline acceptance, and generation confirmation. |
| `utils/file_selector.py` | Opens native input and Save As dialogs and resolves the default desktop output path. |
| `utils/ics_utils.py` (`ICSCalendarHandler`) | Reads and decodes the ICS once, exposes cached typed raw events, extracts source metadata, and retains the preamble. |
| `core/source_formats.py` | Scores the known formats, selects an adapter per event, creates semantic event projections, and emits format/projection diagnostics. |
| `core/semantic.py` | Defines canonical activity and location behavior, location relations, and conservative same-calendar/baseline fallback. |
| `core/models.py` | Defines raw source values, format evidence, semantic identities, loaded calendars, comparisons, diagnostics, collisions, and generation results. |
| `core/change_tracking.py` | Creates semantic hashes, matches sessions without relying on UID, categorizes event/collision changes, and detects possibly unrelated calendars. |
| `core/state_store.py` | Validates/migrates schema v2, performs atomic manifest writes, verifies raw baselines, and commits content-addressed baselines. |
| `core/tracking_workflow.py` | Reparses the retained raw baseline with current code, applies baseline fallback, compares calendars, and records last-check metadata. |
| `core/subject_catalog.py` | Builds the stable subject-ID-to-UV-name catalog. |
| `core/collision_detector.py` | Detects all half-open interval overlaps and derives the laboratory-focused view. |
| `core/calendar_workflow.py` | Provides UI-independent calendar loading, subject-name preparation, and formatted-calendar generation. |
| `core/activity_policy.py` | Uses canonical activity identities for collision priority and generated busy/free behavior. |
| `reports/change_report.py` | Renders and saves chronological comparison reports. |
| `reports/collision_report.py` | Renders and saves deterministic collision reports. |

`core/ics_formatter.py` and `ICSCalendarHandler.as_dicts()` remain compatibility
surfaces for older callers. The current `load_calendar()` path projects typed
`RawCalendarEvent` instances through `core/source_formats.py`; it does not use
the old generic-dictionary formatter as its parsing boundary.

## 1. Select and read the source

Pressing **Select ICS calendar** opens the native file selector. Cancellation
leaves the UI unchanged. A selected file is processed in a Textual worker so
the terminal UI can continue updating.

`ICSCalendarHandler`:

1. reads the source bytes once;
2. detects an optional UTF-8 BOM;
3. decodes with `utf-8-sig` and normalizes newlines;
4. parses the text with `ics.py`;
5. retains the text before the first `BEGIN:VEVENT` as the output preamble;
6. caches one immutable `RawCalendarEvent` per parsed event.

The raw boundary preserves the application-facing distinction between a
missing property (`None`) and a present blank string. It is not a byte-perfect
model of every ICS property, parameter, spelling, or property order.

| Raw field | ICS source |
| --- | --- |
| `uid` | `UID` |
| `summary` | `SUMMARY` / `ics.Event.name` |
| `description` | `DESCRIPTION` converted to one string |
| `classification` | `CLASSIFICATION` |
| `categories` | `CATEGORIES` converted to a comma-separated string |
| `created` | `CREATED`/library value converted to `datetime` when possible |
| `last_modified` | `LAST-MODIFIED` converted to `datetime` when possible |
| `start` | `DTSTART` converted to `datetime` when possible |
| `end` | `DTEND` converted to `datetime` when possible |
| `location` | `LOCATION`, preserving absence |

Calendar-level `PRODID`, `X-WR-CALNAME`, and BOM presence are captured in
`CalendarSourceMetadata`. They support source-format evidence but do not
participate in semantic calendar equality.

## 2. Detect the source shape and project events

`project_calendar()` evaluates both known adapters. `PRODID` contributes to
confidence, but the event shape determines which adapter parses each event.
This allows a mixed calendar to be handled per event instead of trusting only
the filename or calendar metadata.

The resulting `SourceFormatEvidence` records:

```text
adapter_id              calendar-download, direct-download, mixed, or unknown
confidence              aggregate confidence for matched shapes
calendar_prodid         source PRODID
calendar_name           source X-WR-CALNAME
matched_shape_rules     evidence used by the detector
warnings                mixed-format or metadata-mismatch warnings
```

An event that matches neither known layout is passed through the unknown
adapter. Readable raw data is retained where possible, and a review diagnostic
prevents uncertain data from being silently accepted as a trusted baseline.
An event without `DTSTART` or `DTEND` is rejected because comparison and
collision analysis require a complete interval.

### Calendar-download projection

Observed shape:

```ics
PRODID:-//UXXIAC-GRD//ES
SUMMARY:34082 - Tecnologia Farmaceutica I(TEORIA (34082))
DESCRIPTION:DG-T - Grupo Teoria
LOCATION:21 AULARI INTERFACULTATIU - AULA AF-14 B
```

The adapter extracts the subject ID/name and activity from `SUMMARY`, the group
from `DESCRIPTION`, and the location from `LOCATION`. A recognized location is
split into:

```text
building_code   = 21
room_key        = aula af-14 b
display_value   = 21 AULARI INTERFACULTATIU - AULA AF-14 B
source_property = LOCATION
```

### Direct-download projection

Observed shape:

```ics
PRODID:-//secvirtual.uv.es//SECVIRTUAL UV
SUMMARY:34082 - Tecnologia Farmaceutica I Grupo Teoria DG-T
DESCRIPTION:AULA AF-14 B 21
```

The adapter extracts subject ID/name, activity, and group from `SUMMARY`. It
parses the compact `DESCRIPTION` location into:

```text
building_code   = 21
room_key        = aula af-14 b
display_value   = AULA AF-14 B 21
source_property = DESCRIPTION
```

Thus the two source strings retain different display values and provenance,
but share the canonical location key `("21", "aula af-14 b")`. Direct-download
room information is no longer lost and can be emitted as `LOCATION` in the
formatted calendar.

Subject IDs accept four to six digits followed by a hyphen, en dash, or em
dash. Parsed group tags are uppercased. Values that do not match a supported
location or description shape produce diagnostics rather than being treated as
known-empty data.

## 3. Build semantic identities

Each projected `CalendarEventData` retains user-facing fields while adding
identities used by every downstream feature.

### Activity identity

Activity text is normalized by replacing non-breaking spaces, trimming and
collapsing whitespace, removing accents, and applying case-insensitive Unicode
comparison. An explicit alias table then maps known equivalent terms to stable
keys. In particular:

```text
INFORMATICA       -> informatica
Aula informatica  -> informatica
teoria/teorias    -> teoria
laboratorio(s)    -> laboratorio
seminario(s)      -> seminario
tutoria(s)        -> tutoria
```

Unknown labels retain their normalized text as their identity instead of being
collapsed into a generic class.

### Location identity and states

A `LocationIdentity` keeps canonical building/room fields separately from its
display text, raw source value, property, provenance, and confidence. Its state
is one of the implemented conditions such as:

- `known`: confidently parsed from the source;
- `absent`: the source explicitly contained a blank value;
- `unavailable`: the source did not provide comparable data;
- `unknown`: source text exists but cannot be safely interpreted;
- `inferred`: filled from conservative fallback evidence;
- `conflicting`: fallback candidates disagree.

Missing, blank, unknown, and conflicting values are deliberately not treated
as equivalent.

## 4. Resolve conservative location fallback

Fallback is used only for an `unavailable` location. It never replaces an
explicit current location, an explicit blank value, or unrecognized current
text.

The first fallback pass uses known events in the selected calendar. The second
pass, performed only when an accepted baseline exists, uses known events from
that freshly reparsed baseline. Candidates are anchored by:

```text
subject ID + canonical activity type
```

This implements the rule that sessions sharing a subject ID and class type
normally share location metadata. If the broad candidates disagree, matching
group is used to narrow them. A location is inferred only when the remaining
candidates unanimously identify one canonical building/room.

Inferred values record `same-calendar` or `accepted-baseline` provenance. A
conflict produces a review diagnostic and no room is selected. If a known and
an inferred location have different canonical keys, comparison requests review
instead of declaring a confirmed relocation.

There is no standalone subject-location table in `calendar_config.json`.
Historical fallback comes from the exact accepted raw ICS, reparsed using the
current adapter and semantic rules. This avoids accumulating location facts
from multiple edited timetable versions without their original event context.

## 5. Load and compare the retained baseline

Portable state is stored beside the script or executable:

```text
data/
    calendar_config.json
    baseline/
        <source-sha256>.ics
```

The content-addressed baseline ICS is the exact source previously accepted by
the user. It is the historical source of truth; JSON stores metadata and hashes
about it, not a replacement event snapshot.

On each load, `analyze_with_baseline()`:

1. loads and validates schema-v2 state;
2. verifies that the retained baseline bytes match the stored source SHA-256;
3. reparses the baseline with the current `load_calendar()` implementation;
4. migrates derived canonical metadata when `PARSER_DATA_VERSION` changes;
5. applies baseline-backed fallback to still-unavailable current locations;
6. compares current and baseline semantic projections;
7. records lightweight `last_check` metadata when state is writable.

The semantic canonical signature contains:

```text
subject ID (or normalized subject name fallback)
canonical activity key
normalized group
UTC start
UTC end
semantic location signature, including its state
```

It intentionally excludes source UID, filename, event order, raw display
spelling, and calendar producer. Equivalent formats and timezone-offset
spellings therefore compare equally.

If canonical multisets differ, matching proceeds conservatively without
depending on UID. Strong candidates share subject, canonical activity, and
group; time/location evidence resolves unique candidates. Ambiguous candidates
remain unmatched and are reported for review rather than guessed.

Matched changes are categorized as `rescheduled`, `relocated`, `regrouped`, or
`retyped`. Unmatched sessions become `added` or `removed`. Collision sets are
also classified as new, resolved, or overlap-changed.

Low subject/date overlap or a non-overlapping date gap greater than 90 days is
reported as a possibly unrelated calendar. Such a calendar cannot replace the
baseline. The baseline is also not replaceable while any projection diagnostic
requires review.

## 6. Detect and present collisions

Collision analysis validates timezone-aware, positive event intervals. Events
overlap when:

```python
max(first.start, second.start) < min(first.end, second.end)
```

This half-open rule includes partial, contained, and identical overlaps while
excluding adjacent sessions. No input or output event is modified or removed.

The main screen shows aggregate counts. **Review collisions** opens a dedicated
screen with all collision pairs, laboratory-involved pairs, affected laboratory
sessions, categories, row details, report preview, and save action.

The shared priority order is:

```text
laboratory > seminar > tutorial > class
```

It affects the laboratory-focused presentation and generated busy/free policy;
it does not suppress lower-priority collisions.

## 7. Merge and edit subject names

After analysis, `prepare_subject_names()` loads `subject_names` from the JSON
manifest and adds newly discovered subject IDs using their UV names. Stored
aliases take precedence. The table shows:

| Status | Meaning |
| --- | --- |
| `UV default` | Newly discovered subject still using its parsed UV name. |
| `Configured` | Name loaded from persistent state. |
| `Modified` | Name changed in memory during this run. |

Editing a subject name does **not** immediately write the JSON file. The edit
remains in memory and is used by report previews and output generation. The
complete mapping is persisted when either:

- **Generate formatted ICS** is confirmed and its state write succeeds; or
- **Remember as baseline** succeeds.

Generation saves aliases before writing the output ICS. A later output-write
failure therefore does not roll back an already successful alias save.

If portable state is read-only, editing and generation still work, but the
alias mapping is not persisted.

## 8. First analysis, reports, and baseline actions

With no accepted baseline, comparison status is `first`. Sessions are not
listed as additions, because there is no earlier calendar to compare against.
The **View changes** and **Save change report** buttons are hidden for this
state. The change table is normally hidden too, but may show review-level
projection diagnostics even without a baseline.

Once a baseline exists, **View changes** previews a chronological report and
**Save change report** writes `<output-stem>_changes.txt`. This includes the
current/baseline source formats and hashes, event changes, collision changes,
ambiguities, and projection diagnostics. On an unchanged comparison the report
simply records that no calendar changes were found.

Saving a change report only writes that report. It does not save subject-name
edits, regenerate the ICS, or advance the baseline. Collision reports behave
the same way and use `<output-stem>_collisions.txt`.

**Remember as baseline** is available for a safe first or changed analysis. It:

- verifies that the selected source did not change after analysis;
- stores its exact bytes under `data/baseline/<sha256>.ics`;
- atomically updates baseline metadata and subject names;
- retains the latest meaningful comparison when accepting a changed calendar;
- removes superseded, unreferenced baseline files.

An unchanged calendar cannot be remembered again, so duplicate baseline files
are not created. Generation and baseline acceptance remain independent.

There is no in-app new-course reset button. To start fresh for another academic
year, close the application, delete its portable `data` directory, restart, and
load the new calendar. A missing state directory/configuration is treated as
fresh state; the startup writability probe may recreate an empty directory.
Deleting `data` removes subject aliases, comparison metadata, and the retained
raw baseline.

## 9. Generate the formatted calendar

The output defaults to `new_calendar.ics` on the desktop, with a home-directory
fallback when no desktop exists. **Choose output...** selects filename and
directory together. The selected output must differ from the input path and
generation requires confirmation.

For each semantic event, `generate_formatted_calendar()` builds a new event:

```python
{
    "UID": source UID,
    "SUMMARY": "<configured-or-UV subject> - <source activity display>",
    "DESCRIPTION": "(<subject ID>) - <activity> grupo <group>.",
    "CREATED": source creation time,
    "LAST_MODIFIED": current processing time,
    "DTSTART": source start,
    "DTEND": source end,
    "TRANSP": derived busy/free value,
    "LOCATION": semantic display location, if non-empty,
}
```

If the location was inferred, the generated description states its provenance.
Known direct-download locations are emitted from their parsed compact
`DESCRIPTION` value; calendar-download locations retain their full `LOCATION`
display value. Both use the same canonical identity for analysis.

| Activity identity | Generated ICS | Effect |
| --- | --- | --- |
| laboratory | `TRANSP:OPAQUE` | Busy |
| seminar | `TRANSP:OPAQUE` | Busy |
| tutorial | `TRANSP:OPAQUE` | Busy |
| any other activity | `TRANSP:TRANSPARENT` | Free/transparent |

The source UID, start/end, and creation time are retained where available.
`LAST-MODIFIED` is replaced with generation time. Source classification,
categories, original description, original last-modified value, and properties
outside the rebuilt model are not copied.

`ICSGenerator` serializes the rebuilt events. When a source preamble exists,
generation combines:

```text
source text before first BEGIN:VEVENT
    + newly serialized VEVENT blocks
    + END:VCALENDAR
```

This retains leading calendar metadata and timezone definitions while replacing
the source events. Because `ics.py` stores events in a set, physical event order
in the generated file is not guaranteed; calendar clients normally order by
timestamp.

## State schema and persistence boundaries

The schema-v2 manifest has this conceptual shape:

```json
{
  "schema_version": 2,
  "subject_names": {
    "34082": "Tec Farm I"
  },
  "tracking": {
    "baseline": {
      "raw_ics_path": "baseline/<source-sha256>.ics",
      "source_sha256": "...",
      "canonical_sha256": "...",
      "source_format": "calendar-download",
      "parser_data_version": 2
    },
    "last_check": {},
    "last_change": {}
  }
}
```

Writes use a temporary file, flush/synchronization, and atomic replacement.
Legacy flat subject-name configurations are migrated on the first successful
write with aliases preserved and a recovery backup created. Invalid or future
schemas are reported rather than overwritten.

The directory represents one academic year's local state. It can contain
private timetable locations and other source metadata through the retained raw
calendar, so copying the portable application together with `data` also copies
that information.

## Error and review behavior

- Missing, invalidly encoded, or malformed ICS input is reported without
  closing the application.
- Invalid state disables tracking use for that load; formatting and collision
  review remain available with safe fallbacks.
- A read-only portable directory disables persistence and baseline actions but
  does not prevent parsing, in-memory alias editing, reports, or generation.
- Unknown/mixed/malformed source shapes retain data where possible and expose
  diagnostics in the comparison information/report surfaces.
- Review-level diagnostics prevent baseline acceptance.
- Reports are optional writes and never mutate comparison state.
- Regeneration overwrites the chosen output and assigns new `LAST-MODIFIED`
  timestamps.

## Verified fixture behavior

The automated compatibility tests establish the current behavior:

- `calendar_07092025.ics`: 372 events, detected as `calendar-download`;
- `direct_download_07092025.ics`: 372 events, detected as
  `direct-download`;
- both project to equal semantic hashes and compare as unchanged in either
  direction;
- both produce 19 total collisions, 16 laboratory-involved pairs, and 13
  affected laboratory sessions;
- their 372 locations reduce to the same eight canonical building/room pairs;
- their activity identity counts match, including `INFORMATICA` versus
  `Aula informatica`;
- `2025/oldcal2025.ics` remains a direct-download regression fixture and is
  flagged as possibly unrelated to either current-year calendar.

