import os
import boto3
from enum import Enum
from functools import partial, wraps
import asyncio
import dotenv

dotenv.load_dotenv()

INSTANCE_NAME = os.getenv("AWS_INSTANCE_ID")
INSTANCE_TYPE = os.getenv("AWS_INSTANCE_TYPE")
INSTANCE_SIZE_MIB = "102400"

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS")
SERVER_PORT = os.getenv("SERVER_PORT")

MIN_PLAYERS = 1
SHUTDOWN_DELAY_SEC = 1800
BACKUP_INTERVAL_SEC = 86400
CHECK_ACTIVE_INTERVAL_SEC = 60
CHECK_LOBBY_INTERVAL_SEC = 1

MAX_ATTEMPTS = 60


class InstanceState(Enum):
    RUNNING = 'running'
    PENDING = 'pending'
    STOPPING = 'stopping'
    STOPPED = 'stopped'
    SHUTTING_DOWN = 'shutting-down'
    TERMINATED = 'terminated'

class InstanceStatus(Enum):
    OK = 'ok'
    IMPAIRED = 'impaired'
    INITIALIZING = 'initializing'
    INSUFFICIENT_DATA = 'insufficient-data'
    NOT_APPLICABLE = 'not-applicable'


class InstanceError(Exception):
    def __init__(self, message="Instance failed to start"):
        self.message = message
        super().__init__(self.message)

class ServerStartError(Exception):
    def __init__(self, message="Server failed to start"):
        self.message = message
        super().__init__(self.message)

class NetworkingError(Exception):
    def __init__(self, message="Networking error occurred"):
        self.message = message
        super().__init__(self.message)



def asyncify(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, self, *args, **kwargs))
    return wrapper

class Server:
    def __init__(self, name=INSTANCE_NAME, type=INSTANCE_TYPE, size=INSTANCE_SIZE_MIB):
        self.name = name
        self.type = type
        self.size = size

        self.ec2 = boto3.client('ec2')
        self.s3 = boto3.client('s3')
        self.ssm = boto3.client('ssm')
    
    def send_command(self, command, **kwargs):
        try:
            response = self.ssm.send_command(
                InstanceIds=[self.name],
                DocumentName="AWS-RunShellScript",
                Parameters={"commands": [f'sudo -u ec2-user bash -c "{command}"']},
                **kwargs
            )
            command_id = response['Command']['CommandId']

        except Exception as e:
            raise InstanceError(f"Failed to send command: {e}")
    
    async def state(self):
        return (await self.query_status())["state"]

    @asyncify
    def query_status(self):
        response = self.ec2.describe_instance_status(InstanceIds=[self.name])
        print(response)
        if not response["InstanceStatuses"]:
            raise InstanceError("Instance not found or does not exist")
        instance = response["InstanceStatuses"][0]
        return (
            InstanceState(instance["InstanceState"]["Name"]),
            InstanceStatus(instance["InstanceStatus"]["Status"])
        )

    @asyncify
    def query_instance(self):
        response = self.ec2.describe_instances(InstanceIds=[self.name])
        if not response["Reservations"]:
            raise InstanceError("Instance not found or does not exist")
        instance = response["Reservations"][0]["Instances"][0]
        return {
            "id": instance["InstanceId"],
            "state": InstanceState(instance["State"]["Name"]),
            "type": instance["InstanceType"],
            "public_ip": instance.get("PublicIpAddress"),
            "private_ip": instance.get("PrivateIpAddress"),
        }

    @asyncify
    def start_instance(self):
        try:
            self.ec2.start_instances(InstanceIds=[self.name])
        except Exception as e:
            raise InstanceError("Failed to start the instance")

    @asyncify
    def stop_instance(self):
        try:
            self.ec2.stop_instances(InstanceIds=[self.name])
        except Exception as e:
            raise InstanceError("Failed to stop the instance")
        
    @asyncify
    def is_running(self, port=SERVER_PORT):
        pass

    @asyncify
    def start_server(self, memory=4096, port=SERVER_PORT):
        try:
            self.send_command(f"cd /home/ec2-user/server && ./start --mem {memory} --port {port} --disown")
        except Exception as e:
            raise ServerStartError("Failed to start the server")
    
    @asyncify
    def stop_server(self, port=SERVER_PORT):
        try:
            # Probably check is_running first.
            self.send_command(f"tmux send-keys -t minecraft-server-{port} C-c")
        except Exception as e:
            raise ServerStartError("Failed to stop the server")

    async def start(self, progress_callback):
        try:
            state = await self.state()
            attempts = 0
            if state in [InstanceState.TERMINATED, InstanceState.SHUTTING_DOWN]:
                raise InstanceError("Instance has been terminated and cannot be restarted")
            while state != InstanceState.RUNNING and attempts < MAX_ATTEMPTS:
                if state == InstanceState.STOPPED:
                    await self.start_instnace()
                    await asyncio.sleep(2)
                elif state == InstanceState.STOPPING:
                    await asyncio.sleep(5)
                elif state == InstanceState.PENDING:
                    await progress_callback("instance")
                    await asyncio.sleep(2) # boots absurdly fast for some reason            
                state = await self.state()
                attempts += 1
            progress_callback("server")
            await self.start_server()
        except Exception as e:
            await progress_callback("failure")
            raise e
        else:
            await progress_callback("success")
        
    async def stop(self, progress_callback):
        pass # check if server is running, then stop it, then wait for it to not be running, then stop the instance