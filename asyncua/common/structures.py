"""
Support for custom structures in client and server
We only support a subset of features but should be enough
for custom structures
"""

import uuid
import logging

# The next two imports are for generated code
from datetime import datetime, timezone
from enum import IntEnum, EnumMeta
from dataclasses import dataclass, field
from typing import List, Optional


from xml.etree import ElementTree as ET
from asyncua import ua

from .structures104 import get_default_value, clean_name

_logger = logging.getLogger(__name__)


class EnumType:
    def __init__(self, name):
        self.name = clean_name(name)
        self.fields = []
        self.typeid = None

    def __str__(self):
        return f"EnumType({self.name, self.fields})"

    __repr__ = __str__

    def get_code(self):
        code = """

class {0}(IntEnum):

    '''
    {0} EnumInt autogenerated from xml
    '''

""".format(self.name)

        for EnumeratedValue in self.fields:
            name = clean_name(EnumeratedValue.Name)
            value = EnumeratedValue.Value
            code += f"    {name} = {value}\n"

        return code


class EnumeratedValue:
    def __init__(self, name, value):
        if name == "None":
            name = "None_"
        name = name.replace(" ", "")
        self.Name = name
        self.Value = value


class Struct:
    def __init__(self, name):
        self.name = clean_name(name)
        self.fields = []
        self.typeid = None
        self.option_counter = 0

    def __str__(self):
        return f"Struct(name={self.name}, fields={self.fields}"

    __repr__ = __str__

    def get_code(self):
        code = f"""

@dataclass
class {self.name}:

    '''
    {self.name} structure autogenerated from xml
    '''

"""
        if self.option_counter > 0:
            field = Field("Encoding")
            field.uatype = "UInt32"
            self.fields = [field] + self.fields
        for sfield in self.fields:
            if sfield.name != "SwitchField":
                """
                SwitchFields is the 'Encoding' Field in OptionSets to be
                compatible with 1.04 structs we added
                the 'Encoding' Field before and skip the SwitchField Field
                """
                uatype = f"'ua.{sfield.uatype}'"
                if sfield.array:
                    uatype = f"List[{uatype}]"
                if uatype == "List[ua.Char]":
                    uatype = "String"
                if sfield.is_optional:
                    code += f"    {sfield.name}: Optional[{uatype}] = None\n"
                else:
                    uavalue = sfield.value
                    if isinstance(uavalue, str) and uavalue.startswith("ua."):
                        uavalue = f"field(default_factory=lambda: {uavalue})"
                    code += f"    {sfield.name}:{uatype} = {uavalue}\n"
        return code


class Field:
    def __init__(self, name):
        self.name = name
        self.uatype = None
        self.value = None
        self.array = False
        self.is_optional = False

    def __str__(self):
        return f"Field(name={self.name}, uatype={self.uatype})"

    __repr__ = __str__


class StructGenerator:
    def __init__(self):
        self.model = []

    def make_model_from_string(self, xml):
        obj = ET.fromstring(xml)
        self._make_model(obj)

    def make_model_from_file(self, path):
        obj = ET.parse(path)
        root = obj.getroot()
        self._make_model(root)

    def _is_array_field(self, name):
        if name.startswith("NoOf"):
            return True
        if name.startswith("__") and name.endswith("Length"):
            # Codesys syntax
            return True
        if name.startswith("#"):
            # BR syntax
            return True
        return False

    def _make_model(self, root):
        enums = {}
        for child in root:
            if child.tag.endswith("EnumeratedType"):
                intenum = EnumType(child.get("Name"))
                for xmlfield in child:
                    if xmlfield.tag.endswith("EnumeratedValue"):
                        name = xmlfield.get("Name")
                        value = xmlfield.get("Value")
                        enumvalue = EnumeratedValue(name, value)
                        intenum.fields.append(enumvalue)
                        enums[child.get("Name")] = value
                self.model.append(intenum)

        for child in root:
            if child.tag.endswith("StructuredType"):
                struct = Struct(child.get("Name"))
                array = False
                # these lines can be reduced in >= Python3.8 with root.iterfind("{*}Field") and similar
                for xmlfield in child:
                    if xmlfield.tag.endswith("Field"):
                        name = xmlfield.get("Name")
                        _clean_name = clean_name(name)
                        if self._is_array_field(name):
                            array = True
                            continue
                        _type = xmlfield.get("TypeName")
                        if ":" in _type:
                            _type = _type.split(":")[1]
                        if _type == "Bit":
                            # Bits are used for bit fields and filler ignore
                            continue
                        field = Field(_clean_name)
                        field.uatype = clean_name(_type)
                        if xmlfield.get("SwitchField", "") != "":
                            # Optional Field
                            field.is_optional = True
                            struct.option_counter += 1
                        field.value = get_default_value(field.uatype, enums, hack=True)
                        if array:
                            field.array = True
                            field.value = "field(default_factory=list)"
                            array = False
                        struct.fields.append(field)
                self.model.append(struct)

    def save_to_file(self, path, register=False):
        _file = open(path, "w+")
        self._make_header(_file)
        for struct in self.model:
            _file.write(struct.get_code())
        if register:
            _file.write(self._make_registration())
        _file.close()

    def _make_registration(self):
        code = "\n\n"
        for struct in self.model:
            if isinstance(struct, EnumType):
                continue  # No registration required for enums
            code += (
                f"ua.register_extension_object('{struct.name}',"
                f" ua.NodeId.from_string('{struct.typeid}'), {struct.name})\n"
            )
        return code

    def get_python_classes(self, env=None):
        return _generate_python_class(self.model, env=env)

    def _make_header(self, _file):
        _file.write("""
'''
THIS FILE IS AUTOGENERATED, DO NOT EDIT!!!
'''

from datetime import datetime, timezone
import uuid
from dataclasses import dataclass, field
from typing import List, Union, Optional
from enum import IntEnum

from asyncua import ua
""")

    def set_typeid(self, name, typeid):
        for struct in self.model:
            if struct.name == name:
                struct.typeid = typeid
                return


async def load_type_definitions(server, nodes=None):
    """
    Download xml from given variable node defining custom structures.
    If no node is given, attempts to import variables from all nodes under
    "0:OPC Binary"
    the code is generated and imported on the fly. If you know the structures
    are not going to be modified it might be interesting to copy the generated files
    and include them in you code
    """
    if nodes is None:
        nodes = []
        for desc in await server.nodes.opc_binary.get_children_descriptions():
            if desc.BrowseName != ua.QualifiedName("Opc.Ua"):
                nodes.append(server.get_node(desc.NodeId))

    structs_dict = {}
    generators = []
    for node in nodes:
        xml = await node.read_value()
        generator = StructGenerator()
        generators.append(generator)
        generator.make_model_from_string(xml)
        # generate and execute new code on the fly
        generator.get_python_classes(structs_dict)
        # same but using a file that is imported. This can be useful for debugging library
        # name = node.read_browse_name().Name
        # Make sure structure names do not contain characters that cannot be used in Python class file names
        # name = clean_name(name)
        # name = "structures_" + node.read_browse_name().Name
        # generator.save_and_import(name + ".py", append_to=structs_dict)

        # register classes
        # every children of our node should represent a class
        for ndesc in await node.get_children_descriptions():
            ndesc_node = server.get_node(ndesc.NodeId)
            ref_desc_list = await ndesc_node.get_references(
                refs=ua.ObjectIds.HasDescription, direction=ua.BrowseDirection.Inverse
            )
            if ref_desc_list:  # some server put extra things here
                name = clean_name(ndesc.BrowseName.Name)
                if name not in structs_dict:
                    _logger.warning("%s is found as child of binary definition node but is not found in xml", name)
                    continue
                nodeid = ref_desc_list[0].NodeId
                ua.register_extension_object(name, nodeid, structs_dict[name])
                # save the typeid if user want to create static file for type definition
                generator.set_typeid(name, nodeid.to_string())

        for key, val in structs_dict.items():
            if isinstance(val, EnumMeta) and key != "IntEnum":
                setattr(ua, key, val)

    return generators, structs_dict


def _generate_python_class(model, env=None):
    """
    generate Python code and execute in a new environment
    return a dict of structures {name: class}
    Rmw: Since the code is generated on the fly, in case of error the stack trace is
    not available and debugging is very hard...
    """
    if env is None:
        env = ua.__dict__
    #  Add the required libraries to dict
    if "ua" not in env:
        env["ua"] = ua
    if "datetime" not in env:
        env["datetime"] = datetime
        env["timezone"] = timezone
    if "uuid" not in env:
        env["uuid"] = uuid
    if "enum" not in env:
        env["IntEnum"] = IntEnum
    if "dataclass" not in env:
        env["dataclass"] = dataclass
    if "field" not in env:
        env["field"] = field
    if "List" not in env:
        env["List"] = List
    if "Optional" not in env:
        env["Optional"] = Optional
    # generate classes one by one and add them to dict
    for element in model:
        code = element.get_code()
        try:
            exec(code, env)
        except Exception:
            _logger.exception("Failed to execute auto-generated code from UA datatype: %s", code)
            raise
    return env


async def load_enums(server, env=None, force=False):
    """
    Read enumeration data types on server and generate python Enums in ua scope for them
    """
    model = []

    for desc in await server.nodes.enum_data_type.get_children_descriptions(refs=ua.ObjectIds.HasSubtype):
        enum_name = desc.BrowseName.Name
        enum_node = server.get_node(desc.NodeId)
        if not force and hasattr(ua, enum_name):
            _logger.debug("Enum type %s is already in ua namespace, ignoring", enum_name)
            continue
        c = None
        for child_desc in await enum_node.get_children_descriptions(refs=ua.ObjectIds.HasProperty):
            child_node = server.get_node(child_desc.NodeId)
            if child_desc.BrowseName.Name == "EnumStrings":
                c = await _get_enum_strings(enum_name, child_node)
            elif child_desc.BrowseName.Name == "EnumValues":
                c = await _get_enum_values(enum_name, server.get_node(child_desc.NodeId))
            else:
                _logger.warning("Unexpected children of node %s: %s", desc, child_desc)
        if c is not None:
            model.append(c)
    return _generate_python_class(model, env=env)


async def _get_enum_values(name, node):
    val = await node.read_value()
    c = EnumType(name)
    c.fields = [EnumeratedValue(enumval.DisplayName.Text, enumval.Value) for enumval in val]
    return c


async def _get_enum_strings(name, node):
    val = await node.read_value()
    c = EnumType(name)
    c.fields = [EnumeratedValue(st.Text, idx) for idx, st in enumerate(val)]
    return c
