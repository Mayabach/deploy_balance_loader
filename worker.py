import json
import time
from datetime import datetime

import requests

with open("conf.json", 'r') as f:
    conf = json.load(f)
parent_ip = conf['parentPublicIp']
instance_id = conf['InstanceId']
other_ip = conf['otherPublicIp']


def work(buffer, iterations):
    import hashlib
    output = hashlib.sha512(buffer).digest()
    for i in range(iterations - 1):
        output = hashlib.sha512(output).digest()
    return output


def kill_me():
    global parent_ip, instance_id
    requests.post(f'https://{parent_ip}:5000/killMe', params={'workerId': instance_id})


def do_work(job):
    result = work(job['text'], job['iters'])
    requests.post(f'https://{parent_ip}:5000/finishedWork', data=result, params={'jobId': job['jobId'], })


def get_work():
    global parent_ip, other_ip
    last_time = datetime.now().timestamp()
    while (datetime.now().timestamp() - last_time) <= 600:
        job = requests.get(f'https://{parent_ip}:5000/getWork').json()
        if 'jobId' in job:
            do_work(job)
        else:
            job = requests.get(f'https://{other_ip}:5000/getWork').json()
            if 'jobId' in job:
                do_work(job)
        time.sleep(60)
    kill_me()


def main():
    get_work()


if __name__ == "__main__":
    main()
