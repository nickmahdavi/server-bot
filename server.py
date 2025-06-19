import boto3
from enum import Enum
from functools import partial, wraps
import asyncio

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
 

class AWSError(Exception):
    def __init__(self, message="Instance failed to start"):
        self.message = message
        super().__init__(self.message)


def asyncify(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, self, *args, **kwargs))
    return wrapper

async def _noop(_):
    pass

class Server:
    def __init__(self, instance_id, ec2=None, s3=None, ssm=None):
        self.instance_id = instance_id

        self.ec2 = ec2 or boto3.client('ec2')
        self.s3 = s3 or boto3.client('s3')
        self.ssm = ssm or boto3.client('ssm')

        self.lock = asyncio.Lock()
    
    @classmethod
    def from_config(cls, config):
        return cls(
            instance_id=config.aws_instance_id,
        )

    @asyncify
    def _ssm_send_command(self, command, **kwargs):
        return self.ssm.send_command(
            InstanceIds=[self.instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": [command]},
            **kwargs
        )
    
    @asyncify
    def _ssm_get_command_invocation(self, CommandId, InstanceId):
        response = self.ssm.get_command_invocation(
            CommandId=CommandId,
            InstanceId=InstanceId
        )
        return {
            "Status": response["Status"],
            "ResponseCode": response["ResponseCode"],
            "StandardOutputContent": response["StandardOutputContent"],
            "StandardErrorContent": response["StandardErrorContent"]
        }
    
    async def send_command(self, command, **kwargs):
        try:
            response = await self._ssm_send_command(command, **kwargs)
            command_id = response['Command']['CommandId']
            attempts = 0
            while attempts < 60:
                attempts += 1
                try:
                    invocation = await self._ssm_get_command_invocation(
                        CommandId=command_id,
                        InstanceId=self.instance_id
                    )

                    if invocation["Status"] in ["Success", "Failed"]:
                        break

                except self.ssm.exceptions.InvocationDoesNotExist:
                    await asyncio.sleep(0.5)
                    continue

                await asyncio.sleep(0.5)

            return invocation
        except Exception as e:
            raise AWSError(f"Failed to send command: {e}")

    @asyncify
    def query_status(self):
        response = self.ec2.describe_instances(InstanceIds=[self.instance_id])
        if not response["Reservations"]:
            raise AWSError("Instance not found or does not exist")
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
        self.ec2.start_instances(InstanceIds=[self.instance_id])

    @asyncify
    def stop_instance(self):
        self.ec2.stop_instances(InstanceIds=[self.instance_id])

    async def state(self):
        status = await self.query_status()
        return status["state"]
    
    async def ssm_ready(self, max_attempts=30):
        for i in range(max_attempts):
            try:
                result = await self.send_command("echo 'SSM ready'")
                if result["ResponseCode"] == 0:
                    return True
            except:
                await asyncio.sleep(2)
        return False
    
    async def is_running(self):
        if await self.state() != InstanceState.RUNNING:
            return False
        invocation = await self.send_command("systemctl is-active minecraft.service")
        return invocation["StandardOutputContent"].strip() == "active"
    
    async def is_ready(self):
        if await self.state() != InstanceState.RUNNING:
            return False
        invocation = await self.send_command("ss -tlnp | grep -q :25565")
        return invocation["ResponseCode"] == 0

    async def start_server(self):
        await self.send_command(f"sudo systemctl start minecraft.service")

    async def stop_server(self):
        await self.send_command(f"sudo systemctl stop minecraft.service")

    async def start(self, progress_callback=_noop, max_attempts=60):
        async with self.lock:
            try:
                state = await self.state()
                attempts = 0
                if state in [InstanceState.TERMINATED, InstanceState.SHUTTING_DOWN]:
                    raise AWSError("Instance has been terminated and cannot be restarted")
                while state != InstanceState.RUNNING and attempts < max_attempts:
                    if state == InstanceState.STOPPED:
                        await self.start_instance()
                        await asyncio.sleep(2)
                    elif state == InstanceState.STOPPING:
                        await asyncio.sleep(5)
                    elif state == InstanceState.PENDING:
                        await progress_callback("instance")
                        await asyncio.sleep(2) # boots absurdly fast for some reason            
                    state = await self.state()
                    attempts += 1
                if state != InstanceState.RUNNING:
                    raise AWSError("Instance failed to start")
                
                if not await self.ssm_ready():
                    raise AWSError("SSM agent failed to get ready")

                await progress_callback("server")
                attempts = 0
                await self.start_server()
                while not await self.is_ready() and attempts < max_attempts:
                    await asyncio.sleep(2)
                    attempts += 1
                if not await self.is_ready():
                    raise AWSError("Server failed to start")

            except Exception as e:
                await progress_callback("failure")
                raise e
            else:
                await progress_callback("success")

    async def stop(self):
        async with self.lock:
            if not await self.is_running():
                return
            
            await self.stop_server()
            while await self.is_running():
                await asyncio.sleep(1)
            
            await self.stop_instance()
            while (await self.state()) != InstanceState.STOPPED:
                await asyncio.sleep(5)
