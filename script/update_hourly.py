# -*- coding: UTF-8 -*-

from simple_salesforce import Salesforce
from base64 import b64decode as b
import requests
import pygeohash as pgh

import asyncio
from datetime import datetime,  timedelta
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
Connect to salesforce
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



def login_log():
    result = sf.query_all("SELECT id, ApiType, ApiVersion, Application, AuthenticationServiceId, AuthMethodReference, Browser, ClientVersion, CountryIso,  \
                            LoginGeo.City, LoginGeo.Longitude, LoginGeo.Latitude, SourceIp, Status, NetworkId, LoginTime, Platform, UserId  \
                            FROM LoginHistory \
                            WHERE LoginTime = TODAY \
                            AND HOUR_IN_DAY(LoginTime) > 2")
    
    for element in result['records']:          
            print(element['LoginGeo']['Longitude'])
            print(element['LoginGeo']['Latitude'])
            print(element['LoginGeo']['City'])
            print()
            print(element['UserId'])
            print(element['SourceIp'])
       
            point = {
                "measurement": "logins.logs",
                "tags": {
                "geohash": pgh.encode(latitude=element['LoginGeo']['Latitude'], longitude=element['LoginGeo']['Longitude'])
                },
                "time": element['LoginTime'],
                "fields": {
                    "Longitude": element['LoginGeo']['Longitude'],
                    "Latitude": element['LoginGeo']['Latitude'],
                    "Geohash": pgh.encode(latitude=element['LoginGeo']['Latitude'], longitude=element['LoginGeo']['Longitude']),
                    "Country": element['CountryIso'],
                    "City": element['LoginGeo']['City'],
                    "Status": element['Status'],
                    "Ip": element['SourceIp'],
                    "Application": element['Application'],
                    "NetworkId": element['NetworkId'],
                    "AuthMethodReference": element['AuthMethodReference'],
                    "UserId": element['UserId'],
                    "Platform": element['Platform'],
                    "AuthenticationServiceId": element['AuthenticationServiceId']


                    }
            }
            print(point)
            record_to_insert.append(point)


"""
Update get SecurityHealthCheck
"""
def get_SecurityHealthCheck():
    score = sf_api_call('/services/data/v53.0/tooling/query/?q=SELECT+Score+FROM+SecurityHealthCheck')
    score['records'][0]['Score']
    point = {
                "measurement": "SecurityHealthCheckScore",
                "tags": {
                "type": 'Security'
                },
                "fields": {
                    "Score": score['records'][0]['Score']
                    }
            }
    record_to_insert.append(point)


"""
get SecurityHealthCheck RISk
"""
def get_SecurityHealthCheckRisks():
    i=0
    response = sf_api_call('/services/data/v53.0/tooling/query/?q=SELECT+RiskType,+Setting,+SettingGroup,+OrgValue,+StandardValue+FROM+SecurityHealthCheckRisks+where+RiskType=\'HIGH_RISK\'+OR+RiskType=\'MEDIUM_RISK\'')
    for element in response['records']:
        record_to_insert.append({
                "measurement": "SecurityHealthCheck",
                "tags": {
                "type": element['Setting'],
                "detail": element['SettingGroup'],
                "increment": i
                },
                "time": datetime.now() + timedelta(seconds=i),
                "fields": {
                    "RiskType": element['RiskType'],
                    "Setting": element['Setting'],
                    "OrgValue": element['OrgValue'],
                    "StandardValue": element['StandardValue'],
                    "SettingGroup": element['SettingGroup']
                    }
        })
        i = i + 1






"""
Update Database
"""
def update_database_sync():
    client = InfluxDBClient(url=INF_URL, token=INF_TOKEN, org=INF_ORG)
    write_api = client.write_api(write_options=SYNCHRONOUS)
    login_log()
    get_SecurityHealthCheck()
    get_SecurityHealthCheckRisks()
    print(record_to_insert)
    write_api.write(bucket=INF_BUCKET, record=record_to_insert)
    

update_database_sync()
