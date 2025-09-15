# About
Script used to format the calendar given by University of Valencia (UV) for better readability.

## What it does
From SUMMARY, which is the name shown at first in the calendar, it removes the subject ID and the ending of class group (e.g. "Grupo Teoría D-T").
Alternatively, desired names can be added in the config file by the subject ID, allowing custom names.

Changes the location from the description to the LOCATION field of `.ics` file.

TODO:

- Extract from SUMMARY subject ID and grouping
    - Keep in only the subject itself, allowing modificiation by config of each subject individually.
- From grouping extract ["Teoría", "Laboratorio", "Tutorías", "Seminario"] and other. From these, generate:
    - PRIORITY: 1 highest to 9 lowest. 
    - TRANSP: OPAQUE (Laboratorio, Seminario) or TRANSPARENT (Teorías, tutorías)
    - (Coloring is applied only to google calendar...)
- Move/Copy DESCRIPTION to LOCATION 

# About and Development
## Data extracted from the calendar
For each event, the following info is extracted:
```
{
    'UID': '20260325T1100-20260325T1200-33957-DG-T', 
    'SHORT_DESCRIPTION': '33957 - Nutrición: Nutrición Grupo Teoría DG-T', 
    'DESCRIPTION': 'AULA AF-14 B 21', 
    'CLASSIFICATION': None, 
    'CATEGORIES': '', 
    'CREATED': datetime.datetime(2025, 9, 15, 6, 12, 14, tzinfo=tzutc()), 
    'LAST_MODIFIED': None, 
    'DTSTART': datetime.datetime(2026, 3, 25, 11, 0, tzinfo=tzfile('Europe/Madrid')), 
    'DTEND': datetime.datetime(2026, 3, 25, 12, 0, tzinfo=tzfile('Europe/Madrid'))
}
```
## Subject ID
Each subject contains an identifier composed of 5 numbers.

Ideally, each subject should have its own color/opacity

## Event UID
- Example UID `20250915T1100-20250915T1200-34072-DG-T`
Each calendar event seems to have its UID composed of start time, end time, subject ID, group and class type.