import hashlib
import pandas as pd
from ics import Calendar, Event
import json
from datetime import datetime
from pathlib import Path

from utils.logger import LoggerSingleton
log = LoggerSingleton().get_logger()

class ICSHandler:
    def __init__(self, ics_filepath):
        self.filepath = None  
        self.calendar = self._open_file(ics_filepath)

    def _open_file(self, path:str|Path):
        ics_file_path = Path(path) if isinstance(path, str) else path 

        log.info(f"Searching for calendar file '{ics_file_path}'")
        if not ics_file_path.exists():
            msg = f"Calendar file not found: {ics_file_path.resolve()}"
            log.error(msg)
            raise FileNotFoundError(msg)
        self.filepath = ics_file_path

        with open(ics_file_path, 'r',encoding='utf-8') as f:
            return Calendar(f.read())

    def as_list(self)-> list:
        calendar = self.calendar
        events = []
        for event in calendar.events:
            categories_str  = ICSHelpers._stringify(getattr(event, "categories", None), sep=", ")
            description_str = ICSHelpers._stringify(getattr(event, "description", None), sep=" ")
            
            events.append({
                'UID':getattr(event, 'uid', None),
                'SHORT_DESCRIPTION': getattr(event, 'name', '') or '',
                'DESCRIPTION': description_str,
                'CLASSIFICATION': getattr(event, 'classification', None),
                'CATEGORIES': categories_str,
                'CREATED': ICSHelpers._to_datetime(getattr(event, 'created', None)),
                'LAST_MODIFIED': ICSHelpers._to_datetime(getattr(event, 'last_modified', None)),
                'DTSTART': ICSHelpers._to_datetime(getattr(event, 'begin', None)),
                'DTEND':   ICSHelpers._to_datetime(getattr(event, 'end', None)),
            })
        
        return events

class ICSHelpers:
    @staticmethod
    def _to_datetime(value) -> datetime | None:
        """
        Return a datetime if possible; otherwise None.
        Handles ics.py Arrow-like objects, datetime, and ISO-ish strings.
        """
        if value is None:
            return None
        # ics.py uses Arrow; its fields expose `.datetime`
        if hasattr(value, "datetime"):
            try:
                dt = value.datetime
                return dt if isinstance(dt, datetime) else None
            except Exception:
                return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            s = value.strip()
            try:
                # Handle trailing 'Z' and offset forms
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    @staticmethod
    def _stringify(value, sep: str = ", ") -> str:
        """Convert strings/iterables/None to a single string."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        try:
            return sep.join(str(x) for x in value)
        except TypeError:
            # Not iterable; fall back to plain str
            return str(value)
# ------------------------- OLD FILES -------------------------

def main_ics_formater():
    schedule_df = convert_schedule_json_to_df()

    events_df = convert_event_cal_ics_to_df()

    combined_df = join_both_df(schedule_df, events_df)
    
    final_df = hash_df_event_UID(combined_df)
    
    convert_df_to_ics(final_df)

def convert_schedule_json_to_df():
    def convert_dates_to_ics_standard(df):
        df['DTSTART'] = pd.to_datetime(df['inicio'], utc=True)
        df['DTSTART'] = df['DTSTART'].dt.strftime('%Y%m%dT%H%M%SZ')

        df['DTEND'] = pd.to_datetime(df['fin'], utc=True)
        df['DTEND'] = df['DTEND'].dt.strftime('%Y%m%dT%H%M%SZ')

        df.drop('inicio', axis=1,inplace=True)
        df.drop('fin', axis=1,inplace=True)

        return df

    def set_priorities_by_act(row):
        actividad = row['actividad']
        priority = None
        
        if 'Seminario' in actividad:
            priority = int(4)
        elif 'Laboratorio' in actividad:
            priority = int(2)
        elif 'Teoría' in actividad:
            priority = int(7)

        return priority

    def add_sem_and_lab_to_summary(row):
        actividad = row['actividad']
        summary = row['SUMMARY']

        if 'Seminario' in actividad:
            summary = 'Seminario ' + summary
        elif 'Laboratorio' in actividad:
            summary = 'Laboratorio ' + summary
    
        return summary

    def obtain_df_from_json():
        with open(r'app\data\schedule.json', 'r', encoding='utf-8') as f:
            data = json.load(f)  
        
        items = data.get('items', [])  

        df = pd.json_normalize(items)
        return df
        
    log.info(f"Converting data from Schedule Calendar.")
    df = obtain_df_from_json()

    wanted_columns = ['inicio', 'fin', 'nombre_lugar', 'nombre_asignatura', 'nombre_actividad', 'identificador_grupo','identificador_edificio'] # , 'codigo_asignatura'
    df = df[wanted_columns]
    
    df = convert_dates_to_ics_standard(df)

    df.rename(columns={
        'nombre_actividad': 'actividad',
        'nombre_asignatura': 'SUMMARY',
        'identificador_grupo': 'grupo',
        }, inplace=True)

    df['actividad'] = df['actividad'].str.split(' ').str[0]
    df['actividad'] = df['actividad'].str.capitalize()
    df['SUMMARY'] = df['SUMMARY'].str.capitalize()
    
    df['nombre_lugar'] = df['nombre_lugar'].str.replace("AULA","Class")
    df['LOCATION'] = df['nombre_lugar'].str.cat(df['identificador_edificio'], sep=' Building ',na_rep='')
    df.drop('identificador_edificio', axis=1,inplace=True)
    df.drop('nombre_lugar', axis=1,inplace=True)

    df['DESCRIPTION'] = df['actividad'].str.cat(df['grupo'], sep='. ', na_rep='')    
    df.drop('grupo', axis=1,inplace=True)
    
    current_time = datetime.utcnow()
    df['DTSTAMP'] = current_time.strftime('%Y%m%dT%H%M%SZ')

    df['PRIORITY'] = df.apply(set_priorities_by_act, axis=1)

    df['SUMMARY'] = df.apply(add_sem_and_lab_to_summary, axis=1)
    df.drop('actividad', axis=1,inplace=True)

    return df

def convert_event_cal_ics_to_df():

    def categorize_activity(short_descript):
        exercises_keywords = ['cuestionario','questionario','quiz','tarea','evaluación continua']
        exam_keywords = ['exam','test','examen']
        obligatory_presence_keywords = ['asistencia', 'tutoría', 'seminario']

        if any(keyword in short_descript.lower() for keyword in exercises_keywords):
            return 'Exercises'
        elif any(keyword in short_descript.lower() for keyword in exam_keywords):
            return 'Exam'
        elif any(keyword in short_descript.lower() for keyword in obligatory_presence_keywords):
            return 'Obligatory class'
        else:
            return 'event'
            
    log.info(f"Converting data from Event Calendar.")
    ics_file_path = r'app\data\event_calendar.ics'
    with open(ics_file_path, 'r',encoding='utf-8') as f:
        calendar = Calendar(f.read())

    events = []
    for event in calendar.events:
        categories_str = event.categories if isinstance(event.categories, str) else ', '.join(event.categories)
        description_str = event.description if isinstance(event.description, str) else ' '.join(event.description)

        events.append({
            'short_descript': event.name,
            # 'class': event.classification,
            'asignatura': categories_str,
            # 'dtstamp': event.created.datetime,
            'DTSTAMP': event.last_modified.datetime,
            'DTSTART': event.begin.datetime,
            'DTEND': event.end.datetime,
            'description': description_str,
        })

    df = pd.DataFrame(events)

    df['DTSTART'] = pd.to_datetime(df['DTSTART'], utc=True).dt.strftime('%Y%m%dT%H%M%SZ')
    df['DTEND'] = pd.to_datetime(df['DTEND'], utc=True).dt.strftime('%Y%m%dT%H%M%SZ')
    df['DTSTAMP'] = pd.to_datetime(df['DTSTAMP'], utc=True).dt.strftime('%Y%m%dT%H%M%SZ')

    df['asignatura'] = df['asignatura'].str[8:]
    df['asignatura'] = df['asignatura'].str[0:-8]


    df['SUMMARY'] = df['short_descript'].apply(categorize_activity)

    df['DESCRIPTION'] = df['asignatura'].str.cat(df['short_descript'], sep='. ', na_rep='')
    df['DESCRIPTION'] = df['DESCRIPTION'].str.cat(df['description'], sep='. ', na_rep='')

    df.drop('asignatura', axis=1, inplace=True) 
    df.drop('short_descript', axis=1, inplace=True) 
    df.drop('description', axis=1, inplace=True) 
    
    return df

def hash_df_event_UID(df):
    df['UID'] = None

    for index, row in df.iterrows():
        unique_string = f"{row['SUMMARY']}{row['LOCATION']}{row['DESCRIPTION']}{row['DTSTAMP']}{row['DTSTART']}{row['DTEND']}"
        unique_string = unique_string.replace(" ", "")

        uid = hashlib.sha1(unique_string.encode('utf-8')).hexdigest()
        df.at[index, 'UID'] = uid + "@university"
        
    if not (len(df['UID'].unique())/len(df)) == 1:
        log.warning(f"There seems to be repeating events in the calendar.")

    return df

def join_both_df(schedule_df, events_df):
    log.info(f"Merging data.")
    df = pd.concat([schedule_df, events_df], axis=0).reset_index()

    return df

def convert_df_to_ics(df):
    log.info(f"Converting data into .ics file.")
    calendar = Calendar()

    for _, row in df.iterrows():
        event = Event()

        event.name = row['SUMMARY']
        event.begin = row['DTSTART']
        event.end = row['DTEND']
        event.location = str(row.get('LOCATION', ''))
        event.description = str(row.get('DESCRIPTION', ''))
        event.priority = row.get('PRIORITY', '')
        event.dtstamp = row.get('DTSTAMP', '')
        event.uid = row.get('UID','')

        calendar.events.add(event)

    filename=r'app\data\university_calendar.ics'
    with open(filename, 'w', encoding='utf-8') as f:
        f.writelines(calendar)

    log.info(f"Final Calendar saved as {filename}. <--")
