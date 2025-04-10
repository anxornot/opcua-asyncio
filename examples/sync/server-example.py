import copy
import logging
import sys
import time
from datetime import datetime, UTC
from math import sin
from threading import Thread

sys.path.insert(0, "../..")

try:
    from IPython import embed
except ImportError:
    import code

    def embed():
        myvars = globals()
        myvars.update(locals())
        shell = code.InteractiveConsole(myvars)
        shell.interact()


from asyncua import ua, uamethod
from asyncua.sync import Server, ThreadLoop


class SubHandler:
    """
    Subscription Handler. To receive events from server for a subscription
    """

    def datachange_notification(self, node, val, data):
        print("Python: New data change event", node, val)

    def event_notification(self, event):
        print("Python: New event", event)


# method to be exposed through server


def func(parent, variant):
    ret = False
    if variant.Value % 2 == 0:
        ret = True
    return [ua.Variant(ret, ua.VariantType.Boolean)]


# method to be exposed through server
# uses a decorator to automatically convert to and from variants


@uamethod
def multiply(parent, x, y):
    print("multiply method call with parameters: ", x, y)
    return x * y


class VarUpdater(Thread):
    def __init__(self, var):
        Thread.__init__(self)
        self._stopev = False
        self.var = var

    def stop(self):
        self._stopev = True

    def run(self):
        while not self._stopev:
            v = sin(time.time() / 10)
            self.var.write_value(v)
            time.sleep(0.1)


if __name__ == "__main__":
    # optional: setup logging
    logging.basicConfig(level=logging.WARN)
    # logger = logging.getLogger("opcua.address_space")
    # logger.setLevel(logging.DEBUG)
    # logger = logging.getLogger("opcua.internal_server")
    # logger.setLevel(logging.DEBUG)
    # logger = logging.getLogger("opcua.binary_server_asyncio")
    # logger.setLevel(logging.DEBUG)
    # logger = logging.getLogger("opcua.uaprocessor")
    # logger.setLevel(logging.DEBUG)
    with ThreadLoop() as tloop:
        # now set up our server
        server = Server(tloop=tloop)
        # server.disable_clock()
        # server.set_endpoint("opc.tcp://localhost:4840/freeopcua/server/")
        server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
        server.set_server_name("FreeOpcUa Example Server")
        # set all possible endpoint policies for clients to connect through
        server.set_security_policy(
            [
                ua.SecurityPolicyType.NoSecurity,
                ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                ua.SecurityPolicyType.Basic256Sha256_Sign,
            ]
        )

        # set up our own namespace
        uri = "http://examples.freeopcua.github.io"
        idx = server.register_namespace(uri)
        print("IDX", idx)

        # create a new node type we can instantiate in our address space
        dev = server.nodes.base_object_type.add_object_type(idx, "MyDevice")
        dev.add_variable(idx, "sensor1", 1.0).set_modelling_rule(True)
        dev.add_property(idx, "device_id", "0340").set_modelling_rule(True)
        ctrl = dev.add_object(idx, "controller")
        ctrl.set_modelling_rule(True)
        ctrl.add_property(idx, "state", "Idle").set_modelling_rule(True)

        # populating our address space

        # First a folder to organise our nodes
        myfolder = server.nodes.objects.add_folder(idx, "myEmptyFolder")
        # instanciate one instance of our device
        mydevice = server.nodes.objects.add_object(idx, "Device0001", dev)
        mydevice_var = mydevice.get_child(
            [f"{idx}:controller", f"{idx}:state"]
        )  # get proxy to our device state variable
        # create directly some objects and variables
        myobj = server.nodes.objects.add_object(idx, "MyObject")
        myvar = myobj.add_variable(idx, "MyVariable", 6.7)
        mysin = myobj.add_variable(idx, "MySin", 0, ua.VariantType.Float)
        myvar.set_writable()  # Set MyVariable to be writable by clients
        mystringvar = myobj.add_variable(idx, "MyStringVariable", "Really nice string")
        mystringvar.set_writable()  # Set MyVariable to be writable by clients
        mydtvar = myobj.add_variable(idx, "MyDateTimeVar", datetime.now(UTC))
        mydtvar.set_writable()  # Set MyVariable to be writable by clients
        myarrayvar = myobj.add_variable(idx, "myarrayvar", [6.7, 7.9])
        myarrayvar = myobj.add_variable(idx, "myStronglyTypedVariable", ua.Variant([], ua.VariantType.UInt32))
        myprop = myobj.add_property(idx, "myproperty", "I am a property")
        mymethod = myobj.add_method(idx, "mymethod", func, [ua.VariantType.Int64], [ua.VariantType.Boolean])
        multiply_node = myobj.add_method(
            idx, "multiply", multiply, [ua.VariantType.Int64, ua.VariantType.Int64], [ua.VariantType.Int64]
        )

        # import some nodes from xml
        server.import_xml("custom_nodes.xml")

        # creating a default event object
        # The event object automatically will have members for all events properties
        # you probably want to create a custom event type, see other examples
        myevgen = server.get_event_generator()
        myevgen.event.Severity = 300

        # starting!
        with server:
            print("Available loggers are: ", logging.Logger.manager.loggerDict.keys())
            vup = VarUpdater(mysin)  # just a stupid class updating a variable
            vup.start()

            # enable following if you want to subscribe to nodes on server side
            # handler = SubHandler()
            # sub = server.create_subscription(500, handler)
            # handle = sub.subscribe_data_change(myvar)
            # trigger event, all subscribed clients wil receive it
            var = myarrayvar.read_value()  # return a ref to value in db server side! not a copy!
            var = copy.copy(
                var
            )  # WARNING: we need to copy before writing again, otherwise no data change event will be generated
            var.append(9.3)
            myarrayvar.write_value(var)
            mydevice_var.write_value("Running")
            myevgen.trigger(message="This is BaseEvent")
            server.write_attribute_value(
                myvar.nodeid, ua.DataValue(9.9)
            )  # Server side write method which is a bit faster than using write

            embed()
            vup.stop()
