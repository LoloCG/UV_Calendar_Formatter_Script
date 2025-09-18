# About
Script used to format the calendar .ics file given by University of Valencia (UV) for better readability.

Takes the summary field of the events and converts it into something more readable at first sight, either defined by user or automatically.
Data removed from summary is moved into description.

## Example of changes
Summary:
`33957 - Nutrición: Nutrición Grupo Teoría DG-T` -> `Nutrición - Teoría`

Description
`AULA AF-14 B 21` -> `(33957) - Teoría grupo DG-T. Location: AULA AF-14 B 21`

## Custom naming
After running the script with one .ics file, all subject IDs and their name are stored in a json file.
Modify the names of each subject to the desired one and re-run the script again to apply custom naming. 


# Current bug
Seems like headers of the generated calendar file are not copied well. See #2
