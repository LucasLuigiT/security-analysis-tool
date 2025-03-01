# Databricks notebook source
# MAGIC %run ../Includes/install_sat_sdk

# COMMAND ----------

# MAGIC %run ../Utils/initialize

# COMMAND ----------

# MAGIC %run ../Utils/common

# COMMAND ----------

from core.logging_utils import LoggingUtils
LoggingUtils.set_logger_level(LoggingUtils.get_log_level(json_['verbosity']))
loggr = LoggingUtils.get_logger()

# COMMAND ----------

dfexist = readWorkspaceConfigFile()
dfexist.filter((dfexist.analysis_enabled==True) & (dfexist.connection_test==True)).createOrReplaceGlobalTempView('all_workspaces') 

# COMMAND ----------

import json
context = json.loads(dbutils.notebook.entry_point.getDbutils().notebook().getContext().toJson())
current_workspace = context['tags']['orgId']

# COMMAND ----------

workspacedf = spark.sql("select * from `global_temp`.`all_workspaces` where workspace_id='" + current_workspace + "'" )
if (workspacedf.rdd.isEmpty()):
    dbutils.notebook.exit("The current workspace is not found in configured list of workspaces for analysis.")
display(workspacedf)
ws = (workspacedf.collect())[0]

# COMMAND ----------

workspacesdf = spark.sql('select * from `global_temp`.`all_workspaces`')
display(workspacesdf)
workspaces = workspacesdf.collect()

# COMMAND ----------

#todo: Add parent folder to all SQL assets, expose name in _json (default SAT)
#create a folder to house all SAT sql artifacts
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
session = requests.Session()
retry = Retry(connect=10, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

def create_ws_folder(ws, dir_name):
    #delete tthe WS folder if it exists
    delete_ws_folder(ws, dir_name)
    
    token = dbutils.secrets.get(json_['workspace_pat_scope'], ws.ws_token)
    url = "https://"+ ws.deployment_url
    headers = {"Authorization": "Bearer " + token, 'Content-type': 'application/json'}
    path = "/Users/"+context['tags']['user']+"/"+ dir_name
    body = {"path":  path}
    target_url = url + "/api/2.0/workspace/mkdirs"
    
    loggr.info(f"Creating {path} using {target_url}")
    session.post(target_url, headers=headers, json=body,timeout=60).json()
    
    target_url = url + "/api/2.0/workspace/get-status"
    loggr.info(f"Get Status {path} using {target_url}")
    response=requests.get(target_url, headers=headers, json=body).json()    
    print(response)
    return response['object_id']


#delete folder that houses all SAT sql artifacts
def get_ws_folder_object_id(ws, dir_name):
    
    #Use the workspace list API to get the object_id for the folder you want to use. 
    #Here’s an example for how to get it for a folder called “/Users/me@example.com”:
    token = dbutils.secrets.get(json_['workspace_pat_scope'], ws.ws_token)
    url = "https://"+ ws.deployment_url
    headers = {"Authorization": "Bearer " + token, 'Content-type': 'application/json'}
    path = "/Users/"+context['tags']['user']+"/"
    body = {"path":  path}
    
    target_url = url + "/api/2.0/workspace/list"
    loggr.info(f"Get metadata for all of the subfolders and objects in this path {path} using {target_url}")
    response=requests.get(target_url, headers=headers, json=body, timeout=60).json()    
    loggr.info(response['objects'])
    path = path+dir_name
    for ws_objects in response['objects']:
        loggr.info(ws_objects)
        if str(ws_objects['object_type']) == 'DIRECTORY' and str(ws_objects['path']) == path:
            return str(ws_objects['object_id'])
    
    
    return None
    

#delete folder that houses all SAT sql artifacts
def delete_ws_folder(ws, dir_name):
    
    token = dbutils.secrets.get(json_['workspace_pat_scope'], ws.ws_token)
    url = "https://"+ ws.deployment_url
    headers = {"Authorization": "Bearer " + token, 'Content-type': 'application/json'}
    path = "/Users/"+context['tags']['user']+"/"+ dir_name
    body = {"path":  path, "recursive": True}
    target_url = url + "/api/2.0/workspace/delete"
    loggr.info(f"Creating {path} using {target_url}")
    
    session.post(target_url, headers=headers, json=body, timeout=60  ).json()
    loggr.info(f"Dir {dir_name} deleted")
    


# COMMAND ----------

folder_id = create_ws_folder(ws, 'SAT_alerts')

# COMMAND ----------

#object_id = get_ws_folder_object_id(ws, 'SAT')

#loggr.info(f"Using object_id for the SAT folder : {object_id}!") 

# COMMAND ----------

import requests
data_source_id =''
user_id = None
DOMAIN = ws.deployment_url
TOKEN =  dbutils.secrets.get(json_['workspace_pat_scope'], ws.ws_token) 
        
loggr.info(f"Looking for data_source_id for : {json_['sql_warehouse_id']}!") 
       
response = requests.get(
          'https://%s/api/2.0/preview/sql/data_sources' % (DOMAIN),
          headers={'Authorization': 'Bearer %s' % TOKEN},
          json=None,
          timeout=60  
        )
resources = json.loads(response.text)
#print (resources)
for resource in resources:
    if resource['endpoint_id'] == json_['sql_warehouse_id']:
        data_source_id = resource['id']
        loggr.info(f"Found data_source_id for : {json_['sql_warehouse_id']}!") 

# COMMAND ----------

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
session = requests.Session()
retry = Retry(connect=10, backoff_factor=0.5)
adapter = HTTPAdapter(max_retries=retry)
session.mount('http://', adapter)
session.mount('https://', adapter)

DOMAIN = ws.deployment_url
TOKEN =  dbutils.secrets.get(json_['workspace_pat_scope'], ws.ws_token) 
loggr.info(f"Creating alerts on: {DOMAIN}!") 

#load alerts templates for each workspace
for ws_to_load in workspaces:

    alert_name = "sat_alerts_"+ws_to_load.workspace_id
    body = {"name" : alert_name}
    response = requests.get(
              'https://%s/api/2.0/preview/sql/alerts' % (DOMAIN),
              json = body,
              headers={'Authorization': 'Bearer %s' % TOKEN},
              timeout=60)
    alerts = response.json()
    found = False
    #for alert in alerts:
    #    if (alert['name'] == alert_name):
    #        found = True
    #if alert is already configured, or folder is not found move on to next ws
    if (response.status_code == 200 and found):
        loggr.info(f"Alert already configured for workspace {ws_to_load.workspace_id}") 
        continue

    if (folder_id is None):
        loggr.info(f"Folder can't be created or found {ws_to_load.workspace_id}") 
        continue    
    response = session.post(
              'https://%s/api/2.0/preview/sql/queries' % (DOMAIN),
              headers={'Authorization': 'Bearer %s' % TOKEN},
              json={
                        "data_source_id":data_source_id,
                        "name": "sat_alert_"+ws_to_load.workspace_id,
                        "description": "",
                        "parent":"folders/"+str(folder_id),
                        "query": "(\n  SELECT\n    concat(\n      \"<br> <b>Configured Alert: Check name:</b> \",\n      sbp.check_id,\n      \", <b>Check:</b>\",\n      sbp.check,\n      \" in workspace:\",\n      sc.workspaceid,\n      \", <b>Recommendation:</b>\",\n      sbp.recommendation,\n      \"</br>\"\n    ) as message,\n    count(*) as total\n  FROM\n    security_analysis.security_checks sc,\n    security_analysis.security_best_practices sbp\n  WHERE\n    sbp.id = sc.id\n    and sc.workspaceid = "+ws_to_load.workspace_id+" \n    and sbp.alert = 1\n    and sc.score = 1\n    and run_id = (\n      select\n        max(run_id)\n      from\n        security_analysis.workspace_run_complete\n      where\n        workspace_id = "+ws_to_load.workspace_id+" \n        and completed = true\n    )\n  GROUP BY\n    1\n  ORDER BY\n    total DESC\n)\nUNION\n  (\n    SELECT\n      concat(\n        \"<br> <b>Detrimental Alert: Check name:</b> \",\n        sbp.check_id,\n        \", <b>Check:</b>\",\n        sbp.check,\n        \" in workspace:\",\n        sc1.workspaceid,\n        \", <b>Recommendation:</b>\",\n        sbp.recommendation,\n        \"</br>\"\n      ) as message,\n      count(*) as total\n    FROM\n      security_analysis.security_checks sc1,\n      security_analysis.security_checks sc2,\n      security_analysis.security_best_practices sbp\n    where\n      sc1.workspaceid = "+ws_to_load.workspace_id+" \n      and sc2.workspaceid = sc1.workspaceid\n      and sc1.id = sc2.id\n      and sc1.id = sbp.id\n      and sc1.score > sc2.score\n      and sc1.run_id = (\n        select\n          max(run_id)\n        from\n          security_analysis.workspace_run_complete\n        where\n          workspace_id = "+ws_to_load.workspace_id+" \n          and completed = true\n      )\n      and sc2.run_id = (\n        select\n          max(run_id)\n        from\n          security_analysis.workspace_run_complete\n        where\n          workspace_id = "+ws_to_load.workspace_id+" \n          and completed = true\n          and run_id = (\n            select\n              max(run_id)\n            from\n              security_analysis.workspace_run_complete\n            where\n              workspace_id = "+ws_to_load.workspace_id+" \n              and completed = true\n              and run_id < (\n                select\n                  max(run_id)\n                from\n                  security_analysis.workspace_run_complete\n                where\n                  workspace_id = "+ws_to_load.workspace_id+"\n                  and completed = true\n              )\n          )\n      )\n    GROUP BY\n      1\n    ORDER BY\n      total DESC\n  )"
                  
                   

                      },
              timeout=60  
            )

    if response.status_code == 200:
        loggr.info(f"Alert query is successfuly created: {response.json()['id']}!")
        query_id = response.json()["id"] 
    else:
        loggr.info(f"Error creating alert query: {(response.json())}")   

    if query_id is not None:
        response = session.post(
                  'https://%s/api/2.0/preview/sql/alerts' % (DOMAIN),
                  headers={'Authorization': 'Bearer %s' % TOKEN},
                  json={
                   "name":"sat_alerts_"+ws_to_load.workspace_id+"",
                   "options":{
                      "op":">=",
                      "value":1,
                      "muted":False,
                      "column":"total",
                      "custom_subject":"SAT-Alert for workspace:"+ws_to_load.workspace_id,
                      "custom_body":"Hello,\nAlert \"{{ALERT_NAME}}\" changed status to {{ALERT_STATUS}}.\nThere have been the following unexpected events on the last run:\n{{QUERY_RESULT_ROWS}}\n\n",
                      "schedule_failures":0
                
                   },
                   "query_id":query_id,
                   "parent":"folders/"+str(folder_id)   
                },
                timeout=60  
                )

    if response.status_code == 200:
        loggr.info(f"Alert is successfuly created {response.json()['id']}!")
        alert_id = response.json()["id"]
    else:
        loggr.info(f"Error creating alert: {(response.json())}")  

# COMMAND ----------

dbutils.notebook.exit('OK')
