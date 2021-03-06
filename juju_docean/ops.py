import logging
import time
import subprocess

from juju_docean.exceptions import TimeoutError
from juju_docean import ssh

log = logging.getLogger("juju.docean")


class MachineOp(object):

    def __init__(self, provider, env, params, **options):
        self.provider = provider
        self.env = env
        self.params = params
        self.created = time.time()
        self.options = options

    def run(self):
        raise NotImplementedError()


class MachineAdd(MachineOp):

    timeout = 240
    delay = 8

    def run(self):
        instance = self.provider.launch_instance(self.params)
        self.provider.wait_on(instance)
        instance = self.provider.get_instance(instance.id)
        self.verify_ssh(instance)
        if self.options['series'] == 'precise':
            self.update_image(instance)
        return instance

    def update_image(self, instance):
        """Workaround for Digital ocean precise images.

        Those images are too old to be used out of the box without updating.
        Ie. basic tasks like apt-get install python-software-properties failed.
        Filed as upstream DO issue @ http://bit.ly/1gLwsgs

        Unfortunately this can take several minutes, depending on instance
        type.
        """
#        log.info("Update precise instance %s (DO bug http://bit.ly/1gLwsgs)",
#                 instance.ip_address)
        t = time.time()
        ssh.update_instance(instance.ip_address)
        log.debug("Update precise instance %s complete in %0.2f",
                  instance.ip_address, time.time() - t)

    def verify_ssh(self, instance):
        # Manual provider bails immediately upon failure to connect
        # on ssh, we loop to allow the instance time to start ssh.
        max_time = self.timeout + time.time()
        running = False
        while max_time > time.time():
            try:
                if ssh.check_ssh(instance.ip_address):
                    running = True
                    break
            except subprocess.CalledProcessError, e:
                if ("Connection refused" in e.output or
                        "Connection timed out" in e.output or
                        "Connection closed" in e.output):
                    log.debug(
                        "Waiting for ssh on id:%s ip:%s name:%s remaining:%d",
                        instance.id, instance.ip_address, instance.name,
                        int(max_time-time.time()))
                    time.sleep(self.delay)
                else:
                    log.error(
                        "Could not ssh to instance name: %s id: %s ip: %s\n%s",
                        instance.name, instance.id, instance.ip_address,
                        e.output)
                    raise

        if running is False:
            raise TimeoutError(
                "Could not provision id:%s name:%s ip:%s before timeout" % (
                    instance.id, instance.name, instance.ip_address))


class MachineRegister(MachineAdd):

    def run(self):
        instance = super(MachineRegister, self).run()
        machine_id = self.env.add_machine("ssh:root@%s" % instance.ip_address)
        return instance, machine_id


class MachineDestroy(MachineOp):

    def run(self):
        self.env.terminate_machines([self.params['machine_id']])
        log.debug("Destroying instance %s", self.params['instance_id'])
        self.provider.terminate_instance(self.params['instance_id'])
