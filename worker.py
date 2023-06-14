import json
import time
from datetime import datetime
import hashlib
import requests

with open("conf.json", 'r') as f:
    conf = json.load(f)
parent_dns = conf['parentPublicDNS']
instance_id = conf['InstanceId']
other_dns = conf['otherPublicDNS']


def work(buffer, iterations):
    output = hashlib.sha512(buffer.encode("utf-8")).digest()
    for i in range(iterations - 1):
        output = hashlib.sha512(output).digest()
    return output


def kill_me():
    global parent_dns, instance_id
    requests.post(f'http://{parent_dns}:5000/killMe', params={'workerId': instance_id})


def do_work(job):
    job_dict = json.loads(job)
    result = work(job_dict['text'], job_dict['iters'])
    print(f"result {result} for job: {job_dict}")
    requests.post(f'http://{parent_dns}:5000/finishedWork', params={'jobId': job_dict['jobId'], 'result': result})


def get_work():
    global parent_dns, other_dns
    last_time = datetime.now().timestamp()
    while (datetime.now().timestamp() - last_time) <= 600:
        print("Trying to get work")
        job = requests.get(f'http://{parent_dns}:5000/getWork').json()
        if 'jobId' in job:
            do_work(job)
        else:
            job = requests.get(f'http://{other_dns}:5000/getWork').json()
            if 'jobId' in job:
                do_work(job)
        time.sleep(15)
    print("Killing Instance, Bye")
    kill_me()


def main():
    get_work()


if __name__ == "__main__":
    main()
