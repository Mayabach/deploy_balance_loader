import time

import boto3
import datetime

import paramiko as paramiko
import requests as requests

# Ubuntu 20.04 Amazon Machine Image (AMI)
ubuntu_20_04_ami = "ami-0136ddddd07f0584f"

# Create a new EC2 key pair and save it locally
key_name = f"CCC-Maya-{datetime.datetime.now().timestamp()}"
key_pem = f"{key_name}.pem"
session = boto3.Session(profile_name='maya-uni')
ec2_client = session.client('ec2')
response = ec2_client.create_key_pair(KeyName=key_name)
key_material = response['KeyMaterial']
ssh_commands = ["sudo apt-get update",
                "sudo apt-get install -y python3-pip git",
                "git clone https://github.com/Mayabach/deploy_balance_loader.git",
                "sudo python3 -m pip install -r deploy_balance_loader/requirements.txt"]

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
            'IpRanges': [{'CidrIp': f'{my_ip}/32'}]
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


class Instance:
    def __init__(self, instance_id, public_ip):
        self.instanceId = instance_id
        self.publicIp = public_ip


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

ubuntu_instances = [Instance(instance['InstanceId'], instance['PublicIpAddress']) for reservation
                    in response['Reservations'] for instance in reservation['Instances']]

# Execute commands on the instances
for i, instance in enumerate(ubuntu_instances):
    json = {
        "thisInstanceId": instance.instanceId,
        "thisPublicIp": instance.publicIp,
        "otherInstanceId": ubuntu_instances[(i + 1) % 2].instanceId,
        "otherPublicIp": ubuntu_instances[(i + 1) % 2].publicIp,
        "securityGroup": security_group_id,
        "keyName": key_name,
        "instanceAmi": ubuntu_20_04_ami
    }
    ssh_commands.append(f"cd deploy_balance_loader; echo {str(json)} > conf.txt; nohup sudo python3 main.py")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    time.sleep(15)
    ssh.connect(hostname=instance.publicIp, username='ubuntu', key_filename=key_pem)

    print("Preparing instances through SSH commands")
    for line in ssh_commands:
        stdin, stdout, stderr = ssh.exec_command(line)
        print(stdout.read().decode(), "\n", stderr.read().decode())

    ssh.close()

print("Instances initialized.")
instance_ips = [instance.publicIp for instance in ubuntu_instances]
print(f"Work can be sent to: https://<<ip>>:5000/enqueue,\n"
      f"Work can be retrieved through: https://<<ip>>:5000/pullCompleted\n"
      f"From IPs: {instance_ips} ")
