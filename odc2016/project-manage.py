#!/usr/bin/python
# This script will create projects and instances for ODC2016 contest. 
# You need api key to access ccdb


import os,sys
from  keystoneclient.v2_0 import client as ks_client
from novaclient import client as nova_client
import keystoneclient.exceptions as ex

import json
import urllib2

# read env for needed vars
try:
  username=os.environ['OS_USERNAME']
  password=os.environ['OS_PASSWORD']
  tenant_name=os.environ['OS_TENANT_NAME']
  auth_url=os.environ['OS_AUTH_URL']
  cloud_api_key=os.environ['CLOUD_API_KEY']
  cloud_api_host=os.environ['CLOUD_API_HOST']
  cloud=os.environ['CLOUD']
except KeyError, e:
  print "Please export the following key: %s, or source the openrc file" % e
  sys.exit(1)

keystone=ks_client.Client(username=username, password=password, \
                       tenant_name=tenant_name, auth_url=auth_url)

creds={'api_key': password, 'auth_url': auth_url, 'username': username }

#print type(keystone.tenants.list())


def create_project(name=None, description=None, mentor=None, configuration=None):
  """
  This function will create the tenant, set the quota, create the network and 
  add the user (mentor) to the project.
  name: (tenant["name"])
  description: (tenant['description'])
  mentor: tenant['odc_application']['mentor']['username']
  """
  try:
    project=keystone.tenants.create(tenant_name=name, description=description, enabled=True)
  except ex.Conflict, e: 
    project=find_project_by_name(name=name)
    if project == None:
      print "Error, cannot create project and it doesn't exist"
      sys.exit(1)
  try:
    # error on duplicate, no error when the user doesn't exist.
    project.add_user(user=mentor,role=find_role_id())
    project.add_user(user='mgariepy',role=find_role_id())
  except ex.Conflict, e:
    # already a member
    pass
 
  print project.list_users()
  print project.id
  set_quota(project=project, config=configuration)  
  
  
def set_quota(project=None, config=None):
  """
  nova quota-update $tenant_id --instances $Q_instances --cores $Q_cores \
    --ram $Q_ram --floating_ips $Q_floatingips --security-groups $Q_sec_group \
    --security-group-rules $Q_sec_group_rules
    neutron quota-update --tenant-id $tenant_id --port $Q_ports \
    --network $Q_network --subnet $Q_subnet --router $Q_router \
    --floatingip $Q_floatingips
   cinder quota-update --volumes $Q_volumes --snapshots $Q_snapshots \
    --gigabytes $Q_gigabytes $tenant_id
  """
  #my_creds=creds
  #my_creds.update('project_id': project)
  #nova=nova_client.Client('1.1',**creds)
  pass
  
  
  
def find_project_by_name(name=None):
  """
  Find project by name.
  """
  project_list=keystone.tenants.list()
  my_project=None
  for project in project_list:
    if project.name == name:
      my_project=project
  return my_project

def find_role_id(name="Member"):
  roles_list=keystone.roles.list()
  role_id=None
  for role in roles_list:
    if role.name == name:
      role_id=role.id
  return role_id

def add_ssh_key():
  """
  This function will add the public key to a user.
  """
  pass

def build_instance():
  """
  This function will create the instance, associate the floating ip, and 
  configure security rules (ssh/rdesktop, + something else).
  """
  pass

def get_data_from_ccdb():
  """
  This function will get data from ccdb, project and so on.
  """
  endpoint = "https://%s/api/cloud" % (cloud_api_host)
  cloud_url = "%s/clouds/%s" % (endpoint, cloud)
  headers = { 'Authorization': "Token token=\"%s\"" % (cloud_api_key) }
  request = urllib2.Request(cloud_url, headers=headers)
  attempt = 0
  content = None
  while attempt < 3:
    try:
      response = urllib2.urlopen(request, timeout = 5)
      content = response.read()
      break
    except urllib2.URLError as e:
      attempt += 1
      print type(e)

  if attempt == 3:
    sys.stderr.write("Dang, couldn't get the data!\n")
    sys.exit(1)

  if response.code != 200:
    sys.stderr.write("Bad code from server! (%s)\n" % response.code)
    sys.exit(1)

  # Everything is A-Okay if we're here
  # Convert JSON output from server to python dict
  cloud_data = json.loads(content)
  return cloud_data

def push_data_to_ccdb():
  """
  This function will push data to CCDB, ip of the instances and inform that 
  the project is created.
  """
  pass

ccdb_cloud_data=get_data_from_ccdb()
if not ccdb_cloud_data.has_key("tenants"):
  sys.stderr.write("No 'tenants' key in output data!!!\n")
  sys.exit(1)

ccdb_tenants = ccdb_cloud_data["tenants"]
for tenant in ccdb_tenants:
  if tenant['odc_application']['status'] == "approved":
    create_project(name=tenant['name'], description=tenant['description'], 
                   mentor=tenant['odc_application']['mentor']['username'], 
                   configuration=tenant['configurations'])
    
  

