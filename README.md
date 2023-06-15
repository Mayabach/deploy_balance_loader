# deploy_balance_loader

make sure to configure awscli prior to runnig program.
please run the following linesni order to run the program: 
- python3 -m pip install -r requirements.txt
- python3 deploy.py

# Possible faliure reasons:
- Internal endpoints in flask program are not protected and can be reached by a user, meaning if i had malicious intent i could request quota from both endpoints and stop the program from running, as well as requesting work such that no work reaches the workers.
- Some of the params are not checked throuroughly enough, i could insert bad data into the code and it would shut down.
- The first run will allways take longer, if there isnt a worker up, it could take up to a minute to recieve the answer to the request.
- If one of the machines stopped working, the other one will keep taking requests and deploying new instances, some of the internal requests might make the whole system to crash though.
- If a timeout occures in one of the workers, it will crash and not request to be terminated and therefore will continue to take up resources although not running code.
