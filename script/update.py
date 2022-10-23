# -*- coding: UTF-8 -*-

from simple_salesforce import Salesforce
from base64 import b64decode as b
import requests
import json

import asyncio
from datetime import datetime
import os
import influxdb_client
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS


# ==========================================
# Variables
# ==========================================

SF_CONSUMER_KEY = os.environ.get('SF_CONSUMER_KEY')
SF_CONSUMER_SECRET = os.environ.get('SF_CONSUMER_SECRET')
SF_USERNAME = os.environ.get('SF_USERNAME')
SF_PASSWORD = os.environ.get('SF_PASSWORD')
SF_TOKEN = os.environ.get('SF_TOKEN')

INF_URL = os.environ.get('INF_URL')
INF_TOKEN = os.environ.get('INF_TOKEN')
INF_ORG = os.environ.get('INF_ORG')
INF_BUCKET = os.environ.get('INF_BUCKET')
record_to_insert = []

# ========================================== 
# Init
# ==========================================

"""
Connect to salesforce VIA SImple_Salesforce
"""
sf = Salesforce(username=SF_USERNAME,password=SF_PASSWORD, security_token=SF_TOKEN, domain='test')

"""
Connect to salesforce via API
"""


params = {
    "grant_type": "password",
    "client_id": SF_CONSUMER_KEY, # Consumer Key
    "client_secret": SF_CONSUMER_SECRET, # Consumer Secret
    "username": SF_USERNAME, # The email you use to login
    "password": SF_PASSWORD+SF_TOKEN # Concat your password and your security token 
}
r = requests.post("https://test.salesforce.com/services/oauth2/token", params=params)
# if you connect to a Sandbox, use test.salesforce.com instead
access_token = r.json().get("access_token")
instance_url = r.json().get("instance_url")
print("r: ", r.json())
print("Access Token:", access_token)
print("Instance URL", instance_url)



# ==========================================
# Utilities
# ==========================================

def sf_api_call(action, parameters = {}, method = 'get', data = {}):
    """
    Helper function to make calls to Salesforce REST API.
    Parameters: action (the URL), URL params, method (get, post or patch), data for POST/PATCH.
    """
    headers = {
        'Content-type': 'application/json',
        'Accept-Encoding': 'gzip',
        'Authorization': 'Bearer %s' % access_token
    }
    if method == 'get':
        r = requests.request(method, instance_url+action, headers=headers, params=parameters, timeout=30)
    elif method in ['post', 'patch']:
        r = requests.request(method, instance_url+action, headers=headers, json=data, params=parameters, timeout=10)
    else:
        # other methods not implemented in this example
        raise ValueError('Method should be get or post or patch.')
    print('Debug: API %s call: %s' % (method, r.url) )
    if r.status_code < 300:
        if method=='patch':
            return None
        else:
            return r.json()
    else:
        raise Exception('API error when calling %s : %s' % (r.url, r.content))


"""
Timestamp
"""
def insertTimestamp():

    _pointa = Point("log").tag("type", "datetime").field("last update", datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
    record_to_insert.append(_pointa)


"""
Get Salesforce limits
"""
def getsalesforcelimits():

    result = sf.query_more("/services/data/v50.0/limits", True)
    # print(result2)
    for element in result:
        count = result[element]['Max'] - result[element]['Remaining']
        used_percent = 0
        if (result[element]['Max'] != 0):
            used_percent = (count / result[element]['Max']) * 100

        record_to_insert.append({
            "measurement": "limits", 
            "tags": {"type": element}, 
            "fields": {
                "Done": count,
                "Remaining": result[element]['Remaining'],
                "Max": result[element]['Max'],
                "UsedPercent": used_percent
            }
        })



"""
Get Salesforce Licenses
"""
def getsalesforcelicense():

    result2 = sf.query_all("select Id, Name, UsedLicenses, TotalLicenses, Status, MasterLabel, LicenseDefinitionKey from UserLicense WHERE Name ='Salesforce'")
    remains = result2['records'][0]['TotalLicenses'] - result2['records'][0]['UsedLicenses']
    if (result2['records'][0]['TotalLicenses'] != 0):
        percent_used = (result2['records'][0]['UsedLicenses'] / result2['records'][0]['TotalLicenses']) * 100
        
    record_to_insert.append({
        "measurement": "license", 
        "tags": {"type": "Licenses"}, 
        "fields": {
            "Used": result2['records'][0]['UsedLicenses'],
            "Remains": remains,
            "Total": result2['records'][0]['TotalLicenses'],
            "Percent_used": percent_used
        }
    })


"""
Get Salesforce count records
"""
def countRecords():

    result = sf.query_more("/services/data/v50.0/limits/recordCount", True)
    for element in result['sObjects']:

        record_to_insert.append({
            "measurement": "CountRecords", 
            "tags": {"type": element['name']}, 
            "fields": {
                "counts": element['count'],
                "size": element['count'] * 2
            }
        })

"""
Get Last Logs
"""
def getSalesforceApexlog():

    result = json.dumps(sf_api_call('/services/data/v53.0/tooling/query/?q=SELECT+Request,+LogUserId,+Status,+DurationMilliseconds,+SystemModstamp+from+ApexLog'), indent=2)
    

"""
Get Salesforce Instance info
"""
def getsalesforceInstance():

    result2 = sf.query_all("Select FIELDS(ALL) From Organization LIMIT 1")
    pod = result2['records'][0]['InstanceName']

    responsestatus = requests.get("https://api.status.salesforce.com/v1/instances/"+ pod +"/status/preview?childProducts=false")

    record_to_insert.append({
        "measurement": "OrgInformation", 
        "tags": {"type": 'OrgInformation'}, 
        "fields": {
            "Pod": result2['records'][0]['InstanceName'],
            "OrganizationType": result2['records'][0]['OrganizationType'],
            "IsSandbox": result2['records'][0]['IsSandbox'],
            "releaseVersion": responsestatus.json()['releaseVersion'],
            "releaseNumber": responsestatus.json()['releaseNumber'],
            "nextMaintenance": responsestatus.json()['maintenanceWindow']

        }
    })
    return result2['records'][0]['InstanceName']


"""
Get Salesforce Incident
"""
def getsalesforceIncidents(instancepod):

    response = requests.get("https://api.status.salesforce.com/v1/incidents/active")


    incident_to_insert = []
    no_incident_to_insert = ''
    pod = ''
    message = ''
    severity = ''

    for element in response:
        try: 
            message = response.json()[element]['IncidentEvents'][0]['message']
            endTime = response.json()[element]['IncidentImpacts'][0]['endTime']
            severity = response.json()[element]['severity']
        except:
            pass

        try: 
            pod = response.json()[element]['instanceKeys']
            pod = str(pod)
            pod = pod.replace("'", "").replace("[", "").replace("]", "")
        except:
            pass
        #print(instancepod + ' vs ' + pod)
        if (instancepod  in pod) :
            incident = {
            "measurement": "SF_Incident", 
            "tags": { "Pod": pod, 
                },
            "fields": {
                "id": '',
                "IsError": 20,
                "message": message,
                "severity": severity
                    }
            }
            incident_to_insert.append(incident)
            print(incident) 
        else:
            incident = {
            "measurement": "SF_Incident", 
            "tags": { "Pod": pod, 
                },
            "fields": {
                "id": '',
                "IsError": 10,
                "message": "Pod" + pod + " OK"
                    }
            }
            no_incident_to_insert = incident

        if ( len(incident_to_insert) == 0):
            record_to_insert.append(no_incident_to_insert)
        else:
            record_to_insert.append(incident_to_insert)




"""
Update Database
"""
def update_database_sync():
    client = InfluxDBClient(url=INF_URL, token=INF_TOKEN, org=INF_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    getsalesforcelimits()
    getsalesforcelicense()
    instancepod = getsalesforceInstance()
    getsalesforceIncidents(instancepod) 
    countRecords()
    insertTimestamp()
    getSalesforceApexlog()
    print(record_to_insert)
    write_api.write(bucket=INF_BUCKET, record=record_to_insert)
    


update_database_sync()
