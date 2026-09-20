# UV Calendar Formatter

This is a personal productivity tool I use during the school year to check
whether the University of Valencia course calendar has changed and to spot
colliding calendar events. It formats UV `.ics` exports, compares successive
timetable versions, reports collision changes, and generates a clearer calendar
with user-defined subject names. Everything remains local.

## Download a portable application

Download the archive for your platform from the
[latest GitHub Release](https://github.com/LoloCG/UV_Calendar_Formatter_Script/releases/latest):

- Windows x64: `UV-Calendar-Formatter-windows-x64.zip`
- Linux x64: `UV-Calendar-Formatter-linux-x64.tar.gz`

Extract the archive and run `UV-Calendar-Formatter.exe` on Windows or
`./UV-Calendar-Formatter` on Linux. The app is a terminal user interface, so a
terminal window is expected. Python does not need to be installed.

Do not run the executable from inside the ZIP or place it in a protected folder
such as `Program Files`: its portable `data` directory is created beside the
executable. Keep the executable and its `runtime` directory together, and move
the whole extracted application folder (including `data`) to preserve aliases
and calendar change history. Windows may show a SmartScreen warning because
this personal build is not code-signed.

## Requirements and launch

- Python 3.10 or later
- Packages from `requirements.txt`

```text
python -m pip install -r requirements.txt
python main.py
```

The generated calendar defaults to `Desktop/new_calendar.ics` (or the home
directory when no desktop folder is available). The selected input is never
modified.

## Workflow

1. Select a UV ICS calendar. Parsing, normalization, collision detection, and
   comparison run in a background worker.
2. Review **Changes since previous calendar**. A first analysis deliberately
   does not list every session as added. Later analyses show added, removed,
   rescheduled, relocated, regrouped, retyped, and ambiguous sessions plus new,
   resolved, and changed collisions.
3. Use **View changes** or **Save change report** for the chronological report.
4. Select subject rows to edit their output names.
5. Use **Review collisions** to open the dedicated in-app collision screen. It
   contains the complete pair table, row details, report preview, report path,
   and save action. **Back** returns without losing the loaded analysis or edits.
6. Use **Remember as baseline** only when you want the exact selected source to
   become the next comparison reference. Generating a formatted ICS never
   advances the baseline.
7. Choose an output path and generate the formatted calendar.

An unchanged semantic calendar disables **Remember as baseline**, updates only
the lightweight last-check timestamp, stores no duplicate ICS, and preserves
the last meaningful change report. UID, filename, event order, and equivalent
timezone-offset changes do not create false differences.

## UV download-format compatibility

UV currently exposes at least two ICS representations through different
download paths. One uses `PRODID:-//UXXIAC-GRD//ES`, puts group data in
`DESCRIPTION`, and supplies a full `LOCATION`. The direct download uses
`PRODID:-//secvirtual.uv.es//SECVIRTUAL UV`, puts activity and group in
`SUMMARY`, and stores a compact room/building value in `DESCRIPTION` without a
`LOCATION` property.

The parser detects both known shapes and projects their subject, activity,
group, times, and locations into the same semantic model. Full and compact room
representations share a building/room identity, and `INFORMÁTICA` and
`Aula informática` share one activity identity. The two representations of the
same timetable therefore compare as unchanged even though their event UIDs and
raw property layouts differ.

Unknown, mixed, malformed, or genuinely incomplete inputs retain their raw
values and produce projection diagnostics. When location data is unavailable,
a unanimous subject/activity location may be inferred from the selected
calendar or the last explicitly accepted raw baseline. Inferred values retain
their provenance, never override explicit current values, and cannot hide a
schedule, group, activity, or confirmed room change.

Generated calendars use the semantic location display value for either known
format and note inferred-location provenance in the event description. The
change **Info** view shows the detected current and baseline formats, detection
confidence, and projection diagnostics. Review-level diagnostics also appear
in the change table and text report and prevent **Remember as baseline** until
the source can be projected safely.

## Portable local data

State is resolved relative to the executable/script, not the terminal's working
directory:

```text
data/
    calendar_config.json
    baseline/
        <source-sha256>.ics
```

The versioned JSON manifest stores aliases, UTC action timestamps, parser and
application versions, hashes, baseline metadata, last-check metadata, and the
latest meaningful comparison. The content-addressed ICS is the exact accepted
source of truth. Only one baseline and one latest meaningful comparison are
retained.

A legacy flat `calendar_config.json` beside the executable is migrated on the
first write; all aliases are preserved and a `.legacy.bak` recovery copy is
created beside the legacy file. The old discovery filename is retired after a
successful migration so deleting `data` does not import it again. Invalid or
future state schemas are not silently overwritten.

The visible `data` directory represents one academic year. A low-overlap or
distant calendar is labelled **Possibly unrelated calendar** and cannot replace
the baseline. To begin a different academic year, close the application, delete
its portable `data` directory, restart it, and load the new calendar. A missing
directory is detected as fresh state. The calibrated heuristic uses
containment-friendly subject/date overlap thresholds of 25%, plus a
greater-than-90-day non-overlapping date gap for distant academic periods.

If the directory is read-only, the UI displays its resolved path and an
actionable warning. Calendar parsing, alias editing in memory, generation, and
collision review continue; persistence and baseline actions are disabled.

The raw baseline can contain timetable locations and other source metadata.
Copying the executable together with `data` copies that private information.
Deleting `data` performs a complete manual new-course reset.

## Collision behavior

Intervals use half-open semantics, so a session ending exactly when another
starts is not a collision. The review screen first lists only subjects with
collisions. Each subject shows distinct affected sessions, total sessions, and
`affected / total` values for laboratory, seminar, tutorial, and class sessions;
an unavailable activity for that subject is shown as `0 / 0`. The existing
collision-pair table and laboratory-priority projection remain available below
the summary. Priority affects presentation and generated busy/free behavior
only:

```text
Laboratory > Seminar > Tutorial > Class
```

Collision reports are saved as `<calendar-name>_collisions.txt`; change reports
use `<calendar-name>_changes.txt`.

## Tests

```text
python -m unittest discover -s tests -v
```

See [DATAFLOW.md](DATAFLOW.md) for current implementation details.
