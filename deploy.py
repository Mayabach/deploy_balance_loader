import json
import time

import boto3
import datetime

import paramiko as paramiko
import requests as requests
from flask import jsonify

# Ubuntu 20.04 Amazon Machine Image (AMI)
ubuntu_20_04_ami = "ami-0136ddddd07f0584f"

# Create a new EC2 key pair and save it locally
key_name = f"CCC-Maya-{datetime.datetime.now().timestamp()}"
key_pem = f"{key_name}.pem"
session = boto3.Session(region_name='eu-west-1')
ec2_client = session.client('ec2')
response = ec2_client.create_key_pair(KeyName=key_name)
key_material = response['KeyMaterial']
ssh_commands = ["sudo apt-get update > /dev/null",
                "sudo apt-get install -y python3-pip git > /dev/null",
                "git clone https://github.com/Mayabach/deploy_balance_loader.git > /dev/null",
                "sudo python3 -m pip install -r deploy_balance_loader/requirements.txt > /dev/null"]

with open(key_pem, 'w') as key_file:
    key_file.write(key_material)
print(f"Key pair {key_name} was created")

# Create a new security group
sec_grp_name = f"my-sg-{datetime.datetime.now().timestamp()}"
response = ec2_client.create_security_group(
    GroupName=sec_grp_name,
    Description="Access instances"
)
security_group_id = response['GroupId']
print(f"Security group {security_group_id} was created")
# Determine the machine's public IP address
try:
    my_ip = requests.get('https://ipinfo.io/ip').text
    if my_ip is None:
        print('Unable to retrieve public IP address.')
except requests.RequestException as e:
    print('Error occurred while retrieving public IP address:', str(e))
    exit()
print(f"IP retrieved {my_ip}")

# Authorize inbound rules for SSH and HTTP
ec2_client.authorize_security_group_ingress(
    GroupName=sec_grp_name,
    IpPermissions=[
        {
            'FromPort': 22,
            'ToPort': 22,
            'IpProtocol': 'tcp',
            'UserIdGroupPairs': [{'GroupId': security_group_id}],
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        },
        {
            'FromPort': 5000,
            'ToPort': 5000,
            'IpProtocol': 'tcp',
            'UserIdGroupPairs': [{'GroupId': security_group_id}],
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        }
    ]
)

iam_role_name = f"iam-role-{datetime.datetime.now().timestamp()}"

iam = session.client('iam')
assume_role_policy_document = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "ec2.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
role = iam.create_role(
    RoleName=iam_role_name,
    AssumeRolePolicyDocument=json.dumps(assume_role_policy_document)
)
time.sleep(3)
role_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": [
            "ec2:RunInstances",
            "ec2:TerminateInstances",
            "ec2:DescribeInstances"
        ],
        "Resource": "*"
    }]
}

iam.put_role_policy(
    RoleName=iam_role_name,
    PolicyName=iam_role_name,
    PolicyDocument=json.dumps(role_policy)
)
print(f"IAM role {iam_role_name} created successfully")

instance_profile_name = f"instance_profile-{datetime.datetime.now().timestamp()}"

iam.create_instance_profile(InstanceProfileName=instance_profile_name)
iam.add_role_to_instance_profile(
    InstanceProfileName=instance_profile_name,
    RoleName=iam_role_name
)
print(f"Instance profile {instance_profile_name} created successfully")


class Instance:
    def __init__(self, instance_id, public_ip, public_dns):
        self.instanceId = instance_id
        self.publicIp = public_ip
        self.publicDNS = public_dns


# Launch Ubuntu 20.04 instance
instances = ec2_client.run_instances(
    ImageId=ubuntu_20_04_ami,
    InstanceType='t3.micro',
    KeyName=key_name,
    SecurityGroupIds=[security_group_id],
    MinCount=2,
    MaxCount=2
)['Instances']

instance_ids = [instance['InstanceId'] for instance in instances]
print(f"2 instances were created: {instance_ids}")

# Wait for the instance to reach the running state
ec2_client.get_waiter('instance_running').wait(InstanceIds=instance_ids)
response = ec2_client.describe_instances(InstanceIds=instance_ids)

ubuntu_instances = [Instance(instance['InstanceId'], instance['PublicIpAddress'], instance['PublicDnsName'])
                    for reservation in response['Reservations'] for instance in reservation['Instances']]

# Execute commands on the instances
for i, instance in enumerate(ubuntu_instances):
    response = ec2_client.associate_iam_instance_profile(
        IamInstanceProfile={
            'Name': instance_profile_name
        },
        InstanceId=instance.instanceId
    )

    json_data = {
        "thisInstanceId": instance.instanceId,
        "thisPublicDNS": instance.publicDNS,
        "otherInstanceId": ubuntu_instances[(i + 1) % 2].instanceId,
        "otherPublicDNS": ubuntu_instances[(i + 1) % 2].publicDNS,
        "securityGroup": security_group_id,
        "keyName": key_name,
        "instanceAmi": ubuntu_20_04_ami
    }

    ssh_commands.append(f"cd deploy_balance_loader; echo '{json.dumps(json_data)}' "
                        f"> conf.json; echo '{key_material}' > {key_pem}; sudo chmod 400 {key_pem};"
                        f"nohup sudo python3 main.py > main.log 2>&1 &")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    time.sleep(15)
    ssh.connect(hostname=instance.publicIp, username='ubuntu', key_filename=key_pem)

    print(f"Preparing instance {instance.instanceId} through SSH commands")
    for line in ssh_commands:
        stdin, stdout, stderr = ssh.exec_command(line)
        err = stderr.read().decode()
        if err:
            print(err)

    ssh.close()

print("Instances initialized.")
instance_dns = [instance.publicDNS for instance in ubuntu_instances]
for dns_name in instance_dns:
    print(f"Work can be sent to: http://{dns_name}:5000")
