import datetime
import json
import logging
import threading
import time

import requests
import boto3
import paramiko
from flask import Flask, request, jsonify

workQueue = []
workComplete = []
maxNumOfWorkers = 3
numOfWorkers = 0
worker_spawn_lock = threading.Lock()
with open("conf.json", 'r') as f:
    conf = json.load(f)
instance_id = conf['thisInstanceId']
instance_dns = conf['thisPublicDNS']
other_dns = conf['otherPublicDNS']
key_name = conf['keyName']
key_pem = f"{key_name}.pem"

logging.basicConfig(filename='main.log', level=logging.INFO)
app = Flask(__name__)


class Job:
    def __init__(self, job_id, text, iterations, r_time):
        self.jobId = job_id
        self.text = text
        self.iters = iterations
        self.time = r_time


def spawn_worker():
    global key_name, instance_dns, key_pem, conf
    ec2_client = boto3.client('ec2', region_name='eu-west-1')
    ssh_commands = ["sudo apt-get update > /dev/null",
                    "sudo apt-get install -y python3 git > /dev/null",
                    "git clone https://github.com/Mayabach/deploy_balance_loader.git > /dev/null"]
    # Launch Ubuntu 20.04 instance
    instances = ec2_client.run_instances(
        ImageId=conf["instanceAmi"],
        InstanceType='t3.micro',
        KeyName=key_name,
        SecurityGroupIds=[conf["securityGroup"]],
        MinCount=1,
        MaxCount=1
    )['Instances']
    instance_ids = [instance['InstanceId'] for instance in instances]

    app.logger.info(f"An instance was created: {instance_ids}")
    # Wait for the instance to reach the running state
    ec2_client.get_waiter('instance_running').wait(InstanceIds=instance_ids)
    response = ec2_client.describe_instances(InstanceIds=instance_ids)
    public_dns_address = [instance['PublicDnsName'] for reservation in response['Reservations']
                          for instance in reservation['Instances']][0]
    # Execute commands on the instances
    json_data = {"parentPublicDNS": instance_dns, "otherPublicDNS": other_dns, "InstanceId": instance_ids[0]}
    ssh_commands.append(f"cd deploy_balance_loader; echo '{json.dumps(json_data)}' "
                        f"> conf.json; nohup sudo python3 worker.py > worker.log 2>&1 &")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    time.sleep(15)
    app.logger.info(f"Trying to connect to {public_dns_address} with {key_pem}")
    ssh.connect(hostname=public_dns_address, username='ubuntu', key_filename=key_pem)

    app.logger.info("Preparing instance through SSH commands")
    for line in ssh_commands:
        stdin, stdout, stderr = ssh.exec_command(line)
        err = stderr.read().decode()
        if err:
            print(err)
    ssh.close()


def timer_30_sec():
    global workQueue, numOfWorkers, maxNumOfWorkers
    if len(workQueue) > 0:
        if (datetime.datetime.now().timestamp() - workQueue[0].time) > 30:
            if numOfWorkers < maxNumOfWorkers:
                spawn_worker()
            else:
                r = requests.get(f'http://{other_dns}:5000/getQuota', headers={'Accept': 'application/json'})
                if r.status_code == 200:
                    maxNumOfWorkers += 1


def handle_workers():
    while True:
        with worker_spawn_lock:
            timer_30_sec()
            time.sleep(10)


@app.route('/getQuota', methods=['GET'])
def try_get_node_quota():
    global numOfWorkers, maxNumOfWorkers
    if numOfWorkers < maxNumOfWorkers:
        maxNumOfWorkers -= 1
        return jsonify({}), 200
    return jsonify({}), 400


@app.route('/getWork', methods=['GET'])
def get_work():
    global workQueue
    if len(workQueue) > 0:
        job = workQueue.pop()
        app.logger.info(job.__dict__)
        return jsonify(json.dumps(job.__dict__)), 200
    else:
        return jsonify({}), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({}), 200


@app.route('/enqueue', methods=['PUT'])
def enqueue():
    global instance_id, workQueue
    try:
        new_job = Job(f"{instance_id}-{datetime.datetime.now().timestamp()}",
                      request.data.decode("utf-8"),
                      int(request.args.get('iterations', 1)),
                      datetime.datetime.now().timestamp())
    except:
        return jsonify({"Error: request not valid"}), 400

    workQueue.append(new_job)
    return jsonify({'jobId': new_job.jobId}), 200


@app.route('/pullCompleted', methods=['POST'])
def pull_completed():
    global workComplete, other_dns
    try:
        top = int(request.args.get('top', 1))
    except:
        return jsonify({"Error": "top usage is wrong, please input an integer"}), 404
    if len(workComplete) > 0:
        jobs = workComplete[-top:]
        return jsonify(jobs), 200
    try:
        r = requests.post(f'http://{other_dns}:5000/pullCompletedInternal', params={'top': top})
        return jsonify(r.json()), r.status_code
    except:
        return jsonify({"Error": "wait and try again later"}), 404


@app.route('/pullCompletedInternal', methods=['POST'])
def pull_completed_internal():
    global workComplete
    top = int(request.args.get('top', 1))
    if len(workComplete) > 0:
        jobs = workComplete[-top:]
        return jsonify(jobs), 200
    else:
        return jsonify({"Error": "wait and try again later"}), 404


@app.route('/finishedWork', methods=['POST'])
def finished_work():
    global workComplete
    try:
        job_id = request.args.get('jobId')
        result = request.args.get('result', 'N/A')
        workComplete.append({'jobId': job_id, 'result': result})
        return jsonify({'jobId': job_id, 'result': result})
    except:
        return jsonify({}), 404


@app.route('/killMe', methods=['POST'])
def kill_instance():
    global numOfWorkers
    try:
        ec2_client = boto3.client('ec2', region_name='eu-west-1')
        worker_id = request.args.get('workerId')
        ec2_client.terminate_instances(InstanceIds=[worker_id])
        app.logger.info(f"killed instance {worker_id}")
        numOfWorkers += 1
        return jsonify({"OK": f"Instance {instance_id} terminated"}), 200
    except:
        return jsonify({"Error": "Could not delete resource"}), 404


if __name__ == "__main__":
    try:
        handler = threading.Thread(target=handle_workers)
        handler.start()
        app.run(host='0.0.0.0', port=5000)
    except:
        exit()
    finally:
        handler.join()
