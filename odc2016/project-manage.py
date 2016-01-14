#!/usr/bin/python
# This script will create projects and instances for ODC2016 contest. 
# You need api key to access ccdb


import os,sys
from  keystoneclient.v2_0 import client as ks_client
from novaclient import client as nova_client
from neutronclient.neutron import client as neutron_client
from cinderclient import client as cinder_client
import keystoneclient.exceptions as ex

import json
import urllib2
from random import randint
import time

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

def create_project(name=None, description=None, mentor=None, configuration=None):
  """
  This function will create the tenant, set the quota, create the network and 
  add the user (mentor) to the project.
  name: (tenant["name"])
  description: (tenant['description'])
  mentor: tenant['odc_application']['mentor']['username']
  """
  project_exist=False
  try:
    project=keystone.tenants.create(tenant_name=name, description=description, enabled=True)
  except ex.Conflict, e: 
    project=find_project_by_name(name=name)
    if project == None:
      print "Error, cannot create project and it doesn't exist"
      sys.exit(1)
    else:
      print "project already exist: %s" % name
      project_exist=True
  try:
    # error on duplicate, no error when the user doesn't exist.
    project.add_user(user=mentor,role=find_role_id())
    project.add_user(user='cccs',role=find_role_id())
    # hack to be able to create the vm in the project.
    project.add_user(user=username,role=find_role_id())
  except ex.Conflict, e:
    # already a member
    pass
 
  #print project.list_users()
  #print project.id
  set_quota(project=project, config=configuration)  

  #create the network, only if the project doesn't already exist. shoud add support to detect when the network already exist at some point.
  if project_exist == False:
    n_client=neutron_client.Client('2.0', auth_url=auth_url,username=username, \
                 tenant_name=os.environ['OS_TENANT_NAME'],password=password)
    #neutron_quota={'quota': {'floatingip': config['floating-ips'],
    #                         'network': config['networks'],
    #                         'router': config['router'],
    #                         'subnet': config['subnet'],
    #                         'tenant_id':project.id}}
    #n_client.
    network = { 'name': name.replace(' ','_')+'_network', 
                'admin_state_up': True, 
                'tenant_id':project.id }
    network_info=n_client.create_network( { 'network': network })
  
    subnet =  { 'name': name.replace(' ','_')+'_subnet', 
                'network_id': network_info['network']['id'],
                'tenant_id': network_info['network']['tenant_id'],
                'cidr': '192.168.%i.0/24' % (randint(0,254)),
                'enable_dhcp': True,
                'ip_version': 4 }
    subnet_info=n_client.create_subnet( { 'subnet': subnet })
    
    router = { 'name': name.replace(' ','_')+'_router',
               'tenant_id' : network_info['network']['tenant_id'] }
    router_info=n_client.create_router({ 'router': router })
    # this is specific to East-cloud. (network_id is set to the external network id)
    n_client.add_gateway_router(router_info['router']['id'], {u'enable_snat': True,'network_id': u'f6a2af4a-f7c2-4d68-9c28-63714c931ec0'})
    n_client.add_interface_router(router_info['router']['id'], {'subnet_id': subnet_info['subnet']['id']})
    

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
  nova=nova_client.Client('2',username,password,'admin', auth_url=auth_url)
  nova.authenticate()
  nova_quota={'cores': config['cores'],
         'floating_ips': config['floating-ips'],
         'injected_file_content_bytes': config['injected-file-content-bytes'],
         'injected_files': config['injected-files'],
         'instances': config['instances'],
         'metadata_items': config['metadata-items'],
         'ram': config['ram'],
         'security_group_rules': config['security-group-rules'],
         'security_groups': config['security-groups']}
  nova.quotas.update(project.id,**nova_quota)
  cinder=cinder_client.Client('2', username, password, 'admin',auth_url=auth_url)
  cinder.authenticate()
  cinder_quota={ 'gigabytes': config['gigabytes'],
                 'snapshots': config['snapshots'],
                  'volumes': config['volumes'] }
  cinder.quotas.update(project.id, **cinder_quota)
 
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

def build_instance(my_tenant, config_data):
  """
  This function will create the instance, associate the floating ip, and 
  configure security rules (ssh/rdesktop, + something else).
  this need to be run from the user account (cccs/cloud-adm or something else.)
  """
  nova=nova_client.Client('2',username,password,my_tenant, auth_url=auth_url)
  nova.authenticate()
  cinder=cinder_client.Client('2',username,password,my_tenant, auth_url=auth_url)
  cinder.authenticate()
  image=None
  flavor=None
  port=None

  flavor=nova.flavors.find(name="c8-15gb-430")
  if 'ubuntu' in config_data['os_name'].lower():
    image=nova.images.find(name='Ubuntu_14.04_Trusty-amd64-20150708')
    port=22
    cloud_init="""#cloud-config
users:
  - name: odc2016
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - %%%CLOUD_SSH_KEY%%%

package_upgrade: true

packages:
    - apache2-bin
    - wget
    - mysql-server
    - libapache2-mod-php5
    - php5
    - php5-mysql
    - r-base
    - gdebi-core
    - python-pip
    - libzmqpp3
    - libzmqpp-dev

# manual install for ipython/jupyter, globus and RStudio
runcmd:
 - [ pip, install, jupyter ]
 - [ wget, "https://s3.amazonaws.com/connect.globusonline.org/linux/stable/globusconnectpersonal-latest.tgz", -O, /tmp/globusconnectpersonal-latest.tgz ]
 - [ tar, zxvf, /tmp/globusconnectpersonal-latest.tgz, -C, /home/odc2016 ]
 - [ chown, -R, odc2016., /home/odc2016 ]
 - [ wget, "https://download2.rstudio.org/rstudio-server-0.99.489-amd64.deb", -O, /tmp/rstudio-server-0.99.489-amd64.deb ]
 - [ gdebi, --n, /tmp/rstudio-server-0.99.489-amd64.deb ]

# Could maybe use this function?
# phone_home: if this dictionary is present, then the phone_home
# cloud-config module will post specified data back to the given
# url
# default: none
# phone_home:
#  url: http://my.foo.bar/$INSTANCE/
#  post: all
#  tries: 10
#
#phone_home:
# url: http://my.example.com/$INSTANCE_ID/
# post: [ pub_key_dsa, pub_key_rsa, pub_key_ecdsa, instance_id ]

power_state:
 delay: "+2"
 mode: reboot
 timeout: 30
""".replace("%%%CLOUD_SSH_KEY%%%",config_data['ssh_public_key'])
  elif 'centos' in config_data['os_name'].lower():
    image=nova.images.find(name='CentOS-7-x86_64-GenericCloud-1508')
    port=22
    cloud_init="""#cloud-config
users:
  - name: odc2016
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - %%%CLOUD_SSH_KEY%%%

package_upgrade: true

yum_repos:
    epel:
        baseurl: http://download.fedoraproject.org/pub/epel/7/$basearch
        enabled: true
        gpgcheck: false
        gpgkey: file:///etc/pki/rpm-gpg/RPM-GPG-KEY-EPEL-7
        name: Extra Packages for Enterprise Linux 7 - $basearch

packages:
    - epel-release
    - wget
    - httpd
    - mariadb.x86_64
    - php.x86_64
    - R.x86_64
    - python-pip
    - python-devel
    - zeromq
    - zeromq-devel
    - xorg-x11-xauth.x86_64

# manual install for ipython/jupyter, globus and RStudio
runcmd:
 - [ pip, install, jupyter ]
 - [ wget, "https://s3.amazonaws.com/connect.globusonline.org/linux/stable/globusconnectpersonal-latest.tgz", -O, /tmp/globusconnectpersonal-latest.tgz ]
 - [ tar, zxvf, /tmp/globusconnectpersonal-latest.tgz, -C, /home/odc2016 ]
 - [ chown, -R, odc2016., /home/odc2016 ]
 - [ wget, "https://download2.rstudio.org/rstudio-server-rhel-0.99.489-x86_64.rpm", -O, /tmp/rstudio-server-rhel-0.99.489-x86_64.rpm ]
 - [ yum, install, --nogpgcheck, -y, /tmp/rstudio-server-rhel-0.99.489-x86_64.rpm ]

# Could maybe use this function?
# phone_home: if this dictionary is present, then the phone_home
# cloud-config module will post specified data back to the given
# url
# default: none
# phone_home:
#  url: http://my.foo.bar/$INSTANCE/
#  post: all
#  tries: 10
#
#phone_home:
# url: http://my.example.com/$INSTANCE_ID/
# post: [ pub_key_dsa, pub_key_rsa, pub_key_ecdsa, instance_id ]

power_state:
 delay: "+2"
 mode: reboot
 timeout: 30
""".replace("%%%CLOUD_SSH_KEY%%%",config_data['ssh_public_key'])
     
  elif 'windows' in config_data['os_name'].lower():
    image=None
    cloud_init="""some cloud init for windows.."""
    return None
  else:
    return -1

  if flavor is not None and image is not None:

    volume=cinder.volumes.create(size=100,name='odc2016_boot_vol',imageRef=image.id)
    status=volume.status
    loop=0
    while status == 'downloading' or status == 'creating':
      time.sleep(5)
      volume=cinder.volumes.get(volume.id)
      status=volume.status
      loop = loop + 1
      if loop == 30:
        print "error creating volume, please diag the problem, aborting"
        return 1
      print "volume status %s, %s" % (status, my_tenant)
    block_device_mapping={'vda':volume.id}
    server=nova.servers.create("ODC2016",flavor=flavor, image='',block_device_mapping=block_device_mapping,userdata=cloud_init)
    status=server.status
    loop=0
    while status == 'BUILD':
      time.sleep(5)
      server=nova.servers.get(server.id)
      status=server.status
      loop = loop + 1
      if loop == 30:
        print "error creating vm, please diag the problem, aborting"
        return 2
      print "server status %s, %s" % (status, my_tenant)

    if status == 'ACTIVE':
      floating_ip=nova.floating_ips.create('net04_ext')
      nova.servers.add_floating_ip(server, floating_ip)
      #allow everyone to connect to port 
      try:
        nova.security_group_rules.create(parent_group_id=nova.security_groups.list()[0].id,
                                       ip_protocol='tcp',
                                       from_port=port,
                                       to_port=port,
                                       cidr='0.0.0.0/0')
      except:
        pass
      return floating_ip.ip # the ipv4
    else:
      return None

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
      response = urllib2.urlopen(request, timeout = 50)
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

def push_data_to_ccdb(setup_url,data):
  """
  This function will push data to CCDB, ip of the instances and inform that 
  the project is created.
  """
  headers = { 'Authorization': "Token token=\"%s\"" % (cloud_api_key),
              'Content-type': 'application/json'}
  request = urllib2.Request(setup_url,
                            headers=headers, data=data)
  request.get_method = lambda: 'PUT'
  attempt = 0
  content = None

  while attempt < 3:
    try:
      response = urllib2.urlopen(request, timeout = 50)
      content = response.read()
      break
    except urllib2.URLError as e:
      attempt += 1
      print type(e)

  if attempt == 3:
    sys.stderr.write("Dang, couldn't put the data!\n")
    sys.exit(1)

  code = response.getcode()
  if code != 200:
    sys.stderr.write("Bad code from server! (%s)\n" % code)
    sys.exit(1)
  

ccdb_cloud_data=get_data_from_ccdb()
if not ccdb_cloud_data.has_key("tenants"):
  sys.stderr.write("No 'tenants' key in output data!!!\n")
  sys.exit(1)

ccdb_tenants = ccdb_cloud_data["tenants"]
for tenant in ccdb_tenants:
  if tenant['odc_application']['status'] == "approved":
    
    create_project(name=tenant['name'], description=tenant['description'], 
                   mentor=tenant['odc_application']['mentor']['username'], 
                   configuration=tenant['configurations'][0])
    tenant_ip=build_instance(my_tenant=tenant['name'],config_data=tenant['odc_application'])
    if tenant_ip == 1 or tenant_ip == 2:
      print "error %d" % tenant_ip
      continue #next project on error.
    if tenant_ip is not None:
      print tenant_ip
      put_data = {"tenant_ip": tenant_ip}
      push_data_to_ccdb(tenant['odc_application']['setup_tenant_url'],data=json.dumps(put_data))
    
  

