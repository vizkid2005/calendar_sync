from gcsa.event import Event
from gcsa.google_calendar import GoogleCalendar
from google.oauth2.credentials import Credentials
from datetime import datetime, timezone
import re
import argparse
import yaml
from requests import get, post
import json
from pytz import utc

bay_regex = re.compile(r'Bay\s+(\d+).*')
bay_to_event = {}
now = datetime.now().astimezone()
print("Current time - ", now)

## Get current event from local calendar and only get events after it ends
def get_existing_event(calendar_id: str, current_event_start: datetime, current_event_end: datetime, search_start: datetime, search_end: datetime):
    local_events = []
    try:
        start_str = search_start.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = search_end.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{ha_url}/calendars/{calendar_id}?start={start_str}&end={end_str}"
        print(url)
        result = get(url, 
             headers={"Authorization": f"Bearer {ha_access_token}",
                      "Content-Type": "application/json"})
        print(result.text)
        local_events = json.loads(result.text)
    except Exception as e:
        raise e
    print("Local events - ", local_events)
    for event in local_events:
        print(event['start']['dateTime'], event['end']['dateTime'])
        event_start = datetime.strptime(event['start']['dateTime'], "%Y-%m-%dT%H:%M:%S%z")
        event_end = datetime.strptime(event['end']['dateTime'], "%Y-%m-%dT%H:%M:%S%z")
        if event_start <= current_event_start and event_end >= current_event_end:
            print("Found existing event - ", event['summary'])
            return event['summary']
    print("No existing event found")
    return None

def filter_events_greater_than_now(event: Event):
    return event.start > now

def get_future_events(start_time: datetime, end_time: datetime, bay_number: int, calendar: GoogleCalendar):
    events = list(calendar.get_events(time_min=start_time, time_max=end_time, single_events=True, order_by='startTime'))
    events_by_bay = get_events_by_bay(events)
    print(events_by_bay)
    ## if not future events exits, return empty list
    if(events_by_bay.get(str(bay_number)) == None):
        return []
    ## if they exist, filter the ones that are greater than now
    print("Filtering events greater than now - ", now)
    return list(filter(filter_events_greater_than_now, events_by_bay[str(bay_number)]))

def get_events_by_bay(events: list[Event]):
    bay_to_events = {}
    for event in events:
        bay_number = get_bay_from_event(event)
        if not bay_number in bay_to_events:
            bay_to_events[bay_number] = [event]
        else:
            bay_to_events[bay_number].append(event)
    return bay_to_events

def get_bay_from_event(event: Event):
    bay_number = bay_regex.search(event.location).group(1)
    return bay_number

def create_local_event(calendar_id: str, start_time: datetime, end_time: datetime, summary: str):
    
    response = post(f"{ha_url}/services/calendar/create_event",
                    headers={"Authorization": f"Bearer {ha_access_token}",
                             "Content-Type": "application/json"},
                    json={"entity_id": calendar_id,
                          "start_date_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
                          "end_date_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
                          "summary": summary,
                          "description": summary})
    if response.status_code >= 200 and response.status_code < 300:
        print("Created event - ", summary)
    else:
        print("ERROR in creating event - ", response.text)
        
def main():
    global current_bay_number
    global current_calendar_id
    global ha_access_token
    global ha_client
    global ha_url

    parser = argparse.ArgumentParser(description="Sync Google Calendar with Home Assistant Calendar")
    parser.add_argument("--bay-number", type=int, required=True, help="The bay number")
    parser.add_argument("--local-calendar-id", type=str, required=True, help="The local calendar id for that bay number")
    parser.add_argument("--config", type=str, required=True, help="The config file path")
    args = parser.parse_args()
    
    print(f"Bay Number: {args.bay_number}")
    current_bay_number = args.bay_number
    
    print(f"Local Calendar ID: {args.local_calendar_id}")
    current_calendar_id = args.local_calendar_id

    print(f"Config: {args.config}")
    with open(args.config, 'r') as file:
        config_data = yaml.safe_load(file)
    
    ha_access_token = config_data.get('ha_access_token').strip()
    ha_url = config_data.get('ha_url')

    print(f"HA Access Token: {ha_access_token}")
    print(f"HA URL: {ha_url}")

    token = Credentials(
    token=config_data.get('google_access_token'),
    refresh_token=config_data.get('google_refresh_token'),
    client_id=config_data.get('google_client_id'),
    client_secret=config_data.get('google_client_secret'),
    scopes=["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/calendar.events.readonly"],
    token_uri='https://oauth2.googleapis.com/token'
)
    google_calendar = GoogleCalendar("primary",credentials=token)
    current_time = now
    end_of_day = datetime(year=now.year, month=now.month, day=now.day, hour=23, minute=59, second=0)
    print("Fetching events from Google Calendar - ", current_time, " to ", end_of_day)
    future_events = get_future_events(current_time,end_of_day, current_bay_number, google_calendar)
    if(len(future_events) == 0):
        print("No events found")
        return
    
    # Currently no method exists to remove stale events from local calendar
    start_time = future_events[0].start
    end_time = future_events[0].end
    summary = future_events[0].summary
    for idx, event in enumerate(future_events):
        if(idx == 0):
            continue # First event, nothing to compare
        # Extend the window if next event is about to overlap
        if(event.start > start_time and event.start <= end_time ):
            end_time = event.end
            summary += " ," + event.summary
            continue
        if(event.start > end_time):
            local_event_summary = get_existing_event(current_calendar_id, start_time, end_time, current_time, end_of_day)
            if local_event_summary is None:
                print("Creating new event - ", summary, " Start time -",  start_time, " End time -", end_time)
                create_local_event(current_calendar_id, start_time, end_time, summary)
            else:
                print("Event for ", local_event_summary, " already exists. Skipping ....")
            start_time = event.start
            end_time = event.end
            summary = event.summary
            continue
    
    local_event_summary = get_existing_event(current_calendar_id, start_time, end_time, current_time, end_of_day)
    if local_event_summary is None:
        print("Attempting to create new event - ", summary, " Start time -", start_time, " End time -", end_time)
        create_local_event(current_calendar_id, start_time, end_time, summary)
    else:
        print("Event for ", local_event_summary, " already exists. Skipping ....")
        
if __name__ == "__main__":
    main()
