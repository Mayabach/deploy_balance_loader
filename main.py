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
workComplete = {}
maxNumOfWorkers = 3
numOfWorkers = 0
with open("conf.txt", 'r') as f:
    conf = json.load(f)
instance_id = conf['thisInstanceId']
instance_ip = conf['thisPublicIp']
other_ip = conf['otherPublicIp']

app = Flask(__name__)


class Job:
    def __init__(self, job_id, text, iterations, r_time):
        self.jobId = job_id
        self.text = text
        self.iters = iterations
        self.time = r_time


def run_app():
    app.run(host='0.0.0.0', port=5000)


def spawn_worker():
    global conf, instance_ip
    ec2_client = boto3.client('ec2')
    ssh_commands = ["sudo apt-get update",
                    "sudo apt-get install -y python3 git",
                    "git clone https://github.com/Mayabach/deploy_balance_loader.git"]
    # Launch Ubuntu 20.04 instance
    instance = ec2_client.run_instances(
        ImageId=conf["instanceAmi"],
        InstanceType='t3.micro',
        KeyName=conf["keyName"],
        SecurityGroupIds=conf["securityGroup"],
        MinCount=1,
        MaxCount=1
    )['Instances'][0]
    # Wait for the instance to reach the running state
    ec2_client.get_waiter('instance_running').wait(InstanceIds=instance['InstanceId'])
    response = ec2_client.describe_instances(InstanceIds=instance['InstanceId'])
    # Execute commands on the instances
    json_data = {"parentPublicIp": instance_ip, "otherPublicIp": other_ip, "InstanceId": instance['InstanceId']}
    ssh_commands.append(f"cd deploy_balance_loader; echo {str(json_data)} > conf.txt; nohup sudo python3 worker.py")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname=instance['PublicIpAddress'], username='ubuntu', key_filename=conf["keyName"])

    logging.getLogger().info("Preparing instances through SSH commands")
    for line in ssh_commands:
        stdin, stdout, stderr = ssh.exec_command(line)
        print(stdout.read().decode(), "\n", stderr.read().decode())

    ssh.close()


def timer_10_sec():
    global workQueue, numOfWorkers, maxNumOfWorkers
    if len(workQueue) > 0:
        if (datetime.datetime.now().timestamp() - workQueue[0].time) > 15:
            if numOfWorkers < maxNumOfWorkers:
                spawn_worker()
            else:
                r = requests.get(f'https://{other_ip}:5000/getQuota', headers={'Accept': 'application/json'})
                if r:
                    maxNumOfWorkers += 1


def handle_workers():
    while True:
        timer_10_sec()
        time.sleep(10)


@app.route('/getQuota', methods=['GET'])
def try_get_node_quota():
    global numOfWorkers, maxNumOfWorkers
    if numOfWorkers < maxNumOfWorkers:
        maxNumOfWorkers -= 1
        return True, 200
    return False, 400


@app.route('/getWork', methods=['GET'])
def get_work():
    global workQueue
    if len(workQueue) > 0:
        return jsonify(workQueue.pop().__dict__()), 200
    else:
        return jsonify({}), 200


@app.route('/enqueue', methods=['PUT'])
def enqueue():
    global instance_id, workQueue
    try:
        new_job = Job(f"{instance_id}-{datetime.datetime.now().timestamp()}",
                      request.data.decode('utf-8').encode(),
                      int(request.args.get('iterations', 1)),
                      datetime.datetime.now().timestamp())
    except:
        return jsonify({"Error: request not valid"})

    workQueue.append(new_job)
    return jsonify({'jobId': new_job.jobId}), 200


@app.route('/pullCompleted', methods=['POST'])
def pull_completed():
    global workComplete, other_ip
    job_id = request.args.get('jobId')
    result = workComplete.pop(job_id)
    if len(result) > 0:
        return jsonify({'jobId': job_id, 'result': result}), 200
    try:
        r = requests.post(f'https://{other_ip}:5000/pullCompletedInternal', params={'jobId': job_id})
        return r
    except:
        return jsonify({}), 404


@app.route('/pullCompletedInternal', methods=['POST'])
def pull_completed_internal():
    global workComplete
    job_id = request.args.get('jobId')
    results = workComplete.pop(job_id)
    if len(results) > 0:
        return jsonify({'jobId': job_id, 'result': results}), 200
    else:
        return jsonify({}), 404


@app.route('/finishedWork', methods=['POST'])
def finished_work():
    global workComplete
    try:
        job_id = request.args.get('jobId')
        result = request.data
        workComplete[job_id] = result
        return jsonify({'jobId': job_id, 'result': result})
    except:
        return jsonify({}), 404


@app.route('/killMe', methods=['POST'])
def kill_instance():
    ec2_client = boto3.client('ec2')
    worker_id = request.args.get('workerId')
    ec2_client.terminate_instances(InstanceIds=[worker_id])


if __name__ == "__main__":
    app = threading.Thread(target=run_app)
    app.start()
    handler = threading.Thread(target=handle_workers)
    handler.start()
