from gcsa.event import Event
from gcsa.google_calendar import GoogleCalendar
from beautiful_date import *
from datetime import datetime
from homeassistant_api import Client
import re
import argparse
import yaml
from requests import get, post
import json

bay_regex = re.compile(r'Bay\s+(\d+).*')
bay_to_event = {}
now = D.now().astimezone()

## Get current event from local calendar and only get events after it ends
def does_event_exist(ha_client: Client, calendar_id: str, google_event: Event, start_time: datetime, end_time: datetime):
    local_events = []
    try:
        start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{ha_url}/calendars/{calendar_id}?start={start_str}&end={end_str}" 
        result = get(url, 
             headers={"Authorization": f"Bearer {ha_access_token}",
                      "Content-Type": "application/json"})
        local_events = json.loads(result.text)
    except Exception as e:
        raise e
    for event in local_events:
        event_start = datetime.strptime(event['start']['dateTime'], "%Y-%m-%dT%H:%M:%S%z")
        event_end = datetime.strptime(event['end']['dateTime'], "%Y-%m-%dT%H:%M:%S%z")
        if(event_start <= google_event.start and event_end >= google_event.end and event['summary'] == google_event.summary):
            return True
    return False

def filter_events_greater_than_now(event: Event):
    print(event.start.tzinfo)
    print(now.tzinfo)
    return event.start > now

def get_future_events(start_time: datetime, end_time: datetime, bay_number: int, calendar: GoogleCalendar):
    events = list(calendar.get_events(time_min=start_time, time_max=end_time, single_events=True, order_by='startTime'))
    events_by_bay = get_events_by_bay(events)

    ## if not future events exits, return empty list
    if(events_by_bay.get(str(bay_number)) == None):
        return []
    ## if they exist, filter the ones that are greater than now
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
    print(response.text)
    print(response.status_code)
    print("Created event - ", summary)
        
def main():
    global current_bay_number
    global current_calendar_id
    global credentials_path
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
    
    credentials_path = config_data.get('google_credentials_path')
    ha_access_token = config_data.get('ha_access_token').strip()
    ha_url = config_data.get('ha_url')

    print(f"Google Credentials Path: {credentials_path}")
    print(f"HA Access Token: {ha_access_token}")
    print(f"HA URL: {ha_url}")
    print("Initializing Home Assistant Client")
    ha_client = Client(ha_url, ha_access_token)

    google_calendar = GoogleCalendar("primary",credentials_path=credentials_path)
    start_time = now
    end_time = datetime(year=now.year, month=now.month, day=now.day, hour=23, minute=59, second=0)
    
    future_events = get_future_events(start_time,end_time, current_bay_number, google_calendar)
    if(len(future_events) == 0):
        print("No events found")
        return
    
    # Currently no method exists to remove stale events from local calendar
    for event in future_events:
        local_event_exists = does_event_exist(ha_client, current_calendar_id, event, start_time, end_time)
        if(local_event_exists):
            print("Event for ", event.summary, " already exists. Skipping ....")
            continue
        create_local_event(current_calendar_id, event.start, event.end, event.summary)

    # Code to merge overlapping events
    # start_time = future_events[0].start
    # end_time = future_events[0].end
    # for idx, event in enumerate(future_events):
    #     if(idx == 0):
    #         continue # First event, nothing to compare
    #     # Extend the window if next event is about to overlap
    #     # Todo add buffer time of 5 minutes
    #     if(event.start > start_time and event.start <= end_time ):
    #         end_time = event.end
    #         continue
    #     if(event.start > end_time):
    #         print("Creating new event - ", start_time, "  ",  end_time)
    #         create_local_event(current_calendar_id, start_time, end_time, "Hello")
    #         start_time = event.start
    #         end_time = event.end
    #         continue
    # print("Creating a new event - ", start_time, "  ", end_time)
    # create_local_event(current_calendar_id, start_time, end_time, "Hello")

        
if __name__ == "__main__":
    main()


