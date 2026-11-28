# SPDX-FileCopyrightText: 2011-2024 Blender Foundation
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
from http.cookiejar import debug

logger = logging.getLogger("import_x3d")

DEBUG = False

# This should work without a blender at all
import os
import shlex
import math
import re
import mathutils

from . import budget
from . import default_uv
from math import sin, cos, pi, sqrt, ceil
from itertools import chain
from . import geospatial, matrix_safety, mfstring
from .extract import (BACKGROUND_PROPERTY, FOG_PROPERTY, TWO_SIDED_PROPERTY, COLOUR_SPACE_PROPERTY, HEAD_META_PROPERTY, LIGHT_AMBIENT_INTENSITY_PROPERTY,
                      HEADLIGHT_PROPERTY, MATERIAL_MODEL_PROPERTY, LIGHT_GLOBAL_PROPERTY, LIGHT_SCOPE_LIT_PROPERTY, LINE_WIDTH_PROPERTY, POINT_PROPERTIES_PROPERTY, COORDINATE_DOUBLE_PROPERTY, SOLID_PROPERTY, LIGHT_ATTENUATION_PROPERTY, LIGHT_COLOR_PROPERTY, LIGHT_ENERGY_PER_INTENSITY_PROPERTY,
                      IMPORTED_ANIMATION_PROPERTY, LOD_HIDDEN_PROPERTY, SWITCH_HIDDEN_PROPERTY, VISIBLE_FALSE_PROPERTY,
                      LIGHT_INTENSITY_PROPERTY,
                      LIGHT_RADIUS_PROPERTY, LIGHT_REFERENCE_DISTANCE_PROPERTY, LIGHT_SHADOW_INTENSITY_PROPERTY,
                      METADATA_NODE_TYPES, METADATA_PROPERTY, SCENE_METADATA_PROPERTY, TRANSFORM_METADATA_PROPERTY,
                      VIEWPOINT_DESCRIPTION_PROPERTY, record_inline_source, scene_head_meta,
                      HEADLIGHT_LUX_PROPERTY, IMPORTED_OBJECT_PROPERTY, LIGHTING_MODEL_PROPERTY, clear_stale_scene_properties)
from .viewpoint_fov import blender_camera_angle, render_size

texture_cache = {}
material_cache = {}
image_alpha_cache = {}
font_variants_cache = {}
download_cache = {}
current_file_path = None
conversion_scale = 1.0

EPSILON = 0.0000001  # Very crude.


def vrml_find_quote(text,j=0):
    """Finds the next unescaped quote (") in a VRML-encoded string.

    This function accounts for VRML escaping rules, which allow quotes (") and
    backslashes (\\) to be included in SFString values.

    Args:
        text (str): The input string to search.
        j (int, optional): The starting index. Defaults to 0.

    Returns:
        int: The index of the next unescaped quote, or -1 if none is found.

    Notes:
        - If `text[j] == '"'`, the function returns `j` (handling empty VRML strings).
        - If an escaped quote (`\"`) or backslash (`\\`) is encountered, it is skipped.
        - For strict VRML syntax enforcement, an exception could be raised
          if an isolated backslash (`\`) is found.

    See:
    https://www.web3d.org/documents/specifications/19776-2/V3.3/Part02/EncodingOfFields.html#SFString
    """
    while j < len(text):
        if text[j] == '"':
            return j
        if text[j:j + 2] in {'\\"', '\\\\'}:
            j += 2  # Skip escaped characters
        else:
            j += 1  # Move to the next character

    return -1


def vrml_count_quote(text):
    """
    A replacement for text.count('"')

    But returns the number of un-escaped quotes taking
    into account vrml string escaping rules

    Importantly, this function does not take into account the case
    where the beginning of the text value is within a VRML string

    In the import vrml code an odd return value is taken to mean a VRML string
    is not terminated in a line
    """
    returnCount = 0
    j = 0
    LOOP_GUARD = 64
    while j < len(text):
        LOOP_GUARD -= 1
        if LOOP_GUARD < 0:
            raise Exception("infinite loop error in vrml_count_quote")

        nj = text.find('"',j)
        if nj == -1:
            break
        returnCount += 1

        nnj = vrml_find_quote(text,nj+1)
        if nnj == -1:
            break
        returnCount += 1

        j = nnj+1
    return returnCount


# The regex pattern for splitting items in a line
# is either a single comma and optional whitespace, or at least one whitespace
# followed by optional comma and whitespace
vrml_split_pattern = re.compile(r"(?:,\s*)|(?:\s+,?\s*)")
def vrml_split(text):
    """Splits a VRML-encoded string into a list of words or SFString values.

        Args:
            text (str): The input string.

        Returns:
            list: A list of strings where:
                - Items enclosed in quotes are treated as SFString values (quotes included).
                - Other items are split by whitespace.
            or a string with no embedded whitespace

        Notes:
            - Ensures proper handling of quoted SFString values.
            - Detects and prevents infinite loops by checking text length changes.
            - Logs an error if an unterminated quoted string is encountered.
        """
    original_text = text
    result = []
    prev_length = None

    while text:
        if prev_length is not None and len(text) >= prev_length:
            raise Exception("Infinite loop detected in vrml_split")
        prev_length = len(text)

        text = text[vrml_split_pattern.match(text).end():] if vrml_split_pattern.match(text) else text
        if not text:
            break

        if text.startswith('"'):
            end_idx = vrml_find_quote(text, 1)
            if end_idx == -1:
                logger.error("Unterminated SFString value: |%s|", text)
                break
            result.append(text[:end_idx + 1])
            text = text[end_idx + 1:]
        else:
            match = vrml_split_pattern.search(text)
            result.append(text[:match.start()] if match else text)
            text = text[match.end():] if match else ''

    logger.debug("vrml_split |%s| --> %s", original_text, result)
    return result


# A 1 x 1 GIF, for asking the running Blender whether it reads GIF itself
_GIF_PROBE = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
_blender_reads_gif_cache = []
GIF_CONVERT_ENV = "BLENDER_X3D_CONVERT_GIF"


def blender_reads_gif():
    """Whether this Blender loads GIF images itself (5.1 does, through OpenImageIO). Probed once per session."""
    if not _blender_reads_gif_cache:
        import tempfile
        ok = False
        fd, probe = tempfile.mkstemp(prefix="x3d-gif-probe-", suffix=".gif")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(_GIF_PROBE)
            image = bpy.data.images.load(probe, check_existing=False)
            try:
                size = tuple(image.size)          # reading the size loads the pixels; has_data is False before
                ok = bool(size == (1, 1) and image.has_data)
            finally:
                bpy.data.images.remove(image)
        except (RuntimeError, OSError):
            ok = False
        finally:
            try:
                os.unlink(probe)
            except OSError:
                pass
        _blender_reads_gif_cache.append(ok)
    return _blender_reads_gif_cache[0]


def imageConvertCompat(path):
    """Image path for Blender to load. A GIF is converted to PNG only when this Blender cannot read GIF itself and the
    user opted in (BLENDER_X3D_CONVERT_GIF=1): the converter is an external program (ImageMagick) parsing an image
    from an untrusted scene, the classic ImageTragick route, so it never runs by default. Filenames never reach a
    shell (import_resources.convert_gif)."""
    if os.sep == '\\' or not path.lower().endswith('.gif') or blender_reads_gif():
        return path
    if os.environ.get(GIF_CONVERT_ENV, "").strip().lower() not in {"1", "true", "yes", "on"}:
        logger.warning("GIF texture %r not loaded: this Blender cannot read GIF, and converting it needs ImageMagick; "
                       "set %s=1 to allow that conversion", os.path.basename(path), GIF_CONVERT_ENV)
        return path
    from .import_resources import convert_gif
    import subprocess
    try:
        return convert_gif(path)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Failed to convert GIF image: %s", exc)
    return path

# notes
# transform are relative
# order doesn't matter for loc/size/rot
# right handed rotation
# angles are in radians
# rotation first defines axis then amount in radians


# =============================== VRML Specific

def vrml_split_fields(value):
    """
    key 0.0 otherkey 1,2,3 opt1 opt1 0.0
        -> [key 0.0], [otherkey 1,2,3], [opt1 opt1 0.0]
    """
    def iskey(k):
        if k[0] != '"' and k[0].isalpha() and k.upper() not in {'TRUE', 'FALSE'}:
            return True
        return False

    field_list = []
    field_context = []

    for v in value:
        if iskey(v):
            if field_context:
                field_context_len = len(field_context)
                if (field_context_len > 2) and (field_context[-2] in {'DEF', 'USE'}):
                    field_context.append(v)
                elif (not iskey(field_context[-1])) or ((field_context_len == 3 and field_context[1] == 'IS')):
                    # this IS a key but the previous value was not a key, or it was a defined field.
                    field_list.append(field_context)
                    field_context = [v]
                else:
                    # The last item was not a value, multiple keys are needed in some cases.
                    field_context.append(v)
            else:
                # Is empty, just add this on
                field_context.append(v)
        else:
            # Add a value to the list
            field_context.append(v)

    if field_context:
        field_list.append(field_context)

    return field_list


def vrmlFormat(data):
    """
    Keep this as a valid vrml file, but format in a way we can predict.
    """
    # Strip all comments - # not in strings - warning multiline strings are ignored.
    def strip_comment(l):
        l = l.strip()

        if l.startswith('#'):
            return ''

        i = l.find('#')

        if i == -1:
            return l

        # Most cases accounted for! if we have a comment at the end of the line do this...
        # j = l.find('url "')
        j = l.find('"')

        if j == -1:  # simple no strings
            return l[:i].strip()

        q = False
        for i, c in enumerate(l):
            if c == '"':
                q = not q  # invert

            elif c == '#':
                if q is False:
                    return l[:i - 1]

        return l

    data = '\n'.join([strip_comment(l) for l in data.split('\n')])  # remove all whitespace
    EXTRACT_STRINGS = True  # only needed when strings or filename contains ,[]{} chars :/

    if EXTRACT_STRINGS:

        # removed in PR #81
        # We need this so we can detect URL's
        # data = '\n'.join([' '.join(l.split()) for l in data.split('\n')])  # remove all whitespace

        string_ls = []

        # search = 'url "'
        search = '"'

        ok = True
        last_i = 0

        while ok:
            ok = False
            i = data.find('"', last_i)
            if i != -1:

                start = i + len(search)  # first char after end of search
                end = vrml_find_quote(data,start)
                if end != -1:
                    item = data[start:end]
                    string_ls.append(item)
                    data = data[:start] + data[end:]
                    ok = True  # keep looking

                    last_i = (end - len(item)) + 1

    # done with messy extracting strings part

    data = data.replace('{', '\n{\n')
    data = data.replace('}', '\n}\n')
    data = data.replace('[', '\n[\n')
    data = data.replace(']', '\n]\n')

    # We need to write one property (field) per line only, otherwise we fail later to detect correctly new nodes.
    # See T45195 for details.

    data = '\n'.join([' '.join(value) for l in data.split('\n') for value in vrml_split_fields(vrml_split(l))])
    if EXTRACT_STRINGS:
        # add strings back in

        search = '"'  # fill in these empty strings

        ok = True
        last_i = 0
        while ok:
            ok = False
            i = data.find(search + '"', last_i)
            if i != -1:
                start = i + len(search)  # first char after end of search
                item = string_ls.pop(0)

                data = data[:start] + item + data[start:]

                last_i = start + len(item) + 1

                ok = True
    # strip out empty lines
    def non_empty_line_generator(indata):
        for ll in indata.split("\n"):
            sll = ll.strip()
            if sll:
                yield sll

    returned_lines = list( non_empty_line_generator(data) )

    logger.debug("tokenized lines: \n%s" % "\n".join(returned_lines))
    return returned_lines


NODE_NORMAL = 1  # {}
NODE_ARRAY = 2  # []
NODE_REFERENCE = 3  # USE foobar
# Rigid-body physics nodes are placed once, where they are defined; a USE of one is a reference (a joint's body1 and body2,
# a CollisionCollection's collidables, a RigidBodyCollection's bodies), so the importer does not walk into it again.
PHYSICS_REFERENCE_SPECS = frozenset({'RigidBody', 'CollidableShape', 'CollidableOffset'})
# Nodes that move what is under them like a Transform does, with the same fields, except RigidBody (position, orientation).
PHYSICS_FRAME_SPECS = frozenset({'RigidBody', 'CollidableShape', 'CollidableOffset'})
# Nodes with a Transform's own fields (translation, rotation, scale, center, scaleOrientation) that place their children:
# CADPart is one (node board batch 12; before, its pose was ignored and every part of an assembly sat at the origin).
TRANSFORM_SPECS = frozenset({'Transform', 'CADPart'})
# The CAD product structure (node board batch 12): each of these gets an object of its own in the hierarchy, recorded
# with X3D_CAD_PROPERTY so the X3D 4.0 export writes the node back. CADFace is a mark on the object of its content.
CAD_FRAME_SPECS = frozenset({'CADLayer', 'CADAssembly', 'CADPart'})
CAD_RAW_FIELDS = ('name', 'visible', 'bboxCenter', 'bboxSize', 'bboxDisplay')
X3D_CAD_PROPERTY = "x3d_cad"            # JSON {"node", "def", "fields"[, "face": {"def", "fields"}]}
# NODE_PROTO = 4 #

lines = []


def getNodePreText(i, words):

    use_node = False
    while len(words) < 5:
        if i >= len(lines):
            break
        elif lines[i] == '{':
            return NODE_NORMAL, i + 1
        elif vrml_count_quote(lines[i]) % 2 != 0:  # odd number of quotes? - part of a string.
            break
        else:
            new_words = vrml_split(lines[i])
            if 'USE' in new_words:
                use_node = True

            words.extend(new_words)
            i += 1

        # Check for USE node - no {
        # USE #id - should always be on the same line.
        if use_node:
            words[:] = words[:words.index('USE') + 2]
            if lines[i] == '{' and lines[i + 1] == '}':
                # USE sometimes has {} after it anyway
                i += 2
            return NODE_REFERENCE, i
    return 0, -1


def is_nodeline(i, words):

    if not lines[i][0].isalpha():
        return 0, 0

    # if lines[i].startswith('field'):
    #   return 0, 0

    # Is this a prototype??
    if lines[i].startswith('PROTO'):
        words[:] = vrml_split(lines[i])
        return NODE_NORMAL, i + 1  # TODO - assumes the next line is a '[\n', skip that
    if lines[i].startswith('EXTERNPROTO'):
        words[:] = vrml_split(lines[i])
        return NODE_ARRAY, i + 1  # TODO - assumes the next line is a '[\n', skip that


    # Simple "var [" type
    if lines[i + 1] == '[':
        if vrml_count_quote(lines[i]) % 2 == 0:
            words[:] = vrml_split(lines[i])
            return NODE_ARRAY, i + 2

    node_type, new_i = getNodePreText(i, words)

    if not node_type:
        logger.debug("not node_type", lines[i])
        return 0, 0

    # Ok, we have a { after some values
    # Check the values are not fields
    for i, val in enumerate(words):
        if i != 0 and words[i - 1] in {'DEF', 'USE'}:
            # ignore anything after DEF, it is a ID and can contain any chars.
            pass
        elif val[0].isalpha() and val not in {'TRUE', 'FALSE'}:
            pass
        else:
            # There is a number in one of the values, therefor we are not a node.
            return 0, 0
    return node_type, new_i


is_numline_init_skip_pattern = re.compile(r"\s*,?\s*")
is_numline_first_break_pattern = re.compile(r"\s|,|$")

def is_numline(i):
    """
    Algorithm :
    skip initial white space, at most one comma, any white space following

    then look forward for a comma or white space
    try to parse whats inside as a float
    """
    l = lines[i]

    init_skip = is_numline_init_skip_pattern.match(l)
    if init_skip:
        first_break = is_numline_first_break_pattern.search(l, init_skip.end())
        if first_break:
            try:
                float(l[init_skip.end():first_break.start()])
                return True
            except:
                pass
    return False


class vrmlNode(object):
    __slots__ = ('id',
                 'fields',
                 'proto_node',
                 'proto_field_defs',
                 'proto_fields',
                 'node_type',
                 'parent',
                 'children',
                 'parent',
                 'array_data',
                 'reference',
                 'lineno',
                 'filename',
                 'blendObject',
                 'blendData',
                 'DEF_NAMESPACE',
                 'ROUTE_IPO_NAMESPACE',
                 'PROTO_NAMESPACE',
                 'x3dNode',
                 'parsed',
                 'parsed_vcol',
                 'shared_mesh',
                 'hierarchy_owners')

    def __init__(self, parent, node_type, lineno):
        self.id = None
        self.node_type = node_type
        self.parent = parent
        self.blendObject = None
        self.blendData = None
        self.x3dNode = None  # for x3d import only
        self.parsed = None  # We try to reuse objects in a smart way
        self.parsed_vcol = None  # for a classic material in parsed: whether it was built for a Shape with a Color node
        self.shared_mesh = None  # for a geometry node: (mesh, material) its first Shape built, for its USEs to share
        self.hierarchy_owners = []  # (object, occurrence ancestry) for every DEF/USE of a Transform
        if parent:
            parent.children.append(self)

        self.lineno = lineno

        # This is only set from the root nodes.
        # Having a filename also denotes a root node
        self.filename = None
        self.proto_node = None  # proto field definition eg: "field SFColor seatColor .6 .6 .1"

        # Store in the root node because each inline file needs its own root node and its own namespace
        self.DEF_NAMESPACE = None
        self.ROUTE_IPO_NAMESPACE = None

        self.PROTO_NAMESPACE = None

        self.reference = None

        if node_type == NODE_REFERENCE:
            # For references, only the parent and ID are needed
            # the reference its self is assigned on parsing
            return

        self.fields = []  # fields have no order, in some cases rool level values are not unique so dont use a dict

        self.proto_field_defs = []  # proto field definition eg: "field SFColor seatColor .6 .6 .1"
        self.proto_fields = []  # proto field usage "diffuseColor IS seatColor"
        self.children = []
        self.array_data = []  # use for arrays of data - should only be for NODE_ARRAY types


    def getProtoDict(self):
        node = self           # a loop, not recursion: 5,000 nested VRML Groups hit RecursionError (2.7.3)
        while node.PROTO_NAMESPACE is None:
            node = node.parent
        return node.PROTO_NAMESPACE

    def getDefDict(self):
        node = self           # a loop, not recursion: 5,000 nested VRML Groups hit RecursionError (2.7.3)
        while node.DEF_NAMESPACE is None:
            node = node.parent
        return node.DEF_NAMESPACE

    def getRouteIpoDict(self):
        node = self           # a loop, not recursion: 5,000 nested VRML Groups hit RecursionError (2.7.3)
        while node.ROUTE_IPO_NAMESPACE is None:
            node = node.parent
        return node.ROUTE_IPO_NAMESPACE

    def setRoot(self, filename):
        self.filename = filename
        # self.FIELD_NAMESPACE =        {}
        self.DEF_NAMESPACE = {}
        self.ROUTE_IPO_NAMESPACE = {}
        self.PROTO_NAMESPACE = {}

    def isRoot(self):
        if self.filename is None:
            return False
        else:
            return True

    def getFilename(self):
        if self.filename:
            return self.filename
        elif self.parent:
            return self.parent.getFilename()
        else:
            return None

    def getRealNode(self):
        if self.reference:
            return self.reference
        else:
            return self

    def getSpec(self):
        self_real = self.getRealNode()
        try:
            return self_real.id[-1]  # its possible this node has no spec
        except:
            return None

    def findSpecRecursive(self, spec):
        self_real = self.getRealNode()
        if spec == self_real.getSpec():
            return self

        for child in self_real.children:
            if child.findSpecRecursive(spec):
                return child

        return None

    def getPrefix(self):
        if self.id:
            return self.id[0]
        return None

    def getSpecialTypeName(self, typename):
        self_real = self.getRealNode()
        try:
            return self_real.id[list(self_real.id).index(typename) + 1]
        except:
            return None

    def getDefName(self):
        return self.getSpecialTypeName('DEF')

    def getProtoName(self):
        return self.getSpecialTypeName('PROTO')

    def getExternprotoName(self):
        return self.getSpecialTypeName('EXTERNPROTO')

    def getChildrenBySpec(self, node_spec):  # spec could be Transform, Shape, Appearance
        self_real = self.getRealNode()
        # using getSpec functions allows us to use the spec of USE children that dont have their spec in their ID
        if type(node_spec) == str:
            return [child for child in self_real.children if child.getSpec() == node_spec]
        else:
            # Check inside a list of optional types
            return [child for child in self_real.children if child.getSpec() in node_spec]

    def getChildrenBySpecCondition(self, cond):  # spec could be Transform, Shape, Appearance
        self_real = self.getRealNode()
        # using getSpec functions allows us to use the spec of USE children that dont have their spec in their ID
        return [child for child in self_real.children if cond(child.getSpec())]

    def getChildBySpec(self, node_spec):  # spec could be Transform, Shape, Appearance
        # Use in cases where there is only ever 1 child of this type
        ls = self.getChildrenBySpec(node_spec)
        if ls:
            return ls[0]
        else:
            return None

    def getChildBySpecCondition(self, cond):  # spec could be Transform, Shape, Appearance
        # Use in cases where there is only ever 1 child of this type
        ls = self.getChildrenBySpecCondition(cond)
        if ls:
            return ls[0]
        else:
            return None

    def getChildrenByName(self, node_name):  # type could be geometry, children, appearance
        self_real = self.getRealNode()
        return [child for child in self_real.children if child.id if child.id[0] == node_name]

    def getChildByName(self, node_name):
        self_real = self.getRealNode()
        for child in self_real.children:
            if child.id and child.id[0] == node_name:  # and child.id[-1]==node_spec:
                return child

    def getSerialized(self, results, ancestry):
        """ Return this node and all its children in a flat list """
        ancestry = ancestry[:]  # always use a copy

        # self_real = self.getRealNode()

        results.append((self, tuple(ancestry)))
        ancestry.append(self)
        for child in self.getRealNode().children:
            if child.node_type == NODE_REFERENCE and child.getSpec() in PHYSICS_REFERENCE_SPECS:
                # A joint, a collision collection or a body list names a body or a collidable it already has: it is not
                # a second copy of its geometry (a USE'd Transform is an instance; a USE'd RigidBody never is)
                continue
            if child not in ancestry:
                # We dont want to load proto's, they are only references
                # We could enforce this elsewhere

                # Only add this in a very special case
                # where the parent of this object is not the real parent
                # - In this case we have added the proto as a child to a node instancing it.
                # This is a bit arbitrary, but its how Proto's are done with this importer.
                if child.getProtoName() is None and child.getExternprotoName() is None:
                    child.getSerialized(results, ancestry)
                else:
                    logger.debug('getSerialized() is proto:', child.getProtoName(), child.getExternprotoName(), self.getSpec())
                    self_spec = self.getSpec()

                    if child.getProtoName() == self_spec or child.getExternprotoName() == self_spec:
                        logger.debug("FoundProto!")
                        child.getSerialized(results, ancestry)

        return results

    def searchNodeTypeID(self, node_spec, results):
        self_real = self.getRealNode()
        if self_real.id and self_real.id[-1] == node_spec:  # use last element, could also be only element
            results.append(self_real)
        for child in self_real.children:
            child.searchNodeTypeID(node_spec, results)
        return results

    def getFieldName(self, field, ancestry, AS_CHILD=False, SPLIT_COMMAS=False):
        self_real = self.getRealNode()  # in case we're an instance

        for f in self_real.fields:
            if f and f[0] == field:
                if len(f) >= 3 and f[1] == 'IS':  # eg: 'diffuseColor IS legColor'
                    field_id = f[2]
                    f_proto_lookup = None
                    f_proto_child_lookup = None
                    i = len(ancestry)
                    while i:
                        i -= 1
                        node = ancestry[i]
                        node = node.getRealNode()

                        # proto settings are stored in "self.proto_node"
                        if node.proto_node:
                            # Get the default value from the proto, this can be overwritten by the proto instance
                            # 'field SFColor legColor .8 .4 .7'
                            if AS_CHILD:
                                for child in node.proto_node.children:
                                    # if child.id  and  len(child.id) >= 3  and child.id[2]==field_id:
                                    if child.id and ('point' in child.id or 'points' in child.id):
                                        f_proto_child_lookup = child

                            else:
                                for f_def in node.proto_node.proto_field_defs:
                                    if len(f_def) >= 4:
                                        if f_def[0] == 'field' and f_def[2] == field_id:
                                            f_proto_lookup = f_def[3:]

                        # Node instance, Will be 1 up from the proto-node in the ancestry list. but NOT its parent.
                        # This is the setting as defined by the instance, including this setting is optional,
                        # and will override the default PROTO value
                        # eg: 'legColor 1 0 0'
                        if AS_CHILD:
                            for child in node.children:
                                if child.id and child.id[0] == field_id:
                                    f_proto_child_lookup = child
                        else:
                            for f_def in node.fields:
                                if len(f_def) >= 2:
                                    if f_def[0] == field_id:
                                        logger.debug("getFieldName(), found proto", f_def)
                                        f_proto_lookup = f_def[1:]

                    if AS_CHILD:
                        if f_proto_child_lookup:
                            logger.debug("getFieldName() - AS_CHILD=True, child found")
                            logger.debug(f_proto_child_lookup)
                            return f_proto_child_lookup
                    else:
                        return f_proto_lookup
                else:
                    if AS_CHILD:
                        return None
                    else:
                        # Not using a proto
                        return f[1:]

        # See if this is a proto name
        if AS_CHILD:
            for child in self_real.children:
                if child.id and len(child.id) == 1 and child.id[0] == field:
                    return child

        return None

    def getFieldAsInt(self, field, default, ancestry):
        self_real = self.getRealNode()  # in case we're an instance

        f = self_real.getFieldName(field, ancestry)
        if f is None:
            return default
        if ',' in f:
            f = f[:f.index(',')]  # strip after the comma

        if len(f) != 1:
            logger.warning('"%s" wrong length for int conversion for field "%s"' % (f, field))
            return default

        try:
            return int(f[0])
        except:
            logger.warning('value "%s" could not be used as an int for field "%s"' % (f[0], field))
            return default

    def getFieldAsFloat(self, field, default, ancestry, scale_factor=1.0):
        self_real = self.getRealNode()  # in case we're an instance

        f = self_real.getFieldName(field, ancestry)
        if f is None:
            return default
        if ',' in f:
            f = f[:f.index(',')]  # strip after the comma

        if len(f) != 1:
            logger.warning('"%s" wrong length for float conversion for field "%s"' % (f, field))
            return default

        try:
            value = float(f[0]) * scale_factor
        except:
            logger.warning('value "%s" could not be used as a float for field "%s"' % (f[0], field))
            return default
        if not math.isfinite(value):
            # the parse-time sanitiser (2.7.3): NaN and INF stop here, not in each node's own maths
            logger.warning('value "%s" of field "%s" is not finite; using the default %r' % (f[0], field, default))
            return default
        return value

    def getFieldAsFloatTuple(self, field, default, ancestry, scale_factor=1.0):
        self_real = self.getRealNode()  # in case we're an instance

        f = self_real.getFieldName(field, ancestry)
        if f is None:
            return default
        # if ',' in f: f = f[:f.index(',')] # strip after the comma

        if len(f) < 1:
            logger.warning('"%s" wrong length for float tuple conversion for field "%s"' % (f, field))
            return default

        ret = []
        for v in f:
            if v != ',':
                try:
                    ret.append(float(v.strip('"')) * scale_factor)
                except:
                    break  # quit of first non float, perhaps its a new field name on the same line? - if so we are going to ignore it :/ TODO

        if ret and not all(math.isfinite(v) for v in ret):
            logger.warning('value "%s" of field "%s" is not finite; using the default' % (f, field))
            return default
        if ret:
            # check integrity of the result compared to default expected value. If corrupted, discard to ensure further working
            if default:
                if len(ret) == len(default):
                    return ret
            else:
                return ret
            # a tuple of the wrong length (a two-value position, say) used to fall off the end and return None,
            # which the callers that pass a default then unpacked or indexed: the import aborted
            logger.warning('value "%s" has %d numbers, not the %d of field "%s"; using the default' % (f, len(ret), len(default), field))
            return default
        logger.warning('value "%s" could not be used as a float tuple for field "%s"' % (f, field))
        return default

    def getFieldAsBool(self, field, default, ancestry):
        self_real = self.getRealNode()  # in case we're an instance

        f = self_real.getFieldName(field, ancestry)
        if f is None:
            return default
        if ',' in f:
            f = f[:f.index(',')]  # strip after the comma

        if len(f) != 1:
            logger.warning('"%s" wrong length for bool conversion for field "%s"' % (f, field))
            return default

        if f[0].upper() == '"TRUE"' or f[0].upper() == 'TRUE':
            return True
        elif f[0].upper() == '"FALSE"' or f[0].upper() == 'FALSE':
            return False
        else:
            # f has one entry here, so f[1] raised IndexError and a bool spelt "1", "yes" or "TRUE," ended the whole
            # import (chaos round, 22 Nov 2026; Blender's own importer has the same line)
            logger.warning('"%s" could not be used as a bool for field "%s"' % (f[0], field))
            return default

    def getFieldAsString(self, field, default, ancestry):
        self_real = self.getRealNode()  # in case we're an instance

        f = self_real.getFieldName(field, ancestry)
        logger.debug("getFieldAsString self_real.getFieldName field %s value %r |%s|" % (field, type(f), f))
        if f is None:
            return default

        if not (type(f) == type([]) and len(f) == 1 and len(f[0]) > 1 and f[0][0] == '"' and f[0][-1] == '"'):
            logger.error('getFieldAsString : value |%s| could not be used  to get string for field %s' % (f, field))
            return default

        try:
            slash_encoded = f[0][1:-1]
            return mfstring.slash_decode( slash_encoded )
        except mfstring.SlashEncodingError:
            logger.error("SlashEncodingError for value |%s|" % slash_encoded)
            return default


    def getFieldAsArray(self, field, group, ancestry, scale_factor=1.0):
        """
        For this parser arrays are children
        """

        def array_as_number(array_string):
            array_data = []
            try:
                # base 10 first: int('010', 0) raises (an octal-looking zero pad), which made a whole coordIndex
                # floats; base 0 still reads PixelTexture's 0xRRGGBB
                array_data = [int(val) if val[-1:].isdigit() and 'x' not in val.lower() else int(val, 0)
                              for val in array_string]
            except:
                try:
                    array_data = [float(val) for val in array_string]
                except:
                    logger.warning('Could not parse array data from field')
                    return array_data
                # the parse-time sanitiser (2.7.3): a NaN or INF in a point list or a key list is read as 0 here,
                # once for every node, instead of a guard in each node that reads numbers
                bad = sum(1 for v in array_data if not math.isfinite(v))
                if bad:
                    logger.warning('field "%s" has %d values that are not finite; read as 0' % (field, bad))
                    array_data = [v if math.isfinite(v) else 0.0 for v in array_data]
            return array_data

        self_real = self.getRealNode()  # in case we're an instance

        child_array = self_real.getFieldName(field, ancestry, True, SPLIT_COMMAS=True)

        # if type(child_array)==list: # happens occasionally
        #   array_data = child_array

        if child_array is None:
            # For x3d, should work ok with vrml too
            # for x3d arrays are fields, vrml they are nodes, annoying but not too bad.
            data_split = self.getFieldName(field, ancestry, SPLIT_COMMAS=True)
            if not data_split:
                return []

            array_data = array_as_number(data_split)

        elif type(child_array) == list:
            # x3d creates these
            array_data = array_as_number(child_array)
        else:
            # Normal vrml
            array_data = getattr(child_array, "array_data", None)
            if array_data is None:  # a node where numbers belong: malformed, read as empty
                logger.warning("field %r holds %s, not numbers; read as empty", field, type(child_array).__name__)
                return []

        if group == -1 or len(array_data) == 0:
            return array_data

        # We want a flat list
        flat = True
        for item in array_data:
            if type(item) == list:
                flat = False
                break

        apply_scale = scale_factor != 1.0

        # make a flat array
        if flat:
            if apply_scale:
                # applying scale
                flat_array = [n * scale_factor for n in array_data]  # scaling the data
            else:
                flat_array = array_data  # we are already flat.

        else:
            flat_array = []

            def extend_flat(ls):
                for item in ls:
                    if type(item) == list:
                        extend_flat(item)
                    else:
                        if apply_scale:
                            # applying scale
                            item *= scale_factor

                        flat_array.append(item)

            extend_flat(array_data)

        # We requested a flat array
        if group == 0:
            return flat_array

        new_array = []
        sub_array = []

        for item in flat_array:
            sub_array.append(item)
            if len(sub_array) == group:
                new_array.append(sub_array)
                sub_array = []

        if sub_array:
            logger.warning('warning, array was not aligned to requested grouping %s remaining value %s' % (group,sub_array))

        return new_array

    def getFieldAsStringArray(self, field, ancestry):
        """
        Get a list of strings
        """
        self_real = self.getRealNode()  # in case we're an instance

        child_array = None
        for child in self_real.children:
            if child.id and len(child.id) == 1 and child.id[0] == field:
                child_array = child
                logger.debug("getFieldAsStringArray field %s child.id %r" % (field, child.id))
                break
        if not child_array:
            logger.debug("getFieldAsStringArray : no explicit field, returning []")
            return []

        logger.debug("getFieldAsStringArray child\n%r" % child)
        # each string gets its own list, remove ""'s
        new_array = []
        try:
            for j,f in enumerate(child_array.fields):
                logger.debug("getFieldAsStringArray field %s subfield %i value %r" % (field, j, f))
            try:
                new_array = [mfstring.slash_decode(f[1:-1]) for f in child_array.fields]
            except:
                new_array = []
                raise
        except mfstring.SlashEncodingError as exc:
            logger.warning(str(exc))
        except:
            logger.warning('String array could not be made')

        return new_array

    def getFieldAsMFStringArray(self, field, default, ancestry):
        """
        Get a list of strings based on a field assumed to be a MFString

        return value is a list, possibly enter, never None
        Each item of the list will have already been decoded from the encoded
        form specified in VRML or X3D = XML encoding specifications.
            and may include embedded spaces, backslashes or quotes/
        """
        if self.x3dNode:
            self_real = self.getRealNode()  # in case we're an instance
            field_xml = self.x3dNode.getAttributeNode(field)
            if field_xml is None:
                return []
            logger.debug("getFieldAsMFStringArray for x3dNode: field '%s' raw_text |%s|" % (field, field_xml.value))
            if not field_xml.value:
                return []
            else:
                try:
                    return mfstring.decode(field_xml.value)
                except Exception as exc:
                    logger.error("getFieldAsMFStringArray error from call to mfstring.decode %s" % str(exc))
                    return []

        #  following code is for VRML encoded cases
        array = self.getFieldAsString(field, None, ancestry)
        logger.debug("getFieldAsMFStringArray self.getFieldAsString result: |%r|" % array)
        if array is None: # try get array list
            try:
                array = self.getFieldAsStringArray(field, ancestry)
                logger.debug("getFieldAsMFStringArray getFieldAsStringArray result |%r|" % array)
                # in some cases we get a list of arrays
            except:
                array = default
        else: # parse string to array
            if '" "' in array: # mfstring with multiple elements
                # '"foo" "bar"' --> ['foo', 'bar']
                logger.warning("getFieldAsMFStringArray reckless splitting of |%r|" % array)
                array = [w.strip('"') for w in array.split('" "')]
            else: # regular string or mfstring with single element
                array = [array]


        return array

    def getLevel(self):
        # Ignore self_real
        level = 0
        p = self.parent
        while p:
            level += 1
            p = p.parent
            if not p:
                break

        return level

    def __repr__(self):
        level = self.getLevel()
        ind = '  ' * level
        if self.node_type == NODE_REFERENCE:
            brackets = ''
        elif self.node_type == NODE_NORMAL:
            brackets = '{}'
        else:
            brackets = '[]'

        if brackets:
            text = ind + brackets[0] + '\n'
        else:
            text = ''

        text += ind + 'ID: ' + str(self.id) + ' ' + str(level) + (' lineno %d\n' % self.lineno)

        if self.node_type == NODE_REFERENCE:
            text += ind + "(reference node)\n"
            return text

        if self.proto_node:
            text += ind + 'PROTO NODE...\n'
            text += str(self.proto_node)
            text += ind + 'PROTO NODE_DONE\n'

        text += ind + 'FIELDS:' + str(len(self.fields)) + '\n'

        for i, item in enumerate(self.fields):
            text += ind + 'FIELD:\n'
            text += ind + str(item) + '\n'

        text += ind + 'PROTO_FIELD_DEFS:' + str(len(self.proto_field_defs)) + '\n'

        for i, item in enumerate(self.proto_field_defs):
            text += ind + 'PROTO_FIELD:\n'
            text += ind + str(item) + '\n'

        text += ind + 'ARRAY: ' + str(len(self.array_data)) + ' ' + str(self.array_data) + '\n'
        # text += ind + 'ARRAY: ' + str(len(self.array_data)) + '[...] \n'

        text += ind + 'CHILDREN: ' + str(len(self.children)) + '\n'
        for i, child in enumerate(self.children):
            text += ind + ('CHILD%d:\n' % i)
            text += str(child)

        text += '\n' + ind + brackets[1]

        return text

    def parse(self, i, IS_PROTO_DATA=False):
        new_i = self.__parse(i, IS_PROTO_DATA)

        # Check if this node was an inline or externproto

        url_ls = []

        if self.node_type == NODE_NORMAL and self.getSpec() == 'Inline':
            # An Inline is loaded by importInline, as for XML (with its cycle guard and load budget). Read here as
            # well, it came in twice; before 2.7.3 this branch raised TypeError for every ClassicVRML Inline (the url
            # list itself went to os.path.exists), so no file ever loaded both ways.
            pass

        elif self.getExternprotoName():
            # externproto
            url_ls = []
            for f in self.fields:

                if type(f) == str:
                    f = [f]

                for ff in f:
                    for f_split in ff.split('"'):
                        # "someextern.vrml#SomeID"
                        if '#' in f_split:

                            f_split, f_split_id = f_split.split('#')  # there should only be 1 # anyway

                            url_ls.append((f_split, f_split_id))
                        else:
                            url_ls.append((f_split, None))

        # Was either an Inline or an EXTERNPROTO
        if url_ls:
            for url, extern_key in url_ls:
                logger.debug(url)
                urls = []
                urls.append(url)
                urls.append(bpy.path.resolve_ncase(urls[-1]))

                urls.append(os.path.join(os.path.dirname(self.getFilename()), url))
                urls.append(bpy.path.resolve_ncase(urls[-1]))

                urls.append(os.path.join(os.path.dirname(self.getFilename()), os.path.basename(url)))
                urls.append(bpy.path.resolve_ncase(urls[-1]))

                try:
                    url = [url for url in urls if os.path.exists(url)][0]
                    url_found = True
                except:
                    url_found = False

                if not url_found:
                    logger.warning('Inline URL could not be found: %s' % url)
                else:
                    resolved = os.path.realpath(url)
                    if url == self.getFilename() or resolved in _VRML_INLINE_STACK \
                            or resolved == os.path.realpath(self.getFilename() or ""):
                        # a inlines b and b inlines a recursed until Python's stack ran out (chaos round 2.7.3)
                        logger.warning('Can\'t Inline a file that is already being read: %s' % url)
                    else:
                        _VRML_INLINE_STACK.append(resolved)

                        try:
                            data = gzipOpen(url)
                        except:
                            logger.warning('Can\'t open the file: %s' % url)
                            data = None

                        if data:
                            # Tricky - inline another VRML
                            logger.warning('Loading Inline:"%s"...' % url)

                            # Watch it! - backup lines
                            lines_old = lines[:]

                            lines[:] = vrmlFormat(data)

                            lines.insert(0, '{')
                            lines.insert(0, 'root_node____')
                            lines.append('}')

                            child = vrmlNode(self, NODE_NORMAL, -1)
                            child.setRoot(url)  # initialized dicts
                            child.parse(0)

                            # if self.getExternprotoName():
                            if self.getExternprotoName():
                                if not extern_key:  # if none is specified - use the name
                                    extern_key = self.getSpec()

                                if extern_key:

                                    self.children.remove(child)
                                    child.parent = None

                                    extern_child = child.findSpecRecursive(extern_key)

                                    if extern_child:
                                        self.children.append(extern_child)
                                        extern_child.parent = self
                                        logger.debug("\tEXTERNPROTO ID found!:", extern_key)
                                    else:
                                        logger.warning("EXTERNPROTO ID not found!: %s" % extern_key)

                            # Watch it! - restore lines
                            lines[:] = lines_old
                        _VRML_INLINE_STACK.pop()

        return new_i

    def __parse(self, i, IS_PROTO_DATA=False):
        l = lines[i]

        if l == '[':
            # An anonymous list
            self.id = None
            i += 1
        else:
            words = []

            node_type, new_i = is_nodeline(i, words)
            if not node_type:  # fail for parsing new node.
                logger.warning("Failed to parse new node")
                raise ValueError

            if self.node_type == NODE_REFERENCE:
                # Only assign the reference and quit
                position = words.index('USE') + 1
                key = words[position] if position < len(words) else None
                self.id = (words[0],)

                reference = self.getDefDict().get(key)
                if reference is None:
                    logger.warning('Reference %s not found' % key)
                    if self.parent is not None and self in self.parent.children:
                        self.parent.children.remove(self)
                    return new_i
                self.reference = reference
                return new_i

            self.id = tuple(words)

            # fill in DEF/USE
            key = self.getDefName()
            if key is not None:
                self.getDefDict()[key] = self

            key = self.getProtoName()
            if not key:
                key = self.getExternprotoName()

            proto_dict = self.getProtoDict()
            if key is not None:
                proto_dict[key] = self

                # Parse the proto nodes fields
                self.proto_node = vrmlNode(self, NODE_ARRAY, new_i)
                new_i = self.proto_node.parse(new_i)

                self.children.remove(self.proto_node)
                new_i += 1  # skip past the {

            else:  # If we're a proto instance, add the proto node as our child.
                spec = self.getSpec()
                try:
                    self.children.append(proto_dict[spec])
                    # pass
                except:
                    pass

                del spec

            del proto_dict, key

            i = new_i
        ok = True
        while ok:
            if i >= len(lines):
                return len(lines) - 1

            l = lines[i]
            if l == '':
                i += 1
                continue

            if l == '}':
                if self.node_type != NODE_NORMAL:  # also ends proto nodes, we may want a type for these too.
                    logger.warning('wrong node ending, expected an } ' + str(i) + ' ' + str(self.node_type))
                return i + 1
            if l == ']':
                if self.node_type != NODE_ARRAY:
                    logger.warning('wrong node ending, expected a ] ' + str(i) + ' ' + str(self.node_type))
                    if DEBUG:
                        raise ValueError
                return i + 1

            node_type, new_i = is_nodeline(i, [])
            if node_type:  # check text\n{
                child = vrmlNode(self, node_type, i)
                i = child.parse(i)

            elif l == '[':  # some files have these anonymous lists
                child = vrmlNode(self, NODE_ARRAY, i)
                i = child.parse(i)

            elif is_numline(i):
                l_split = l.replace(',',' ').split()

                values = None
                # See if each item is a float?
                if l_split:
                    for num_type in (int, float):
                        try:
                            values = [num_type(v) for v in l_split]
                            break
                        except:
                            pass
                    else:
                        logger.warning("unable to parse a numline: %s" % (l,))
                    # This should not extend over multiple lines however it is possible
                    if values:
                        self.array_data.extend(values)
                i += 1
            else:
                words = vrml_split(l)
                if len(words) > 2 and words[1] == 'USE':
                    vrmlNode(self, NODE_REFERENCE, i)
                else:
                    while 1:
                        # check to see if this line
                        # is a collection of encoded sfstring values (enclosed by quotes)
                        stripped_line=l.strip()

                        if stripped_line and stripped_line[0] == '"':
                            for str_item in vrml_split(stripped_line):
                                if str_item[0] == '"' and str_item[-1] == '"':
                                    self.fields.append(str_item)
                                else:
                                    logger.warning("unrecognized |%s| in mfstring list" % str_item)
                                    break
                            else:
                                break

                        value = l

                        quote_count = vrml_count_quote(l)
                        if (quote_count % 2) == 1:  # odd number, indicating unterminated VRML string
                            logger.info("__parse: handling multiline VRML string")
                            accumulated_lines = l
                            logger.debug("accumulated_line: %i \n %s" % (quote_count,accumulated_lines) )
                            LOOP_GUARD = 4

                            while 1:
                                LOOP_GUARD -= 1
                                if LOOP_GUARD < 0:
                                    raise ValueError("__parse: infinite loop in handling multiline VRML string")
                                i += 1
                                if i >= len(lines):
                                    raise ValueError("__parse: unterminated VRML string at the end of the file")
                                accumulated_lines = accumulated_lines +"\n" + lines[i]
                                quote_count = vrml_count_quote(accumulated_lines)
                                if (quote_count % 2) == 0:  # even number, VRML string completed
                                    value = accumulated_lines
                                    break
                                logger.debug("accumulated_line: %i \n %s" % (quote_count,accumulated_lines) )

                        value_all = vrml_split(value)
                        logger.debug("vrml_split value |%s| --> |%s|" % (value, value_all))

                        logger.debug("vrml_split_fields |%s| --> |%s|" % (value_all, vrml_split_fields(value_all)))
                        for value in vrml_split_fields(value_all):
                            # Split

                            if value[0] == 'field':
                                # field SFFloat creaseAngle 4
                                self.proto_field_defs.append(value)
                            else:
                                logger.debug("appended value |%s| from |%s|" % (value,value_all))
                                self.fields.append(value)
                        break # guarantee breakout of of while 1 block
                i += 1

    # This is a prerequisite for DEF/USE-based material caching
    def canHaveReferences(self):
        return self.node_type == NODE_NORMAL and self.getDefName()

    # This is a prerequisite for raw XML-based material caching.
    # NOTE - crude, but working implementation for
    # material and texture caching, based on __repr__.
    # Doesn't do any XML, but is better than nothing.
    def desc(self):
        if "material" in self.id or "texture" in self.id:
            node = self.reference if self.node_type == NODE_REFERENCE else self
            return frozenset(line.strip() for line in repr(node).strip().split("\n"))
        else:
            return None



_VRML_INLINE_STACK = []   # ClassicVRML files being inlined right now (resolved paths), to stop a -> b -> a


def gzipOpen(path):
    """The file's text, gunzipped when it is gzip, within the decompressed source budget (import_resources); None when
    it cannot be read, with the reason logged."""
    from .import_resources import ResourceLimitError, read_source_bytes

    try:
        return read_source_bytes(path).decode(encoding='utf-8', errors='surrogateescape')
    except ResourceLimitError as exc:
        logger.error("Not importing %s: %s", path, exc)
    except Exception:
        import traceback
        traceback.print_exc()
    return None



def vrml_parse(path):
    """
    Sets up the root node and returns it so load_web3d() can deal with the blender side of things.
    Return root (vrmlNode, '') or (None, 'Error String')
    """
    data = gzipOpen(path)

    if data is None:
        return None, 'Failed to open file: ' + path

    _note_protos('PROTO' in data)
    # Stripped above
    lines[:] = vrmlFormat(data)

    lines.insert(0, '{')
    lines.insert(0, 'dymmy_node')
    lines.append('}')
    # Use for testing our parsed output, so we can check on line numbers.

    '''
    ff = open('/tmp/test.txt', 'w')
    ff.writelines([l+'\n' for l in lines])
    ff.close()
    '''

    # Now evaluate it
    node_type, new_i = is_nodeline(0, [])
    if not node_type:
        return None, 'Error: VRML file has no starting Node'

    # Trick to make sure we get all root nodes.
    lines.insert(0, '{')
    lines.insert(0, 'root_node____')  # important the name starts with an ascii char
    lines.append('}')

    root = vrmlNode(None, NODE_NORMAL, -1)
    root.setRoot(path)  # we need to set the root so we have a namespace and know the path in case of inlineing

    # Parse recursively
    root.parse(0)

    return root, ''


# ====================== END VRML

# ====================== X3d Support

# Sane as vrml but replace the parser
class x3dNode(vrmlNode):
    def __init__(self, parent, node_type, x3dNode):
        vrmlNode.__init__(self, parent, node_type, -1)
        self.x3dNode = x3dNode

    def parse(self, IS_PROTO_DATA=False):
        self.lineno = self.x3dNode.parse_position[0]

        define = self.x3dNode.getAttributeNode('DEF')
        if define:
            self.getDefDict()[define.value] = self
        else:
            use = self.x3dNode.getAttributeNode('USE')
            if use:
                try:
                    self.reference = self.getDefDict()[use.value]
                    self.node_type = NODE_REFERENCE
                except:
                    logger.warning('Reference %s not found' % use.value )
                    self.parent.children.remove(self)

                return

        for x3dChildNode in self.x3dNode.childNodes:
            if x3dChildNode.nodeType in {x3dChildNode.TEXT_NODE, x3dChildNode.COMMENT_NODE, x3dChildNode.CDATA_SECTION_NODE}:
                continue

            node_type = NODE_NORMAL
            if x3dChildNode.getAttributeNode('USE'):
                node_type = NODE_REFERENCE

            child = x3dNode(self, node_type, x3dChildNode)
            child.parse()

        # TODO - x3d Inline

    def getSpec(self):
        return self.x3dNode.tagName  # should match vrml spec

    # Used to retain object identifiers from X3D to Blender
    def getDefName(self):
        node_id = self.x3dNode.getAttributeNode('DEF')
        if node_id:
            return node_id.value
        node_id = self.x3dNode.getAttributeNode('USE')
        if node_id:
            return "USE_" + node_id.value
        return None

    # Other funcs operate from vrml, but this means we can wrap XML fields, still use nice utility funcs
    # getFieldAsArray getFieldAsBool etc
    def getFieldName(self, field, ancestry, AS_CHILD=False, SPLIT_COMMAS=False):
        # ancestry and AS_CHILD are ignored, only used for VRML now


        self_real = self.getRealNode()  # in case we're an instance

        # 2025-02-22 Note added for future code archaeologists
        # self.x3dNode is an instance of xml.dom.Element and
        # getAttributeNode  returns an instance of class xml.dom.Attr
        # https://docs.python.org/3/library/xml.dom.html#attr-objects
        field_xml = self.x3dNode.getAttributeNode(field)
        if field_xml:
            value = field_xml.value

            # We may want to edit. for x3d specific stuff
            # Sucks a bit to return the field name in the list but vrml excepts this :/
            if SPLIT_COMMAS:
                value = value.replace(",", " ")
            if '"' in value:
                logger.warning("applying str.split to an X3D XML attribute '%s'; that contains SFString |%s|" % (field,value))
            return value.split()
        else:
            return None

    def getFieldAsString(self, field, default, ancestry):
        # In the XML encoding an SFString attribute is plain text; only the
        # classic (VRML) encoding wraps it in quotes. Accept both.
        self_real = self.getRealNode()
        field_xml = self_real.x3dNode.getAttributeNode(field)
        if field_xml is None:
            return default
        value = field_xml.value
        if len(value) > 1 and value[0] == '"' and value[-1] == '"':
            try:
                return mfstring.slash_decode(value[1:-1])
            except mfstring.SlashEncodingError:
                return default
        return value

    def canHaveReferences(self):
        return self.x3dNode.getAttributeNode('DEF')

    def desc(self):
        return self.getRealNode().x3dNode.toxml()


def _make_sax_parser():
    """An Expat SAX parser with reparse deferral switched off.

    Expat 2.6 and later defers a very large start tag (a multi-megabyte
    attribute such as GaussianSplats positions or a big Coordinate point list)
    until the parser is closed. minidom.parseString drives the parser through
    pulldom, which stops reading events once close() is called, so the deferred
    element was silently dropped: a 4.1 file with 18,000 or more splats
    imported nothing. With deferral off every element arrives before close().
    """
    from .import_resources import make_x3d_sax_parser

    return make_x3d_sax_parser()


def _parse_bytes(raw, make_parser, path):
    """``(document, None)`` or ``(None, why)``. The parser gets bytes, so expat honours a UTF-16 BOM and the
    encoding declaration. A file that is not well-formed is refused with the parser's reason instead of ending the
    import with a traceback (chaos round 2.7.3: a cut-off file, an entity declaration, a NUL byte). A file that is
    not UTF-8 and declares no other encoding (Latin-1 or Windows-1252 bytes in a name) is read once more as
    Windows-1252, with a warning. ``make_parser`` returns a fresh SAX parser: one cannot be reused."""
    import io
    import xml.dom.minidom
    import xml.sax
    from xml.parsers.expat import ExpatError

    errors = (xml.sax.SAXException, ExpatError, ValueError, UnicodeError, LookupError)
    declared = re.match(rb"""^(\xef\xbb\xbf)?<\?xml[^>]*?encoding\s*=\s*(['"])([^'"]*)\2""", raw)
    if declared:
        import codecs
        try:
            codecs.lookup(declared.group(3).decode('ascii', 'replace'))
        except LookupError:
            # an encoding name Python does not know (a fuzzed "UTF1e309"): read the bytes as UTF-8, which the str
            # parser before 2.7.3 did by ignoring the declaration
            logger.warning("%s declares the unknown encoding %r; reading it as UTF-8", os.path.basename(path),
                           declared.group(3).decode('ascii', 'replace'))
            raw = raw[:declared.start(3)] + b'UTF-8' + raw[declared.end(3):]
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        # UTF-16 with a BOM: expat refuses it when the declaration says UTF-8, which an editor that saved the file
        # as UTF-16 leaves in place. The BOM decides; the text goes on as UTF-8.
        try:
            text = raw.decode('utf-16')
            raw = re.sub(r"""^(<\?xml[^>]*?encoding\s*=\s*)(['"])[^'"]*\2""", r"\1\2UTF-8\2", text).encode('utf-8')
        except UnicodeError:
            pass
    try:
        return xml.dom.minidom.parse(io.BytesIO(raw), make_parser()), None
    except errors as exc:
        first = exc
    try:
        raw.decode('utf-8')
        undecodable = False
    except UnicodeDecodeError:
        undecodable = not raw.startswith((b'\xff\xfe', b'\xfe\xff'))
    declaration = raw[:200].split(b'?>')[0].lower()
    declares_other = re.search(rb"encoding\s*=\s*['\"](?!utf-8['\"])", declaration) is not None
    if undecodable and not declares_other:
        try:
            doc = xml.dom.minidom.parse(io.BytesIO(raw.decode('cp1252', errors='replace').encode('utf-8')),
                                        make_parser())
            logger.warning("%s is not UTF-8; read it as Windows-1252", os.path.basename(path))
            return doc, None
        except errors:
            pass
    return None, f'Not a well-formed X3D file, not importing {os.path.basename(path)}: {first}'


def x3d_parse(path):
    """
    Sets up the root node and returns it so load_web3d() can deal with the blender side of things.
    Return root (x3dNode, '') or (None, 'Error String')
    """
    import xml.dom.minidom
    import xml.sax
    from xml.sax import handler

    from .import_resources import ResourceLimitError, read_source_bytes

    try:
        raw = read_source_bytes(path)
    except ResourceLimitError as exc:
        return None, f'Not importing {path}: {exc}'
    except OSError as exc:
        return None, f'Failed to open file: {path} ({exc})'
    text = raw.decode('utf-8', errors='replace').lstrip('\ufeff')
    if not text.strip() or not raw.strip(b'\x00\xef\xbb\xbf\xfe\xff \t\r\n'):
        return None, 'File is empty: ' + path   # minidom raises TypeError on an empty document

    # Enable line number reporting in the parser - kinda brittle
    def set_content_handler(dom_handler):
        def startElementNS(name, tagName, attrs):
            orig_start_cb(name, tagName, attrs)
            cur_elem = dom_handler.elementStack[-1]
            cur_elem.parse_position = (parser._parser.CurrentLineNumber, parser._parser.CurrentColumnNumber)

        orig_start_cb = dom_handler.startElementNS
        dom_handler.startElementNS = startElementNS
        orig_set_content_handler(dom_handler)

    parser = orig_set_content_handler = None

    def make_parser():
        nonlocal parser, orig_set_content_handler
        parser = _make_sax_parser()
        orig_set_content_handler = parser.setContentHandler
        parser.setFeature(handler.feature_external_ges, False)
        parser.setFeature(handler.feature_external_pes, False)
        parser.setContentHandler = set_content_handler
        return parser

    _note_protos(b'ProtoDeclare' in raw or b'ProtoInstance' in raw or b'ExternProtoDeclare' in raw)
    doc, why = _parse_bytes(raw, make_parser, path)
    if doc is None:
        return None, why

    # the root element, without minidom's recursive getElementsByTagName (RecursionError on a deep file, which the
    # bare except below read as "not a valid document": 1,500 nested Transforms, chaos round 2.7.3)
    x3dnode = doc.documentElement
    if x3dnode is None or x3dnode.tagName != 'X3D':
        try:
            x3dnode = doc.getElementsByTagName('X3D')[0]
        except Exception:
            return None, 'Not a valid x3d document, cannot import'

    if not _INLINE_STACK:
        # once per import, not once per Inline file: the operator walks every object in the scene, so an Inline
        # fan-out paid it a thousand times over a growing scene (chaos round 2.7.3)
        bpy.ops.object.select_all(action='DESELECT')

    root = x3dNode(None, NODE_NORMAL, x3dnode)
    root.setRoot(path)  # so images and Inline's we load have a relative path
    root.parse()

    return root, ''




# NO BLENDER CODE ABOVE THIS LINE.
# -----------------------------------------------------------------------------------
import bpy
from bpy_extras import image_utils, node_shader_utils
from mathutils import Vector, Matrix, Quaternion

GLOBALS = {'CIRCLE_DETAIL': 16}


def translateRotation(rot):
    """ axis, angle """
    if len(rot) < 4:  # malformed SFRotation (fewer than four numbers): no rotation
        logger.warning("rotation %r has %d of 4 numbers; read as no rotation", rot, len(rot))
        return Matrix.Identity(4)
    return Matrix.Rotation(rot[3], 4, Vector(rot[:3]))


def translateScale(sca):
    if len(sca) < 3:  # malformed SFVec3f: '1 1 --1' parses as two numbers, and sca[2] raised IndexError
        logger.warning("scale %r has %d of 3 numbers; read as no scale", sca, len(sca))
        return Matrix.Identity(4)
    mat = Matrix()  # 4x4 default
    mat[0][0] = sca[0]
    mat[1][1] = sca[1]
    mat[2][2] = sca[2]
    return mat


def translateTransform(node, ancestry):
    # RigidBody places itself with position and orientation; CollidableShape and CollidableOffset use a Transform's names
    is_body = node.getSpec() == 'RigidBody'
    cent = node.getFieldAsFloatTuple('center', None, ancestry, conversion_scale)  # (0.0, 0.0, 0.0)
    rot = node.getFieldAsFloatTuple('orientation' if is_body else 'rotation', None, ancestry)  # (0.0, 0.0, 1.0, 0.0)
    sca = node.getFieldAsFloatTuple('scale', None, ancestry)  # (1.0, 1.0, 1.0)
    scaori = node.getFieldAsFloatTuple('scaleOrientation', None, ancestry)  # (0.0, 0.0, 1.0, 0.0)
    tx = node.getFieldAsFloatTuple('position' if is_body else 'translation', None, ancestry, conversion_scale)  # (0.0, 0.0, 0.0)

    if cent and len(cent) != 3:
        logger.warning("center %r has %d of 3 numbers; read as no center", cent, len(cent))
        cent = None
    if tx and len(tx) != 3:
        logger.warning("translation %r has %d of 3 numbers; read as no translation", tx, len(tx))
        tx = None

    if cent:
        cent_mat = Matrix.Translation(cent)
        cent_imat = cent_mat.inverted()
    else:
        cent_mat = cent_imat = None

    if rot:
        rot_mat = translateRotation(rot)
    else:
        rot_mat = None

    if sca:
        sca_mat = translateScale(sca)
    else:
        sca_mat = None

    if scaori:
        scaori_mat = translateRotation(scaori)
        scaori_imat = scaori_mat.inverted()
    else:
        scaori_mat = scaori_imat = None

    if tx:
        tx_mat = Matrix.Translation(tx)
    else:
        tx_mat = None

    new_mat = Matrix()

    mats = [tx_mat, cent_mat, rot_mat, scaori_mat, sca_mat, scaori_imat, cent_imat]
    for mtx in mats:
        if mtx:
            new_mat = new_mat @ mtx

    return new_mat


def translateTexTransform(node, ancestry):
    cent = node.getFieldAsFloatTuple('center', None, ancestry, conversion_scale)  # (0.0, 0.0)
    rot = node.getFieldAsFloat('rotation', None, ancestry)  # 0.0
    sca = node.getFieldAsFloatTuple('scale', None, ancestry)  # (1.0, 1.0)
    tx = node.getFieldAsFloatTuple('translation', None, ancestry, conversion_scale)  # (0.0, 0.0)

    if cent:
        # cent is at a corner by default
        cent_mat = Matrix.Translation(Vector(cent).to_3d())
        cent_imat = cent_mat.inverted()
    else:
        cent_mat = cent_imat = None

    if rot:
        rot_mat = Matrix.Rotation(rot * (-1), 4, 'Z')  # translateRotation(rot), -1 because we need -Z axis rotation
    else:
        rot_mat = None

    if sca:
        sca_mat = translateScale((sca[0], sca[1], 0.0))
    else:
        sca_mat = None

    if tx:
        tx_mat = Matrix.Translation(Vector(tx).to_3d())
    else:
        tx_mat = None

    new_mat = Matrix()

    # as specified in VRML97 docs
    mats = [cent_imat, sca_mat, rot_mat, cent_mat, tx_mat]

    for mtx in mats:
        if mtx:
            new_mat = new_mat @ mtx

    return new_mat


# Each node's own Transform matrix, read once per import. getFinalMatrix walks every ancestor for every node, so
# 5,000 nested Transforms read 12.5 million Transforms and took minutes (chaos round 2.7.3). A file with PROTOs is
# not cached: an IS field reads differently through a different ancestry.
_transform_cache = {}
_transform_cache_on = True


def _transform_of(node_tx, ancestry):
    if not _transform_cache_on:
        return translateTransform(node_tx, ancestry)
    mat = _transform_cache.get(node_tx)
    if mat is None:
        mat = _transform_cache[node_tx] = translateTransform(node_tx, ancestry)
    return mat


def _note_protos(has_protos):
    global _transform_cache_on
    if has_protos:
        _transform_cache_on = False


def getFinalMatrix(node, mtx, ancestry, global_matrix):

    transform_nodes = [node_tx for node_tx in ancestry if node_tx.getSpec() in TRANSFORM_SPECS or node_tx.getSpec() in PHYSICS_FRAME_SPECS]
    if node.getSpec() in TRANSFORM_SPECS:
        transform_nodes.append(node)
    transform_nodes.reverse()

    if mtx is None:
        mtx = Matrix()

    for node_tx in transform_nodes:
        mat = _transform_of(node_tx, ancestry)
        mtx = mat @ mtx

    # worldspace matrix
    mtx = global_matrix @ mtx

    return mtx


def linear_to_srgb(linear):
    """Converts a linear color value to srgb color space"""
    if linear <= 0.0031308:
        return linear * 12.92
    else:
        return 1.055 * (linear ** (1.0 / 2.4)) - 0.055


def srgb_to_linear(srgb_value):
    """Converts a srgb color value to linear space"""
    if srgb_value <= 0.04045:
        return srgb_value / 12.92
    else:
        return ((srgb_value + 0.055) / 1.055) ** 2.4


# -----------------------------------------------------------------------------------
# Mesh import utilities

# X_ITE reads a Color or ColorRGBA node in two ways (measured 12 Nov 2026, X_ITE 16.7.1, headless Chrome 153,
# SwiftShader): under Material, TwoSidedMaterial or UnlitMaterial in display space, as their own colours (a Color of
# 0.5 on a white Material draws 128, the same as a diffuseColor of 0.5); under PhysicalMaterial as a linear factor on
# baseColor (a Color of 0.5 on a baseColor of 1 draws 110, the same as a baseColor of 0.5). importShape sets this
# while it builds a PhysicalMaterial shape's geometry, so those colours are kept as they are.
vertex_colours_linear = False


def make_colour_attribute_active(bpymesh, attribute):
    """Blender leaves a new colour attribute inactive, and the X3D, glTF and USD exporters write only the active
    (or render) one, so an imported Color node was dropped on the way out."""
    colours = bpymesh.color_attributes
    for prop in ("active_color_name", "default_color_name"):
        try:
            setattr(colours, prop, attribute.name)
        except (AttributeError, TypeError):  # older Blender: only active_color
            try:
                colours.active_color = attribute
            except (AttributeError, TypeError):
                pass


def _vertex_colours_are_display():
    """Whether this shape's Color / ColorRGBA values are display (sRGB) values to convert to linear: under the SRGB
    colour space and not drawn with a PhysicalMaterial. The export's rule mirrored (extract.display_colour and
    emit_x3d40.with_display_colours): under AS_IS it writes vertex colours as Blender holds them, so the import must
    read them back unchanged, or each AS_IS round trip darkens them once more (a point colour 0.5 became 0.214, then
    0.038)."""
    return colour_space == 'SRGB' and not vertex_colours_linear


def set_new_float_color_attribute(bpymesh, color_data, name: str = "ColorPerCorner", convert_to_linear: bool = True):
    """Uses the new blender api to apply colors to a mesh as vertex colors (domain face corner)"""
    if convert_to_linear and _vertex_colours_are_display():
        # convert color spaces to account for api changes from legacy to newer api; every fourth value is alpha,
        # which is not a colour (a ColorRGBA alpha of 0.5 used to become 0.21)
        color_data = [col_val if i % 4 == 3 else srgb_to_linear(col_val) for i, col_val in enumerate(color_data)]
    # add new color attribute
    attribute = bpymesh.color_attributes.new(name, 'FLOAT_COLOR', 'CORNER')
    attribute.data.foreach_set("color", color_data)
    if not name.startswith("temp_"):
        make_colour_attribute_active(bpymesh, attribute)


# Assumes that the mesh has polygons.
def importMesh_ApplyColors(bpymesh, geom, ancestry):
    colors = geom.getChildBySpec(['ColorRGBA', 'Color'])
    if colors:
        if colors.getSpec() == 'ColorRGBA':
            rgb = colors.getFieldAsArray('color', 4, ancestry)
        else:
            # Array of arrays; no need to flatten
            rgb = [c + [1.0] for c in colors.getFieldAsArray('color', 3, ancestry)]

        rgb_overflow_warning = "Vertex colors applied with non matching numbers of vertices or loops (rgb colors too big)"
        rgb_len = len(rgb)
        vertices_len = len(bpymesh.vertices)
        loops_len = len(bpymesh.loops)
        if rgb_len < vertices_len and rgb_len != loops_len:
            # colours are per vertex in the triangle sets; a vertex past them (an index past the points adds one)
            # is white, as pad_values does for IndexedFaceSet, instead of the colours going on by corner
            logger.warning("Color has %d values for %d vertices; the rest are white", rgb_len, vertices_len)
            rgb = list(rgb) + [[1.0, 1.0, 1.0, 1.0]] * (vertices_len - rgb_len)
            rgb_len = vertices_len
        # usually we want an exact length match, however some files are corrupted
        # having more color values is not critical, but we need to ensure that neither verts nor loops are exact matches
        if rgb_len >= vertices_len and rgb_len != loops_len:
            if rgb_len > vertices_len:
                rgb = rgb[:vertices_len]
                print(rgb_overflow_warning)
            rgb = [rgb[l.vertex_index] for l in bpymesh.loops]
            rgb = tuple(chain(*rgb))
        elif rgb_len >= loops_len:
            if rgb_len > loops_len:
                rgb = rgb[:loops_len]
                print(rgb_overflow_warning)
            rgb = tuple(chain(*rgb))
        else:
            logger.warning(
                "Not applying vertex colors, non matching numbers of vertices or loops (%d vs %d/%d)" %
                (rgb_len, vertices_len, loops_len)
            )
            return

        set_new_float_color_attribute(bpymesh, rgb)


# Assumes that the vertices have not been rearranged compared to the
# source file order # or in the order assumed by the spec (e. g. in
# Elevation, in rows by x).
# Assumes polygons have been set.
def importMesh_ApplyNormals(bpymesh, geom, ancestry):
    normals = geom.getChildBySpec('Normal')
    if not normals:
        return

    per_vertex = geom.getFieldAsBool('normalPerVertex', True, ancestry)
    vectors = normals.getFieldAsArray('vector', 0, ancestry)
    target = bpymesh.vertices if per_vertex else bpymesh.polygons
    need = 3 * len(target)
    if len(vectors) != need:
        # a short or long Normal list (or vertices added for an index past the points): foreach_set needs the exact
        # length, so pad with +Z or cut, with a warning
        logger.warning("Normal has %d values for %d %s; padded or cut to fit", len(vectors) // 3, len(target),
                       "vertices" if per_vertex else "faces")
        vectors = (list(vectors) + [0.0, 0.0, 1.0] * len(target))[:need]
    try:
        target.foreach_set("normal", vectors)
    except (AttributeError, RuntimeError, TypeError):   # read-only normals in this Blender: Blender computes them
        pass


# Reads the standard Coordinate object - common for all mesh elements
# Feeds the vertices in the mesh.
# Rearranging the vertex order is a bad idea - other elements
# in X3D might rely on it,  if you need to rearrange, please play with
# vertex indices in the polygons instead.
#
# Vertex culling that we have in IndexedFaceSet is an unfortunate exception,
# brought forth by a very specific issue.
def importMesh_ReadVertices(bpymesh, geom, ancestry):
    # We want points here as a flat array, but the caching logic in
    # IndexedFaceSet presumes a 2D one.
    # The case for caching is stronger over there.
    coord = _coordinate_of(geom)
    if coord is None:
        logger.warning("%s has no Coordinate; it has no vertices", geom.getSpec())
        return
    points = coord.getFieldAsArray('point', 0, ancestry, conversion_scale)
    points = points[:len(points) - len(points) % 3]
    bpymesh.vertices.add(len(points) // 3)
    bpymesh.vertices.foreach_set("co", points)


# Assumes that the order of vertices matches the source file.
# Relies upon texture coordinates in the X3D node; if a coordinate generation
# algorithm for a geometry is in the spec (e. g. for ElevationGrid), it needs
# to be implemented by the geometry handler.
#
# Texture transform is applied in ProcessObject.
def importMesh_ApplyUVs(bpymesh, geom, ancestry):
    tex_coord = geom.getChildBySpec('TextureCoordinate')
    if not tex_coord:
        return

    uvs = tex_coord.getFieldAsArray('point', 2, ancestry)
    if not uvs:
        return

    # a vertex past the texture coordinates (an index past the points adds one) reads (0, 0)
    uvs = pad_values(uvs, len(bpymesh.vertices), (0.0, 0.0), 'TextureCoordinate')
    d = bpymesh.uv_layers.new().data
    uvs = [i for poly in bpymesh.polygons
           for vidx in poly.vertices
           for i in uvs[vidx]]
    d.foreach_set('uv', uvs)


# Common steps for all triangle meshes once the geometry has been set:
# normals, vertex colors, and UVs.
def importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry):
    importMesh_ApplyNormals(bpymesh, geom, ancestry)
    importMesh_ApplyColors(bpymesh, geom, ancestry)
    importMesh_ApplyUVs(bpymesh, geom, ancestry)
    bpymesh.validate()
    bpymesh.update()
    return bpymesh


# Assumes that the mesh is stored as polygons and loops, and the premade array
# of texture coordinates follows the loop array.
# The loops array must be flat.
def importMesh_ApplyTextureToLoops(bpymesh, loops):
    if len(loops) != 2 * len(bpymesh.loops):  # e.g. a texCoordIndex shorter than coordIndex
        logger.warning("%d texture coordinates for %d face corners; UVs skipped", len(loops) // 2, len(bpymesh.loops))
        return
    d = bpymesh.uv_layers.new().data
    d.foreach_set('uv', loops)


def flip(r, ccw):
    return r if ccw else r[::-1]

def clean_index_field(values, field):
    """An MFInt32 index field as ints: a non-integer, non-finite or negative entry other than -1 is malformed and
    becomes -1 (end of face) with a warning, instead of raising TypeError/IndexError deep in the mesh build."""
    cleaned, bad = [], 0
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = math.nan
        if not math.isfinite(number) or not number.is_integer() or number < -1:
            cleaned.append(-1)
            bad += 1
        else:
            cleaned.append(int(number))
    if bad:
        logger.warning("%s: %d malformed entr%s read as -1", field, bad, "y" if bad == 1 else "ies")
    return cleaned


class _PaddedValues(list):
    """A value list that reads ``filler`` for any index past its end, without storing the padding."""

    def __init__(self, values, filler):
        super().__init__(values)
        self.filler = filler

    def __getitem__(self, i):
        if isinstance(i, int) and i >= len(self):
            return self.filler
        return super().__getitem__(i)


PAD_IN_PLACE = 1 << 16   # a gap this small is padded for real, as before


def pad_values(values, need, filler, field):
    """Extend ``values`` to ``need`` entries with ``filler`` when an index points past its end (as
    validate_points_field does for points), so a short Normal/Color/TextureCoordinate cannot crash the import.
    A gap of more than PAD_IN_PLACE entries is not stored: one coordIndex of 2147483647 on a coloured mesh asked for
    two billion colours and raised MemoryError (chaos round, 22 Nov 2026), so such a list reads the filler past its end."""
    if len(values) < need:
        logger.warning("%s has %d values but is indexed up to %d; padding", field, len(values), need - 1)
        if need - len(values) > PAD_IN_PLACE:
            return _PaddedValues(values, filler)
        values = list(values) + [filler] * (need - len(values))
    return values


def _index_need(*arrays):
    return max((max(array) + 1 for array in arrays if array), default=0)


def _attribute_need(own_index, coord_index, per_vertex, face_count):
    """How many Normal/Color/TextureCoordinate values a face set reads, by the X3D IndexedFaceSet rules: its own
    index field when given; otherwise coordIndex when the values are per vertex, or one value per face when not.
    (Taking the maximum over coordIndex as well, as before, warned "indexed up to" on correct per-face files.)"""
    if own_index:
        return _index_need(own_index)
    return _index_need(coord_index) if per_vertex else face_count


def validate_points_field(coord_index, points):
    """
    validate number of points compared to coordIndex to ensure proper face building without errors
    """
    # Each distinct out-of-range index gets one added vertex at the origin and the face points at it. The faces keep
    # their count and order, so per-face colours and normals stay aligned. The old code padded the point list up to the
    # largest index, so a single coordIndex of 2147483647 asked for two billion vertices (MemoryError, or a frozen
    # Blender on a machine with the RAM), and 5000000 built 5,000,001 vertices for a quad (chaos round, 22 Nov 2026).
    count = len(points)
    added = {}
    for f in coord_index:
        for k, v in enumerate(f):
            if 0 <= v < count:
                continue
            if v not in added:
                added[v] = count + len(added)
            f[k] = added[v]
    if added:
        logger.warning("%d coordIndex value(s) past the %d points (largest %d); each is read as a vertex at the origin",
                       len(added), count, max(added))
        points = list(points) + [(0, 0, 0)] * len(added)
    return points

# -----------------------------------------------------------------------------------
# Now specific geometry importers


COORDINATE_SPECS = ['Coordinate', 'CoordinateDouble']   # CoordinateDouble: the same points in double precision


def _coordinate_of(geom):
    """The geometry's Coordinate or CoordinateDouble child, or None (2.7.3 read only Coordinate, so a triangle set
    with CoordinateDouble raised AttributeError: two real files in the project, receipt-to-rule engine, 23 Nov 2026)."""
    return geom.getChildBySpec(COORDINATE_SPECS)


def _fan_strip_runs(index):
    """An index list split at -1 into its fans or strips; a run shorter than three makes no triangle and is dropped."""
    runs, run = [], []
    for value in index:
        if value == -1:
            if run:
                runs.append(run)
            run = []
        else:
            run.append(value)
    if run:
        runs.append(run)
    return [r for r in runs if len(r) >= 3]


def _strip_triangles(run, cw):
    """The triangles of one strip, every other one turned so that they all face the same way."""
    out = []
    for j in range(len(run) - 2):
        odd = (j + cw) % 2
        out += [run[j + odd], run[j + 1 - odd], run[j + 2]]
    return out


def _fan_triangles(run, cw):
    out = []
    for j in range(1, len(run) - 1):
        out += [run[0], run[j + cw], run[j + 1 - cw]]
    return out


def _set_triangles(bpymesh, corners, what):
    """Give ``bpymesh`` one triangle per three entries of ``corners`` (vertex indices).

    An index past the vertices, or negative, gets one added vertex at the origin, as validate_points_field does for
    IndexedFaceSet, so the triangle count and order stay as the file says. 2.7.3 passed such an index to Blender
    as it was, and the colour and texture-coordinate passes then read past their lists (IndexError: the
    receipt-to-rule engine's replay, 23 Nov 2026)."""
    corners = corners[:len(corners) - len(corners) % 3]
    count = len(bpymesh.vertices)
    added = {}
    for k, v in enumerate(corners):
        if 0 <= v < count:
            continue
        if v not in added:
            added[v] = count + len(added)
        corners[k] = added[v]
    if added:
        logger.warning("%s: %d index value(s) outside the %d points (largest %d); each is read as a vertex at the "
                       "origin", what, len(added), count, max(added))
        bpymesh.vertices.add(len(added))
    num_polys = len(corners) // 3
    bpymesh.loops.add(num_polys * 3)
    bpymesh.polygons.add(num_polys)
    bpymesh.polygons.foreach_set("loop_start", range(0, num_polys * 3, 3))
    bpymesh.polygons.foreach_set("vertices", corners)


def _triangle_set_index(geom, ancestry, what):
    return clean_index_field(geom.getFieldAsArray('index', 0, ancestry), what + ' index')


def importMesh_IndexedTriangleSet(geom, ancestry):
    # Ignoring solid
    # colorPerVertex is always true
    if _coordinate_of(geom) is None:
        return None
    ccw = geom.getFieldAsBool('ccw', True, ancestry)

    bpymesh = bpy.data.meshes.new(name="XXX")
    importMesh_ReadVertices(bpymesh, geom, ancestry)

    # Read the faces; -1 has no meaning in an IndexedTriangleSet, so a triangle that has one is dropped
    index = _triangle_set_index(geom, ancestry, 'IndexedTriangleSet')
    triangles = [index[3 * i:3 * i + 3] for i in range(len(index) // 3)]
    triangles = [t for t in triangles if -1 not in t]
    corners = [t[j] for t in triangles for j in ((0, 1, 2) if ccw else (1, 0, 2))]
    _set_triangles(bpymesh, corners, 'IndexedTriangleSet')
    bpymesh["x3d_geometry"] = "IndexedTriangleSet"     # the X3D 4.0 export writes it back as one (extract.GEOMETRY_NODE_PROPERTY)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def importMesh_IndexedTriangleStripSet(geom, ancestry):
    # Ignoring solid
    # colorPerVertex is always true
    if _coordinate_of(geom) is None:
        return None
    cw = 0 if geom.getFieldAsBool('ccw', True, ancestry) else 1
    bpymesh = bpy.data.meshes.new(name="IndexedTriangleStripSet")
    importMesh_ReadVertices(bpymesh, geom, ancestry)
    runs = _fan_strip_runs(_triangle_set_index(geom, ancestry, 'IndexedTriangleStripSet'))
    _set_triangles(bpymesh, [c for run in runs for c in _strip_triangles(run, cw)], 'IndexedTriangleStripSet')
    bpymesh["x3d_geometry"] = "IndexedTriangleStripSet"     # written back as one by the X3D 4.0 export (node board batch 5)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def importMesh_IndexedTriangleFanSet(geom, ancestry):
    # Ignoring solid
    # colorPerVertex is always true
    if _coordinate_of(geom) is None:
        return None
    cw = 0 if geom.getFieldAsBool('ccw', True, ancestry) else 1
    bpymesh = bpy.data.meshes.new(name="IndexedTriangleFanSet")
    importMesh_ReadVertices(bpymesh, geom, ancestry)
    # 2.7.3 restarted the third fan and every later one at the wrong index (i = j + 2, not i + j + 2), so a set of
    # three or more fans asked Blender for more corners than it had made (RuntimeError, receipt-to-rule engine)
    runs = _fan_strip_runs(_triangle_set_index(geom, ancestry, 'IndexedTriangleFanSet'))
    _set_triangles(bpymesh, [c for run in runs for c in _fan_triangles(run, cw)], 'IndexedTriangleFanSet')
    bpymesh["x3d_geometry"] = "IndexedTriangleFanSet"     # written back as one by the X3D 4.0 export (node board batch 5)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def _counted_runs(counts, n, what):
    """stripCount / fanCount as runs of consecutive vertex indices; a count under 3 makes no triangle, and counts
    that run past the vertices stop at the last one (a count of two billion must not build a two-billion list)."""
    runs, start = [], 0
    for count in clean_index_field(counts, what):
        if count < 0:
            continue
        run = list(range(min(start, n), min(start + count, n)))
        start += count
        if len(run) >= 3:
            runs.append(run)
    if start > n:
        logger.warning("%s adds up to %d vertices but there are %d; the strips or fans stop at the last one",
                       what, start, n)
    return runs


def importMesh_TriangleSet(geom, ancestry):
    # Ignoring solid
    # colorPerVertex is always true
    if _coordinate_of(geom) is None:
        return None
    ccw = geom.getFieldAsBool('ccw', True, ancestry)
    bpymesh = bpy.data.meshes.new(name="TriangleSet")
    importMesh_ReadVertices(bpymesh, geom, ancestry)
    n = len(bpymesh.vertices)
    corners = [3 * i + j for i in range(n // 3) for j in ((0, 1, 2) if ccw else (1, 0, 2))]
    _set_triangles(bpymesh, corners, 'TriangleSet')
    bpymesh["x3d_geometry"] = "TriangleSet"     # written back as one by the X3D 4.0 export (node board batch 5)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def importMesh_TriangleStripSet(geom, ancestry):
    # Ignoring solid
    # colorPerVertex is always true
    if _coordinate_of(geom) is None:
        return None
    cw = 0 if geom.getFieldAsBool('ccw', True, ancestry) else 1
    bpymesh = bpy.data.meshes.new(name="TriangleStripSet")
    importMesh_ReadVertices(bpymesh, geom, ancestry)
    runs = _counted_runs(geom.getFieldAsArray('stripCount', 0, ancestry), len(bpymesh.vertices), 'stripCount')
    _set_triangles(bpymesh, [c for run in runs for c in _strip_triangles(run, cw)], 'TriangleStripSet')
    bpymesh["x3d_geometry"] = "TriangleStripSet"     # written back as one by the X3D 4.0 export (node board batch 5)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def importMesh_TriangleFanSet(geom, ancestry):
    # Ignoring solid
    # colorPerVertex is always true
    if _coordinate_of(geom) is None:
        return None
    cw = 0 if geom.getFieldAsBool('ccw', True, ancestry) else 1
    bpymesh = bpy.data.meshes.new(name="TriangleFanSet")
    importMesh_ReadVertices(bpymesh, geom, ancestry)
    runs = _counted_runs(geom.getFieldAsArray('fanCount', 0, ancestry), len(bpymesh.vertices), 'fanCount')
    _set_triangles(bpymesh, [c for run in runs for c in _fan_triangles(run, cw)], 'TriangleFanSet')
    bpymesh["x3d_geometry"] = "TriangleFanSet"     # written back as one by the X3D 4.0 export (node board batch 5)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def importMesh_IndexedFaceSet(geom, ancestry):
    # Saw the following structure in X3Ds: the first mesh has a huge set
    # of vertices and a reasonably sized index. The rest of the meshes
    # reference the Coordinate node from the first one, and have their
    # own reasonably sized indices.
    #
    # In Blender, to the best of my knowledge, there's no way to reuse
    # the vertex set between meshes. So we have culling logic instead -
    # for each mesh, only leave vertices that are used for faces.

    ccw = geom.getFieldAsBool('ccw', True, ancestry)
    coord = _coordinate_of(geom)

    if coord is None:
        return None

    if coord.reference and coord.getRealNode().parsed:
        points = coord.getRealNode().parsed
        # We need unflattened coord array here, while
        # importMesh_ReadVertices uses flattened. Can't cache both :(
        # TODO: resolve that somehow, so that vertex set can be effectively
        # reused between different mesh types?
    else:
        points = coord.getFieldAsArray('point', 3, ancestry, conversion_scale)
        if coord.canHaveReferences():
            coord.parsed = points
    index = clean_index_field(geom.getFieldAsArray('coordIndex', 0, ancestry), 'coordIndex')

    while index and index[-1] == -1:
        del index[-1]

    if len(points) >= 2 * len(index):  # Need to cull
        culled_points = []
        cull = {}  # Maps old vertex indices to new ones
        uncull = []  # Maps new indices to the old ones
        new_index = 0
    else:
        uncull = cull = None

    faces = []
    face = []
    past_points = 0
    # Generate faces. Cull the vertices if necessary,
    for i in index:
        if i == -1:
            if face:
                faces.append(flip(face, ccw))
            face = []
        else:
            if cull is not None:
                if not (i in cull):
                    # an index past the points is one vertex at the origin, as validate_points_field reads it on the
                    # uncut path (2.7.3 raised IndexError here: the receipt-to-rule engine's replay, 23 Nov 2026)
                    if i < len(points):
                        culled_points.append(points[i])
                    else:
                        culled_points.append((0.0, 0.0, 0.0))
                        past_points += 1
                    cull[i] = new_index
                    uncull.append(i)
                    i = new_index
                    new_index += 1
                else:
                    i = cull[i]
            face.append(i)
    if face:
        faces.append(flip(face, ccw))  # The last face

    if past_points:
        logger.warning("%d coordIndex value(s) past the %d points; each is read as a vertex at the origin",
                       past_points, len(points))
    if cull:
        points = culled_points

    points = validate_points_field(faces, points)

    bpymesh = bpy.data.meshes.new(name="IndexedFaceSet")
    # With a Normal node the faces must be smooth while the custom normals are set: Blender encodes each custom normal
    # against its corner fan, and a flat face (from_pydata's default since 4.1) is a fan of its own, so every corner of
    # a shared vertex was quantised on its own (up to ~0.04 degree apart) and the re-export split each such vertex.
    # Blender marks the edges sharp itself where the file's normals differ across a vertex.
    try:
        bpymesh.from_pydata(points, [], faces, shade_flat=not geom.getChildBySpec('Normal'))
    except TypeError:  # Blender before 4.1: no shade_flat, faces are smooth
        bpymesh.from_pydata(points, [], faces)
    # No validation here. It throws off the per-face stuff.

    # Similar treatment for normal and color indices

    def processPerVertexIndex(ind):
        if ind:
            # Deflatten into an array of arrays by face; the latter might
            # need to be flipped
            i = 0
            verts_by_face = []
            for f in faces:
                verts_by_face.append(flip(ind[i:i + len(f)], ccw))
                i += len(f) + 1
            return verts_by_face
        elif uncull:
            return [[uncull[v] for v in f] for f in faces]
        else:
            return faces  # Reuse coordIndex, as per the spec

    # Normals
    normals = geom.getChildBySpec('Normal')
    if normals:
        per_vertex = geom.getFieldAsBool('normalPerVertex', True, ancestry)
        vectors = normals.getFieldAsArray('vector', 3, ancestry)
        normal_index = clean_index_field(geom.getFieldAsArray('normalIndex', 0, ancestry), 'normalIndex')
        vectors = pad_values(vectors, _attribute_need(normal_index, index, per_vertex, len(faces)), (0.0, 0.0, 1.0), 'Normal')
        if per_vertex:
            if len(normal_index) == 0:
                normal_index = index
            co = [co for f in processPerVertexIndex(normal_index)
                  for v in f
                  for co in mathutils.Vector(vectors[v]).normalized().to_tuple()]
            bpymesh.vertices.foreach_set("normal", co)

            # Mesh must be validated before assigning normals, but validation might
            # reorder corners. We must store normals in a temporary attribute
            bpymesh.attributes.new("temp_custom_normals", 'FLOAT_VECTOR', 'CORNER')
            bpymesh.attributes["temp_custom_normals"].data.foreach_set("vector", co)
        else:
            co = [co for (i, f) in enumerate(faces)
                  for j in f
                  for co in mathutils.Vector(vectors[normal_index[i] if normal_index else i]).normalized().to_tuple()]
            bpymesh.polygons.foreach_set("normal", co)

    # Apply vertex/face colors
    colors = geom.getChildBySpec(['ColorRGBA', 'Color'])
    if colors:
        if colors.getSpec() == 'ColorRGBA':
            rgb = colors.getFieldAsArray('color', 4, ancestry)
        else:
            # Array of arrays; no need to flatten
            rgb = [c + [1.0] for c in colors.getFieldAsArray('color', 3, ancestry)]

        color_per_vertex = geom.getFieldAsBool('colorPerVertex', True, ancestry)
        color_index = clean_index_field(geom.getFieldAsArray('colorIndex', 0, ancestry), 'colorIndex')
        rgb = pad_values(rgb, _attribute_need(color_index, index, color_per_vertex, len(faces)), [1.0, 1.0, 1.0, 1.0], 'Color')
        has_color_index = len(color_index) != 0
        has_valid_color_index = index.count(-1) == color_index.count(-1)

        # rebuild a corrupted colorIndex field (assuming the end of face markers -1 are missing)
        # this is only needed for vertex colors, for face colors not as each value is its own face
        if color_per_vertex and has_color_index and not has_valid_color_index:
            # remove all -1 beforehand to ensure clean working copy
            color_index = [x for x in color_index if x != -1]
            # copy all -1 from coordIndex to colorIndex
            for i, v in enumerate(index):
                if v == -1:
                    color_index.insert(i, -1)

        if color_per_vertex and has_color_index:  # Color per vertex with index
            cco = [cco for f in processPerVertexIndex(color_index)
                   for v in f
                   for cco in rgb[v]]
        elif color_per_vertex:  # Color per vertex without index
            # use vertex value by default, however if lengths mismatch use the positional value to access rgb value
            # ain't ideal by far, but should most likely work
            try:
                cco = [cco for f in faces
                       for v in f
                       for cco in rgb[v]]
            except IndexError:
                logger.warning("reattempting reading color_per_vertex without index by using positional value because vertex value failed")
                cco = [cco for f in faces
                       for (i, v) in enumerate(f)
                       for cco in rgb[i]]
        elif color_index:  # Color per face with index
            cco = [cco for (i, f) in enumerate(faces)
                   for j in f
                   for cco in rgb[color_index[i]]]
        elif len(faces) > len(rgb):  # Static color per face without index, when all faces have the same color.
            # Exported from SOLIDWORKS, see: `blender/blender-addons#105398`.
            cco = [cco for (i, f) in enumerate(faces)
                   for j in f
                   for cco in rgb[0]]
        else:  # Color per face without index
            cco = [cco for (i, f) in enumerate(faces)
                   for j in f
                   for cco in rgb[i]]

        if color_per_vertex:
            # Mesh must be validated before assigning colors, but validation might
            # reorder corners. We must store colors in a temporary attribute, as they
            # are: they go from sRGB to linear once, when the final attribute is set
            # (converting here too made a Color of 0.5 come out as 0.04, not 0.21)
            set_new_float_color_attribute(bpymesh, cco, name="temp_custom_colors", convert_to_linear=False)
        else:
            set_new_float_color_attribute(bpymesh, cco)

    # Texture coordinates (UVs)
    tex_coord = geom.getChildBySpec('TextureCoordinate')
    if tex_coord:
        tex_coord_points = tex_coord.getFieldAsArray('point', 2, ancestry)
        tex_index = clean_index_field(geom.getFieldAsArray('texCoordIndex', 0, ancestry), 'texCoordIndex')
        tex_coord_points = pad_values(tex_coord_points, _attribute_need(tex_index, index, True, len(faces)), (0.0, 0.0), 'TextureCoordinate')
        tex_index = processPerVertexIndex(tex_index)
        loops = [co for f in tex_index
                 for v in f
                 for co in tex_coord_points[v]]
    else:
        x_min = y_min = z_min = math.inf
        x_max = y_max = z_max = -math.inf
        for f in faces:
            # Unused vertices don't participate in size; X3DOM does so
            for v in f:
                (x, y, z) = points[v]
                x_min = min(x_min, x)
                x_max = max(x_max, x)
                y_min = min(y_min, y)
                y_max = max(y_max, y)
                z_min = min(z_min, z)
                z_max = max(z_max, z)

        mins = (x_min, y_min, z_min)
        deltas = (x_max - x_min, y_max - y_min, z_max - z_min)
        axes = [0, 1, 2]
        axes.sort(key=lambda a: (-deltas[a], a))
        # Tuple comparison breaks ties
        (s_axis, t_axis) = axes[0:2]
        s_min = mins[s_axis]
        ds = deltas[s_axis]
        t_min = mins[t_axis]
        dt = deltas[t_axis]

        # Avoid divide by zero T76303.
        if not (ds > 0.0):
            ds = 1.0
        if not (dt > 0.0):
            dt = 1.0

        def generatePointCoords(pt):
            return (pt[s_axis] - s_min) / ds, (pt[t_axis] - t_min) / dt
        loops = [co for f in faces
                 for v in f
                 for co in generatePointCoords(points[v])]

    importMesh_ApplyTextureToLoops(bpymesh, loops)

    bpymesh.validate(clean_customdata=False)
    if not tex_coord and bpymesh.uv_layers.active is not None:
        default_uv.mark(bpymesh, bpymesh.uv_layers.active)   # the export leaves it out again while untouched

    # Apply normals per vertex
    if normals and per_vertex:
        co2 = [0.0 for x in range(int(len(bpymesh.attributes["temp_custom_normals"].data) * 3))]
        bpymesh.attributes["temp_custom_normals"].data.foreach_get("vector", co2)
        bpymesh.normals_split_custom_set(tuple(zip(*(iter(co2),) * 3)))
        bpymesh.attributes.remove(bpymesh.attributes["temp_custom_normals"])

    # Apply colors per vertex
    if colors and color_per_vertex:
        cco2 = [0.0 for x in range(int(len(bpymesh.attributes["temp_custom_colors"].data) * 4))]
        bpymesh.attributes["temp_custom_colors"].data.foreach_get("color", cco2)
        set_new_float_color_attribute(bpymesh, cco2)
        bpymesh.attributes.remove(bpymesh.attributes["temp_custom_colors"])

    # Remember which Coordinate DEF this mesh was built from, and which point each vertex came from when the
    # vertices were culled, so a ROUTE from a CoordinateInterpolator can find them again (see _import_coordinate_morphs).
    coord_def = coord.getRealNode().getDefName()
    if coord_def:
        bpymesh["x3d_coord_def"] = coord_def
        if uncull:
            bpymesh["x3d_point_map"] = uncull

    bpymesh.update()
    return bpymesh


def importMesh_ElevationGrid(geom, ancestry):
    height = geom.getFieldAsArray('height', 0, ancestry)
    x_dim = budget.count(geom.getFieldAsInt('xDimension', 0, ancestry), "ElevationGrid xDimension")
    x_spacing = geom.getFieldAsFloat('xSpacing', 1, ancestry)
    z_dim = budget.count(geom.getFieldAsInt('zDimension', 0, ancestry), "ElevationGrid zDimension")
    z_spacing = geom.getFieldAsFloat('zSpacing', 1, ancestry)
    ccw = geom.getFieldAsBool('ccw', True, ancestry)
    if not budget.within(x_dim * z_dim, f"ElevationGrid {x_dim} x {z_dim}"):
        return None
    if len(height) < x_dim * z_dim:
        # A grid whose heights come later (a Script or ROUTE into set_height) has none in the file. The missing
        # heights are 0, as X_ITE draws them, instead of the whole import stopping with an IndexError.
        logger.warning("ElevationGrid %d x %d has %d heights; the missing ones are 0", x_dim, z_dim, len(height))
        height = list(height) + [0.0] * (x_dim * z_dim - len(height))

    # The spec assumes a certain ordering of quads; outer loop by z, inner by x
    bpymesh = bpy.data.meshes.new(name="ElevationGrid")
    bpymesh.vertices.add(x_dim * z_dim)
    # Vertex k = z * x_dim + x, the order the faces, the colours and a TextureCoordinate all index by
    # (the loops used to run x outer and z inner, which is only the same order on a square grid).
    co = [w for z in range(z_dim) for x in range(x_dim)
          for w in (x * x_spacing, height[x_dim * z + x], z * z_spacing)]
    bpymesh.vertices.foreach_set("co", co)

    num_polys = (x_dim - 1) * (z_dim - 1)
    bpymesh.loops.add(num_polys * 4)
    bpymesh.polygons.add(num_polys)
    bpymesh.polygons.foreach_set("loop_start", range(0, num_polys * 4, 4))
    # If the ccw is off, we flip the 2nd and the 4th vertices of each face.
    # For quad tessfaces, it was important that the final vertex index was not 0
    # (Blender treated it as a triangle then).
    # So simply reversing the face was not an option.
    # With bmesh polygons, this has no importance anymore, but keep existing code for now.
    verts = [i for x in range(x_dim - 1) for z in range(z_dim - 1)
             for i in (z * x_dim + x,
                       z * x_dim + x + 1 if ccw else (z + 1) * x_dim + x,
                       (z + 1) * x_dim + x + 1,
                       (z + 1) * x_dim + x if ccw else z * x_dim + x + 1)]
    bpymesh.polygons.foreach_set("vertices", verts)

    importMesh_ApplyNormals(bpymesh, geom, ancestry)
    # ApplyColors won't work here; faces are quads, and also per-face
    # coloring should be supported
    colors = geom.getChildBySpec(['ColorRGBA', 'Color'])
    if colors:
        # A FLOAT_COLOR corner attribute holds four floats per corner, so keep the
        # alpha of ColorRGBA and give Color an opaque one (as importMesh_ApplyColors does).
        if colors.getSpec() == 'ColorRGBA':
            rgb = colors.getFieldAsArray('color', 4, ancestry)
        else:
            rgb = [c + [1.0] for c in colors.getFieldAsArray('color', 3, ancestry)]

        # TODO: this can probably be simplified
        if geom.getFieldAsBool('colorPerVertex', True, ancestry):
            # Per-vertex coloring
            # Note the 2/4 flip here
            set_new_float_color_attribute(bpymesh,
                                          [c for x in range(x_dim - 1)
                                           for z in range(z_dim - 1)
                                           for rgb_idx in (z * x_dim + x,
                                                           z * x_dim + x + 1 if ccw else (z + 1) * x_dim + x,
                                                           (z + 1) * x_dim + x + 1,
                                                           (z + 1) * x_dim + x if ccw else z * x_dim + x + 1)
                                           for c in rgb[rgb_idx]])
        else:  # Coloring per face
            set_new_float_color_attribute(bpymesh,
                                          [c for x in range(x_dim - 1)
                                           for z in range(z_dim - 1)
                                           for rgb_idx in (z * (x_dim - 1) + x,) * 4
                                           for c in rgb[rgb_idx]])

    # Textures also need special treatment; it's all quads,
    # and there's a builtin algorithm for coordinate generation
    tex_coord = geom.getChildBySpec('TextureCoordinate')
    if tex_coord:
        uvs = tex_coord.getFieldAsArray('point', 2, ancestry)
    else:
        uvs = [(i / (x_dim - 1), j / (z_dim - 1))
               for j in range(z_dim)
               for i in range(x_dim)]

    d = bpymesh.uv_layers.new().data
    # Rather than repeat the face/vertex algorithm from above, we read
    # the vertex index back from polygon. Might be suboptimal.
    uvs = [i for poly in bpymesh.polygons
           for vidx in poly.vertices
           for i in uvs[vidx]]
    d.foreach_set('uv', uvs)

    bpymesh.validate()
    bpymesh.update()
    if not (colors or tex_coord or geom.getChildBySpec('Normal')):      # children the node could not be written back with
        mark_primitive(bpymesh, geom, ancestry, 'ElevationGrid', xDimension=x_dim, zDimension=z_dim, xSpacing=x_spacing,
                       zSpacing=z_spacing, height=[float(h) for h in height[:x_dim * z_dim]], ccw=ccw,
                       creaseAngle=geom.getFieldAsFloat('creaseAngle', 0.0, ancestry))
    return bpymesh


def geo_system_of(node, ancestry):
    """The geoSystem field of a Geospatial node as a geospatial.GeoSystem (GD WE when it has none)."""
    return geospatial.parse_geo_system(node.getFieldAsMFStringArray('geoSystem', [], ancestry))


def geo_origin_of(node, gs, ancestry):
    """A Geospatial node's geoOrigin as (the origin in geocentric metres, the rotation that aligns the scene with the
    origin's local east/up/south frame or None). X3D 4.0 discourages GeoOrigin (models built on different origins do
    not combine) and X_ITE 16.7.1 still reads it: the node's coordinates become its geocentric ones minus the origin,
    and with rotateYUp turned into that frame."""
    import numpy as np
    child = node.getChildBySpec('GeoOrigin')
    if child is None:
        return np.zeros(3), None
    origin_node = child.getRealNode()
    coords = origin_node.getFieldAsFloatTuple('geoCoords', (0.0, 0.0, 0.0), ancestry)
    origin = np.array(geospatial.to_geocentric(geo_system_of(origin_node, ancestry), *coords))
    frame = None
    if origin_node.getFieldAsBool('rotateYUp', False, ancestry):
        frame = geospatial.local_frame(gs, origin)
    return origin, frame


def geo_to_local(points, origin, frame):
    """Geocentric points (an (n, 3) array or one point) in the coordinates of a node with this geoOrigin."""
    points = points - origin
    return points if frame is None else points @ frame


def importMesh_GeoElevationGrid(geom, ancestry):
    """GeoElevationGrid (X3D 4.0 Geospatial component), as X_ITE 16.7.1 builds it: the grid starts at geoGridOrigin
    and steps xSpacing in longitude (easting) and zSpacing in latitude (northing), the heights times yScale are metres
    along the ellipsoid normal, and every cell is two triangles, SW-NE-NW and SW-SE-NE, facing out of the ellipsoid
    for ccw TRUE."""
    import numpy as np
    gs = geo_system_of(geom, ancestry)
    x_dim = budget.count(geom.getFieldAsInt('xDimension', 0, ancestry), "GeoElevationGrid xDimension")
    z_dim = budget.count(geom.getFieldAsInt('zDimension', 0, ancestry), "GeoElevationGrid zDimension")
    if x_dim < 2 or z_dim < 2:
        return None   # a grid with no cell has nothing to draw
    if not budget.within(x_dim * z_dim, f"GeoElevationGrid {x_dim} x {z_dim}"):
        return None
    height = geom.getFieldAsArray('height', 0, ancestry)
    if len(height) < x_dim * z_dim:
        logger.warning("GeoElevationGrid %d x %d has %d heights; the missing ones are 0", x_dim, z_dim, len(height))
    y_scale = geom.getFieldAsFloat('yScale', 1.0, ancestry)
    ccw = geom.getFieldAsBool('ccw', True, ancestry)

    # float64 all the way to the vertices, which Blender keeps in float32: 0.5 m apart at the Earth's radius
    points = geospatial.grid_points(
        gs, geom.getFieldAsFloatTuple('geoGridOrigin', (0.0, 0.0, 0.0), ancestry), x_dim, z_dim,
        geom.getFieldAsFloat('xSpacing', 1.0, ancestry), geom.getFieldAsFloat('zSpacing', 1.0, ancestry),
        np.asarray(height, dtype=np.float64) * y_scale)
    origin, frame = geo_origin_of(geom, gs, ancestry)
    points = geo_to_local(points, origin, frame) * conversion_scale

    bpymesh = bpy.data.meshes.new(name="GeoElevationGrid")
    bpymesh.vertices.add(len(points))
    bpymesh.vertices.foreach_set("co", points.astype(np.float32).ravel())

    # p1 - p4 (z, x) .. (z, x+1)   Cell (x, z) is two triangles p1 p3 p2 and p1 p4 p3, in rows of z. The x and z
    # | \ |      axes run east and north here (they run east and south in an ElevationGrid), so the same corner
    # p2 - p3     order faces up the other way round.
    cells = (np.arange(z_dim - 1)[:, None] * x_dim + np.arange(x_dim - 1)[None, :]).ravel()
    p1, p2, p3, p4 = cells, cells + x_dim, cells + x_dim + 1, cells + 1
    corners = np.stack((p1, p3, p2, p1, p4, p3) if ccw else (p1, p2, p3, p1, p3, p4), axis=1).reshape(-1)
    num_polys = len(cells) * 2
    cell_of_corner = np.repeat(np.arange(len(cells)), 6)   # a colour per face is one per cell
    bpymesh.loops.add(num_polys * 3)
    bpymesh.polygons.add(num_polys)
    bpymesh.polygons.foreach_set("loop_start", range(0, num_polys * 3, 3))
    bpymesh.polygons.foreach_set("vertices", corners)
    bpymesh.update(calc_edges=True)

    colors = geom.getChildBySpec(['ColorRGBA', 'Color'])
    if colors:
        if colors.getSpec() == 'ColorRGBA':
            rgb = np.array(colors.getFieldAsArray('color', 4, ancestry), dtype=np.float64).reshape(-1, 4)
        else:
            rgb = np.array([c + [1.0] for c in colors.getFieldAsArray('color', 3, ancestry)], dtype=np.float64)
        per_vertex = geom.getFieldAsBool('colorPerVertex', True, ancestry)
        if len(rgb) >= (len(points) if per_vertex else len(cells)):
            set_new_float_color_attribute(bpymesh, rgb[corners if per_vertex else cell_of_corner].ravel().tolist())
        else:
            logger.warning("GeoElevationGrid has %d colours for %d %s; they are left out", len(rgb),
                           len(points) if per_vertex else len(cells), "vertices" if per_vertex else "cells")

    uvs = None
    tex_coord = geom.getChildBySpec('TextureCoordinate')
    if tex_coord:
        uvs = np.array(tex_coord.getFieldAsArray('point', 2, ancestry), dtype=np.float64).reshape(-1, 2)
        if len(uvs) < len(points):
            logger.warning("GeoElevationGrid has %d texture coordinates for %d vertices; the default ones are used",
                           len(uvs), len(points))
            uvs = None
    if uvs is None:   # X3D's default: S across the longitude (x) direction, T up the latitude (z) one
        zz, xx = np.divmod(np.arange(len(points)), x_dim)
        uvs = np.column_stack((xx / (x_dim - 1), zz / (z_dim - 1)))
    importMesh_ApplyTextureToLoops(bpymesh, uvs[corners].ravel())

    normals = geom.getChildBySpec('Normal')
    if normals:
        vectors = np.array(normals.getFieldAsArray('vector', 3, ancestry), dtype=np.float64).reshape(-1, 3)
        per_vertex = geom.getFieldAsBool('normalPerVertex', True, ancestry)
        if len(vectors) >= (len(points) if per_vertex else len(cells)):
            lengths = np.linalg.norm(vectors, axis=1)
            vectors = vectors / np.where(lengths > 0.0, lengths, 1.0)[:, None]
            bpymesh.normals_split_custom_set(vectors[corners if per_vertex else cell_of_corner].tolist())
        else:
            logger.warning("GeoElevationGrid has %d normals for %d %s; they are left out", len(vectors),
                           len(points) if per_vertex else len(cells), "vertices" if per_vertex else "cells")

    bpymesh.update()
    # written back as a GeoElevationGrid while unedited (extract.primitive_for_mesh), its fields as the file wrote them,
    # when nothing the record cannot carry is there: a unit scale, no Color, Normal or TextureCoordinate child
    if conversion_scale == 1.0 and getattr(geom.getRealNode(), "x3dNode", None) is not None and not any(
            geom.getChildBySpec(child) is not None for child in ('Color', 'ColorRGBA', 'Normal', 'TextureCoordinate')):
        fields = raw_fields(geom, GEO_GRID_FIELDS)
        origin = geom.getChildBySpec('GeoOrigin')
        if origin is not None:
            fields["geoOrigin"] = raw_fields(origin, GEO_ORIGIN_FIELDS)
        mark_primitive(bpymesh, geom, ancestry, 'GeoElevationGrid', **fields)
    return bpymesh


GEO_GRID_FIELDS = ('geoSystem', 'geoGridOrigin', 'xDimension', 'zDimension', 'xSpacing', 'zSpacing', 'yScale', 'height',
                   'ccw', 'creaseAngle')


def importMesh_Extrusion(geom, ancestry):
    # Interestingly, the spec doesn't allow for vertex/face colors in this
    # element, nor for normals.
    # Since coloring and normals are not supported here, and also large
    # polygons for caps might be required, we shall use from_pydata().

    ccw = geom.getFieldAsBool('ccw', True, ancestry)
    begin_cap = geom.getFieldAsBool('beginCap', True, ancestry)
    end_cap = geom.getFieldAsBool('endCap', True, ancestry)
    # what the export writes back while the mesh is unedited (mark_primitive, extract.primitive_for_mesh)
    extrusion_fields = {
        "crossSection": [list(map(float, c)) for c in geom.getFieldAsArray('crossSection', 2, ancestry)],
        "spine": [list(map(float, s)) for s in geom.getFieldAsArray('spine', 3, ancestry)],
        "scale": [list(map(float, s)) for s in geom.getFieldAsArray('scale', 2, ancestry)],
        "orientation": [list(map(float, o)) for o in geom.getFieldAsArray('orientation', 4, ancestry)],
        "beginCap": begin_cap, "endCap": end_cap, "ccw": ccw,
        "convex": geom.getFieldAsBool('convex', True, ancestry),
        "creaseAngle": geom.getFieldAsFloat('creaseAngle', 0.0, ancestry),
    }
    cross = geom.getFieldAsArray('crossSection', 2, ancestry)
    if not cross:
        cross = ((1, 1), (1, -1), (-1, -1), (-1, 1), (1, 1))
    spine = geom.getFieldAsArray('spine', 3, ancestry)
    if not spine:
        spine = ((0, 0, 0), (0, 1, 0))
    orient = geom.getFieldAsArray('orientation', 4, ancestry)
    if orient:
        orient = [Quaternion(o[:3], o[3]).to_matrix()
                  if o[3] else None for o in orient]
    scale = geom.getFieldAsArray('scale', 2, ancestry)
    if scale:
        scale = [Matrix(((s[0], 0, 0), (0, 1, 0), (0, 0, s[1])))
                 if s[0] != 1 or s[1] != 1 else None for s in scale]

    # Special treatment for the closed spine and cross section.
    # Let's save some memory by not creating identical but distinct vertices;
    # later we'll introduce conditional logic to link the last vertex with
    # the first one where necessary.
    cross_closed = cross[0] == cross[-1]
    if cross_closed:
        cross = cross[:-1]
    nc = len(cross)
    cross = [Vector((c[0], 0, c[1])) for c in cross]
    ncf = nc if cross_closed else nc - 1
    # Face count along the cross; for closed cross, it's the same as the
    # respective vertex count

    spine_closed = spine[0] == spine[-1]
    if spine_closed:
        spine = spine[:-1]
    ns = len(spine)
    spine = [Vector(s) for s in spine]
    nsf = ns if spine_closed else ns - 1
    # fill up scale with the last value of scale if the length is different to spine to prevent index error later on
    # as extrusion works by mapping scale values to the spine values
    # https://projects.blender.org/extensions/io_scene_x3d/issues/29
    if scale:
        while len(scale) < len(spine):
            scale.append(scale[-1])

    # This will be used for fallback, where the current spine point joins
    # two collinear spine segments. No need to recheck the case of the
    # closed spine/last-to-first point juncture; if there's an angle there,
    # it would kick in on the first iteration of the main loop by spine.
    def findFirstAngleNormal():
        for i in range(1, ns - 1):
            spt = spine[i]
            z = (spine[i + 1] - spt).cross(spine[i - 1] - spt)
            if z.length > EPSILON:
                return z
        # All the spines are collinear. Fallback to the rotated source
        # XZ plane.
        # TODO: handle the situation where the first two spine points match
        v = spine[1] - spine[0]
        orig_y = Vector((0, 1, 0))
        orig_z = Vector((0, 0, 1))
        if v.cross(orig_y).length >= EPSILON:
            # Spine at angle with global y - rotate the z accordingly
            orig_z.rotate(orig_y.rotation_difference(v))
        return orig_z

    verts = []
    z = None
    for i, spt in enumerate(spine):
        if (i > 0 and i < ns - 1) or spine_closed:
            snext = spine[(i + 1) % ns]
            sprev = spine[(i - 1 + ns) % ns]
            y = snext - sprev
            vnext = snext - spt
            vprev = sprev - spt
            try_z = vnext.cross(vprev)
            # Might be zero, then all kinds of fallback
            if try_z.length > EPSILON:
                if z is not None and try_z.dot(z) < 0:
                    try_z.negate()
                z = try_z
            elif not z:  # No z, and no previous z.
                # Look ahead, see if there's at least one point where
                # spines are not collinear.
                z = findFirstAngleNormal()
        elif i == 0:  # And non-crossed
            snext = spine[i + 1]
            y = snext - spt
            z = findFirstAngleNormal()
        else:  # last point and not crossed
            sprev = spine[i - 1]
            y = spt - sprev
            # If there's more than one point in the spine, z is already set.
            # One point in the spline is an error anyway.

        x = y.cross(z)
        m = Matrix(((x.x, y.x, z.x), (x.y, y.y, z.y), (x.z, y.z, z.z)))
        # Columns are the unit vectors for the xz plane for the cross-section
        m.normalize()
        if orient:
            mrot = orient[i] if len(orient) > 1 else orient[0]
            if mrot:
                m @= mrot  # Not sure about this. Counterexample???
        if scale:
            mscale = scale[i] if len(scale) > 1 else scale[0]
            if mscale:
                m @= mscale
                # First the cross-section 2-vector is scaled,
                # then applied to the xz plane unit vectors
        for cpt in cross:
            verts.append((spt + m @ cpt).to_tuple())
            # Could've done this with a single 4x4 matrix... Oh well

    # The method from_pydata() treats correctly quads with final vertex
    # index being zero.
    # So we just flip the vertices if ccw is off.

    faces = []
    if begin_cap:
        faces.append(flip([x for x in range(nc - 1, -1, -1)], ccw))

    # Order of edges in the face: forward along cross, forward along spine,
    # backward along cross, backward along spine, flipped if now ccw.
    # This order is assumed later in the texture coordinate assignment;
    # please don't change without syncing.

    faces += [flip((
        s * nc + c,
        s * nc + (c + 1) % nc,
        (s + 1) * nc + (c + 1) % nc,
        (s + 1) * nc + c), ccw) for s in range(ns - 1) for c in range(ncf)]

    if spine_closed:
        # The faces between the last and the first spine points
        b = (ns - 1) * nc
        faces += [flip((
            b + c,
            b + (c + 1) % nc,
            (c + 1) % nc,
            c), ccw) for c in range(ncf)]

    if end_cap:
        faces.append(flip([(ns - 1) * nc + x for x in range(0, nc)], ccw))

    bpymesh = bpy.data.meshes.new(name="Extrusion")
    bpymesh.from_pydata(verts, [], faces)

    # The way we deal with textures in triangular meshes doesn't apply.
    # The structure of the loop array goes: cap, side, cap
    if begin_cap or end_cap:  # Need dimensions
        x_min = x_max = z_min = z_max = None
        for c in cross:
            (x, z) = (c.x, c.z)
            if x_min is None or x < x_min:
                x_min = x
            if x_max is None or x > x_max:
                x_max = x
            if z_min is None or z < z_min:
                z_min = z
            if z_max is None or z > z_max:
                z_max = z
        dx = x_max - x_min
        dz = z_max - z_min
        cap_scale = dz if dz > dx else dx

    # Takes an index in the cross array, returns scaled
    # texture coords for cap texturing purposes
    def scaledLoopVertex(i):
        c = cross[i]
        return (c.x - x_min) / cap_scale, (c.z - z_min) / cap_scale

    # X3DOM uses raw cap shape, not a scaled one. So we will, too.

    loops = []
    mloops = bpymesh.loops
    if begin_cap:  # vertex indices match the indices in cross
        # Rely on the loops in the mesh; don't repeat the face
        # generation logic here
        loops += [co for i in range(nc)
                  for co in scaledLoopVertex(mloops[i].vertex_index)]

    # Sides
    # Same order of vertices as in face generation
    # We don't rely on the loops in the mesh; instead,
    # we repeat the face generation logic.
    loops += [co for s in range(nsf)
              for c in range(ncf)
              for v in flip(((c / ncf, s / nsf),
                             ((c + 1) / ncf, s / nsf),
                             ((c + 1) / ncf, (s + 1) / nsf),
                             (c / ncf, (s + 1) / nsf)), ccw) for co in v]

    if end_cap:
        # Base loop index for end cap
        lb = ncf * nsf * 4 + (nc if begin_cap else 0)
        # Rely on the loops here too.
        loops += [co for i in range(nc) for co
                  in scaledLoopVertex(mloops[lb + i].vertex_index % nc)]
    importMesh_ApplyTextureToLoops(bpymesh, loops)

    bpymesh.validate()
    bpymesh.update()
    mark_primitive(bpymesh, geom, ancestry, 'Extrusion', **extrusion_fields)
    return bpymesh


# -----------------------------------------------------------------------------------
# Line and point sets


def _coloured_line_mesh(name, polylines):
    """A mesh of loose edges for polylines [(points, rgba per point)], each polyline with its own vertices, and the
    colours as the LINE_COLOUR_ATTRIBUTE. Blender curves have no per-vertex colour, and only a mesh's colour attribute
    reaches the glTF (COLOR_0)."""
    verts, edges, colours = [], [], []
    for points, rgba in polylines:
        if len(points) < 2:
            continue
        base = len(verts)
        verts.extend(tuple(p[:3]) for p in points)
        colours.extend(rgba)
        edges.extend((base + i, base + i + 1) for i in range(len(points) - 1))
    if not edges:
        return None
    bpymesh = bpy.data.meshes.new(name)
    bpymesh.from_pydata(verts, edges, [])
    return bpymesh, colours


def importMesh_LineSet(geom, ancestry):
    # TODO: line display properties are ignored
    coord = _coordinate_of(geom)
    if coord is None:
        return None
    src_points = coord.getFieldAsArray('point', 3, ancestry, conversion_scale)
    colours, kind = x3d_point_colours(geom, ancestry)
    counts = [int(n) for n in geom.getFieldAsArray('vertexCount', 0, ancestry)]
    if kind and len(colours) >= sum(counts):
        # X3D LineSet colours are per vertex, in coordinate order
        polylines, b = [], 0
        for n in counts:
            polylines.append((src_points[b:b + n], colours[b:b + n]))
            b += n
        made = _coloured_line_mesh("LineSet", polylines)
        if made is not None:
            set_point_colours(made[0], made[1], kind)
            made[0]["x3d_geometry"] = "LineSet"     # written back as one by the X3D 4.0 export (node board batch 8)
            made[0].update()
            return made[0]
    elif kind:
        logger.warning("LineSet: %d colours for %d vertices; colours not imported", len(colours), sum(counts))
    # Array of 3; Blender needs arrays of 4
    bpycurve = bpy.data.curves.new("LineSet", 'CURVE')
    bpycurve.dimensions = '3D'
    counts = geom.getFieldAsArray('vertexCount', 0, ancestry)
    b = 0
    for n in counts:
        sp = bpycurve.splines.new('POLY')
        sp.points.add(n - 1)  # points already has one element

        def points():
            for x in src_points[b:b + n]:
                yield x[0]
                yield x[1]
                yield x[2]
                yield 0
        sp.points.foreach_set('co', [x for x in points()])
        b += n
    bpycurve["x3d_geometry"] = "LineSet"     # written back as one by the X3D 4.0 export (node board batch 8)
    return bpycurve


def _indexed_line_colours(geom, ancestry, points, lines, colours):
    """The coloured mesh of an IndexedLineSet, or None (with a warning) when its colour indices don't fit.

    colorPerVertex TRUE (the default): colorIndex, laid out like coordIndex, else coordIndex, picks each vertex's
    colour. FALSE: colorIndex[i], else i, picks polyline i's colour (X3D 4.0, 11.4.5)."""
    per_vertex = geom.getFieldAsBool('colorPerVertex', True, ancestry)
    color_index = [int(i) for i in geom.getFieldAsArray('colorIndex', 0, ancestry)]
    polylines = []
    try:
        if per_vertex:
            if color_index:
                runs, run = [], []
                for i in color_index:
                    if i < 0:
                        runs.append(run)
                        run = []
                    else:
                        run.append(i)
                runs.append(run)
            else:
                runs = lines
            for line, run in zip(lines, runs):
                if len(run) < len(line):
                    raise IndexError("colorIndex is shorter than coordIndex")
                polylines.append(([points[i] for i in line], [colours[c] for c in run[:len(line)]]))
        else:
            for n, line in enumerate(l for l in lines if l):
                c = colours[color_index[n] if color_index else n]
                polylines.append(([points[i] for i in line], [c] * len(line)))
    except IndexError as exc:
        logger.warning("IndexedLineSet: colours not imported (%s)", exc)
        return None
    return _coloured_line_mesh('IndexedLineSet', polylines)


def importMesh_IndexedLineSet(geom, ancestry):
    # VRML not x3d
    # coord = geom.getChildByName('coord') # 'Coordinate'
    coord = _coordinate_of(geom)  # works for x3d and vrml
    if coord:
        points = coord.getFieldAsArray('point', 3, ancestry, conversion_scale)
    else:
        points = []

    if not points:
        logger.warning('Warning: IndexedLineSet had no points')
        return None

    ils_lines = geom.getFieldAsArray('coordIndex', 0, ancestry)

    lines = []
    line = []

    for il in ils_lines:
        if il == -1:
            lines.append(line)
            line = []
        else:
            line.append(int(il))
    lines.append(line)

    colours, kind = x3d_point_colours(geom, ancestry)
    if kind:
        made = _indexed_line_colours(geom, ancestry, points, lines, colours)
        if made is not None:
            bpymesh, rgba = made
            set_point_colours(bpymesh, rgba, kind)
            bpymesh.update()
            return bpymesh

    bpycurve = bpy.data.curves.new('IndexedCurve', 'CURVE')
    bpycurve.dimensions = '3D'

    for line in lines:
        if not line:
            continue
        # co = points[line[0]]  # UNUSED
        nu = bpycurve.splines.new('POLY')
        nu.points.add(len(line) - 1)  # the new nu has 1 point to begin with
        missing_point = False
        for il, pt in zip(line, nu.points):
            try:
                pt.co[0:3] = points[il]
            except IndexError:
                missing_point = True
                pass
        if missing_point:
            logger.warning("More coordIndex than points found")

    return bpycurve


def importMesh_PointSet(geom, ancestry):
    # VRML not x3d
    coord = _coordinate_of(geom)  # works for x3d and vrml
    if coord:
        points = coord.getFieldAsArray('point', 3, ancestry, conversion_scale)
    else:
        points = []

    bpymesh = bpy.data.meshes.new("PointSet")
    bpymesh.vertices.add(len(points))
    bpymesh.vertices.foreach_set("co", [a for v in points for a in v])

    colours, kind = x3d_point_colours(geom, ancestry)      # one colour per point
    if kind and len(colours) >= len(points):
        set_point_colours(bpymesh, colours[:len(points)], kind)
    elif kind:
        logger.warning("PointSet: %d colours for %d points; colours not imported", len(colours), len(points))

    # No need to validate
    bpymesh.update()
    return bpymesh


# -----------------------------------------------------------------------------------
# Primitives
# SA: they used to use bpy.ops for primitive creation. That was
# unbelievably slow on complex scenes. I rewrote to generate meshes
# by hand.


GLOBALS['CIRCLE_DETAIL'] = 12

# X3D draws these as smooth curved surfaces (the segment count is the browser's choice, not part of the scene), so the
# importer shades them smooth: Sphere everywhere, Cylinder and Cone on the side while their flat caps keep their own
# normal. Before this they came in faceted (no creaseAngle field, so every face was flat), and Cycles, Eevee and the
# glTF that Unreal and Babylon.js read all showed the facets.
SMOOTH_PRIMITIVES = frozenset({'Sphere', 'Cylinder', 'Cone'})
CIRCLE_DIV_RANGE = (3, 512)


# X_ITE and Castle Game Engine, by default (their LINEAR_WHEN_PHYSICAL_MATERIAL colour space), draw the colours of a
# Material, TwoSidedMaterial and UnlitMaterial as sRGB values and those of a PhysicalMaterial as linear ones. Blender,
# glTF and Unreal read every material colour as linear. 'AS_IS' passes X3D colours through unchanged (this importer's
# behaviour so far); 'SRGB' converts the classic materials' colours from sRGB to linear, so Blender and every glTF
# viewer show what X_ITE shows. Measured on 12 Nov 2026 (X_ITE 16.7, Babylon.js 9.32, headless Chrome): an
# emissiveColor of 0.5 is 128 in X_ITE, 186 in Babylon.js from the glb made as is, 128 from the glb made with SRGB.
# Color and ColorRGBA values are converted under SRGB unless the shape uses a PhysicalMaterial, and kept under AS_IS,
# the same rule the export applies (_vertex_colours_are_display), so an import and an export with the same colour
# space round-trip.
COLOUR_SPACES = ('AS_IS', 'SRGB')
COLOUR_SPACE_ALIASES = {"X_ITE": "SRGB", "XITE": "SRGB", "LINEAR_WHEN_PHYSICAL_MATERIAL": "SRGB", "LINEAR": "AS_IS",
                        "NONE": "AS_IS", "AUTO": ""}
colour_space = 'SRGB'


def resolve_colour_space(value=None, default='SRGB'):
    """The import option when given (not AUTO), else the BLENDER_X3D_COLOR_SPACE environment variable (for headless
    pipelines), else `default`: 'SRGB', the way X_ITE and Castle read classic colours (measured in both, Nov 2026).
    'X_ITE' is accepted for 'SRGB'."""
    raw = COLOUR_SPACE_ALIASES.get(str(value or "").strip().upper(), str(value or "").strip().upper())
    if not raw:
        env = os.environ.get("BLENDER_X3D_COLOR_SPACE", "").strip().upper()
        raw = COLOUR_SPACE_ALIASES.get(env, env) or default
    if raw not in COLOUR_SPACES:
        logger.warning("ImportX3D: colour space %r is not one of %s; using %s", raw, ", ".join(COLOUR_SPACES), default)
        return default
    return raw


def classic_colour(rgb):
    """A Material, TwoSidedMaterial or UnlitMaterial colour as Blender should hold it (see COLOUR_SPACES)."""
    rgb = [float(c) for c in list(rgb)[:3]]
    if colour_space == 'SRGB':
        return [srgb_to_linear(max(0.0, c)) for c in rgb]
    return rgb


# Light units. X3D gives a light an intensity, not watts or candela, and X_ITE 16.7.1 draws it in two ways (measured
# 12 Nov 2026 in headless Chrome 153, SwiftShader, against Babylon.js 9.32 on the glb):
#  - a PhysicalMaterial is lit the glTF way: i x attenuation(d) / d^2, the colour / pi, in linear space;
#  - a Material or TwoSidedMaterial is lit the classic way: i x attenuation(d), with no 1/d^2 (the default
#    attenuation 1 0 0 does not fall off at all), in display space (an sRGB 0.8 lit at i = 1 shows as 204).
# glTF (KHR_lights_punctual), Blender, Babylon.js and Unreal light every surface the first way.
# 'BLENDER' is this importer's scale so far: point and spot lights get 1.75 W per unit of intensity (the exporters'
# round trip), suns 1 W/m2. Through a COMPAT glTF that is 0.139 cd per unit, so a PointLight of 1 is 7.2 times too
# dark on a PhysicalMaterial, and a classic scene lit at 1 shows 120 where X_ITE shows 204.
# 'X_ITE' gives each light the glTF intensity that draws what X_ITE draws (see finalize_light_units): exact for a
# PhysicalMaterial lit by a point or spot light without attenuation, and at one reference distance otherwise.
# The scale is kept on each light (x3d_energy_per_intensity), so both X3D exports still write the file's intensity.
LIGHT_UNITS = ('BLENDER', 'X_ITE')
LIGHT_UNITS_ALIASES = {"LEGACY": "BLENDER", "AS_IS": "BLENDER", "XITE": "X_ITE", "X3D": "X_ITE", "BROWSER": "X_ITE",
                       "AUTO": ""}
lighting_units = 'BLENDER'   # the resolved light_units of the import in progress
# Filled while a file (and its Inlines) is read, used by finalize_light_units once the whole import is in.
# radius is the file's (X3D units, -1 for unlimited); frame is the Blender length of one unit of the light's own X3D
# frame (the file unit times its Transforms' scale), the frame X_ITE measures the light's distances in.
imported_lights = []   # (light object, X3D node type, intensity, attenuation, radius, frame)
lit_surfaces = []      # (mesh object, 'classic' or 'physical', a classic Material's diffuseColor, its emissiveColor)
lit_by_node = {}       # Shape node -> ('classic' or 'physical', diffuseColor, emissiveColor), so each USE counts too
navigation_headlight = None   # the first NavigationInfo's headlight (X3D's default, and a browser's, is on)
bound_view = None   # the first Viewpoint's camera, the one a browser binds first (None when the file has none)
default_view = None   # X3D's default view (0 0 10, looking down -z) in Blender, for a file without a Viewpoint


def resolve_light_units(value=None, colour=None, default='BLENDER'):
    """The import option when given (not AUTO), else the BLENDER_X3D_LIGHT_UNITS environment variable, else the
    colour space's partner: 'X_ITE' when the colours are read as X_ITE reads them (SRGB), else `default`."""
    raw = LIGHT_UNITS_ALIASES.get(str(value or "").strip().upper(), str(value or "").strip().upper())
    if not raw:
        env = os.environ.get("BLENDER_X3D_LIGHT_UNITS", "").strip().upper()
        raw = LIGHT_UNITS_ALIASES.get(env, env) or ('X_ITE' if colour == 'SRGB' else default)
    if raw not in LIGHT_UNITS:
        logger.warning("ImportX3D: light units %r are not one of %s; using %s", raw, ", ".join(LIGHT_UNITS), default)
        return default
    return raw


def x3d_attenuation_factor(attenuation, distance):
    """X3D's attenuation at a distance: 1 / max(a0 + a1 d + a2 d^2, 1) (X3D 4.0, 17.2.2.4)."""
    a0, a1, a2 = (list(attenuation) + [0.0, 0.0, 0.0])[:3] if attenuation else (1.0, 0.0, 0.0)
    return 1.0 / max(a0 + a1 * distance + a2 * distance * distance, 1.0)


MIN_REFERENCE_DISTANCE = 1e-3   # Blender units; a light touching a surface is matched there


def _box_distance(point, lo, hi):
    """Distance from a point to an axis-aligned box (0 inside it), and the distance to its nearest face from inside."""
    outside = Vector(tuple(max(lo[i] - point[i], 0.0, point[i] - hi[i]) for i in range(3)))
    inside = min(min(point[i] - lo[i], hi[i] - point[i]) for i in range(3))
    return outside.length, inside


def reference_distance(origin, radius, surfaces, axis=None, cut_off=None):
    """The distance at which a point or spot light is matched (Blender units), or None when it reaches nothing:
    the median distance from the light to the surfaces it reaches. A surface counts at its bounding-box centre, or,
    when the light is within its bounding sphere (above a large floor), at the nearest point of its box, so the shape
    is not matched at its far corner. A surface whose box holds the light (a bulb around it, the room it is in)
    counts, at its nearest face, only when nothing else is in reach. Surfaces beyond the radius (None: unlimited)
    or outside a spot light's cone are skipped. `surfaces` holds (centre, half diagonal, box min, box max)."""
    distances, enclosing = [], []
    for centre, half, lo, hi in surfaces:
        offset = centre - origin
        distance = offset.length
        near, face = _box_distance(origin, lo, hi)
        if radius is not None and near > radius:
            continue
        if axis is not None and cut_off is not None and distance > half and \
                offset.normalized().dot(axis) < math.cos(min(cut_off, math.pi / 2.0)):
            continue
        if near <= 0.0:
            enclosing.append(max(face, MIN_REFERENCE_DISTANCE))
        elif distance < half:
            distances.append(max(near, MIN_REFERENCE_DISTANCE))
        else:
            distances.append(distance)
    distances = distances or enclosing
    if not distances:
        return None
    distances.sort()
    middle = len(distances) // 2
    return distances[middle] if len(distances) % 2 else 0.5 * (distances[middle - 1] + distances[middle])



def range_window(distance, reach):
    """The range window a glTF viewer draws a light's range with: clamp(1 - (d / r)^4, 0, 1)^2, as Babylon.js 9.32
    does (computeDistanceLightFalloff_GLTF in babylon.max.js squares saturate(1 - factor^2), factor = d^2 / r^2);
    KHR_lights_punctual's recommended formula, which X_ITE's PhysicalMaterial applies (getRangeAttenuation,
    x_ite.js line 67903), is the unsquared window. 1 when the light has no range. Works on numpy arrays too."""
    if reach is None or reach <= 0.0:
        return 1.0
    window = 1.0 - (distance / reach) ** 4
    if isinstance(window, float):
        return max(0.0, min(1.0, window)) ** 2
    import numpy as np
    return np.clip(window, 0.0, 1.0) ** 2


VIEW_SAMPLES = 64   # rays per side of the square grid the classic light fit casts from the first Viewpoint


def _view_samples(surfaces, camera, view):
    """What the first Viewpoint sees of the lit classic surfaces, as numpy arrays (world points, unit normals turned
    towards the view, weights, sRGB diffuse and emissive colours side by side), or None: a ray through each cell of a square grid over the view
    (the square X3D's fieldOfView spans) stops at the first surface it meets, so hidden faces, and pixels of lines,
    text, emissive-only and physical shapes, do not count. `camera` is the bound Viewpoint's camera, else `view` the
    world matrix of X3D's default view (fieldOfView pi / 4). Either is used without its scale (a Viewpoint under a
    scaled Transform sees what the same camera unscaled sees, as Blender views through it)."""
    import numpy as np
    try:
        scene = bpy.context.scene
        depsgraph = bpy.context.evaluated_depsgraph_get()
    except (AttributeError, RuntimeError):
        return None
    diffuse_of = {}
    for bpyob, model, diffuse, glow in surfaces:
        try:
            if model == 'classic' and diffuse is not None and not bpyob.hide_render:
                albedo = 0.2126 * diffuse[0] + 0.7152 * diffuse[1] + 0.0722 * diffuse[2]
                if albedo > 0.02:   # black, emissive-only: not lit
                    diffuse_of[bpyob.name] = tuple(min(max(float(channel), 0.0), 1.0)
                                                   for channel in tuple(diffuse[:3]) + tuple((glow or (0.0,) * 3)[:3]))
        except ReferenceError:
            continue
    if not diffuse_of:
        return None
    try:
        if camera is not None:
            matrix = camera.matrix_world.normalized()
            corner = camera.data.view_frame(scene=scene)[0]
            half, depth = min(abs(corner.x), abs(corner.y)), abs(corner.z)
        elif view is not None:
            matrix, half, depth = view.normalized(), math.tan(0.785398 / 2.0), 1.0
        else:
            return None
    except ReferenceError:
        return None
    origin = matrix.translation.copy()
    turn = matrix.to_3x3()
    points, normals, colours = [], [], []
    steps = [(index + 0.5) / VIEW_SAMPLES * 2.0 - 1.0 for index in range(VIEW_SAMPLES)]
    for v in steps:
        for u in steps:
            direction = (turn @ Vector((u * half, v * half, -depth))).normalized()
            start = origin
            for _ in range(8):   # pass through objects a render leaves out
                hit, location, normal, _face, hit_object, _matrix = scene.ray_cast(depsgraph, start, direction)
                if not hit:
                    break
                original = getattr(hit_object, 'original', hit_object)
                if original.hide_render:
                    start = location + direction * 1e-4
                    continue
                colour = diffuse_of.get(original.name)
                if colour is not None:
                    normal = normal.normalized()
                    if normal.dot(direction) > 0.0:   # seen from behind: lit on that side, as X3D lights solid FALSE
                        normal = -normal
                    points.append(tuple(location))
                    normals.append(tuple(normal))
                    colours.append(colour)
                break
    if not points:
        return None
    count = len(points)
    return (np.array(points, dtype=float), np.array(normals, dtype=float), np.ones(count) / count,
            np.array(colours, dtype=float))


def _x_ite_spot_factor(cosine, cut_off, beam):
    """How much of a classic SpotLight X_ITE 16.7.1 draws in a direction at `cosine` from its axis (getSpotFactor,
    x_ite.js line 66744): 0 from the cut-off out, 1 within the beam, and between them linear in the angle,
    (angle - cutOffAngle) / (beamWidth - cutOffAngle); the cut-off is clamped to [0, pi / 2] and the beam to the
    cut-off (SpotLight getCutOffAngle and getBeamWidth, x_ite.js lines 83041-83054)."""
    import numpy as np
    cut_off = min(max(cut_off, 0.0), math.pi / 2.0)
    beam = min(max(beam, 0.0), cut_off)
    angle = np.arccos(np.clip(cosine, -1.0, 1.0))
    if cut_off - beam <= 1e-9:
        return (angle < cut_off).astype(float)
    return np.clip((angle - cut_off) / (beam - cut_off), 0.0, 1.0)


def _gltf_spot_factor(cosine, cut_off, beam):
    """How much of a KHR_lights_punctual spot light a glTF viewer draws at `cosine` from its axis, with the cut-off as
    outerConeAngle and the beam as innerConeAngle (what the glTF exporter writes): t^2, t = clamp((cos - cos outer) /
    max(0.001, cos inner - cos outer), 0, 1), as Babylon.js 9.32 does (computeDirectionalLightFalloff_GLTF with
    SpotLight _computeAngleValues, babylon.max.js) and the extension's sample code."""
    import numpy as np
    outer, inner = math.cos(cut_off), math.cos(min(beam, cut_off))
    t = np.clip((cosine - outer) / max(0.001, inner - outer), 0.0, 1.0)
    return t * t


def fit_classic_lights(faces, lights, headlight, view, srgb):
    """Fit a classic scene's lights to what X_ITE draws on the faces seen from the first Viewpoint, or None when no
    face is lit. Per colour channel, X = min(e + b L, 1) is X_ITE's display-space value on a face (e and b its sRGB
    emissive and diffuse colours, L the sum of i x color x attenuation(d / s) x cos x spot of the lights that reach it,
    spot X_ITE's, linear in the angle (see _x_ite_spot_factor), plus the headlight's cos when it is on) and
    G = srgb(min(E' + B E / pi, 1)) a glTF viewer's (E' and B the emissive and diffuse colours Blender renders with, E
    the sum of the glTF lights' lux there in their Blender colours: each point or spot light falls off as 1/d^2 from
    its reference distance, within its range window, a spot light as t^2 in the cosine, see _gltf_spot_factor).
    Returns (f, factors, headlight): f is the one factor for every light that makes the weighted mean of |X - G| least
    (a sun f x i lux, a point or spot light f x i x attenuation(d / s) x d^2 / window(d) cd at its reference distance
    d); factors holds each light's own factor (index in `lights` -> factor), fitted by least squares near the display
    and pulled towards f, kept only when they draw closer than f; headlight is the headlight's lux. A light that
    starts dark, that no face in view sees, or that reaches nothing (reach 0: X_ITE lights a face only when
    dL <= radius || radius < 0, x_ite.js line 66922, so a radius of 0 lights none) keeps f. `lights` holds (spec,
    intensity, attenuation, frame, reach (None: unlimited), origin, axis, cut-off, beam, reference distance, X3D color,
    Blender color)."""
    import numpy as np
    centre, normal, weight, colours = faces
    albedo, glow = colours[:, :3], colours[:, 3:6]
    white = np.ones(3)
    xite_columns, gltf_columns, keys = [], [], []   # per light: (faces, 3) display level, (faces, 3) lux per factor
    if headlight and view is not None:   # a unit DirectionalLight along the view (x_ite.js line 64123 normalises it)
        towards = -np.array((view.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized(), dtype=float)
        cosine = np.maximum(normal @ towards, 0.0)
        xite_columns.append(np.outer(cosine, white))
        gltf_columns.append(np.outer(cosine, white))
        keys.append(None)
    for index, light in enumerate(lights):
        spec, intensity, attenuation, frame, reach, origin, axis, cut_off, beam, distance, shown, held = light
        given = max(0.0, intensity)
        if given <= 0.0 or reach == 0.0:
            continue
        shown, held = np.array(shown, dtype=float), np.array(held, dtype=float)
        if spec == 'DirectionalLight':
            cosine = np.maximum(normal @ -np.array(axis, dtype=float), 0.0)
            xite_columns.append(np.outer(given * cosine, shown))
            gltf_columns.append(np.outer(given * cosine, held))
            keys.append(index)
            continue
        offset = np.array(origin, dtype=float) - centre
        far = np.maximum(np.linalg.norm(offset, axis=1), 1e-9)
        cosine = np.maximum(np.einsum('ij,ij->i', normal, offset) / far, 0.0)
        xite_cone = gltf_cone = 1.0
        if spec == 'SpotLight':
            along = -(offset @ np.array(axis, dtype=float)) / far
            xite_cone, gltf_cone = _x_ite_spot_factor(along, cut_off, beam), _gltf_spot_factor(along, cut_off, beam)
        a0, a1, a2 = (list(attenuation) + [0.0, 0.0, 0.0])[:3] if attenuation else (1.0, 0.0, 0.0)
        local = far / frame
        fade = 1.0 / np.maximum(a0 + a1 * local + a2 * local * local, 1.0)
        reached = np.ones(len(far)) if reach is None else (far <= reach).astype(float)
        xite_columns.append(np.outer(given * fade * cosine * xite_cone * reached, shown))
        anchor = given * x3d_attenuation_factor(attenuation, distance / frame) * distance * distance \
            / max(range_window(distance, reach), 0.1)
        gltf_columns.append(np.outer(anchor * range_window(far, reach) * cosine * gltf_cone / (far * far), held))
        keys.append(index)
    if not keys:
        return None
    xite = np.stack(xite_columns, axis=-1)   # (faces, 3, lights)
    gltf = np.stack(gltf_columns, axis=-1)
    lit = (xite.sum(axis=(1, 2)) > 0.0) | (gltf.sum(axis=(1, 2)) > 0.0)
    if not lit.any():
        return None
    weight, albedo, glow, xite, gltf = weight[lit], albedo[lit], glow[lit], xite[lit], gltf[lit]
    if not all(np.isfinite(array).all() for array in (weight, albedo, glow, xite, gltf)) or not weight.sum() > 0.0:
        return None   # a NaN/inf colour or intensity in the file: nothing to fit (every miss() would be NaN)
    rows = len(weight) * 3
    weight = np.repeat(weight / weight.sum() / 3.0, 3)   # one row per face and channel
    albedo, glow = albedo.reshape(rows), glow.reshape(rows)
    xite = xite.reshape(rows, -1)
    gltf = gltf.reshape(rows, -1)
    shown = np.minimum(glow + albedo * xite.sum(axis=1), 1.0)   # X_ITE adds the emissive colour in display space

    def linear(value):
        return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)

    held = linear(albedo) if srgb else albedo
    shine = linear(glow) if srgb else glow   # a glTF viewer adds it in linear space

    def miss(factors):
        value = np.minimum(shine + held * (gltf @ factors) / math.pi, 1.0)
        value = np.where(value <= 0.0031308, 12.92 * value, 1.055 * np.maximum(value, 0.0) ** (1.0 / 2.4) - 0.055)
        return float(weight @ np.abs(shown - value))

    def search(make, low, high):
        """The least-miss scale on a log grid from low to high, refined by golden section; the dimmest of equals."""
        grid = [low * (high / low) ** (step / 320.0) for step in range(321)]
        errors = [miss(make(scale)) for scale in grid]
        least = min(errors)
        best = next(index for index, error in enumerate(errors) if error <= least + 1e-12)
        left, right = grid[max(best - 1, 0)], grid[min(best + 1, len(grid) - 1)]
        golden = (math.sqrt(5.0) - 1.0) / 2.0
        for _ in range(60):
            one, two = right - golden * (right - left), left + golden * (right - left)
            if miss(make(one)) <= miss(make(two)):
                right = two
            else:
                left = one
        return 0.5 * (left + right)

    count = len(keys)
    ones = np.ones(count)
    f = search(lambda scale: scale * ones, math.pi * 1e-4, math.pi * 1e4)

    # Each light's own factor: weighted least squares on the linear lux each face and channel needs to show X, weighted
    # by how much a lux there changes the display, with values X_ITE clips met once they are as bright; pulled
    # towards f. A black channel (nothing to show) does not count.
    usable = held > 1e-6
    target = np.where(usable, math.pi * np.maximum(linear(shown) - shine, 0.0) / np.maximum(held, 1e-6), 0.0)
    clipped = shown >= 1.0
    level = linear(shown)
    slope = np.where(level <= 0.0031308, 12.92, 1.055 / 2.4 * np.maximum(level, 1e-9) ** (1.0 / 2.4 - 1.0))
    importance = np.where(usable, weight * (slope * held / math.pi) ** 2, 0.0)
    factors = f * ones
    for _ in range(4):
        use = usable & (~clipped | (gltf @ factors < target))
        matrix = (gltf[use].T * importance[use]) @ gltf[use]
        vector = (gltf[use].T * importance[use]) @ target[use]
        pull = 1e-3 * np.trace(matrix) / count + 1e-30
        free = np.ones(count, dtype=bool)
        solution = np.zeros(count)
        for _ in range(count):   # active set: a light never goes negative
            index = np.flatnonzero(free)
            solution[:] = 0.0
            solution[index] = np.linalg.solve(matrix[np.ix_(index, index)] + pull * np.eye(len(index)),
                                              vector[index] + pull * f)
            if (solution[index] >= 0.0).all():
                break
            free[index[solution[index] < 0.0]] = False
        factors = solution.copy()
    scale = search(lambda scale: scale * factors, 0.25, 4.0) if factors.any() else 1.0
    factors = np.where(gltf.any(axis=0), scale * factors, f)   # a light no face in view sees keeps f
    if not factors.any() or miss(factors) >= miss(f * ones):
        factors = f * ones
    own = {key: float(value) for key, value in zip(keys, factors)}
    return f, {key: value for key, value in own.items() if key is not None}, own.get(None, f)


def finalize_light_units(scene, units=None):
    """Set the energy of every light this import made (see LIGHT_UNITS). In 'X_ITE' units, with K = 4 pi (Blender
    watts per COMPAT candela), d a point or spot light's reference distance (Blender units) and s its frame (the
    Blender length of one unit of its X3D frame: the file unit times its Transforms' scale; X_ITE measures the
    light's distances, attenuation and radius in that frame):
      - the scene is lit the classic way when its lit shapes have a Material or TwoSidedMaterial and none has a
        PhysicalMaterial (an Inlined glTF counts as PhysicalMaterial), else physically;
      - physical: a DirectionalLight's sun strength is its intensity (lux); a point or spot light gets
        i x attenuation(d / s) x s^2 cd, exact at every distance for the default attenuation 1 0 0;
      - classic: X_ITE shades in display space (colours, light colours and the sum of the lights all as sRGB values,
        with no falloff but attenuation), which no factor matches everywhere in a linear glTF viewer. So the lights
        are fitted to what X_ITE draws on the surfaces the first Viewpoint sees (rays cast through a grid over its
        view, see fit_classic_lights): a sun gets f_k x i lux and a point or spot light f_k x i x attenuation(d / s)
        x d^2 cd, divided by the glTF range window at d (see range_window), which X_ITE's classic shader does not
        apply. f_k is one factor for every light, or each light's own when that draws closer; with nothing lit in
        view, f = pi lin(a S) / (A S), S the sum of what each light gives at its reference distance (and 1 for the
        headlight when it is on), a the median sRGB albedo of the lit classic Materials and A = lin(a) when the
        colours were read as sRGB (a when as is). Read as sRGB, a light's color becomes linear too (its file value
        kept in x3d_color);
      - the light's radius times s becomes its glTF range (Blender's custom distance); a radius of -1 (unlimited)
        or 0 leaves the light without a range. A radius of 0 lights nothing in X_ITE (a face only when
        dL <= radius || radius < 0, x_ite.js lines 66922 and 67826, the classic and the physical shader), so the
        light gets energy 0 and keeps its scale, as a light that starts dark; it counts neither in the fit nor in S.
    The scene gets x3d_lighting_model and x3d_headlight_lux (what an X3D headlight, a DirectionalLight of 1 along the
    view, should be in a glTF viewer), since this importer does not make the headlight."""
    global imported_lights, lit_surfaces, navigation_headlight, bound_view, default_view
    units = units or lighting_units
    lights, surfaces, headlight = imported_lights, lit_surfaces, navigation_headlight is not False
    camera = bound_view
    try:
        view = camera.matrix_world.copy() if camera is not None else default_view
    except ReferenceError:
        camera, view = None, default_view
    # without its scale: a Viewpoint under a scaled Transform views (and its headlight shines) the same way
    view = view.normalized() if view is not None else None
    imported_lights, lit_surfaces, navigation_headlight, bound_view, default_view = [], [], None, None, None
    lit_by_node.clear()
    if scene is None:
        return
    scene[HEADLIGHT_PROPERTY] = bool(headlight)   # the X3D 4.0 export writes the NavigationInfo headlight back as it was
    try:
        bpy.context.view_layer.update()   # world matrices of objects parented since they were made
    except (AttributeError, RuntimeError):
        pass
    counts = {'classic': 0, 'physical': 0}
    boxes = []
    albedos = []
    for bpyob, model, diffuse, _glow in surfaces:
        try:
            if bpyob.hide_render:
                continue
            corners = [bpyob.matrix_world @ Vector(corner) for corner in bpyob.bound_box]
        except ReferenceError:  # removed after it was made
            continue
        counts[model] += 1
        if diffuse is not None:
            # the sRGB value X_ITE multiplies by the light level; a black (emissive-only) surface is not lit, so it
            # counts neither for the albedo nor for a light's reference distance
            albedo = 0.2126 * diffuse[0] + 0.7152 * diffuse[1] + 0.0722 * diffuse[2]
            if albedo <= 0.02:
                continue
            albedos.append(min(albedo, 1.0))
        lo = Vector(tuple(min(corner[i] for corner in corners) for i in range(3)))
        hi = Vector(tuple(max(corner[i] for corner in corners) for i in range(3)))
        centre = 0.5 * (lo + hi)
        boxes.append((centre, (hi - centre).length, lo, hi))
    # One PhysicalMaterial in view decides: classic units would light it pi lin(i) / i times too bright (a key
    # light of 2.4 gives 23.9 lux where X_ITE lights it with 2.4), and an overexposed surface loses its detail,
    # while a classic surface lit physically is only darker.
    classic = counts['classic'] > 0 and counts['physical'] == 0
    # X_ITE multiplies a classic scene's light colours in display space, as it does its Material colours: read as sRGB,
    # a light's color becomes linear in Blender (the file's value is kept for the export), like the Materials' colours,
    # whatever the light units (the X3D 3.3 export sRGB-encodes a light's colour under SRGB as it does a Material's).
    linear_lights = classic and colour_space == 'SRGB'

    def tones(data):
        """(the light's X3D color, the colour Blender renders it with)."""
        given = tuple(float(channel) for channel in data.color[:3])
        return given, tuple(srgb_to_linear(channel) for channel in given) if linear_lights else given

    def hold_colour(data):
        if linear_lights:
            given, held_colour = tones(data)
            data[LIGHT_COLOR_PROPERTY] = given
            data.color = held_colour

    if units != 'X_ITE':
        for bpyob, *_rest in lights:
            try:
                hold_colour(bpyob.data)
            except ReferenceError:
                continue
        return
    albedos.sort()
    typical = albedos[len(albedos) // 2] if albedos else 0.8
    held = srgb_to_linear(typical) if colour_space == 'SRGB' else typical   # the albedo Blender renders with

    plans = []
    shining = []   # what the classic factor fit needs of each light
    total = 1.0 if headlight else 0.0
    for bpyob, spec, intensity, attenuation, radius, frame in lights:
        try:
            data = bpyob.data
            matrix = bpyob.matrix_world
        except ReferenceError:
            continue
        given = max(0.0, intensity)
        axis = (matrix.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        if spec == 'DirectionalLight':
            plans.append((data, spec, intensity, None, False))
            shining.append((spec, intensity, None, 1.0, None, None, axis, None, None, None) + tones(data))
            total += given
            continue
        frame = frame if frame > 0.0 else 1.0
        origin = matrix.to_translation()
        cut_off = data.spot_size / 2.0 if spec == 'SpotLight' else None
        beam = cut_off * (1.0 - data.spot_blend) if spec == 'SpotLight' else None
        reach = radius * frame if radius > 0.0 else None
        dark = radius == 0.0   # X_ITE lights a face only when dL <= radius || radius < 0
        distance = reference_distance(origin, reach, boxes, axis if spec == 'SpotLight' else None, cut_off)
        if distance is None:   # lights nothing: matched at 1 m, adds nothing to the scene's level
            distance = 1.0
        elif not dark:
            total += given * x3d_attenuation_factor(attenuation, distance / frame)
        if dark:
            logger.warning("ImportX3D: %s %r has radius 0, so X_ITE lights nothing with it; it gets no energy and no "
                           "glTF range", spec, bpyob.name)
        plans.append((data, spec, intensity, (distance, frame, reach, attenuation), dark))
        shining.append((spec, intensity, attenuation, frame, 0.0 if dark else reach, origin, axis, cut_off, beam,
                        distance) + tones(data))

    f, own, headlight_lux = 1.0, {}, 1.0
    if classic:
        faces = _view_samples(surfaces, camera, view)
        fitted = fit_classic_lights(faces, shining, headlight, view, colour_space == 'SRGB') if faces else None
        if fitted is not None:
            f, own, headlight_lux = fitted
        else:   # nothing lit in view: the median albedo lit by every light at once shows as in X_ITE
            level = total if total > 0.0 else 1.0
            f = headlight_lux = math.pi * srgb_to_linear(min(typical * level, 1.0)) / (held * level)
    for index, (data, spec, intensity, place, dark) in enumerate(plans):
        unit = 1.0 if intensity <= 0.0 else intensity       # the scale of a light that starts dark (animated later)
        mine = own.get(index, f)
        if place is None:
            energy = mine * unit
        else:
            distance, frame, reach, attenuation = place
            fade = x3d_attenuation_factor(attenuation, distance / frame)
            if classic:
                candela = mine * unit * fade * distance * distance / max(range_window(distance, reach), 0.1)
            else:
                candela = unit * fade * frame * frame
            energy = 4.0 * math.pi * candela
            data[LIGHT_REFERENCE_DISTANCE_PROPERTY] = distance
            data.use_custom_distance = reach is not None
            if reach is not None:
                data.cutoff_distance = reach
        data[LIGHT_ENERGY_PER_INTENSITY_PROPERTY] = energy / unit
        data.energy = energy if intensity > 0.0 and not dark else 0.0
        hold_colour(data)
    scene[LIGHTING_MODEL_PROPERTY] = 'classic' if classic else 'physical'
    scene[HEADLIGHT_LUX_PROPERTY] = headlight_lux if classic else 1.0


def resolve_circle_divisions(value=None, default=16):
    """Segments for Sphere, Cylinder, Cone and the Geometry2D circles: the import option when given, else the
    BLENDER_X3D_CIRCLE_DIV environment variable (for headless pipelines), else `default`; clamped to 3..512."""
    raw = value
    if raw is None:
        raw = os.environ.get("BLENDER_X3D_CIRCLE_DIV", "").strip() or default
    try:
        n = int(raw)
    except (TypeError, ValueError):
        logger.warning("ImportX3D: BLENDER_X3D_CIRCLE_DIV=%r is not a whole number; using %d", raw, default)
        n = default
    return max(CIRCLE_DIV_RANGE[0], min(CIRCLE_DIV_RANGE[1], n))


def smooth_primitive(bpymesh, spec):
    """Shade an imported Sphere, Cylinder or Cone as X3D draws it.

    Sphere: every face smooth. Cylinder and Cone: side faces smooth; the caps (faces whose normal runs along +y or -y in
    the primitive's own frame) flat, and the rim edges between them marked sharp, so the caps keep their normal in
    every exporter."""
    count = len(bpymesh.polygons)
    if not count:
        return
    if spec == 'Sphere':
        bpymesh.polygons.foreach_set("use_smooth", [True] * count)
        return
    normals = [0.0] * (3 * count)
    bpymesh.polygons.foreach_get("normal", normals)
    side = [abs(normals[3 * i + 1]) < 0.9999 for i in range(count)]
    bpymesh.polygons.foreach_set("use_smooth", side)
    edge_index = {edge.key: edge.index for edge in bpymesh.edges}
    kinds = {}
    for poly, is_side in zip(bpymesh.polygons, side):
        for key in poly.edge_keys:
            kinds.setdefault(key, set()).add(is_side)
    for key, seen in kinds.items():
        if len(seen) == 2 and key in edge_index:
            bpymesh.edges[edge_index[key]].use_edge_sharp = True


# X3D draws line and point geometry unlit (X3D 4.0, 17.2.2.3): in the colours of a Color or ColorRGBA node when the
# geometry has one, else in the Material's emissiveColor (black when the Material does not set it), else white when
# the Appearance has no material. The surface material a Shape shares with other Shapes stays as it is; lines and
# points get their own unlit material, cached per import.
# Geometry2D nodes whose solid field defaults to FALSE in X3D 4.0 (every other mesh geometry defaults to TRUE)
SOLID_DEFAULT_FALSE_SPECS = frozenset({'Rectangle2D', 'Disk2D', 'ArcClose2D', 'TriangleSet2D'})


def geometry_solid(geom, ancestry):
    """The geometry's solid field with the default of its own node type."""
    return geom.getFieldAsBool('solid', geom.getSpec() not in SOLID_DEFAULT_FALSE_SPECS, ancestry)


LINE_POINT_SPECS = frozenset({'IndexedLineSet', 'LineSet', 'PointSet', 'Polyline2D', 'Polypoint2D', 'Arc2D', 'Circle2D'})
LINE_COLOUR_ATTRIBUTE = "Color"     # a point or line set's X3D colours, one per vertex (POINT domain)
line_material_cache = {}


def x3d_unlit_colour(appr, ancestry):
    """(rgb, alpha) X3D draws a line or point set in when it has no Color node.

    The emissiveColor of the Appearance's Material, TwoSidedMaterial (front), PhysicalMaterial or UnlitMaterial
    (whose default is white), and 1 - transparency. With no Appearance or no material node, lighting is off and the
    colour is white (X3D 4.0, 17.2.2.3)."""
    mat = appr.getChildBySpec(('Material', 'TwoSidedMaterial', 'PhysicalMaterial', 'UnlitMaterial')) if appr else None
    if mat is None:
        return (1.0, 1.0, 1.0), 1.0
    default = [1.0, 1.0, 1.0] if mat.getSpec() == 'UnlitMaterial' else [0.0, 0.0, 0.0]
    rgb = tuple(float(c) for c in mat.getFieldAsFloatTuple('emissiveColor', default, ancestry)[:3])
    if mat.getSpec() != 'PhysicalMaterial':
        rgb = tuple(classic_colour(rgb))
    alpha = 1.0 - mat.getFieldAsFloat('transparency', 0.0, ancestry)
    return rgb, max(0.0, min(1.0, alpha))


def x3d_point_colours(geom, ancestry):
    """The geometry's Color / ColorRGBA values as RGBA tuples, and 'RGB' or 'RGBA' (([], None) without one)."""
    node = geom.getChildBySpec(['ColorRGBA', 'Color'])
    if node is None:
        return [], None
    if node.getSpec() == 'ColorRGBA':
        return [tuple(float(x) for x in c[:4]) for c in node.getFieldAsArray('color', 4, ancestry)], 'RGBA'
    return [tuple(float(x) for x in c[:3]) + (1.0,) for c in node.getFieldAsArray('color', 3, ancestry)], 'RGB'


def set_point_colours(bpymesh, rgba, kind):
    """One X3D colour per vertex as the POINT-domain attribute LINE_COLOUR_ATTRIBUTE. RGB goes from sRGB to linear as
    for faces when _vertex_colours_are_display(); alpha is not a colour and is kept as it is."""
    encode = srgb_to_linear if _vertex_colours_are_display() else float
    flat = [v for (r, g, b, a) in rgba for v in (encode(r), encode(g), encode(b), a)]
    attr = bpymesh.color_attributes.new(LINE_COLOUR_ATTRIBUTE, 'FLOAT_COLOR', 'POINT')
    attr.data.foreach_set("color", flat)
    bpymesh["x3d_colour_kind"] = kind


def line_colour_kind(bpydata):
    """'RGB' / 'RGBA' when the imported line or point data carries its X3D colours, else None."""
    if isinstance(bpydata, bpy.types.Mesh) and LINE_COLOUR_ATTRIBUTE in bpydata.color_attributes:
        return bpydata.get("x3d_colour_kind", 'RGB')
    return None


def wire_unlit(mat, colour, alpha_source=None, alpha_value=1.0, out=None):
    """Draw `colour` (an output socket, or an RGB value left on the Emission node) unlit on `mat`: Emission (strength
    1) for camera rays and Transparent BSDF for every other ray (the light-path mix Blender's glTF importer uses for
    KHR_materials_unlit, so an unlit surface lights nothing and casts no shadow, as in X3D), then a Mix Shader with
    Transparent BSDF when there is alpha. The Mix keeps `alpha_value` as its factor's value even when `alpha_source`
    feeds it, as the Principled Alpha does, so the X3D export still reads 1 - transparency there.

    Both exporters read this shape: Blender's glTF exporter writes KHR_materials_unlit with the colour as
    baseColorFactor, baseColorTexture or COLOR_0, and alpha as alphaMode BLEND; this add-on's X3D export finds the
    Emission node and writes an unlit material in its colour and alpha."""
    tree = mat.node_tree
    if out is None:
        out = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) \
            or next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL'), None) or tree.nodes.new('ShaderNodeOutputMaterial')
    x, y = out.location
    emission = tree.nodes.new('ShaderNodeEmission')
    emission.inputs['Strength'].default_value = 1.0
    emission.location = (x - 400, y - 60)
    if isinstance(colour, bpy.types.NodeSocket):
        tree.links.new(colour, emission.inputs['Color'])
    else:
        emission.inputs['Color'].default_value = tuple(colour[:3]) + (1.0,)
    path = tree.nodes.new('ShaderNodeLightPath')
    path.location = (x - 600, y + 250)
    indirect = tree.nodes.new('ShaderNodeBsdfTransparent')
    indirect.location = (x - 400, y + 60)
    unlit = tree.nodes.new('ShaderNodeMixShader')
    unlit.location = (x - 200, y)
    tree.links.new(path.outputs['Is Camera Ray'], unlit.inputs[0])
    tree.links.new(indirect.outputs[0], unlit.inputs[1])
    tree.links.new(emission.outputs[0], unlit.inputs[2])
    surface = unlit.outputs[0]
    for link in list(out.inputs['Surface'].links):
        tree.links.remove(link)
    if alpha_source is not None or alpha_value < 1.0:
        mix = tree.nodes.new('ShaderNodeMixShader')
        clear = tree.nodes.new('ShaderNodeBsdfTransparent')
        mix.location, clear.location = (x - 100, y - 200), (x - 300, y - 300)
        mix.inputs[0].default_value = alpha_value
        if alpha_source is not None:
            tree.links.new(alpha_source, mix.inputs[0])
        tree.links.new(clear.outputs[0], mix.inputs[1])
        tree.links.new(surface, mix.inputs[2])
        surface = mix.outputs[0]
        mat.surface_render_method = "BLENDED"
    tree.links.new(surface, out.inputs['Surface'])
    return mat


MATERIAL_SPECS = ('Material', 'TwoSidedMaterial', 'PhysicalMaterial', 'UnlitMaterial')
SHADER_SPECS = ('ComposedShader', 'PackagedShader', 'ProgramShader')
unlit_surface_cache = {}


def draws_unlit(appr):
    """True when X3D draws a surface unlit because its Appearance has no material node (or it has no Appearance):
    lighting is off and the colour is the texture's, else the Color node's, else white (X3D 4.0, 17.2.2.3). An
    Appearance with a shader is left to the shader, which only a browser that runs it can draw."""
    if appr is None:
        return True
    return appr.getChildBySpec(MATERIAL_SPECS) is None and appr.getChildBySpec(SHADER_SPECS) is None


def unlit_surface_material(bpymat, vertex_colours=None):
    """The unlit copy of the default material the importer made for a surface without a material node: whatever feeds
    its Base Color (the texture, else the Color node's attribute), else white, drawn unlit (wire_unlit), with the
    Alpha when it is linked or below 1. Before, such a surface was lit grey (0.8), and a Color node's surface came out
    black in a scene without lights.

    vertex_colours: None, or 'RGB' / 'RGBA' for a Color / ColorRGBA node. A ColorRGBA's alpha is the surface's alpha,
    as line_point_material does for lines: X_ITE 16.7.1 draws a Shape without a material with its default
    UnlitMaterial (getDefaultMaterial), whose shader takes vec4 (color.rgb, color.a * (1 - transparency))
    (Unlit2.glsl, getEmissiveColor), and a ColorRGBA makes the geometry transparent (X3DGeometryNode.set_color__), so
    the Shape blends under alphaMode AUTO (X3DShapeNode.set_transparent__). Blender's glTF exporter then writes
    alphaMode BLEND and the alpha in COLOR_0. Before, the alpha stayed in the colour attribute (and in the X3D export)
    but the material ignored it: the glb was OPAQUE. A Color node stays opaque."""
    hit = unlit_surface_cache.get((bpymat.name, vertex_colours))
    if hit is not None:
        return hit
    tree = bpymat.node_tree
    bsdf = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if tree else None
    if bsdf is None:
        return bpymat
    mat = bpymat.copy()
    mat.name = bpymat.name + "_unlit"
    tree = mat.node_tree
    bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    out = next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) \
        or next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL'), None)
    if out is None:
        out = tree.nodes.new('ShaderNodeOutputMaterial')
    base, alpha = bsdf.inputs['Base Color'], bsdf.inputs['Alpha']
    if base.links:
        colour = base.links[0].from_socket
    elif vertex_colours:                       # the Color node's values, as the face importers store them
        vcol = tree.nodes.new('ShaderNodeVertexColor')
        vcol.layer_name = "ColorPerCorner"
        vcol.location = (bsdf.location[0], bsdf.location[1] + 200)
        colour = vcol.outputs['Color']
    else:
        rgb = tree.nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
        rgb.location = (bsdf.location[0], bsdf.location[1] + 200)
        colour = rgb.outputs[0]
    alpha_source = alpha.links[0].from_socket if alpha.links else None
    if vertex_colours == 'RGBA' and alpha_source is None and colour.node.type == 'VERTEX_COLOR':
        alpha_source = colour.node.outputs['Alpha']      # the ColorRGBA's alpha, kept as it is in the attribute
    wire_unlit(mat, colour, alpha_source, float(alpha.default_value), out)
    tree.nodes.remove(bsdf)
    unlit_surface_cache[(bpymat.name, vertex_colours)] = mat
    return mat


# X_ITE 16.7.1 draws an UnlitMaterial with its Unlit shader (x_ite.js, Unlit2.glsl.js, getEmissiveColor): no lighting,
# vec4 (emissiveColor, 1 - transparency), or vec4 (color.rgb, color.a * (1 - transparency)) when the geometry has a
# Color or ColorRGBA node (X3D_COLOR_MATERIAL, X3DShapeNode options from geometryContext.colorMaterial), times the
# emissiveTexture. That is glTF's KHR_materials_unlit, which draws baseColorFactor x baseColorTexture x COLOR_0.
unlit_colour_cache = {}


def _output_node(tree):
    return next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None) \
        or next((n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL'), None) or tree.nodes.new('ShaderNodeOutputMaterial')


def unlit_pbr_material(bpymat, bsdf, emissive):
    """Turn the Principled material appearance_CreatePBRMaterial built for an UnlitMaterial into wire_unlit's shape, in
    place: the colour is what feeds Emission Color (the emissiveTexture, times emissiveColor) or else emissiveColor,
    the alpha the Principled Alpha (1 - transparency, times the colour texture's alpha), and the render method stays
    the one alphaMode chose. The Emission node keeps emissiveColor as its colour's value, where the X3D export reads it.

    Before, the material stayed a Principled BSDF with a black Base Color and the colour as emission: Blender's glTF
    exporter wrote baseColorFactor 0 0 0, emissiveFactor and KHR_materials_specular, which a glTF viewer lights, and
    a Color node's COLOR_0, which glTF multiplies into the black baseColor, never reached the pixel (X_ITE draws the
    vertex colours, Babylon.js drew the habsburg demo's Cloth, FellMat and BeadMat white)."""
    tree = bpymat.node_tree
    render = bpymat.surface_render_method
    socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
    colour = socket.links[0].from_socket if socket.links else emissive
    alpha = bsdf.inputs['Alpha']
    alpha_source = alpha.links[0].from_socket if alpha.links else None
    wire_unlit(bpymat, colour, alpha_source, float(alpha.default_value), _output_node(tree))
    emission = next(n for n in tree.nodes if n.type == 'EMISSION')
    emission.inputs['Color'].default_value = tuple(emissive[:3]) + (1.0,)
    tree.nodes.remove(bsdf)
    bpymat.surface_render_method = render
    return bpymat


physical_colour_cache = {}


_derived_materials = []   # (source, variant, suffix) made by this import; see settle_derived_material_names


def settle_derived_material_names():
    """A colour variant (X_colour) whose source material X ended up drawing nothing takes the name X.

    physical_colour_material and unlit_colour_material copy a material for the shapes with a Color node, since the
    same Appearance may also draw shapes without one. When every user of X had colours, X itself is left unused, and
    the scene's only material for those shapes was X_colour: a Blender material TwoToneTop came back as
    TwoToneTop_colour. Run once per import, after every shape is made."""
    variants = {}
    for source, variant, suffix in _derived_materials:
        try:
            variants.setdefault(source.as_pointer(), []).append((source, variant, suffix))
        except ReferenceError:
            continue
    for entries in variants.values():
        if len(entries) != 1:
            continue
        source, variant, suffix = entries[0]
        try:
            if source.users or not variant.users or variant.name != source.name + suffix:
                continue
            want = source.name
            source.name = want + ".source"
            variant.name = want
        except ReferenceError:
            continue
    _derived_materials.clear()


def _name_derived_material(mat, source, suffix):
    """Name a material derived from ``source`` (its colour or line variant) ``<source><suffix>``, unless ``source``
    already ends with ``suffix``: a file this add-on wrote names the variant itself (MA_X_colour), so the Appearance
    material arrives as X_colour and appending again grew the name on every round trip (X_colour_colour). The variant
    then takes that name and the source, which in such a file only the variant uses, moves aside to <name>.source."""
    if source is not None and suffix == "_colour":
        _derived_materials.append((source, mat, suffix))
    if source is None or not source.name.endswith(suffix):
        mat.name = (source.name if source is not None else mat.name) + suffix
        return
    want = source.name
    source.name = want + ".source"
    mat.name = want


def physical_colour_material(bpymat):
    """The copy of a PhysicalMaterial's Principled material for a filled geometry with a Color or ColorRGBA node,
    made once per import for each material and solid: the colours (ColorPerCorner) drive Base Color, and multiply a
    baseTexture when there is one, as X_ITE 16.7.1 draws them (X3D 4.0: the Color node's values replace baseColor).
    Without this the colours sat on the mesh but no node read them, so Cycles and EEVEE drew the flat baseColor and
    Blender's glTF exporter (vertex colours 'MATERIAL') wrote them nowhere: a baked colour ramp came out white in
    the glb. The Base Color socket keeps baseColor as its value, so the X3D export writes the PhysicalMaterial back
    unchanged beside the Color node. The colours stay linear: the face importers keep a Color under a
    PhysicalMaterial as given (vertex_colours_linear)."""
    key = (bpymat.as_pointer(), bool(bpymat.use_backface_culling))
    hit = physical_colour_cache.get(key)
    if hit is not None:
        return hit
    tree = bpymat.node_tree
    bsdf = next((n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if tree is not None else None
    if bsdf is None:
        return bpymat
    mat = bpymat.copy()
    _name_derived_material(mat, bpymat, "_colour")
    tree = mat.node_tree
    bsdf = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
    base = bsdf.inputs['Base Color']
    vcol = tree.nodes.new('ShaderNodeVertexColor')
    vcol.layer_name = "ColorPerCorner"
    vcol.location = (bsdf.location[0] - 500, bsdf.location[1] + 260)
    textured = bool(base.links)
    if textured:
        texture = base.links[0].from_socket
        mix = tree.nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 1.0
        mix.location = (bsdf.location[0] - 250, bsdf.location[1] + 200)
        tree.links.new(texture, mix.inputs['A'])
        tree.links.new(vcol.outputs['Color'], mix.inputs['B'])
        tree.links.new(mix.outputs['Result'], base)
    else:
        tree.links.new(vcol.outputs['Color'], base)
    # baseColor multiplies the colours (X_ITE 16.7.1 draws baseColor 0.06 0.5 0.48 under a white Color as 0.06 0.5 0.48,
    # not white); with a texture it is already in the texture's Multiply node, and white needs none
    if not textured:
        _modulate_socket_by_color(tree, base, tuple(base.default_value))
    physical_colour_cache[key] = mat
    return mat


def unlit_colour_material(bpymat, colour_kind, alpha_mode='AUTO'):
    """The copy of an UnlitMaterial's unlit material (unlit_pbr_material) for a filled geometry with a Color ('RGB')
    or ColorRGBA ('RGBA') node, made once per import for each material and kind, as X_ITE 16.7.1 draws it (Unlit2.glsl,
    getEmissiveColor): the colours (ColorPerCorner) replace emissiveColor and multiply the emissiveTexture; a
    ColorRGBA's alpha multiplies 1 - transparency (and the texture's alpha) and makes the geometry transparent
    (ColorRGBA: setTransparent (true)), so the Shape blends under alphaMode AUTO (X3DShapeNode.set_transparent__).
    Blender's glTF exporter writes it as KHR_materials_unlit with COLOR_0 (linear: the face importers convert the
    Color values, which X_ITE reads in display space under an UnlitMaterial) and alphaMode BLEND for a ColorRGBA.
    The Emission node keeps emissiveColor as its colour's value, so the X3D export writes the UnlitMaterial back with
    the same emissiveColor and transparency beside the Color node. The copy is per alphaMode and per solid, which
    the copy carries as use_backface_culling (one UnlitMaterial can be USEd on solid and two-sided geometry)."""
    key = (bpymat.as_pointer(), colour_kind, alpha_mode, bool(bpymat.use_backface_culling))
    hit = unlit_colour_cache.get(key)
    if hit is not None:
        return hit
    if bpymat.node_tree is None or not any(n.type == 'EMISSION' for n in bpymat.node_tree.nodes):
        return bpymat
    mat = bpymat.copy()
    _name_derived_material(mat, bpymat, "_colour")
    tree = mat.node_tree
    out = _output_node(tree)
    emission = next(n for n in tree.nodes if n.type == 'EMISSION')
    emissive = tuple(emission.inputs['Color'].default_value)
    texture = emission.inputs['Color'].links[0].from_socket if emission.inputs['Color'].links else None
    if texture is not None and texture.node.bl_idname == "ShaderNodeMix" and texture.node.label == "X3D colour":
        modulate = texture.node                       # _modulate_socket_by_color's texture x emissiveColor
        texture = next(s.links[0].from_socket for s in modulate.inputs if s.type == 'RGBA' and s.is_linked)
        tree.nodes.remove(modulate)
    vcol = tree.nodes.new('ShaderNodeVertexColor')
    vcol.layer_name = "ColorPerCorner"
    vcol.location = (emission.location[0] - 500, emission.location[1] - 300)
    colour = vcol.outputs['Color']
    if texture is not None:
        mix = tree.nodes.new("ShaderNodeMix")
        mix.data_type, mix.blend_type, mix.label = 'RGBA', 'MULTIPLY', "X3D colour"
        mix.location = (emission.location[0] - 250, emission.location[1] - 300)
        mix.inputs[0].default_value = 1.0
        color_a, color_b = (s for s in mix.inputs if s.type == 'RGBA')
        tree.links.new(texture, color_a)
        tree.links.new(colour, color_b)
        colour = next(s for s in mix.outputs if s.type == 'RGBA')
    # wire_unlit's alpha mix, when there is one: its factor (1 - transparency) and what feeds it (the texture's alpha)
    surface = out.inputs['Surface'].links[0].from_node if out.inputs['Surface'].links else None
    alpha_value, alpha_source = 1.0, None
    if surface is not None and surface.type == 'MIX_SHADER' \
            and not (surface.inputs[0].links and surface.inputs[0].links[0].from_node.type == 'LIGHT_PATH'):
        alpha_value = float(surface.inputs[0].default_value)
        alpha_source = surface.inputs[0].links[0].from_socket if surface.inputs[0].links else None
    if colour_kind == 'RGBA' and alpha_mode != 'OPAQUE':
        if alpha_source is None and alpha_value >= 1.0:
            alpha_source = vcol.outputs['Alpha']
        else:
            multiply = tree.nodes.new("ShaderNodeMath")
            multiply.operation, multiply.label = 'MULTIPLY', "X3D alpha"
            multiply.location = (vcol.location[0] + 250, vcol.location[1] - 200)
            multiply.inputs[0].default_value = 1.0      # the exporter reads 1 - transparency through it
            multiply.inputs[1].default_value = alpha_value if alpha_source is None else 1.0
            tree.links.new(vcol.outputs['Alpha'], multiply.inputs[0])
            cut = alpha_source.node if alpha_source is not None and alpha_source.node.type == 'MATH' \
                and alpha_source.node.operation == 'GREATER_THAN' else None   # alphaMode MASK: cut the product
            upstream = (cut.inputs[0].links[0].from_socket if cut.inputs[0].links else None) if cut else alpha_source
            if upstream is not None:
                tree.links.new(upstream, multiply.inputs[1])
            if cut is not None:
                tree.links.new(multiply.outputs[0], cut.inputs[0])
            else:
                alpha_source = multiply.outputs[0]
    for node in list(tree.nodes):                     # wire_unlit's own nodes, made again around the new colour
        if node.type in {'EMISSION', 'LIGHT_PATH', 'BSDF_TRANSPARENT', 'MIX_SHADER'}:
            tree.nodes.remove(node)
    render = bpymat.surface_render_method
    wire_unlit(mat, colour, alpha_source, alpha_value, out)
    next(n for n in tree.nodes if n.type == 'EMISSION').inputs['Color'].default_value = emissive
    if colour_kind == 'RGBA' and alpha_mode in {'AUTO', 'BLEND'}:
        mat.surface_render_method = 'BLENDED'
    else:
        mat.surface_render_method = render
    unlit_colour_cache[key] = mat
    return mat


def line_point_material(name, rgb, alpha=1.0, colours=None, source=None):
    """The unlit material lines and points are drawn with (made once per import for each colour, alpha and kind).

    colours None: the one colour `rgb`. 'RGB' / 'RGBA': the vertex colours in LINE_COLOUR_ATTRIBUTE, which replace
    the emissiveColor; a ColorRGBA's alpha replaces 1 - transparency.

    The node tree is wire_unlit's, which Blender's glTF exporter writes as KHR_materials_unlit and the X3D export as an
    unlit material: the glb holds that baseColorFactor, and COLOR_0 for a Color node, what X_ITE, Babylon.js and
    three.js draw as X3D does. (Before, an unlit copy of the Principled material carried the colour as emission and the
    Color node as a link into Emission Color, which no glTF can express: coloured points came out white.)"""
    rgb = tuple(max(0.0, float(c)) for c in rgb[:3])
    alpha = max(0.0, min(1.0, float(alpha)))
    key = (name, tuple(round(c, 6) for c in rgb), round(alpha, 6), colours)
    hit = line_material_cache.get(key)
    if hit is not None:
        return hit
    # "<name>_lines", as the export names a mesh's loose edges, but never twice (see _name_derived_material)
    mat = bpy.data.materials.new(name + "_lines")
    if source is not None and source.name == name:
        _name_derived_material(mat, source, "_lines")
    elif name.endswith("_lines"):
        mat.name = name
    if mat.node_tree is None:                     # Blender before 5.0 makes the node tree on request
        mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    out.location = (300, 0)
    if colours:
        src = tree.nodes.new('ShaderNodeVertexColor')
        src.layer_name = LINE_COLOUR_ATTRIBUTE
        colour = src.outputs['Color']
    else:
        src = tree.nodes.new('ShaderNodeRGB')
        src.outputs[0].default_value = rgb + (1.0,)
        colour = src.outputs[0]
    src.location = (-500, 0)
    wire_unlit(mat, colour, src.outputs['Alpha'] if colours == 'RGBA' else None, alpha, out)
    mat.diffuse_color = rgb + (alpha,)            # the viewport's solid-mode colour
    line_material_cache[key] = mat
    return mat


def phong_to_principled(shininess, specular_color):
    """X3D's Material specular term as Principled BSDF inputs: (roughness, specular IOR level, specular tint).

    X3D lights a Material with Blinn-Phong: specularColor x (N.H)^(128 x shininess), no Fresnel and no energy
    normalisation (X3D 4.0, 17.2.2.4). The lobe width gives the roughness (a Blinn-Phong exponent n matches a GGX alpha
    of sqrt(2 / (n + 2)); Blender's roughness is sqrt(alpha)), and the peak height gives the reflectance at normal
    incidence, F0 = 8 s / (n + 2) per channel, which a dielectric at IOR 1.5 reaches with an IOR level of F0 / 0.08
    (capped at 1). X3D's default specularColor is black, which draws no highlight at all: the level is then 0, where
    the previous mapping gave every Material Blender's default dielectric specular and every shiny one a mirror
    (roughness = 1 - shininess)."""
    s = max(0.0, min(1.0, float(shininess)))
    n = 128.0 * s
    alpha = sqrt(2.0 / (n + 2.0))
    roughness = sqrt(alpha)
    spec = [max(0.0, min(1.0, float(c))) for c in (list(specular_color or ()) + [0.0, 0.0, 0.0])[:3]]
    peak = max(spec)
    if peak <= 0.0:
        return roughness, 0.0, (1.0, 1.0, 1.0)
    level = min(1.0, 8.0 * peak / (n + 2.0) / 0.08)
    return roughness, level, tuple(c / peak for c in spec)


# A Box, Sphere, Cylinder or Cone imports as a tessellated mesh; the node and its fields are kept on the mesh
# (PRIMITIVE_PROPERTY, JSON) with a checksum of its vertex positions, so the X3D 4.0 export can write the primitive
# back while the mesh is unedited (extract.primitive_for_mesh) instead of a much larger IndexedFaceSet.
PRIMITIVE_PROPERTY = "x3d_primitive"


def position_signature(bpymesh):
    """(vertex count, face count, weighted position sum): changes when any vertex moves or is added or removed."""
    count = len(bpymesh.vertices)
    flat = [0.0] * (count * 3)
    bpymesh.vertices.foreach_get("co", flat)
    weighted = sum(value * (1 + (index % 7)) for index, value in enumerate(flat))
    return [count, len(bpymesh.polygons), round(weighted, 5)]


def _float32(value):
    import struct
    return struct.unpack("f", struct.pack("f", value))[0]


def _data_points(bpydata):
    """The vertex positions of a mesh, or the points of a curve's splines in order (its evaluated mesh's vertices)."""
    if isinstance(bpydata, bpy.types.Mesh):
        flat = [0.0] * (3 * len(bpydata.vertices))
        bpydata.vertices.foreach_get("co", flat)
        return flat
    if isinstance(bpydata, bpy.types.Curve):
        flat = []
        for spline in bpydata.splines:
            if spline.type != 'POLY':
                return None
            for point in spline.points:
                flat.extend(point.co[:3])
        return flat
    return None


def mark_coordinate_double(bpydata, geom):
    """Keep a CoordinateDouble's point text on ``bpydata`` (COORDINATE_DOUBLE_PROPERTY) when its vertices are the file's
    points one to one, in order, at unit scale: then the export can write the doubles back for the vertices nobody has
    moved. Anything else (a face set that culled its points, a USE of the coordinates elsewhere, another scale) keeps
    nothing and the export writes a Coordinate, as before."""
    coord = _coordinate_of(geom)
    if coord is None or coord.getRealNode().getSpec() != 'CoordinateDouble' or conversion_scale != 1.0:
        return
    text = _attribute_raw(coord, 'point')
    if not text:
        return
    tokens = text.replace(',', ' ').split()
    flat = _data_points(bpydata)
    if flat is None or len(tokens) != len(flat) or not flat:
        return
    try:
        if any(_float32(float(token)) != value for token, value in zip(tokens, flat)):
            return
    except ValueError:
        return
    bpydata[COORDINATE_DOUBLE_PROPERTY] = json.dumps(tokens)


def point_properties_fields(node, ancestry):
    """A PointProperties node's fields as numbers ({} when all are the X3D defaults), for POINT_PROPERTIES_PROPERTY."""
    from .extract import POINT_PROPERTIES_DEFAULTS
    fields = {}
    for name, default in POINT_PROPERTIES_DEFAULTS.items():
        if isinstance(default, list):
            value = [float(v) for v in node.getFieldAsArray(name, 0, ancestry)]
            value = value if len(value) == 3 and all(math.isfinite(v) for v in value) else default
        else:
            value = node.getFieldAsFloat(name, default, ancestry)
            value = float(value) if value is not None and math.isfinite(value) else default
        if value != default:
            fields[name] = value
    return fields


def mark_primitive(bpymesh, geom, ancestry, node_type, **fields):
    """Remember the primitive node behind ``bpymesh`` (see PRIMITIVE_PROPERTY)."""
    import json
    fields["solid"] = geom.getFieldAsBool('solid', geom.getSpec() not in SOLID_DEFAULT_FALSE_SPECS, ancestry)
    bpymesh[PRIMITIVE_PROPERTY] = json.dumps({"node": node_type, "fields": fields,
                                              "signature": position_signature(bpymesh)})


def importMesh_Sphere(geom, ancestry):
    # solid is ignored.
    # Extra field 'subdivision="n m"' attribute, specifying how many
    # rings and segments to use (X3DOM).
    r = geom.getFieldAsFloat('radius', 0.5 * conversion_scale, ancestry, conversion_scale)
    subdiv = geom.getFieldAsArray('subdivision', 0, ancestry)
    if subdiv:
        if len(subdiv) == 1:
            nr = ns = subdiv[0]
        else:
            (nr, ns) = subdiv
    else:
        nr = ns = GLOBALS['CIRCLE_DETAIL']
        # used as both ring count and segment count
    nr = budget.divisions(nr, GLOBALS['CIRCLE_DETAIL'], "Sphere")
    ns = budget.divisions(ns, GLOBALS['CIRCLE_DETAIL'], "Sphere")
    lau = pi / nr  # Unit angle of latitude (rings) for the given tessellation
    lou = 2 * pi / ns  # Unit angle of longitude (segments)

    bpymesh = bpy.data.meshes.new(name="Sphere")

    bpymesh.vertices.add(ns * (nr - 1) + 2)
    # The non-polar vertices go from x=0, negative z plane counterclockwise -
    # to -x, to +z, to +x, back to -z
    co = [0, r, 0, 0, -r, 0]  # +y and -y poles
    co += [r * coe for ring in range(1, nr) for seg in range(ns)
           for coe in (-sin(lou * seg) * sin(lau * ring),
                       cos(lau * ring),
                       -cos(lou * seg) * sin(lau * ring))]
    bpymesh.vertices.foreach_set('co', co)

    num_poly = ns * nr
    num_tri = ns * 2
    num_quad = num_poly - num_tri
    num_loop = num_quad * 4 + num_tri * 3
    tf = bpymesh.polygons
    tf.add(num_poly)
    bpymesh.loops.add(num_loop)
    bpymesh.polygons.foreach_set("loop_start",
                                 tuple(range(0, ns * 3, 3)) +
                                 tuple(range(ns * 3, num_loop - ns * 3, 4)) +
                                 tuple(range(num_loop - ns * 3, num_loop, 3)))

    vb = 2 + (nr - 2) * ns  # First vertex index for the bottom cap
    fb = (nr - 1) * ns  # First face index for the bottom cap

    # Because of tricky structure, assign texture coordinates along with
    # face creation. Can't easily do foreach_set, 'cause caps are triangles and
    # sides are quads.

    tex = bpymesh.uv_layers.new().data

    # Faces go in order: top cap, sides, bottom cap.
    # Sides go by ring then by segment.

    # Caps
    # Top cap face vertices go in order: down right up
    # (starting from +y pole)
    # Bottom cap goes: up left down (starting from -y pole)
    for seg in range(ns):
        tf[seg].vertices = (0, seg + 2, (seg + 1) % ns + 2)
        tf[fb + seg].vertices = (1, vb + (seg + 1) % ns, vb + seg)
        for lidx, uv in zip(tf[seg].loop_indices,
                            (((seg + 0.5) / ns, 1),
                             (seg / ns, 1 - 1 / nr),
                             ((seg + 1) / ns, 1 - 1 / nr))):
            tex[lidx].uv = uv
        for lidx, uv in zip(tf[fb + seg].loop_indices,
                            (((seg + 0.5) / ns, 0),
                             ((seg + 1) / ns, 1 / nr),
                             (seg / ns, 1 / nr))):
            tex[lidx].uv = uv

    # Sides
    # Side face vertices go in order:  down right up left
    for ring in range(nr - 2):
        tvb = 2 + ring * ns
        # First vertex index for the top edge of the ring
        bvb = tvb + ns
        # First vertex index for the bottom edge of the ring
        rfb = ns * (ring + 1)
        # First face index for the ring
        for seg in range(ns):
            nseg = (seg + 1) % ns
            tf[rfb + seg].vertices = (tvb + seg, bvb + seg, bvb + nseg, tvb + nseg)
            for lidx, uv in zip(tf[rfb + seg].loop_indices,
                                ((seg / ns, 1 - (ring + 1) / nr),
                                 (seg / ns, 1 - (ring + 2) / nr),
                                 ((seg + 1) / ns, 1 - (ring + 2) / nr),
                                 ((seg + 1) / ns, 1 - (ring + 1) / nr))):
                tex[lidx].uv = uv

    bpymesh.validate()
    bpymesh.update()
    mark_primitive(bpymesh, geom, ancestry, 'Sphere', radius=r)
    return bpymesh


def importMesh_Cylinder(geom, ancestry):
    # solid is ignored
    # no ccw in this element
    # Extra parameter subdivision="n" - how many faces to use
    radius = geom.getFieldAsFloat('radius', 1.0 * conversion_scale, ancestry, conversion_scale)
    height = geom.getFieldAsFloat('height', 2.0 * conversion_scale, ancestry, conversion_scale)
    bottom = geom.getFieldAsBool('bottom', True, ancestry)
    side = geom.getFieldAsBool('side', True, ancestry)
    top = geom.getFieldAsBool('top', True, ancestry)

    n = budget.divisions(geom.getFieldAsInt('subdivision', GLOBALS['CIRCLE_DETAIL'], ancestry),
                         GLOBALS['CIRCLE_DETAIL'], "Cylinder")

    nn = n * 2
    yvalues = (height / 2, -height / 2)
    angle = 2 * pi / n

    # The seam is at x=0, z=-r, vertices go ccw -
    # to pos x, to neg z, to neg x, back to neg z
    verts = [(-radius * sin(angle * i), y, -radius * cos(angle * i))
             for i in range(n) for y in yvalues]
    faces = []
    if side:
        # Order of edges in side faces: up, left, down, right.
        # Texture coordinate logic depends on it.
        faces += [(i * 2 + 3, i * 2 + 2, i * 2, i * 2 + 1)
                  for i in range(n - 1)] + [(1, 0, nn - 2, nn - 1)]
    if top:
        faces += [[x for x in range(0, nn, 2)]]
    if bottom:
        faces += [[x for x in range(nn - 1, -1, -2)]]

    bpymesh = bpy.data.meshes.new(name="Cylinder")
    bpymesh.from_pydata(verts, [], faces)
    # Tried constructing the mesh manually from polygons/loops/edges,
    # the difference in performance on Blender 2.74 (Win64) is negligible.

    bpymesh.validate()

    # The structure of the loop array goes: cap, side, cap.
    loops = []
    if side:
        loops += [co for i in range(n)
                  for co in ((i + 1) / n, 0, (i + 1) / n, 1, i / n, 1, i / n, 0)]

    if top:
        loops += [0.5 + co / 2 for i in range(n)
                  for co in (-sin(angle * i), cos(angle * i))]

    if bottom:
        loops += [0.5 - co / 2 for i in range(n - 1, -1, -1)
                  for co in (sin(angle * i), cos(angle * i))]

    importMesh_ApplyTextureToLoops(bpymesh, loops)

    bpymesh.update()
    mark_primitive(bpymesh, geom, ancestry, 'Cylinder', radius=radius, height=height, bottom=bottom, side=side, top=top)
    return bpymesh


def importMesh_Cone(geom, ancestry):
    # Solid ignored
    # Extra parameter subdivision="n" - how many faces to use
    n = budget.divisions(geom.getFieldAsInt('subdivision', GLOBALS['CIRCLE_DETAIL'], ancestry),
                         GLOBALS['CIRCLE_DETAIL'], "Cone")
    radius = geom.getFieldAsFloat('bottomRadius', 1.0 * conversion_scale, ancestry, conversion_scale)
    height = geom.getFieldAsFloat('height', 2.0 * conversion_scale, ancestry, conversion_scale)
    bottom = geom.getFieldAsBool('bottom', True, ancestry)
    side = geom.getFieldAsBool('side', True, ancestry)

    d = height / 2
    angle = 2 * pi / n

    verts = [(0, d, 0)]
    verts += [(-radius * sin(angle * i),
               -d,
               -radius * cos(angle * i)) for i in range(n)]
    faces = []

    # Side face vertices go: up down right
    if side:
        faces += [(1 + (i + 1) % n, 0, 1 + i) for i in range(n)]
    if bottom:
        faces += [[i for i in range(n, 0, -1)]]

    bpymesh = bpy.data.meshes.new(name="Cone")
    bpymesh.from_pydata(verts, [], faces)

    bpymesh.validate()
    loops = []
    if side:
        loops += [co for i in range(n)
                  for co in ((i + 1) / n, 0, (i + 0.5) / n, 1, i / n, 0)]
    if bottom:
        loops += [0.5 - co / 2 for i in range(n - 1, -1, -1)
                  for co in (sin(angle * i), cos(angle * i))]
    importMesh_ApplyTextureToLoops(bpymesh, loops)

    bpymesh.update()
    mark_primitive(bpymesh, geom, ancestry, 'Cone', bottomRadius=radius, height=height, bottom=bottom, side=side)
    return bpymesh


def importMesh_Box(geom, ancestry):
    # Solid is ignored
    # No ccw in this element
    (dx, dy, dz) = geom.getFieldAsFloatTuple('size', (2.0 * conversion_scale, 2.0 * conversion_scale, 2.0 * conversion_scale), ancestry, conversion_scale)
    dx /= 2
    dy /= 2
    dz /= 2

    bpymesh = bpy.data.meshes.new(name="Box")
    bpymesh.vertices.add(8)

    # xz plane at +y, ccw
    co = (dx, dy, dz, -dx, dy, dz, -dx, dy, -dz, dx, dy, -dz,
          # xz plane at -y
          dx, -dy, dz, -dx, -dy, dz, -dx, -dy, -dz, dx, -dy, -dz)
    bpymesh.vertices.foreach_set('co', co)

    bpymesh.loops.add(6 * 4)
    bpymesh.polygons.add(6)
    bpymesh.polygons.foreach_set('loop_start', range(0, 6 * 4, 4))
    bpymesh.polygons.foreach_set('loop_total', (4,) * 6)
    bpymesh.polygons.foreach_set('vertices', (
        0, 1, 2, 3,   # +y
        4, 0, 3, 7,   # +x
        7, 3, 2, 6,   # -z
        6, 2, 1, 5,   # -x
        5, 1, 0, 4,   # +z
        7, 6, 5, 4))  # -y

    bpymesh.validate()
    d = bpymesh.uv_layers.new().data
    d.foreach_set('uv', (
        1, 0, 0, 0, 0, 1, 1, 1,
        0, 0, 0, 1, 1, 1, 1, 0,
        0, 0, 0, 1, 1, 1, 1, 0,
        0, 0, 0, 1, 1, 1, 1, 0,
        0, 0, 0, 1, 1, 1, 1, 0,
        1, 0, 0, 0, 0, 1, 1, 1))

    # flip normals, so they face outwards
    bpymesh.flip_normals()

    bpymesh.update()
    mark_primitive(bpymesh, geom, ancestry, 'Box', size=[2 * dx, 2 * dy, 2 * dz])
    return bpymesh


def importMesh_Rectangle2D(geom, ancestry):
    # Geometry2D: a rectangle in the local XY plane (z = 0), centred, facing +z.
    # solid is ignored (Blender meshes are two-sided unless backface culling is set).
    size = geom.getFieldAsFloatTuple('size', (2.0 * conversion_scale, 2.0 * conversion_scale), ancestry, conversion_scale)
    hx, hy = size[0] / 2, size[1] / 2
    bpymesh = bpy.data.meshes.new(name="Rectangle2D")
    bpymesh.from_pydata([(-hx, -hy, 0.0), (hx, -hy, 0.0), (hx, hy, 0.0), (-hx, hy, 0.0)], [], [(0, 1, 2, 3)])
    bpymesh.validate()
    bpymesh.uv_layers.new().data.foreach_set('uv', (0, 0, 1, 0, 1, 1, 0, 1))
    bpymesh.update()
    mark_primitive(bpymesh, geom, ancestry, 'Rectangle2D', size=[size[0], size[1]])
    return bpymesh


def importMesh_Disk2D(geom, ancestry):
    # Geometry2D: a disc (innerRadius 0), an annulus (0 < innerRadius < outerRadius)
    # or, when the radii are equal, a circle, in the local XY plane facing +z.
    # Texture coordinates map the outer square onto the unit square, as for Disk2D in the spec.
    outer = geom.getFieldAsFloat('outerRadius', 1.0 * conversion_scale, ancestry, conversion_scale)
    inner = geom.getFieldAsFloat('innerRadius', 0.0, ancestry, conversion_scale)
    n = max(8, 2 * GLOBALS['CIRCLE_DETAIL'])
    ring = [(cos(2 * pi * i / n), sin(2 * pi * i / n)) for i in range(n)]
    bpymesh = bpy.data.meshes.new(name="Disk2D")
    if inner <= 0.0:
        verts = [(outer * c, outer * s_, 0.0) for c, s_ in ring]
        bpymesh.from_pydata(verts, [], [tuple(range(n))])
    elif inner < outer:
        verts = [(outer * c, outer * s_, 0.0) for c, s_ in ring] + [(inner * c, inner * s_, 0.0) for c, s_ in ring]
        faces = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        bpymesh.from_pydata(verts, [], faces)
    else:
        verts = [(outer * c, outer * s_, 0.0) for c, s_ in ring]
        bpymesh.from_pydata(verts, [(i, (i + 1) % n) for i in range(n)], [])
    bpymesh.validate()
    if bpymesh.polygons:
        uv = []
        for poly in bpymesh.polygons:
            for vi in poly.vertices:
                x, y, _z = bpymesh.vertices[vi].co
                uv += [0.5 + 0.5 * x / outer, 0.5 + 0.5 * y / outer]
        bpymesh.uv_layers.new().data.foreach_set('uv', uv)
    bpymesh.update()
    return bpymesh

def _quad_mesh(name, geom, ancestry, index=None):
    """CADGeometry quads: every four indices (IndexedQuadSet) or coordinates (QuadSet) make one quad; a remainder,
    and a quad naming a missing coordinate, are skipped. Colours, normals and texture coordinates are per vertex, as
    for the triangle sets."""
    if _coordinate_of(geom) is None:
        return None
    bpymesh = bpy.data.meshes.new(name=name)
    importMesh_ReadVertices(bpymesh, geom, ancestry)
    nverts = len(bpymesh.vertices)
    index = list(range(nverts)) if index is None else [int(i) for i in index]
    quads = [index[4 * i:4 * i + 4] for i in range(len(index) // 4)]
    quads = [q for q in quads if all(0 <= v < nverts for v in q)]
    if not geom.getFieldAsBool('ccw', True, ancestry):
        quads = [[q[0], q[3], q[2], q[1]] for q in quads]
    count = len(quads)
    bpymesh.loops.add(4 * count)
    bpymesh.polygons.add(count)
    bpymesh.polygons.foreach_set("loop_start", range(0, 4 * count, 4))
    bpymesh.polygons.foreach_set("vertices", [v for q in quads for v in q])
    bpymesh["x3d_geometry"] = name     # QuadSet or IndexedQuadSet, written back as one by the X3D 4.0 export (batch 8)
    return importMesh_FinalizeTriangleMesh(bpymesh, geom, ancestry)


def importMesh_IndexedQuadSet(geom, ancestry):
    # CADGeometry component (X3D 4.0, 32.4.2)
    return _quad_mesh("IndexedQuadSet", geom, ancestry, geom.getFieldAsArray('index', 0, ancestry))


def importMesh_QuadSet(geom, ancestry):
    # CADGeometry component (X3D 4.0, 32.4.4)
    return _quad_mesh("QuadSet", geom, ancestry)


def _arc_angles(geom, ancestry):
    """Arc2D / ArcClose2D: counterclockwise from startAngle to endAngle in the local XY plane. Equal angles, or a span
    of 2 pi or more, make the full circle (X3D 4.0, 14.4.1)."""
    start = geom.getFieldAsFloat('startAngle', 0.0, ancestry)
    end = geom.getFieldAsFloat('endAngle', pi / 2, ancestry)
    span = end - start
    if span == 0.0 or abs(span) >= 2 * pi:
        return start, 2 * pi, True
    if span < 0:
        span += 2 * pi
    return start, span, False


def _arc_points(radius, start, span, closed):
    n = max(2, int(ceil(max(8, 2 * GLOBALS['CIRCLE_DETAIL']) * span / (2 * pi))))
    count = n if closed else n + 1
    return [(radius * cos(start + span * i / n), radius * sin(start + span * i / n)) for i in range(count)]


def _polyline_curve(name, points2d, cyclic=False):
    bpycurve = bpy.data.curves.new(name, 'CURVE')
    bpycurve.dimensions = '3D'
    if len(points2d) < 2:
        return bpycurve
    spline = bpycurve.splines.new('POLY')
    spline.points.add(len(points2d) - 1)
    spline.points.foreach_set('co', [c for x, y in points2d for c in (x, y, 0.0, 1.0)])
    spline.use_cyclic_u = bool(cyclic)
    return bpycurve


def importMesh_Arc2D(geom, ancestry):
    # Geometry2D: an open arc (a circle when the angles say so), drawn as a line
    r = geom.getFieldAsFloat('radius', 1.0 * conversion_scale, ancestry, conversion_scale)
    start, span, full = _arc_angles(geom, ancestry)
    return _polyline_curve("Arc2D", _arc_points(r, start, span, full), cyclic=full)


def importMesh_Circle2D(geom, ancestry):
    # Geometry2D: a circle, drawn as a closed line
    r = geom.getFieldAsFloat('radius', 1.0 * conversion_scale, ancestry, conversion_scale)
    return _polyline_curve("Circle2D", _arc_points(r, 0.0, 2 * pi, True), cyclic=True)


def importMesh_Polyline2D(geom, ancestry):
    # Geometry2D: connected line segments through lineSegments
    pts = geom.getFieldAsArray('lineSegments', 2, ancestry, conversion_scale)
    return _polyline_curve("Polyline2D", [tuple(p[:2]) for p in pts]) if pts else None


def importMesh_Polypoint2D(geom, ancestry):
    # Geometry2D: a set of points in the local XY plane
    pts = geom.getFieldAsArray('point', 2, ancestry, conversion_scale)
    if not pts:
        return None
    bpymesh = bpy.data.meshes.new(name="Polypoint2D")
    bpymesh.vertices.add(len(pts))
    bpymesh.vertices.foreach_set('co', [c for p in pts for c in (p[0], p[1], 0.0)])
    bpymesh.update()
    return bpymesh


def importMesh_ArcClose2D(geom, ancestry):
    # Geometry2D: a filled arc, closed through the centre (closureType PIE, the default) or by its chord (CHORD).
    # Texture coordinates map the full circle's square onto the unit square, as for Disk2D.
    r = geom.getFieldAsFloat('radius', 1.0 * conversion_scale, ancestry, conversion_scale)
    start, span, full = _arc_angles(geom, ancestry)
    closure = (geom.getFieldAsString('closureType', 'PIE', ancestry) or 'PIE').strip().strip('"').upper()
    rim = _arc_points(r, start, span, full)
    verts = [(x, y, 0.0) for x, y in rim]
    if full:
        faces = [tuple(range(len(verts)))]
    elif closure == 'CHORD':
        faces = [tuple(range(len(verts)))]
    else:
        verts.append((0.0, 0.0, 0.0))
        faces = [tuple(range(len(verts)))]
    bpymesh = bpy.data.meshes.new(name="ArcClose2D")
    bpymesh.from_pydata(verts, [], faces)
    bpymesh.validate()
    if bpymesh.polygons and r:
        uv = []
        for poly in bpymesh.polygons:
            for vi in poly.vertices:
                x, y, _z = bpymesh.vertices[vi].co
                uv += [0.5 + 0.5 * x / r, 0.5 + 0.5 * y / r]
        bpymesh.uv_layers.new().data.foreach_set('uv', uv)
    bpymesh.update()
    return bpymesh


def importMesh_TriangleSet2D(geom, ancestry):
    # Geometry2D: every three vertices make a triangle; texture coordinates map the bounding box onto the unit square
    pts = geom.getFieldAsArray('vertices', 2, ancestry, conversion_scale)
    count = len(pts) // 3
    if not count:
        return None
    pts = pts[:3 * count]
    bpymesh = bpy.data.meshes.new(name="TriangleSet2D")
    bpymesh.from_pydata([(p[0], p[1], 0.0) for p in pts], [], [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(count)])
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    w, h = (max(xs) - min(xs)) or 1.0, (max(ys) - min(ys)) or 1.0
    uv = []
    for poly in bpymesh.polygons:
        for vi in poly.vertices:
            x, y, _z = bpymesh.vertices[vi].co
            uv += [(x - min(xs)) / w, (y - min(ys)) / h]
    bpymesh.uv_layers.new().data.foreach_set('uv', uv)
    bpymesh.validate()
    bpymesh.update()
    return bpymesh


# -----------------------------------------------------------------------------------
# Utilities for importShape


# Textures are processed elsewhere.
# TwoSidedMaterial's back fields and their X3D defaults: Blender gives one material to both sides of a face, so they are
# kept on the material as numbers (TWO_SIDED_PROPERTY) and written back; the front fields are the Blender material's
TWO_SIDED_BACK_FIELDS = {"backAmbientIntensity": 0.2, "backDiffuseColor": [0.8, 0.8, 0.8], "backEmissiveColor": [0.0, 0.0, 0.0],
                         "backShininess": 0.2, "backSpecularColor": [0.0, 0.0, 0.0], "backTransparency": 0.0,
                         "separateBackColor": False}


def two_sided_back_fields(mat, ancestry):
    """A TwoSidedMaterial's back fields that differ from the defaults, as numbers (colours as 3 numbers)."""
    fields = {}
    for name, default in TWO_SIDED_BACK_FIELDS.items():
        if isinstance(default, bool):
            value = mat.getFieldAsBool(name, default, ancestry)
        elif isinstance(default, list):
            value = [float(v) for v in mat.getFieldAsArray(name, 0, ancestry)[:3]]
            value = value if len(value) == 3 and all(math.isfinite(v) for v in value) else default
        else:
            value = mat.getFieldAsFloat(name, default, ancestry)
            value = float(value) if value is not None and math.isfinite(value) else default
        if value != default:
            fields[name] = value
    return fields


def appearance_CreateMaterial(vrmlname, mat, ancestry, is_vcol):
    # Given an X3D material, creates a Blender material.
    # texture is applied later, in appearance_Create().
    # All values between 0.0 and 1.0, defaults from VRML docs.
    if mat:
        mat_name = mat.getDefName()
        diff_color = classic_colour(mat.getFieldAsFloatTuple('diffuseColor', [0.8, 0.8, 0.8], ancestry))
        emit_color = classic_colour(mat.getFieldAsFloatTuple('emissiveColor', [0.0, 0.0, 0.0], ancestry))
        shininess = mat.getFieldAsFloat('shininess', 0.2, ancestry)
        alpha = 1.0 - mat.getFieldAsFloat('transparency', 0.0, ancestry)
        # ambientIntensity scales the lights' own ambientIntensity (0 by default in X3D): not mapped.
        specular_color = classic_colour(mat.getFieldAsFloatTuple('specularColor', [0.0, 0.0, 0.0], ancestry))
    else: # object with no appearance node (e.g. only vertex colors), thus use default diffuse material
        mat_name = None
        diff_color = [0.8, 0.8, 0.8]
        emit_color = [0.0, 0.0, 0.0]
        shininess = 0.2
        alpha = 1.0
        specular_color = [0.0, 0.0, 0.0]

    bpymat = bpy.data.materials.new((exported_material_name(mat) if mat_name else None) or vrmlname)
    if mat_name:
        bpymat[X3D_DEF_PROPERTY] = mat_name
    if mat:
        keep_host_metadata(bpymat, mat)
        bpymat[MATERIAL_MODEL_PROPERTY] = 'classic'   # a Material or TwoSidedMaterial: the 4.0 export writes one again
        if mat.getSpec() == 'TwoSidedMaterial':
            bpymat[TWO_SIDED_PROPERTY] = json.dumps(two_sided_back_fields(mat, ancestry), sort_keys=True)
    bpymat_wrap = node_shader_utils.PrincipledBSDFWrapper(bpymat, is_readonly=False)

    bpymat_wrap.base_color = diff_color
    bpymat_wrap.emission_color = emit_color
    # set emission strength to 1 if there is an emissive color
    if emit_color != [0.0, 0.0, 0.0]:
        node_tree = bpymat.node_tree
        bsdf_node = node_tree.nodes.get("Principled BSDF")
        if bsdf_node:
            bsdf_node.inputs["Emission Strength"].default_value = 1.0

    # X3D's Blinn-Phong specular (specularColor, shininess) as roughness and dielectric specular level and tint
    roughness, spec_level, spec_tint = phong_to_principled(shininess, specular_color)
    bpymat_wrap.roughness = roughness
    bsdf = bpymat_wrap.node_principled_bsdf
    if bsdf is not None:
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = spec_level
        if "Specular Tint" in bsdf.inputs:
            tint = bsdf.inputs["Specular Tint"]
            tint.default_value = tuple(spec_tint) + ((1.0,) if len(tint.default_value) == 4 else ())

    bpymat_wrap.alpha = alpha
    if alpha < 1.0:
        bpymat.surface_render_method = "BLENDED"

    if is_vcol: # fun fact: this little beast can exist without appearance node in x3d ffs
        node_vertex_color = bpymat.node_tree.nodes.new("ShaderNodeVertexColor")
        node_vertex_color.location = (-200, 300)
        node_vertex_color.layer_name = "ColorPerCorner"

        bpymat.node_tree.links.new(
            bpymat_wrap.node_principled_bsdf.inputs["Base Color"],
            node_vertex_color.outputs["Color"]
        )

    return bpymat_wrap


def appearance_CreateDefaultMaterial():
    # Just applies the X3D defaults. Used for shapes
    # without explicit material definition
    # (but possibly with a texture).

    bpymat = bpy.data.materials.new("Material")
    bpymat_wrap = node_shader_utils.PrincipledBSDFWrapper(bpymat, is_readonly=False)

    bpymat_wrap.roughness = 0.8
    bpymat_wrap.base_color = (0.8, 0.8, 0.8)
    # bpymat.mirror_color = (0, 0, 0)
    # bpymat.emit = 0

    # TODO: handle 'shininess' and 'specularColor'.
    # bpymat.specular_hardness = 103
    # 0-1 -> 1-511
    # bpymat.specular_color = (0, 0, 0)

    bpymat_wrap.alpha = 1.0
    return bpymat_wrap


def web_resource_download_helper(url, default_ext, default_name, output_path=None):
    """ Downloads a web resource from a url and saves it to output_path on disk. E.g. image file """
    if not bpy.app.online_access: # web download requires network permission which is not always granted
        logger.warning("Can't download web resource: online access denied by user")
        return None

    cached_path = download_cache.get(url)
    if cached_path and os.path.isfile(cached_path):
        return cached_path

    from .import_resources import download_resource

    try:
        full_path = download_resource(url, directory=output_path,
                                      default_extension=default_ext, name=default_name)
        download_cache[url] = full_path
        return full_path
    except Exception as e:
        logger.warning(f"Failed to download web resource: {e}")
        return None


def download_image(url, output_path=None):
    """
    Downloads an image from the web and saves it to disk.
    """
    return web_resource_download_helper(url, '.jpg', "downloaded_image", output_path=output_path)


def appearance_LoadImageTextureFile(ima_urls, node):
    bpyima = None

    for f in ima_urls:
        if f.startswith(('https://', 'http://', 'www.')): # url could be a web url > download image first
            f = download_image(f, os.path.dirname(current_file_path)) or f
        dirname = os.path.dirname(node.getFilename())
        from .file_safety import special_file_reason
        reason = special_file_reason(f if os.path.isabs(f) else os.path.join(dirname, f))
        if reason:      # /dev/zero imported, and the COPY re-export then filled the disk (chaos round 2.7.3)
            logger.warning("Not loading texture %r: %s", f, reason)
            continue
        bpyima = image_utils.load_image(f, dirname,
                                        place_holder=False,
                                        recursive=False,
                                        convert_callback=imageConvertCompat)
        if bpyima:
            break

    return bpyima


def appearance_LoadImageTexture(imageTexture, ancestry, node):
    # TODO: cache loaded textures...
    ima_urls = imageTexture.getFieldAsMFStringArray('url', None, ancestry)

    # ima_urls is a list or None
    if ima_urls is None:
        logger.warning("warning, image with no URL, this is odd")
        return None
    else:
        bpyima = appearance_LoadImageTextureFile(ima_urls, node)

        if not bpyima:
            logger.warning("ImportX3D : unable to load texture from %s" % ima_urls)
        else:
            if bpyima.depth not in {32, 128}:
                bpyima.alpha_mode = 'NONE'
        return bpyima


def appearance_LoadTexture(tex_node, ancestry, node):
    # Both USE-based caching and desc-based caching
    # Works for bother ImageTextures and PixelTextures

    # USE-based caching
    if tex_node.reference:
        real = tex_node.getRealNode()
        if real.parsed is not None:
            return real.parsed
        tex_node = real   # the DEF'd node was not loaded yet (a material met first through its USE)

    # Desc-based caching. It might misfire on multifile models, where the
    # same desc means different things in different files.
    # TODO: move caches to file level.
    desc = tex_node.desc()
    if desc and desc in texture_cache:
        bpyima = texture_cache[desc]
        if tex_node.canHaveReferences():
            tex_node.parsed = bpyima
        return bpyima

    # No cached texture, load it.
    if tex_node.getSpec() == 'ImageTexture' or tex_node.getSpec() == 'MovieTexture':
        bpyima = appearance_LoadImageTexture(tex_node, ancestry, node)
    else:  # PixelTexture
        bpyima = appearance_LoadPixelTexture(tex_node, ancestry)

    if bpyima:  # Loading can still fail
        # Update the desc-based cache
        if desc:
            texture_cache[desc] = bpyima

        # Update the USE-based cache
        if tex_node.canHaveReferences():
            tex_node.parsed = bpyima

    return bpyima


def appearance_ExpandCachedMaterial(bpymat):
    if 0 and bpymat.texture_slots[0] is not None:
        bpyima = bpymat.texture_slots[0].texture.image
        tex_has_alpha = bpyima.alpha_mode not in {'NONE', 'CHANNEL_PACKED'}
        return (bpymat, bpyima, tex_has_alpha)

    return (bpymat, None, False)


def appearance_MakeDescCacheKey(material, tex_node):
    mat_desc = material.desc() if material else "Default"
    tex_desc = tex_node.desc() if tex_node else "Default"

    if not ((tex_node and tex_desc is None) or
            (material and mat_desc is None)):
        # desc not available (in VRML)
        # TODO: serialize VRML nodes!!!
        return (mat_desc, tex_desc)
    elif not tex_node and not material:
        # Even for VRML, we cache the null material
        return ("Default", "Default")
    else:
        return None  # Desc-based caching is off


def rotate_image_texture(bpymat_wrap, bpyima):
    node_tree = bpymat_wrap.material.node_tree
    for node in node_tree.nodes:
        # search for image node
        if node.type == 'TEX_IMAGE' and node.image == bpyima:
            # append new nodes
            node_tex_coord = node_tree.nodes.new("ShaderNodeTexCoord")
            node_mapping = node_tree.nodes.new("ShaderNodeMapping")
            node_mapping.vector_type = 'POINT'
            node_mapping.inputs['Rotation'].default_value = (0, 0, 0)
            node_tree.links.new(node_tex_coord.outputs["UV"], node_mapping.inputs["Vector"])
            node_tree.links.new(
                node_mapping.outputs["Vector"],
                node.inputs["Vector"]
            )
            # adjust node locations
            node_mapping.location.x -= 500
            node_mapping.location.y += 300
            node_tex_coord.location.x -= 700
            node_tex_coord.location.y += 300
            node.location.y -= 300
            break
    return bpymat_wrap


def apply_video_texture_settings(bpymat_wrap, bpyima, tex_node, ancestry):
    loop = tex_node.getFieldAsBool('loop', False, ancestry)
    start_time_seconds = tex_node.getFieldAsFloat('startTime', 0.0, ancestry)  # 0: play at start
    stop_time_seconds = tex_node.getFieldAsFloat('stopTime', -1.0, ancestry)  # -1: play to end
    # unfortunately speed can't be applied to image texture node (yet)
    # speed = tex_node.getFieldAsFloat('speed', 1.0, ancestry)

    fps = bpy.context.scene.render.fps
    start_frame = int(0 + start_time_seconds * fps)
    end_frame = bpyima.frame_duration if stop_time_seconds == - 1 else int((bpyima.frame_duration / fps) * stop_time_seconds)

    node_tree = bpymat_wrap.material.node_tree
    for node in node_tree.nodes:
        # search for image node
        if node.type == 'TEX_IMAGE' and node.image == bpyima:
            image_user = node.image_user
            image_user.use_auto_refresh = True
            image_user.use_cyclic = loop
            image_user.frame_start = start_frame
            image_user.frame_duration = end_frame
            node.location.y -= 300
            break
    return bpymat_wrap


def appearance_Create(vrmlname, material, tex_node, ancestry, node, is_vcol):
    # Creates a Blender material object from appearance
    bpyima = None
    tex_has_alpha = False

    if material:
        bpymat_wrap = appearance_CreateMaterial(vrmlname, material, ancestry, is_vcol)
    else:
        bpymat_wrap = appearance_CreateDefaultMaterial()

    if tex_node:  # Texture caching inside there
        bpyima = appearance_LoadTexture(tex_node, ancestry, node)

    if bpyima:
        repeatS = tex_node.getFieldAsBool('repeatS', True, ancestry)
        repeatT = tex_node.getFieldAsBool('repeatT', True, ancestry)

        bpymat_wrap.base_color_texture.image = bpyima

        if tex_node.getSpec() == 'ImageTexture':
            # insert a mapping and texture coordinate node, for adaptability by the user
            bpymat_wrap = rotate_image_texture(bpymat_wrap, bpyima)

        # NOTE - not possible to handle x and y tiling individually.
        extension = "REPEAT" if repeatS or repeatT else "CLIP"
        bpymat_wrap.base_color_texture.extension = extension

        tex_has_alpha = bpyima.alpha_mode not in {'NONE', 'CHANNEL_PACKED'}
        if tex_has_alpha:
            bpymat_wrap.alpha_texture.image = bpyima
            bpymat_wrap.alpha_texture.extension = extension

        if tex_node.getSpec() == 'MovieTexture':
            bpymat_wrap = apply_video_texture_settings(bpymat_wrap, bpyima, tex_node, ancestry)

        bsdf = bpymat_wrap.node_principled_bsdf
        if material and bsdf is not None and not is_vcol:
            # X_ITE draws diffuseColor x texture (getDiffuseColor: diffuseColor *= getDiffuseTexture()); linked straight
            # into Base Color the texture would replace the diffuse colour. A Color node replaces it there instead, and
            # a white diffuseColor needs no node; the socket keeps the colour as its value, where the export reads it.
            # Last, since the wrapper looks for its image node behind the Base Color link.
            _modulate_socket_by_color(bpymat_wrap.material.node_tree, bsdf.inputs["Base Color"],
                                      tuple(bsdf.inputs["Base Color"].default_value))

    return (bpymat_wrap.material, bpyima, tex_has_alpha)


# -----------------------------------------------------------------------------------
# X3D 4.0 PhysicalMaterial / UnlitMaterial (PBR) import


def _attribute_raw(x3d_node, name, default=None):
    """Read a plain attribute (not an SFString with quotes) from an X3D node."""
    real = x3d_node.getRealNode()
    attr = real.x3dNode.getAttributeNode(name) if getattr(real, "x3dNode", None) is not None else None
    return attr.value if attr else default


def _pbr_texture_children(mat_node):
    """Return {containerField: ImageTexture node} for a PhysicalMaterial/UnlitMaterial."""
    found = {}
    for child in mat_node.getRealNode().getChildrenBySpec(('ImageTexture', 'PixelTexture', 'MovieTexture')):
        # read from the child itself: a USE names its own field (a DEF'd baseTexture USE'd as emissiveTexture), and the
        # DEF'd node it points at says baseTexture
        element = getattr(child, "x3dNode", None)
        container = element.getAttribute('containerField') if element is not None else None
        if not container:
            # X3D 4.0 default containerField for a texture inside a material is baseTexture
            container = 'baseTexture'
        found[container] = child
    return found


def _place_image_node(node_tree, bpyima, location, label, non_color=False):
    image_node = node_tree.nodes.new("ShaderNodeTexImage")
    image_node.image = bpyima
    image_node.location = location
    image_node.label = label
    if non_color and bpyima is not None:
        try:
            bpyima.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass
    return image_node


def _modulate_socket_by_color(node_tree, socket, color):
    """Multiply what is linked into ``socket`` by a constant ``color``.

    X3D 4.0 materials modulate a texture by its colour field (an UnlitMaterial shows
    emissiveColor x emissiveTexture, as X_ITE draws it), but a texture linked straight
    into a Principled socket replaces the socket's colour. A white colour needs no node.
    The socket keeps the colour as its own default value, where the exporter reads it.
    """
    if socket is None or not socket.is_linked or all(abs(c - 1.0) < 1e-6 for c in color[:3]):
        return None
    link = socket.links[0]
    mix = node_tree.nodes.new("ShaderNodeMix")
    mix.data_type = 'RGBA'
    mix.blend_type = 'MULTIPLY'
    mix.label = "X3D colour"
    mix.location = (link.from_node.location.x + 300, link.from_node.location.y)
    mix.inputs[0].default_value = 1.0
    color_a, color_b = (s for s in mix.inputs if s.type == 'RGBA')
    color_b.default_value = (color[0], color[1], color[2], 1.0)
    node_tree.links.new(link.from_socket, color_a)
    node_tree.links.new(next(s for s in mix.outputs if s.type == 'RGBA'), socket)
    return mix


def _image_has_transparency(bpyima):
    """True when some pixel of the image is not opaque.

    X_ITE draws a texture as transparent only when its alpha is below 1 somewhere, so an
    RGBA image that is opaque everywhere stays opaque. Images without an alpha channel
    (JPEG, RGB PNG), movies and tiled images are not scanned, and an image is scanned
    once per import.
    """
    if bpyima is None or getattr(bpyima, "alpha_mode", "STRAIGHT") in {'NONE', 'CHANNEL_PACKED'}:
        return False
    try:
        if bpyima.source not in {'FILE', 'GENERATED'} or bpyima.depth in (24, 48, 96):
            return False
        key = bpyima.as_pointer()
        if key not in image_alpha_cache:
            image_alpha_cache[key] = False
            count = len(bpyima.pixels)
            if bpyima.channels == 4 and count >= 4:
                import numpy as np
                buffer = np.empty(count, dtype=np.float32)
                bpyima.pixels.foreach_get(buffer)
                image_alpha_cache[key] = bool((buffer[3::4] < 0.999).any())
        return image_alpha_cache[key]
    except Exception:  # an image that cannot be read stays opaque
        return False


def _link_texture_alpha(node_tree, bsdf, bpyima, alpha):
    """Feed an image's alpha, times the material's 1 - transparency, into the Principled Alpha.

    X3D 4.0 draws alpha = (1 - transparency) x texture alpha, as X_ITE does. The Alpha socket
    keeps 1 - transparency as its default value and the Multiply node's first input stays 1,
    so the exporter still reads the material's transparency.
    """
    socket = bsdf.inputs.get("Alpha")
    image_node = next((n for n in node_tree.nodes if n.type == 'TEX_IMAGE' and n.image == bpyima), None)
    if socket is None or socket.is_linked or image_node is None:
        return False
    source = image_node.outputs["Alpha"]
    if alpha < 1.0:
        multiply = node_tree.nodes.new("ShaderNodeMath")
        multiply.operation = 'MULTIPLY'
        multiply.label = "X3D alpha"
        multiply.location = (image_node.location.x + 300, image_node.location.y - 260)
        multiply.inputs[0].default_value = 1.0
        multiply.inputs[1].default_value = alpha
        node_tree.links.new(source, multiply.inputs[0])
        source = multiply.outputs[0]
    node_tree.links.new(source, socket)
    return True


def exported_material_name(mat):
    """The Blender name for a material node: its DEF, without the MA_ this add-on's export adds.

    The export writes material X as <Appearance DEF="APP_X"><PhysicalMaterial DEF="MA_X"/>. Naming the Blender material
    MA_X made the next export write MA_MA_X (87 materials renamed per round trip of the export suite). Only that exact
    pattern is stripped (see exported_object_name); x3d_def keeps the DEF as written."""
    name = mat.getDefName()
    if name and name.startswith("MA_") and len(name) > 3:
        appearance = getattr(mat.getRealNode(), "parent", None)
        if appearance is not None and hasattr(appearance, "getDefName") and appearance.getDefName() == "APP_" + name[3:]:
            return name[3:]
    return name


def appearance_CreatePBRMaterial(vrmlname, mat, appr, ancestry, node):
    """Create a Principled (or Emission) Blender material from PhysicalMaterial / UnlitMaterial."""
    spec = mat.getSpec()
    unlit = spec == 'UnlitMaterial'
    mat_name = mat.getDefName()
    bpymat = bpy.data.materials.new(exported_material_name(mat) or vrmlname)
    if mat_name:
        bpymat[X3D_DEF_PROPERTY] = mat_name
    keep_host_metadata(bpymat, mat)
    bpymat_wrap = node_shader_utils.PrincipledBSDFWrapper(bpymat, is_readonly=False)
    node_tree = bpymat.node_tree
    bsdf = bpymat_wrap.node_principled_bsdf

    textures = _pbr_texture_children(mat)
    images = {}
    for container, tex_node in textures.items():
        try:
            images[container] = appearance_LoadTexture(tex_node, ancestry, node)
        except Exception as exc:  # keep the import going when one texture is missing
            logger.warning("Could not load %s for %s: %s", container, bpymat.name, exc)

    transparency = mat.getFieldAsFloat('transparency', 0.0, ancestry)
    alpha = max(0.0, min(1.0, 1.0 - transparency))

    if unlit:
        emissive = classic_colour(mat.getFieldAsFloatTuple('emissiveColor', [1.0, 1.0, 1.0], ancestry))
        bpymat_wrap.base_color = emissive
        bpymat_wrap.emission_color = emissive
        if bsdf:
            bsdf.inputs["Emission Strength"].default_value = 1.0
            # An unlit surface shows its emission only: no diffuse/specular response.
            bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            if "Specular IOR Level" in bsdf.inputs:
                bsdf.inputs["Specular IOR Level"].default_value = 0.0
        bpyima = images.get('emissiveTexture') or images.get('baseTexture')
        if bpyima is not None:
            bpymat_wrap.emission_color_texture.image = bpyima
            bpymat_wrap.emission_color_texture.image.colorspace_settings.name = 'sRGB'
            if bsdf:
                _modulate_socket_by_color(node_tree, bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission"), emissive)
    else:
        base_color = mat.getFieldAsFloatTuple('baseColor', [1.0, 1.0, 1.0], ancestry)
        emissive = mat.getFieldAsFloatTuple('emissiveColor', [0.0, 0.0, 0.0], ancestry)
        bpymat_wrap.base_color = base_color
        bpymat_wrap.metallic = mat.getFieldAsFloat('metallic', 1.0, ancestry)
        bpymat_wrap.roughness = mat.getFieldAsFloat('roughness', 1.0, ancestry)
        bpymat_wrap.emission_color = emissive
        if bsdf and tuple(emissive) != (0.0, 0.0, 0.0):
            bsdf.inputs["Emission Strength"].default_value = 1.0

        bpyima = images.get('baseTexture')
        if bpyima is not None:
            bpymat_wrap.base_color_texture.image = bpyima
            if bsdf:
                # X_ITE and glTF multiply the texture by baseColor; linked straight into Base Color the texture would
                # replace it (a white factor needs no node, and the socket keeps baseColor as its value for the export)
                _modulate_socket_by_color(node_tree, bsdf.inputs["Base Color"], base_color)

        bpyima = images.get('emissiveTexture')
        if bpyima is not None:
            bpymat_wrap.emission_color_texture.image = bpyima
            if bsdf:
                bsdf.inputs["Emission Strength"].default_value = 1.0
                # X_ITE and glTF multiply emissiveTexture by emissiveColor (see baseTexture above)
                _modulate_socket_by_color(node_tree, bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission"), emissive)

        bpyima = images.get('metallicRoughnessTexture')
        if bpyima is not None and bsdf:
            # glTF / X3D 4.0 packing: G = roughness, B = metallic
            image_node = _place_image_node(node_tree, bpyima, (-700, -200), "Metallic Roughness", non_color=True)
            separate = node_tree.nodes.new("ShaderNodeSeparateColor")
            separate.location = (-400, -200)
            node_tree.links.new(image_node.outputs["Color"], separate.inputs["Color"])
            node_tree.links.new(separate.outputs["Green"], bsdf.inputs["Roughness"])
            node_tree.links.new(separate.outputs["Blue"], bsdf.inputs["Metallic"])

        bpyima = images.get('occlusionTexture')
        if bpyima is not None:
            # Blender has no occlusion input on Principled; keep the map in the tree
            # so the exporter (and the user) can find it.
            occlusion_node = _place_image_node(node_tree, bpyima, (-700, -500), "Occlusion", non_color=True)
            occlusion_node.name = "Occlusion"
            strength = mat.getFieldAsFloat('occlusionStrength', 1.0, ancestry)
            value_node = node_tree.nodes.new("ShaderNodeValue")
            value_node.name = value_node.label = "occlusion_strength"
            value_node.location = (-700, -720)
            value_node.outputs[0].default_value = strength

    bpyima = images.get('normalTexture')
    if bpyima is not None:
        bpymat_wrap.normalmap_texture.image = bpyima
        bpymat_wrap.normalmap_strength = mat.getFieldAsFloat('normalScale', 1.0, ancestry)
        try:
            bpyima.colorspace_settings.name = 'Non-Color'
        except TypeError:
            pass

    bpymat_wrap.alpha = alpha
    alpha_mode = (_attribute_raw(appr, 'alphaMode', 'AUTO') or 'AUTO').strip().strip('"').upper()
    # The colour texture's alpha (the base texture's; an UnlitMaterial's emissive, else base, texture's)
    # multiplies 1 - transparency. With alphaMode BLEND or MASK any alpha channel is used; with AUTO,
    # the default, only an image with a pixel that is not opaque, as X_ITE decides.
    colour_image = (images.get('emissiveTexture') or images.get('baseTexture')) if unlit else images.get('baseTexture')
    texture_alpha = False
    if (bsdf is not None and colour_image is not None and colour_image.alpha_mode not in {'NONE', 'CHANNEL_PACKED'}
            and (alpha_mode in {'BLEND', 'MASK'} or (alpha_mode == 'AUTO' and _image_has_transparency(colour_image)))):
        texture_alpha = _link_texture_alpha(node_tree, bsdf, colour_image, alpha)
    if alpha_mode == 'BLEND' or (alpha_mode == 'AUTO' and (alpha < 1.0 or texture_alpha)):
        bpymat.surface_render_method = 'BLENDED'
    elif alpha_mode == 'MASK':
        bpymat.surface_render_method = 'DITHERED'
        cutoff = _attribute_raw(appr, 'alphaCutoff', None)
        if cutoff is not None and bsdf and bsdf.inputs["Alpha"].is_linked:
            try:
                threshold = float(cutoff)
            except ValueError:
                threshold = 0.5
            math_node = node_tree.nodes.new("ShaderNodeMath")
            math_node.operation = 'GREATER_THAN'
            math_node.inputs[1].default_value = threshold
            math_node.location = (-200, -400)
            alpha_link = next((link for link in node_tree.links if link.to_socket == bsdf.inputs["Alpha"]), None)
            if alpha_link is not None:
                source = alpha_link.from_socket
                node_tree.links.remove(alpha_link)
                node_tree.links.new(source, math_node.inputs[0])
                node_tree.links.new(math_node.outputs[0], bsdf.inputs["Alpha"])

    if unlit and bsdf is not None and alpha > 0.0:
        # transparency 1 stays Principled: Blender folds a Mix Shader whose factor is 0 into its Transparent BSDF before
        # the glTF exporter looks, so the unlit shape could not carry alpha 0, which the Principled one does (MASK)
        unlit_pbr_material(bpymat, bsdf, emissive)
    _apply_texture_wrap(bpymat, textures, images, ancestry)
    # Two-sided rendering follows the geometry's solid field, which importShape applies later.
    return bpymat


def _apply_texture_wrap(bpymat, textures, images, ancestry):
    """repeatS / repeatT of each PhysicalMaterial / UnlitMaterial texture as its image nodes' extension.

    The classic Material path set it (appearance_Create) but this one did not, so a clamped texture came back
    repeating, and the re-export, seeing the same image twice with the same wrap, wrote the clamped one as a USE of the
    repeating one. Blender has one extension for both axes: CLIP only when both repeat fields are false, as there."""
    if bpymat.node_tree is None:
        return
    wrap = {}
    for container, tex_node in textures.items():
        bpyima = images.get(container)
        if bpyima is None or tex_node.getSpec() == 'MovieTexture':
            continue
        repeat = tex_node.getFieldAsBool('repeatS', True, ancestry) or tex_node.getFieldAsBool('repeatT', True, ancestry)
        wrap[bpyima.name] = "REPEAT" if repeat else "CLIP"
    for image_node in bpymat.node_tree.nodes:
        if image_node.type == 'TEX_IMAGE' and image_node.image is not None and image_node.image.name in wrap:
            image_node.extension = wrap[image_node.image.name]


def importShape_LoadPBRAppearance(vrmlname, appr, mat_node, ancestry, node):
    if appr.reference and appr.getRealNode().parsed:
        return appearance_ExpandCachedMaterial(appr.getRealNode().parsed)
    if mat_node.reference and mat_node.getRealNode().parsed:
        return appearance_ExpandCachedMaterial(mat_node.getRealNode().parsed)
    cache_key = ("PBR", appr.desc())
    if cache_key in material_cache:
        bpymat = material_cache[cache_key]
    else:
        bpymat = appearance_CreatePBRMaterial(vrmlname, mat_node, appr, ancestry, node)
        material_cache[cache_key] = bpymat
    if appr.canHaveReferences():
        appr.parsed = bpymat
    if mat_node.canHaveReferences():
        mat_node.parsed = bpymat
    return (bpymat, None, False)


def _parsed_for_vcol(node, is_vcol):
    """The material a DEF'd Appearance or Material was built into, if it was built for a Shape with the same
    colour-node state (a classic material depends on it); a material of the X3D 4.0 path does not."""
    real = node.getRealNode()
    return real.parsed if real.parsed and real.parsed_vcol in (None, bool(is_vcol)) else None


def _set_parsed_for_vcol(node, bpymat, is_vcol):
    node.parsed = bpymat
    node.parsed_vcol = bool(is_vcol)


def importShape_LoadAppearance(vrmlname, appr, ancestry, node, is_vcol):
    """
    Material creation takes nontrivial time on large models.
    So we cache them aggressively.
    However, in Blender, texture is a part of material, while in
    X3D it's not. Blender's notion of material corresponds to
    X3D's notion of appearance.

    TextureTransform is not a part of material (at least
    not in the current implementation).

    USE on an Appearance node and USE on a Material node
    call for different approaches.

    Tools generate repeating, identical material definitions.
    Can't rely on USE alone. Repeating texture definitions
    are entirely possible, too.

    Vertex coloring is not a part of appearance, but the material
    depends on it: with a Color node the vertex colours feed Base
    Color, without one a texture is multiplied by the diffuse colour
    (appearance_Create). So every cache below is per is_vcol, and a
    material is shared only by Shapes that agree on it.

    So here's the caching structure:
    For USE on appearance, we store the material object
    in the appearance node.

    For USE on texture, we store the image object in the tex node.

    For USE on material with no texture, we store the material object
    in the material node.

    Also, we store textures by description in texture_cache.

    Also, we store materials by (material desc, texture desc)
    in material_cache.
    """
    # First, check entire-appearance cache
    if appr.reference and _parsed_for_vcol(appr, is_vcol):
        return appearance_ExpandCachedMaterial(appr.getRealNode().parsed)

    # X3D 4.0 physically based materials carry their textures as children
    pbr_material = appr.getChildBySpec(('PhysicalMaterial', 'UnlitMaterial'))
    if pbr_material:
        return importShape_LoadPBRAppearance(vrmlname, appr, pbr_material, ancestry, node)

    tex_node = appr.getChildBySpec(('ImageTexture', 'PixelTexture', 'MovieTexture'))
    # Other texture nodes are: MultiTexture
    # TwoSidedMaterial's front fields are Material's (ambientIntensity, diffuseColor, emissiveColor, shininess,
    # specularColor, transparency); its back* fields have no Blender counterpart on one mesh: they are kept on the
    # material for the export (TWO_SIDED_PROPERTY), and Blender draws both sides with the front.
    material = appr.getChildBySpec(('Material', 'TwoSidedMaterial'))
    if material is not None and material.getSpec() == 'TwoSidedMaterial' \
            and material.getFieldAsBool('separateBackColor', False, ancestry):
        logger.warning('ImportX3D: TwoSidedMaterial "%s": Blender draws the back with the front colours; the back '
                       'fields are kept for the X3D export', material.getDefName() or vrmlname)
    # We're ignoring FillProperties, LineProperties, and shaders

    # Check the USE-based material cache for textureless materials
    if material and material.reference and not tex_node and _parsed_for_vcol(material, is_vcol):
        return appearance_ExpandCachedMaterial(material.getRealNode().parsed)

    # Now the description-based caching: the same Material and texture, with and without a Color node, are two materials
    cache_key = appearance_MakeDescCacheKey(material, tex_node)
    if cache_key:
        cache_key = cache_key + (bool(is_vcol),)

    if cache_key and cache_key in material_cache:
        bpymat = material_cache[cache_key]
        # Still want to make the material available for USE-based reuse
        if appr.canHaveReferences():
            _set_parsed_for_vcol(appr, bpymat, is_vcol)
        if material and material.canHaveReferences() and not tex_node:
            _set_parsed_for_vcol(material, bpymat, is_vcol)
        return appearance_ExpandCachedMaterial(bpymat)

    # Done checking full-material caches. Texture cache may still kick in.
    # Create the material already
    (bpymat, bpyima, tex_has_alpha) = appearance_Create(vrmlname, material, tex_node, ancestry, node, is_vcol)

    # Update the caches
    if appr.canHaveReferences():
        _set_parsed_for_vcol(appr, bpymat, is_vcol)

    if cache_key:
        material_cache[cache_key] = bpymat

    if material and material.canHaveReferences() and not tex_node:
        _set_parsed_for_vcol(material, bpymat, is_vcol)

    return (bpymat, bpyima, tex_has_alpha)


def appearance_LoadPixelTexture(pixelTexture, ancestry):
    def extract_pixel_colors(data_string):
        """
        Read all hexadecimal pixel color values, distributed across multiple fields (mutliline)
        """
        # Use a regular expression to find all hexadecimal color values
        hex_pattern = re.compile(r'0x[0-9a-fA-F]{6}')
        pixel_colors = hex_pattern.findall(data_string)
        # Convert hexadecimal color values to integers
        pixel_colors = [int(color, 0) for color in pixel_colors]
        return pixel_colors

    image = pixelTexture.getFieldAsArray('image', 0, ancestry)
    # read width, height and plane_count value, assuming all are in one field called 'image' (singleline)
    if len(image) < 3:
        logger.warning("PixelTexture image has %d of its 3 header numbers; no texture", len(image))
        return None
    w = budget.count(image[0], "PixelTexture width")
    h = budget.count(image[1], "PixelTexture height")
    plane_count = budget.count(image[2], "PixelTexture components")
    if w == 0 or h == 0 or not budget.within(w * h, f"PixelTexture {w} x {h}"):
        return None
    has_alpha = plane_count in {2, 4}
    # get either hex color values (multiline) or regular color values (singleline)
    pixels = extract_pixel_colors(str(pixelTexture))  # converting to string may not be ideal, but works
    if len(pixels) == 0:
        pixels = image[3:]
    if len(pixels) != w * h:
        logger.warning(f"ImportX3D warning: pixel count in PixelTexture is off. Pixels: {len(pixels)}, Width: {w}, Height: {h}")

    bpyima = bpy.data.images.new("PixelTexture", w, h, alpha=has_alpha, float_buffer=True)
    bpyima["x3d_pixel_texture"] = plane_count     # written back as a PixelTexture (material.PIXEL_TEXTURE_PROPERTY)
    if not has_alpha:
        bpyima.alpha_mode = 'NONE'

    # as some image textures may have no pixel data, ignore those
    if len(pixels) != 0:
        # Conditional above the loop, for performance
        if plane_count == 3:  # RGB
            bpyima.pixels = [(cco & 0xff) / 255 for pixel in pixels
                             for cco in (pixel >> 16, pixel >> 8, pixel, 255)]
        elif plane_count == 4:  # RGBA
            bpyima.pixels = [(cco & 0xff) / 255 for pixel in pixels
                             for cco
                             in (pixel >> 24, pixel >> 16, pixel >> 8, pixel)]
        elif plane_count == 1:  # Intensity - does Blender even support that?
            bpyima.pixels = [(cco & 0xff) / 255 for pixel in pixels
                             for cco in (pixel, pixel, pixel, 255)]
        elif plane_count == 2:  # Intensity/alpha
            bpyima.pixels = [(cco & 0xff) / 255 for pixel in pixels
                             for cco
                             in (pixel >> 8, pixel >> 8, pixel >> 8, pixel)]
    bpyima.update()
    return bpyima


# Called from importShape to insert a data object (typically a mesh)
# into the scene
# object pointer -> its mesh/curve before _set_world_matrix baked shear into a copy; a USE of that Shape starts from it
_UNBAKED_DATA = {}


def _set_world_matrix(bpyob, matrix):
    """Give ``bpyob`` the world ``matrix``, keeping any shear.

    Nested X3D Transforms multiply to a matrix with shear when a rotated Transform sits inside a non-uniformly
    scaled one. An object's location/rotation/scale cannot hold shear, so assigning ``matrix_world`` dropped it and
    the geometry came in skewed. The object gets the nearest location/rotation/scale and the rest is baked into its
    mesh or curve, copied first when other objects share it (a USE elsewhere keeps the original)."""
    import numpy as np
    loc, rot, scale = matrix.decompose()
    nearest = Matrix.LocRotScale(loc, rot, scale)
    target = np.array(matrix, dtype=np.float64)
    size = max(np.abs(target).max(), 1e-30)
    data = bpyob.data
    if (np.abs(np.array(nearest, dtype=np.float64) - target).max() <= 1e-6 * size
            or not hasattr(data, "transform") or not all(s != 0.0 for s in scale)):
        matrix_safety.set_world_exact(bpyob, matrix)   # a flat axis keeps the file's rotation (chaos round 2.7.3)
        return
    rest = Matrix((np.linalg.inv(np.array(nearest, dtype=np.float64)) @ target).tolist())
    _UNBAKED_DATA[bpyob.as_pointer()] = data
    data = bpyob.data = data.copy()
    data.transform(rest)
    bpyob.matrix_world = nearest


def importShape_ProcessObject(
        bpycollection, vrmlname, bpydata, geom, geom_spec, node,
        bpymat, has_alpha, texmtx, ancestry,
        global_matrix, solidify, solidify_value, reused=False):

    # reused: a USE of geometry already built with this material (_shared_mesh); the mesh is final and only the new
    # object below links it
    if not reused:
        geom_name = geom.getDefName() if hasattr(geom, "getDefName") else None
        if geom_name:
            bpydata.name = geom_name[3:] if geom_name.startswith("ME_") and len(geom_name) > 3 else geom_name
            bpydata[X3D_DEF_PROPERTY] = geom_name
        else:
            bpydata.name = vrmlname + "_" + geom_spec

        # curves like IndexedLineSet can also have a material,
        # although it won't be visible until the curve has some depth
        if type(bpydata) == bpy.types.Curve:
            if bpymat:
                bpydata.materials.append(bpymat)

        if type(bpydata) == bpy.types.Mesh:
            # solid, as understood by the spec, is always true in Blender
            # solid=false, we don't support it yet.
            creaseAngle = geom.getFieldAsFloat('creaseAngle', None, ancestry)
            if creaseAngle is not None and not bpydata.has_custom_normals:
                bpydata.set_sharp_from_angle(angle=creaseAngle)
            elif geom_spec in SMOOTH_PRIMITIVES and not bpydata.has_custom_normals:
                smooth_primitive(bpydata, geom_spec)
            elif bpydata.has_custom_normals:
                pass  # the file's normals decide; flat faces would re-split the corner fans (see importMesh_IndexedFaceSet)
            else:
                bpydata.polygons.foreach_set("use_smooth", [False] * len(bpydata.polygons))

            # Only ever 1 material per shape
            if bpymat:
                bpydata.materials.append(bpymat)

            if bpydata.uv_layers:
                if has_alpha and bpymat:
                    bpymat.surface_render_method = "BLENDED"

                if texmtx:
                    # Apply texture transform?
                    uv_copy = Vector()
                    for l in bpydata.uv_layers.active.data:
                        luv = l.uv
                        uv_copy.x = luv[0]
                        uv_copy.y = luv[1]
                        l.uv[:] = (uv_copy @ texmtx)[0:2]

            # Done transforming the texture
            # TODO: check if per-polygon textures are supported here.
        elif type(bpydata) == bpy.types.TextCurve:
            # Text with textures??? Not sure...
            if bpymat:
                bpydata.materials.append(bpymat)

    # Can transform data or object, better the object so we can instance
    # the data
    # bpymesh.transform(getFinalMatrix(node))
    bpyob = node.blendObject = bpy.data.objects.new(vrmlname, bpydata)
    _set_world_matrix(bpyob, getFinalMatrix(node, None, ancestry, global_matrix))
    # solidify modifier
    if solidify and bpyob.type == 'MESH':
        solidify_modifier = bpyob.modifiers.new(name="Solidify", type='SOLIDIFY')
        solidify_modifier.thickness = solidify_value
        solidify_modifier.offset = 0
    bpycollection.objects.link(bpyob)
    bpyob.select_set(True)

    if bpyob.type == 'FONT':
        process_font_object(bpyob)

    if DEBUG:
        bpyob["source_line_no"] = geom.lineno


def process_font_object(bpyob):
    """Set style attributes of text object"""
    if bpyob.data["bold"] or (bpyob.data["italic"]):
        bpy.context.view_layer.objects.active = bpyob
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.font.select_all()
        if bpyob.data["bold"]:
            bpy.ops.font.style_toggle(style='BOLD')
            del bpyob.data["bold"]
        if bpyob.data["italic"]:
            bpy.ops.font.style_toggle(style='ITALIC')
            del bpyob.data["italic"]
        bpy.ops.object.mode_set(mode='OBJECT')


def importText(geom, ancestry):
    fmt = geom.getChildBySpec('FontStyle')
    if fmt:
        size = fmt.getFieldAsFloat("size", 1, ancestry)
        horizontal_alignment = fmt.getFieldAsMFStringArray("justify", [], ancestry)
        line_height = fmt.getFieldAsFloat("spacing", 1, ancestry)
        # style is an SFString in X3D 4.0 (BOLD) and was an MFString before ("BOLD"): read either
        style = fmt.getFieldAsString("style", "PLAIN", ancestry).replace('"', " ").replace("'", " ").split() or None
        family = fmt.getFieldAsMFStringArray("family", None, ancestry)
    else:
        size = 1
        horizontal_alignment = "BEGIN"
        line_height = 1
        style = None
        family = None

    body = geom.getFieldAsMFStringArray("string", [], ancestry)
    logger.debug("importText : body: |%r|" % body)

    bpytext = bpy.data.curves.new(name="Text", type='FONT')
    bpytext.offset_y = - size
    bpytext.body = "\n".join(body)
    bpytext.size = size
    bpytext.space_line = line_height
    for align in horizontal_alignment:
        if align == "BEGIN":
            bpytext.align_x = "LEFT"
            break
        elif align == "MIDDLE":
            bpytext.align_x = "CENTER"
            break
        elif align == "END":
            bpytext.align_x = "RIGHT"
            break

    # set style as temp attribute for later, as we need an object to set it
    bpytext["bold"] = False
    bpytext["italic"] = False
    if style is not None:
        for s in style:
            if s == "BOLD":
                bpytext["bold"] = True
            elif s == "ITALIC":
                bpytext["italic"] = True
            elif s == "BOLDITALIC":
                bpytext["bold"] = True
                bpytext["italic"] = True

    # search for and set font family
    if family is not None:
        # user may provide multiple fonts, choose the first valid one
        for font in family:
            # convert x3d defaults to system fonts
            if font.upper() == "SANS":
                font = "Arial"
            elif font.upper() == "SERIF":
                font = "Times New Roman"
            elif font.upper() == "TYPEWRITER":
                font = "Courier New"
            else:
                # our search works without extensions, so they need to get removed if provided by the user
                for extension in [".ttf", ".otf", ".woff", ".woff2"]:
                    font = ''.join(font.rsplit(extension, maxsplit=1))
            font_path = search_for_font_file(font)
            if font_path:
                if font_path is not None:
                    if font_path["regular"] not in bpy.data.fonts:
                        font_regular = bpy.data.fonts.load(font_path["regular"])
                    else:
                        font_regular = bpy.data.fonts[font_path["regular"]]
                    if font_path["bold"] not in bpy.data.fonts:
                        font_bold = bpy.data.fonts.load(font_path["bold"])
                    else:
                        font_bold = bpy.data.fonts[font_path["bold"]]
                    if font_path["italic"] not in bpy.data.fonts:
                        font_italic = bpy.data.fonts.load(font_path["italic"])
                    else:
                        font_italic = bpy.data.fonts[font_path["italic"]]
                    if font_path["bold_italic"] not in bpy.data.fonts:
                        font_bolditalic = bpy.data.fonts.load(font_path["bold_italic"])
                    else:
                        font_bolditalic = bpy.data.fonts[font_path["bold_italic"]]
                    bpytext.font = font_regular
                    bpytext.font_bold = font_bold
                    bpytext.font_italic = font_italic
                    bpytext.font_bold_italic = font_bolditalic
                    break

    return bpytext


def search_for_font_file(font_name_spec):
    """Searches cached and system font files for supplied font family name"""
    # check cached fonts beforehand
    if font_name_spec in font_variants_cache:
        return font_variants_cache[font_name_spec]

    # well, font not yet cached, thus do a search
    import platform
    from pathlib import Path
    def get_font_paths():
        """Determine platform-specific font paths."""

        if platform.system() == "Windows":
            font_paths = [
                "C:\\Windows\\Fonts",
                str(Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts")
            ]
        elif platform.system() == "Darwin":  # macOS
            font_paths = ["/Library/Fonts", "~/Library/Fonts"]
        elif platform.system() == "Linux":
            font_paths = ["/usr/share/fonts", "~/.fonts", "~/.local/share/fonts"]
        else:
            font_paths = []
        return font_paths

    def load_all_fonts(font_path):
        """Cache all font files in the specified directory."""

        valid_extensions = [".ttf", ".otf", ".woff", ".woff2"]
        font_files = []

        for root, _, files in os.walk(os.path.expanduser(font_path)):
            for file in files:
                if any(file.lower().endswith(ext) for ext in valid_extensions):
                    font_files.append(os.path.join(root, file))

        return font_files

    def find_font_variants(font_name, curr_dir):
        """Find font variants with fallback to regular font variant if others are not found."""

        style_keywords = {
            "regular": ["regular", "book", "normal"],
            "bold": ["bold", "b", "bd"],
            "italic": ["italic", "oblique", "i"],
            "bold_italic": ["bolditalic", "boldoblique", "bi"]
        }

        font_paths = get_font_paths()

        def find_font_by_style(indexed_font_files, font_name_str, keywords, allow_no_keyword=False):
            """Search for a specific style of font in the provided files list."""

            lower_font = font_name_str.lower()

            for fuzzy_font in [lower_font, lower_font[:5], lower_font[:4]]:
                # Case A: Exact match without keyword (only if `allow_no_keyword` is True)
                # this will hopefully always find the regular font variant
                if allow_no_keyword:
                    for font in indexed_font_files:
                        if Path(font).stem.lower() == fuzzy_font:
                            return font

                # Case B: Exact match with style keyword in the filename
                # this will most likely find all font variants
                for font in font_files:
                    for keyword in keywords:
                        if Path(font).stem.lower() == (fuzzy_font + keyword):
                            return font

                # Case C: Name and style keyword somewhere in the filename
                # not ideal, but a fallback to get a somewhat similar font (at least by name)
                for font in indexed_font_files:
                    if fuzzy_font in Path(font).stem.lower() and \
                        any(keyword in Path(font).stem.lower() for keyword in keywords):
                        return font

            return None

        fonts = {"regular": None, "bold": None, "italic": None, "bold_italic": None}

        # Try finding each style in each path until a match is found.
        fonts_found = False
        for font_path in font_paths:
            font_files = load_all_fonts(font_path)
            if not font_files:
                continue

            # Search for each font style
            fonts["regular"] = fonts["regular"] or find_font_by_style(font_files, font_name, style_keywords["regular"],
                                                                      allow_no_keyword=True)
            fonts["bold"] = fonts["bold"] or find_font_by_style(font_files, font_name, style_keywords["bold"])
            fonts["italic"] = fonts["italic"] or find_font_by_style(font_files, font_name, style_keywords["italic"])
            fonts["bold_italic"] = fonts["bold_italic"] or find_font_by_style(font_files, font_name,
                                                                              style_keywords["bold_italic"])

            # If at least one style is found, no need to check further paths
            # as the font variants are usually installed in the same dir
            fonts_found = any(value is not None for value in fonts.values())
            if fonts_found:
                break

        # Fallback: try a fast lookup of the font name inside the current directory
        # we don't want to do a full search, as the size of the directory can be quite large and thus indexing would take too much time
        if not fonts_found:
            for extension in [".ttf", ".otf", ".woff", ".woff2"]:
                font_file = Path(curr_dir + font_name + extension)
                if font_file.is_file():
                    fonts["regular"] = fonts["bold"] = fonts["italic"] = fonts["bold_italic"] = font_file
                    return fonts

        # Fallback: replace None entries with the regular font if available
        regular_font = fonts["regular"]
        if regular_font is not None:
            for style in fonts:
                if fonts[style] is None:
                    fonts[style] = regular_font
            return fonts

        if all(fonts.values()):
            return fonts

        logger.warning("No font file found")
        return None

    try:
        font_variants = find_font_variants(font_name_spec, current_file_path)
    except Exception as e:
        logger.exception(e)
        font_variants = None

    # save to cache, so it can be reused for other text objects
    font_variants_cache[font_name_spec] = font_variants

    return font_variants


# -----------------------------------------------------------------------------------


geometry_importers = {
    'IndexedFaceSet': importMesh_IndexedFaceSet,
    'IndexedTriangleSet': importMesh_IndexedTriangleSet,
    'IndexedTriangleStripSet': importMesh_IndexedTriangleStripSet,
    'IndexedTriangleFanSet': importMesh_IndexedTriangleFanSet,
    'IndexedLineSet': importMesh_IndexedLineSet,
    'TriangleSet': importMesh_TriangleSet,
    'TriangleStripSet': importMesh_TriangleStripSet,
    'TriangleFanSet': importMesh_TriangleFanSet,
    'LineSet': importMesh_LineSet,
    'ElevationGrid': importMesh_ElevationGrid,
    'GeoElevationGrid': importMesh_GeoElevationGrid,
    'Extrusion': importMesh_Extrusion,
    'PointSet': importMesh_PointSet,
    'Sphere': importMesh_Sphere,
    'Box': importMesh_Box,
    'Cylinder': importMesh_Cylinder,
    'Cone': importMesh_Cone,
    'Rectangle2D': importMesh_Rectangle2D,
    'Disk2D': importMesh_Disk2D,
    'ArcClose2D': importMesh_ArcClose2D,
    'TriangleSet2D': importMesh_TriangleSet2D,
    'Arc2D': importMesh_Arc2D,
    'Circle2D': importMesh_Circle2D,
    'Polyline2D': importMesh_Polyline2D,
    'Polypoint2D': importMesh_Polypoint2D,
    'IndexedQuadSet': importMesh_IndexedQuadSet,
    'QuadSet': importMesh_QuadSet,
    'Text': importText,
}


# The file's own identity, kept on each Blender object (and so in the glTF node extras with export_extras): Blender
# suffixes duplicate names (.001), flat import drops Transforms, so the object name alone is not the DEF.
X3D_DEF_PROPERTY = "x3d_def"            # the node's DEF, else the nearest DEF'd Transform above it (what names the object)
X3D_DEF_PATH_PROPERTY = "x3d_def_path"  # DEF'd ancestors, outermost first, "/"-joined (flat import makes no empties for them)
X3D_USE_PROPERTY = "x3d_use"            # the DEF this instance's USE points at


def tag_x3d_identity(bpyob, node, ancestry):
    """Record on ``bpyob`` the DEF names it came from. Always rewritten: a USE copy inherits its DEF's tags."""
    if bpyob is None:
        return
    chain = [name for name in (a.getRealNode().getDefName() for a in ancestry) if name]  # real name: a USE's own reads "USE_x"
    is_use = node.getRealNode() is not node
    own = None if is_use else node.getDefName()
    name = own or (chain[-1] if chain else None)
    for key, value in ((X3D_DEF_PROPERTY, name), (X3D_DEF_PATH_PROPERTY, "/".join(chain)),
                       (X3D_USE_PROPERTY, node.getRealNode().getDefName() if is_use else None)):
        if value:
            bpyob[key] = value
        elif key in bpyob:
            del bpyob[key]


def importMetadata(node, ancestors=()):
    """An X3D (XML) Metadata* node as nested dicts for a custom property: the node type, name and reference, and
    ``value``, the field's X3D text (for MetadataSet, its members). The X3D 4.0 export writes it back.

    USE nodes are resolved; a set that contains itself through USE, which X3D does not allow, is cut there."""
    real = node.getRealNode()
    tree = {"node": real.getSpec()}
    if real.getDefName():
        tree["def"] = real.getDefName()
    for field in ("name", "reference"):
        text = _attribute_raw(real, field, None)
        if text is not None:
            tree[field] = text
    if tree["node"] == "MetadataSet":
        inside = ancestors + (real,)
        members = []
        for child in real.children:
            # members use containerField value; a child marked containerField metadata describes the set itself.
            # The attribute is read from the element itself, since a USE can name a different field than its DEF.
            container = child.x3dNode.getAttribute("containerField") or "value"
            if child.getSpec() in METADATA_NODE_TYPES and container != "metadata" and child.getRealNode() not in inside:
                members.append(importMetadata(child, inside))
        tree["value"] = members
    else:
        text = _attribute_raw(real, "value", None)
        if text is not None:
            tree["value"] = text
    return tree


def host_metadata(node):
    """The nested-dict form of ``node``'s own Metadata* child (its metadata field), or None. Never raises: metadata
    must not stop an import."""
    real = node.getRealNode()
    if getattr(real, "x3dNode", None) is None:   # Classic VRML: no element to read containerField from
        return None
    for child in real.children:
        if child.getSpec() in METADATA_NODE_TYPES and getattr(child.getRealNode(), "x3dNode", None) is not None:
            try:
                return importMetadata(child)
            except (TypeError, ValueError, RecursionError) as exc:
                logger.warning("Metadata of %s %r not kept: %s", real.getSpec(), real.getDefName(), exc)
                return None
    return None


def keep_host_metadata(idblock, node, key=METADATA_PROPERTY):
    """Store ``node``'s Metadata* child on ``idblock`` under ``key`` and mark the node as placed."""
    if idblock is None:
        return
    tree = host_metadata(node)
    if tree is not None:
        idblock[key] = tree
        _METADATA_PLACED.add(id(node.getRealNode()))


# real nodes whose Metadata found a Blender object or material during this import (reset by the outermost load_web3d)
_METADATA_PLACED = set()
_MATERIAL_SPECS = frozenset(("Material", "PhysicalMaterial", "UnlitMaterial", "TwoSidedMaterial"))


def keep_scene_metadata(bpyscene, all_nodes):
    """Every Metadata* node whose host got no Blender object or material, kept on the scene (SCENE_METADATA_PROPERTY)
    so that an import never drops one silently. A Shape's is on its object and is not repeated here."""
    kept, seen = [], set()
    for node, ancestry in all_nodes:
        real = node.getRealNode()
        spec = real.getSpec()
        if spec == 'Shape' or spec in METADATA_NODE_TYPES or id(real) in seen or id(real) in _METADATA_PLACED:
            continue
        if any(a.getSpec() in ('HAnimHumanoid', 'ProtoDeclare', 'ExternProtoDeclare') for a in ancestry):
            continue
        tree = host_metadata(node)
        if tree is None:
            continue
        seen.add(id(real))
        entry = {"host": spec, "def": real.getDefName() or "",
                 "path": "/".join(n for n in (a.getRealNode().getDefName() for a in ancestry) if n), "metadata": tree}
        if spec == 'WorldInfo':
            for field in ("title", "info"):
                text = _attribute_raw(real, field, None)
                if text is not None:
                    entry[field] = text
        kept.append(entry)
    if kept:
        try:   # appended: an inlined file's hosts are stored before its parent's, and a second import adds its own
            bpyscene[SCENE_METADATA_PROPERTY] = [_plain(item) for item in bpyscene.get(SCENE_METADATA_PROPERTY, ())] + kept
        except (TypeError, ValueError) as exc:
            logger.warning("Scene-level Metadata not kept: %s", exc)
    return kept


def _plain(item):
    """An ID property group or array as plain dicts / lists (what assigning a list of dicts needs)."""
    if hasattr(item, "to_dict"):
        return item.to_dict()
    if hasattr(item, "to_list"):
        return item.to_list()
    return item


def _shared_mesh(geom, bpymat, texmtx):
    """The mesh a USE of this geometry can share, or None to build its own.

    The export writes one mesh used by several objects (linked duplicates, collection instances) as a DEF and USEs of
    it; building a new mesh per USE made each a copy, so the re-export wrote the geometry out again for every user. A
    USE shares the first mesh when it gets the same material and no TextureTransform (which is baked into the UVs, so
    such a USE needs its own UVs)."""
    if not geom.reference or texmtx is not None:
        return None
    cached = geom.getRealNode().shared_mesh
    if cached is None:
        return None
    mesh, material = cached
    try:
        mesh.name
    except ReferenceError:  # removed since (File > New between imports)
        return None
    if (material is None) != (bpymat is None) or (material is not None and material != bpymat):
        return None
    return mesh


def importShape(bpycollection, node, ancestry, global_matrix, solidify, solidify_value):
    global vertex_colours_linear
    # Under Shape, we can only have Appearance, MetadataXXX and a geometry node
    def isGeometry(spec):
        return spec != "Appearance" and not spec.startswith("Metadata")

    bpyob = node.getRealNode().blendObject

    if bpyob is not None:
        unbaked = _UNBAKED_DATA.get(bpyob.as_pointer())
        bpyob = node.blendData = node.blendObject = bpyob.copy()
        if unbaked is not None:  # the DEF copy carries its own shear in its data: start from the shared original
            bpyob.data = unbaked
        # Could transform data, but better the object so we can instance the data (unless the matrix has shear)
        _set_world_matrix(bpyob, getFinalMatrix(node, None, ancestry, global_matrix))
        bpycollection.objects.link(bpyob)
        bpyob.select_set(True)
        tag_x3d_identity(bpyob, node, ancestry)
        lit = lit_by_node.get(node.getRealNode())
        if lit is not None:   # each USE is a surface the lights reach, as the DEF is
            lit_surfaces.append((bpyob,) + lit)
        return

    vrmlname = node.getDefName()
    if not vrmlname:
        # Exporters usually DEF the enclosing Transform rather than the Shape;
        # reuse that name so object names survive a round trip.
        for parent in reversed(ancestry):
            parent_name = parent.getDefName() if hasattr(parent, "getDefName") else None
            if parent_name:
                vrmlname = parent_name[3:] if parent_name.startswith("OB_") and len(parent_name) > 3 else parent_name
                break
    if not vrmlname:
        vrmlname = 'Shape'

    appr = node.getChildBySpec('Appearance')
    geom = node.getChildBySpecCondition(isGeometry)
    if not geom:
        # Oh well, no geometry node in this shape
        return

    bpymat = None
    bpyima = None
    texmtx = None
    tex_has_alpha = False

    colour_node = geom.getChildBySpec(['Color', 'ColorRGBA'])
    is_vcol = colour_node is not None
    colour_kind = ('RGBA' if colour_node.getSpec() == 'ColorRGBA' else 'RGB') if is_vcol else None

    if appr:
        (bpymat, bpyima,
         tex_has_alpha) = importShape_LoadAppearance(vrmlname, appr,
                                                     ancestry, node,
                                                     is_vcol)

        textx = appr.getChildBySpec('TextureTransform')
        if textx:
            texmtx = translateTexTransform(textx, ancestry)
        if bpymat is not None and appr.getChildBySpec(('PhysicalMaterial', 'UnlitMaterial')):
            # X3D 4.0 path: a solid surface is single sided in Blender terms
            bpymat.use_backface_culling = geometry_solid(geom, ancestry)
            if colour_kind and geom.getSpec() not in LINE_POINT_SPECS \
                    and appr.getChildBySpec(('PhysicalMaterial', 'UnlitMaterial')).getSpec() == 'UnlitMaterial':
                # the Color / ColorRGBA replaces emissiveColor (see unlit_colour_material)
                alpha_mode = (_attribute_raw(appr, 'alphaMode', 'AUTO') or 'AUTO').strip().strip('"').upper()
                bpymat = unlit_colour_material(bpymat, colour_kind, alpha_mode)
            elif colour_kind and geom.getSpec() not in LINE_POINT_SPECS:
                bpymat = physical_colour_material(bpymat)
    elif is_vcol:
        # this may be a rare case, however sometimes vertex colors get used without material
        # in such case a default material has to get forced
        # for example https://projects.blender.org/extensions/io_scene_x3d/issues/70
        bpymat = appearance_CreateMaterial(vrmlname, None, ancestry, is_vcol).material

    bpydata = None
    geom_spec = geom.getSpec()
    if geom_spec not in LINE_POINT_SPECS and draws_unlit(appr):
        if bpymat is None:                     # no Appearance at all: X3D draws it white, unlit
            bpymat = appearance_CreateDefaultMaterial().material
        kind = colour_kind
        if kind == 'RGBA' and appr and (_attribute_raw(appr, 'alphaMode', 'AUTO') or 'AUTO').strip().strip('"').upper() == 'OPAQUE':
            kind = 'RGB'    # X_ITE takes the alpha from the geometry only under alphaMode AUTO (set_transparent__)
        bpymat = unlit_surface_material(bpymat, kind)

    # ccw is handled by every geometry importer separately; some
    # geometries are easier to flip than others
    geom_fn = geometry_importers.get(geom_spec)
    if geom_fn is not None:
        shared = _shared_mesh(geom, bpymat, texmtx)
        vertex_colours_linear = appr is not None and appr.getChildBySpec('PhysicalMaterial') is not None
        try:
            bpydata = shared if shared is not None else geom_fn(geom, ancestry)
        finally:
            vertex_colours_linear = False

        if bpydata is None:
            logger.warning('ImportX3D warning: empty shape, skipping node "%s"' % vrmlname)
            return
        if isinstance(bpydata, bpy.types.Mesh) and geom_spec not in LINE_POINT_SPECS:
            # the file's solid for the export to write back (D14): a classic Material's surface stays two-sided in Blender
            bpydata[SOLID_PROPERTY] = geometry_solid(geom, ancestry)
        if shared is None:
            mark_coordinate_double(bpydata, geom)

        if geom_spec in LINE_POINT_SPECS:
            rgb, alpha = x3d_unlit_colour(appr, ancestry)
            # a source moved aside by _name_derived_material keeps its cache key
            name = bpymat.name.removesuffix(".source") if bpymat is not None else (vrmlname or geom_spec)
            bpymat = line_point_material(name, rgb, alpha, line_colour_kind(bpydata), source=bpymat)
            line_properties = appr.getChildBySpec('LineProperties') if appr is not None else None
            line_width = line_properties.getFieldAsFloat('linewidthScaleFactor', None, ancestry) if line_properties else None
            point_properties = appr.getChildBySpec('PointProperties') if appr is not None else None
            point_properties = point_properties_fields(point_properties, ancestry) if point_properties else None

        # There are no geometry importers that can legally return
        # no object.  It's either a bpy object, or an exception
        importShape_ProcessObject(
            bpycollection, vrmlname, bpydata, geom, geom_spec,
            node, bpymat, tex_has_alpha, texmtx,
            ancestry, global_matrix, solidify, solidify_value, reused=shared is not None)
        if shared is None and texmtx is None and isinstance(bpydata, bpy.types.Mesh):
            geom.getRealNode().shared_mesh = (bpydata, bpymat)
        if texmtx is not None and isinstance(bpydata, bpy.types.Mesh) and PRIMITIVE_PROPERTY in bpydata:
            del bpydata[PRIMITIVE_PROPERTY]  # its UVs carry a TextureTransform the primitive would lose
        if appr is not None and geom_spec not in LINE_POINT_SPECS and node.blendObject is not None:
            lit = None
            if appr.getChildBySpec('PhysicalMaterial') is not None:
                lit = ('physical', None, None)
            elif appr.getChildBySpec(('Material', 'TwoSidedMaterial')) is not None:
                material = appr.getChildBySpec(('Material', 'TwoSidedMaterial'))
                lit = ('classic', material.getFieldAsFloatTuple('diffuseColor', (0.8, 0.8, 0.8), ancestry),
                       material.getFieldAsFloatTuple('emissiveColor', (0.0, 0.0, 0.0), ancestry))
            if lit is not None:
                lit_by_node[node.getRealNode()] = lit
                lit_surfaces.append((node.blendObject,) + lit)
        tag_x3d_identity(node.blendObject, node, ancestry)
        if geom_spec in LINE_POINT_SPECS and line_width is not None and node.blendObject is not None:
            node.blendObject[LINE_WIDTH_PROPERTY] = line_width   # Blender draws no line width; the 4.0 export writes it back
        if geom_spec in LINE_POINT_SPECS and point_properties and node.blendObject is not None:
            # Blender draws no point size either: kept as a custom property the 4.0 export writes back (batch 8)
            node.blendObject[POINT_PROPERTIES_PROPERTY] = json.dumps(point_properties, sort_keys=True)
        if not node.getFieldAsBool('castShadow', True, ancestry):
            # X3D 4.0 Shape castShadow: the object's shadow visibility in Blender
            node.blendObject.visible_shadow = False
        metadata = next((child for child in node.getRealNode().children if child.getSpec() in METADATA_NODE_TYPES), None)
        if metadata is not None and getattr(metadata.getRealNode(), "x3dNode", None) is not None:
            try:
                node.blendObject[METADATA_PROPERTY] = importMetadata(metadata)
            except (TypeError, ValueError, RecursionError) as exc:  # metadata must never stop the import
                logger.warning("Metadata of shape %r not kept: %s", vrmlname, exc)
    else:
        logger.warning('ImportX3D warning: unsupported type "%s"' % geom_spec)


# -----------------------------------------------------------------------------------
# Lighting

# The exporters write point and spot lights as energy / 1.75, so import undoes the division.
# They also clamp intensity to 1.0: the X3D 3.x writer always (the 3.x schema range), the X3D 4.0
# writer for lights made in Blender. Lights imported from X3D keep their intensity above 1 on the
# 4.0 path (see importLamp_SharedFields); energies above 1.75 clamped on the 3.x path are lost.
LIGHT_ENERGY_PER_INTENSITY = 1.75


def exported_object_name(node, ancestry, prefix):
    """The Blender name for a light or viewpoint: its DEF, without the prefix this add-on's export adds.

    The export writes object X's light as <Transform DEF="OB_X"><PointLight DEF="LA_X"/> (a camera: CA_X). Naming the
    object after the node's own DEF made it LA_X, which the next export wrote as OB_LA_X / LA_LA_X: one more prefix per
    round trip, and every ROUTE or Script naming the node broke. Only that exact pattern is stripped, so a hand-written
    DEF="LA_Lamp" keeps its name; x3d_def still records the DEF as written."""
    own = node.getDefName()
    if own and own.startswith(prefix) and len(own) > len(prefix):
        parent = next((a.getDefName() for a in reversed(ancestry) if hasattr(a, "getDefName") and a.getDefName()), None)
        if parent == "OB_" + own[len(prefix):]:
            return own[len(prefix):]
    return own


def importLamp_PointLight(node, ancestry):
    vrmlname = exported_object_name(node, ancestry, "LA_") or 'PointLight'

    # attenuation = node.getFieldAsFloatTuple('attenuation', (1.0, 0.0, 0.0), ancestry) # TODO
    color = node.getFieldAsFloatTuple('color', (1.0, 1.0, 1.0), ancestry)
    intensity = node.getFieldAsFloat('intensity', 1.0, ancestry)  # max is documented to be 1.0 but some files have higher.
    location = node.getFieldAsFloatTuple('location', (0.0, 0.0, 0.0), ancestry, conversion_scale)
    # is_on = node.getFieldAsBool('on', True, ancestry) # TODO
    radius = node.getFieldAsFloat('radius', 100.0, ancestry, conversion_scale)

    bpylamp = bpy.data.lights.new(vrmlname, 'POINT')
    bpylamp.energy = intensity * LIGHT_ENERGY_PER_INTENSITY
    bpylamp.cutoff_distance = radius
    bpylamp.color = color

    mtx = Matrix.Translation(Vector(location))

    return bpylamp, mtx


def importLamp_DirectionalLight(node, ancestry):
    vrmlname = exported_object_name(node, ancestry, "LA_") or 'DirectLight'

    color = node.getFieldAsFloatTuple('color', (1.0, 1.0, 1.0), ancestry)
    direction = node.getFieldAsFloatTuple('direction', (0.0, 0.0, -1.0), ancestry)
    intensity = node.getFieldAsFloat('intensity', 1.0, ancestry)  # max is documented to be 1.0 but some files have higher.
    # is_on = node.getFieldAsBool('on', True, ancestry) # TODO

    bpylamp = bpy.data.lights.new(vrmlname, 'SUN')
    bpylamp.energy = intensity  # sun strength is exported 1:1, see extract.py
    bpylamp.color = color

    # lamps have their direction as -z, yup
    mtx = Vector(direction).to_track_quat('-Z', 'Y').to_matrix().to_4x4()

    return bpylamp, mtx

# looks like default values for beamWidth and cutOffAngle were swapped in VRML docs.


def importLamp_SpotLight(node, ancestry):
    vrmlname = exported_object_name(node, ancestry, "LA_") or 'SpotLight'

    # attenuation = geom.getFieldAsFloatTuple('attenuation', (1.0, 0.0, 0.0), ancestry) # TODO
    beamWidth = node.getFieldAsFloat('beamWidth', 1.570796, ancestry)  # max is documented to be 1.0 but some files have higher.
    color = node.getFieldAsFloatTuple('color', (1.0, 1.0, 1.0), ancestry)
    cutOffAngle = node.getFieldAsFloat('cutOffAngle', 0.785398, ancestry) * 2.0  # max is documented to be 1.0 but some files have higher.
    direction = node.getFieldAsFloatTuple('direction', (0.0, 0.0, -1.0), ancestry)
    intensity = node.getFieldAsFloat('intensity', 1.0, ancestry)  # max is documented to be 1.0 but some files have higher.
    location = node.getFieldAsFloatTuple('location', (0.0, 0.0, 0.0), ancestry, conversion_scale)
    # is_on = node.getFieldAsBool('on', True, ancestry) # TODO
    radius = node.getFieldAsFloat('radius', 100.0, ancestry, conversion_scale)

    bpylamp = bpy.data.lights.new(vrmlname, 'SPOT')
    bpylamp.energy = intensity * LIGHT_ENERGY_PER_INTENSITY
    bpylamp.cutoff_distance = radius
    bpylamp.color = color
    bpylamp.spot_size = cutOffAngle
    # X3D's beamWidth and cutOffAngle are half angles; X_ITE (like glTF) lights the full intensity inside beamWidth
    # and falls off to zero at cutOffAngle, with a hard edge when beamWidth >= cutOffAngle. Blender's (and its glTF
    # exporter's) inner cone is spot_size / 2 x (1 - spot_blend), so the inner cone becomes beamWidth.
    half = cutOffAngle / 2.0
    bpylamp.spot_blend = 0.0 if half <= 0.0 or beamWidth >= half else 1.0 - beamWidth / half

    # Convert

    # lamps have their direction as -z, y==up
    mtx = Matrix.Translation(location) @ Vector(direction).to_track_quat('-Z', 'Y').to_matrix().to_4x4()

    return bpylamp, mtx


def importLamp_SharedFields(bpylamp, node, ancestry):
    """X3DLightNode fields common to every light type.

    X3D 4.0 ``shadows`` maps to the light's shadow switch; its X3D default is FALSE, so a light that
    does not ask for shadows gets none. ambientIntensity and shadowIntensity have no Blender setting:
    when the file sets them they are kept as custom properties for the X3D 4.0 export to write back.
    The file's intensity is kept too; it tells the X3D 4.0 export that the light came from X3D, so its
    intensity is written as is, also above 1, instead of being capped like a light made in Blender.
    """
    bpylamp.use_shadow = node.getFieldAsBool('shadows', False, ancestry)
    bpylamp[LIGHT_INTENSITY_PROPERTY] = node.getFieldAsFloat('intensity', 1.0, ancestry)
    for field, prop in (('ambientIntensity', LIGHT_AMBIENT_INTENSITY_PROPERTY),
                        ('shadowIntensity', LIGHT_SHADOW_INTENSITY_PROPERTY)):
        value = node.getFieldAsFloat(field, None, ancestry)
        if value is not None:
            bpylamp[prop] = value


def _light_scope_has_geometry(node, ancestry):
    """True when a light that is not global has a Shape (or an Inline, which may hold one) among its parent's other
    children, at any depth: X3D 4.0 lights those and nothing else. With no known parent it counts as lighting."""
    parent = ancestry[-1] if ancestry else None
    if parent is None:
        return True
    me = node.getRealNode()
    for sibling in parent.getRealNode().children:
        if sibling.getRealNode() is me:
            continue
        if sibling.findSpecRecursive('Shape') is not None or sibling.findSpecRecursive('Inline') is not None:
            return True
    return False


def importLamp(bpycollection, node, spec, ancestry, global_matrix):
    if spec == 'PointLight':
        bpylamp, mtx = importLamp_PointLight(node, ancestry)
    elif spec == 'DirectionalLight':
        bpylamp, mtx = importLamp_DirectionalLight(node, ancestry)
    elif spec == 'SpotLight':
        bpylamp, mtx = importLamp_SpotLight(node, ancestry)
    else:
        logger.warning("Error, not a lamp")
        raise ValueError
    importLamp_SharedFields(bpylamp, node, ancestry)
    # X3D 4.0 light scoping: Blender has none, so keep the file's `global` (point and spot lights default TRUE, directional
    # ones FALSE) and whether a light that is not global had any geometry in its scope, for the export (D1)
    given_global = node.getFieldAsBool('global', spec != 'DirectionalLight', ancestry)
    bpylamp[LIGHT_GLOBAL_PROPERTY] = bool(given_global)
    if not given_global:
        bpylamp[LIGHT_SCOPE_LIT_PROPERTY] = _light_scope_has_geometry(node, ancestry)

    bpyob = node.blendData = node.blendObject = bpy.data.objects.new(bpylamp.name, bpylamp)
    bpycollection.objects.link(bpyob)
    tag_x3d_identity(bpyob, node, ancestry)
    bpyob.select_set(True)

    matrix_safety.set_world_exact(bpyob, getFinalMatrix(node, mtx, ancestry, global_matrix))
    attenuation = None
    radius = 100.0
    frame = conversion_scale
    if spec != 'DirectionalLight':
        attenuation = node.getFieldAsFloatTuple('attenuation', None, ancestry)
        if attenuation is not None and len(attenuation) == 3:
            bpylamp[LIGHT_ATTENUATION_PROPERTY] = [float(a) for a in attenuation]
        else:
            attenuation = None
        # the file's radius (X3D's default 100; -1 is unlimited in X_ITE), kept in Blender units of the light's own
        # frame for the X3D exports to write back; the cutoff distance becomes the world-space range below
        radius = node.getFieldAsFloat('radius', 100.0, ancestry)
        bpylamp[LIGHT_RADIUS_PROPERTY] = radius * conversion_scale
        scale = bpyob.matrix_world.to_scale()
        frame = conversion_scale * (abs(scale[0]) + abs(scale[1]) + abs(scale[2])) / 3.0
        if radius > 0.0:
            bpylamp.cutoff_distance = radius * frame
    imported_lights.append((bpyob, spec, node.getFieldAsFloat('intensity', 1.0, ancestry), attenuation, radius, frame))


# -----------------------------------------------------------------------------------


def importGeoViewpoint_Matrix(node, orientation, bpycam, ancestry):
    """The X3D matrix of a GeoViewpoint, as X_ITE 16.7.1 places it: its position (default 0 0 100000) in the node's
    geoSystem, geocentric metres, and its orientation relative to the local east/up/south frame there (the default
    orientation looks north, with up away from the Earth). Sets the camera's clip range: nearDistance and farDistance
    when the file gives them, else from 1 % of the height above the ellipsoid out past the far side of the globe, since
    Blender's 0.1 to 1000 would clip all of it."""
    import numpy as np
    gs = geo_system_of(node, ancestry)
    position = np.array(geospatial.to_geocentric(
        gs, *node.getFieldAsFloatTuple('position', (0.0, 0.0, 100000.0), ancestry)))
    frame = geospatial.local_frame(gs, position)
    origin, origin_frame = geo_origin_of(node, gs, ancestry)
    if origin_frame is not None:
        frame = origin_frame.T @ frame
    rotation = Matrix(frame.tolist()).to_4x4() @ translateRotation(orientation)
    height = geospatial.geocentric_to_geodetic(gs, *position)[2]
    near = node.getFieldAsFloat('nearDistance', -1.0, ancestry)
    far = node.getFieldAsFloat('farDistance', -1.0, ancestry)
    bpycam.clip_start = (near if near > 0.0 else max(0.01 * height, 0.1)) * conversion_scale
    bpycam.clip_end = (far if far > 0.0 else np.linalg.norm(position) + gs.a) * conversion_scale
    return Matrix.Translation(Vector(geo_to_local(position, origin, origin_frame) * conversion_scale)) @ rotation


def importViewpoint(bpycollection, node, ancestry, global_matrix):
    name = exported_object_name(node, ancestry, "CA_") or 'Viewpoint'

    fieldOfView = node.getFieldAsFloat('fieldOfView', 0.785398, ancestry) if node.getSpec() != 'OrthoViewpoint' else None  # max is documented to be 1.0 but some files have higher.
    if fieldOfView is not None and not (0.0 < fieldOfView < math.pi):
        # X3D's range is (0, pi); INF raised "math domain error" in tan() and ended the import (chaos round, 22 Nov 2026)
        logger.warning("Viewpoint fieldOfView %r is outside (0, pi); using the default pi/4", fieldOfView)
        fieldOfView = 0.785398
    # jump = node.getFieldAsBool('jump', True, ancestry)
    orientation = node.getFieldAsFloatTuple('orientation', (0.0, 0.0, 1.0, 0.0), ancestry)
    description = node.getFieldAsString('description', '', ancestry)

    bpycam = bpy.data.cameras.new(name)

    if node.getSpec() == 'OrthoViewpoint':
        # fieldOfView is the four extents minX minY maxX maxY (default -1 -1 1 1). A browser keeps the whole box in
        # view and widens one side to the display's aspect, so ortho_scale spans the box at the render's aspect on
        # the camera's fitted side (the inverse of extract.ortho_extents). An off-centre box comes back centred.
        extents = node.getFieldAsFloatTuple('fieldOfView', (-1.0, -1.0, 1.0, 1.0), ancestry, conversion_scale)
        if len(extents) != 4 or extents[2] <= extents[0] or extents[3] <= extents[1]:
            extents = (-1.0, -1.0, 1.0, 1.0)
        size_x, size_y = extents[2] - extents[0], extents[3] - extents[1]
        width, height = render_size(bpy.context.scene)
        aspect = (float(width) / float(height)) if width and height else 1.0
        bpycam.type = 'ORTHO'
        # AUTO fits ortho_scale to the wider render side
        bpycam.ortho_scale = max(size_x, size_y * aspect) if aspect >= 1.0 else max(size_y, size_x / aspect)
    else:
        bpycam.angle = blender_camera_angle(fieldOfView, bpycam.sensor_fit, *render_size(bpy.context.scene))

    if node.getSpec() == 'GeoViewpoint':
        mtx = importGeoViewpoint_Matrix(node, orientation, bpycam, ancestry)
    else:
        position = node.getFieldAsFloatTuple('position', (0.0, 0.0, 0.0), ancestry, conversion_scale)
        mtx = Matrix.Translation(Vector(position)) @ translateRotation(orientation)

    bpyob = node.blendData = node.blendObject = bpy.data.objects.new(name, bpycam)
    bpycollection.objects.link(bpyob)
    tag_x3d_identity(bpyob, node, ancestry)
    bpyob.select_set(True)
    matrix_safety.set_world_exact(bpyob, getFinalMatrix(node, mtx, ancestry, global_matrix))
    global bound_view
    if bound_view is None and not _INLINE_STACK:   # the Viewpoint a browser binds first
        bound_view = bpyob
    if description:
        # Blender cameras have no description; keep it for the X3D 4.0 export to write back.
        bpyob[VIEWPOINT_DESCRIPTION_PROPERTY] = description


def importBackground(bpyscene, node, ancestry):
    """Keep a Background's sky and ground gradients on the scene for the X3D 4.0 export to write back.

    Blender has no gradient backdrop, and its world colour also lights a render, which an X3D Background
    does not, so the world is left as it is. The export writes this Background in place of one made from
    the world colour; deleting the scene's x3d_background property brings that back.
    """
    background = {"skyColor": [0.0, 0.0, 0.0]}  # the X3D default sky is black
    for field in ("skyColor", "skyAngle", "groundColor", "groundAngle"):
        values = node.getFieldAsArray(field, 0, ancestry)
        if values:
            background[field] = [float(value) for value in values]
    transparency = node.getFieldAsFloat('transparency', None, ancestry)
    if transparency is not None:
        background["transparency"] = transparency
    if node.getSpec() == 'TextureBackground':
        # the six faces are X3DTextureNodes: each ImageTexture or PixelTexture is loaded as a Blender image (the export
        # writes it from that image, through the same path handling as a material's textures); others are not kept
        background["node"] = 'TextureBackground'
        faces = {}
        for child in node.getRealNode().children:
            element = getattr(child, "x3dNode", None)
            field = element.getAttribute('containerField') if element is not None else ""
            if field not in TEXTURE_BACKGROUND_FIELDS:
                continue
            if child.getSpec() not in ('ImageTexture', 'PixelTexture'):
                logger.warning("TextureBackground %s: a %s is not imported", field, child.getSpec())
                continue
            image = appearance_LoadTexture(child, ancestry, node)
            if image is not None:
                faces[field] = image.name
        if faces:
            background["textures"] = faces
    bpyscene[BACKGROUND_PROPERTY] = background


TEXTURE_BACKGROUND_FIELDS = ('backTexture', 'bottomTexture', 'frontTexture', 'leftTexture', 'rightTexture', 'topTexture')
# what an X3D fogType becomes in Blender's mist falloff: LINEAR is the same ramp; X3D's EXPONENTIAL rises fastest near
# the viewer, as Blender's inverse quadratic does (there is no exponential falloff)
FOG_FALLOFF = {'LINEAR': 'LINEAR', 'EXPONENTIAL': 'INVERSE_QUADRATIC'}


def importFog(bpyscene, node, ancestry):
    """A Fog as the scene world's mist (Blender's Mist pass: start 0, depth visibilityRange, the falloff closest to
    fogType), with the Mist pass turned on so it can be seen; mist has no colour, so the colour is kept on the scene
    (FOG_PROPERTY) with the fogType the file gave. The X3D 4.0 export writes the Fog back from the mist and that record.
    A scene without a world keeps the record only (a new world would add a Background the file did not have)."""
    fog_type = (node.getFieldAsString('fogType', 'LINEAR', ancestry) or 'LINEAR').strip().upper()
    fog_type = fog_type if fog_type in FOG_FALLOFF else 'LINEAR'
    color = [float(v) for v in node.getFieldAsArray('color', 0, ancestry)[:3]]
    color = color if len(color) == 3 and all(math.isfinite(v) for v in color) else [1.0, 1.0, 1.0]
    distance = node.getFieldAsFloat('visibilityRange', 0.0, ancestry)
    distance = max(0.0, float(distance)) if distance is not None and math.isfinite(distance) else 0.0
    distance *= conversion_scale
    record = {"color": color, "fogType": fog_type, "visibilityRange": distance}
    world = bpyscene.world
    if world is not None:
        mist = world.mist_settings
        mist.start = 0.0
        mist.depth = distance
        mist.falloff = FOG_FALLOFF[fog_type]
        record["falloff"] = mist.falloff
        for layer in bpyscene.view_layers:
            layer.use_pass_mist = True
    bpyscene[FOG_PROPERTY] = record


def importTransform(bpycollection, node, ancestry, global_matrix):
    name = node.getDefName()
    if not name:
        name = 'Transform'

    bpyob = node.blendData = node.blendObject = bpy.data.objects.new(name, None)
    bpycollection.objects.link(bpyob)
    tag_x3d_identity(bpyob, node, ancestry)
    keep_host_metadata(bpyob, node, TRANSFORM_METADATA_PROPERTY)
    bpyob.select_set(True)

    matrix_safety.set_world_exact(bpyob, getFinalMatrix(node, None, ancestry, global_matrix))

    # so they are not too annoying
    bpyob.empty_display_type = 'PLAIN_AXES'
    bpyob.empty_display_size = 0.2


def importAudio(bpycollection, node, ancestry, global_matrix):
    """ Place speaker object and load content of source if any """

    # audio can be either audio or movie file, doesn't matter
    source = node.getChildBySpec('AudioClip') or node.getChildBySpec('MovieTexture')

    name = node.getDefName()
    if not name:
        name = 'Sound'

    # audio_urls is a list or None
    audio_urls = source.getFieldAsMFStringArray('url', None, ancestry)

    if not audio_urls and source: # only return for corrupt node
        logger.warning("warning, Sound source with no URL, this is odd")
        return None

    bpyaudio = load_audio_file(audio_urls, node)
    if not bpyaudio and source: # only return for corrupt node
        logger.warning("warning, Sound source failed to load")
        return None

    location = node.getFieldAsFloatTuple('location', (0.0, 0.0, 0.0), ancestry, conversion_scale)
    direction = node.getFieldAsFloatTuple('direction', (0.0, 0.0, 0.0), ancestry, conversion_scale)
    volume = node.getFieldAsFloat('intensity', 1.0, ancestry, conversion_scale)
    # Back and Front is not available in blender, thus only use the max value of both. The standard's defaults
    # (10 and 1) stand in for a field the file leaves out: a bare <Sound> used to stop the import with a TypeError.
    max_distance = max(
        node.getFieldAsFloat('maxBack', 10.0 * conversion_scale, ancestry, conversion_scale),
        node.getFieldAsFloat('maxFront', 10.0 * conversion_scale, ancestry, conversion_scale)
    )
    ref_distance = max(
        node.getFieldAsFloat('minBack', 1.0 * conversion_scale, ancestry, conversion_scale),
        node.getFieldAsFloat('minFront', 1.0 * conversion_scale, ancestry, conversion_scale)
    )

    bpy.ops.object.speaker_add(location=location)
    bpyspeaker = node.blendData = bpy.context.object

    # calculate speakers rotation
    # maybe this should get influenced by axis import settings? (not yet implemented)
    local_axis = mathutils.Vector((0, 0, 0))
    rotation = local_axis.rotation_difference(direction)
    bpyspeaker.rotation_mode = 'QUATERNION'
    bpyspeaker.rotation_quaternion = rotation

    bpyspeaker.data.name = name
    bpyspeaker.data.volume = volume
    if max_distance:
        bpyspeaker.data.distance_max = max_distance
    if ref_distance:
        bpyspeaker.data.distance_reference = ref_distance

    if source: # if source is None, create speaker nonetheless according to spec
        pitch = source.getFieldAsFloat('pitch', 1.0, ancestry, conversion_scale)
        description = source.getFieldAsString('description', None, ancestry)
        start_time_seconds = source.getFieldAsFloat('startTime', 0.0, ancestry, conversion_scale)
        stop_time_seconds = source.getFieldAsFloat('stopTime', 0.0, ancestry, conversion_scale)
        # unfortunately loop is not available within blender 3d speaker

        bpyspeaker.data.sound = bpyaudio
        bpyspeaker.data.pitch = pitch
        if description:
            bpyspeaker["description"] = description

        # Handle startTime using NLA strip Frame Start
        fps = bpy.context.scene.render.fps
        start_frame = int(0 + start_time_seconds * fps)
        if start_time_seconds > 0.0:
            nla_tracks = bpyspeaker.animation_data.nla_tracks if bpyspeaker.animation_data else None
            if nla_tracks:
                for track in nla_tracks:
                    for strip in track.strips:
                        strip.frame_start_ui = start_frame
        # Handle stopTime by keyframing volume property
        if stop_time_seconds > 0.0 and stop_time_seconds > start_time_seconds:
            end_frame = int(0 + stop_time_seconds * fps)
            bpyspeaker.data.keyframe_insert(data_path="volume", frame=start_frame)
            bpyspeaker.data.keyframe_insert(data_path="volume", frame=end_frame - 1)
            bpyspeaker.data.volume = 0.0
            bpyspeaker.data.keyframe_insert(data_path="volume", frame=end_frame)

    # this block is odd but required due to an update bug in blender for speakers
    # see https://projects.blender.org/blender/blender/issues/131826
    bpyspeaker.data.update_tag()
    bpycollection.objects.unlink(bpyspeaker)
    bpycollection.objects.link(bpyspeaker)


def load_audio_file(audio_urls, node):
    """ Loads an audio file from the first valid url, either from web or from disk (absolute/relative path) """
    bpyaudio = None

    for f in audio_urls:
        file_path = os.path.dirname(current_file_path)
        if f.startswith(('https://', 'http://', 'www.')): # url could be a web url > download audio clip first
            f = download_audio(f, file_path) or f
        else:
            # Check if the file is a relative or absolute path
            if not os.path.isabs(f):
                f = os.path.join(os.path.dirname(current_file_path), f)

        if os.path.exists(f):
            bpyaudio = bpy.data.sounds.load(f, check_existing=True)
            if bpyaudio:
                break

    return bpyaudio

def download_audio(url, output_path=None):
    """
    Downloads an audio from the web and saves it to disk.
    """
    return web_resource_download_helper(url, '.wav', "downloaded_audio", output_path=output_path)


# def importTimeSensor(node):
def action_fcurve_ensure(action, data_path, array_index):
    from . import blender_version_higher_44
    # blender 4.4 has new api, so support both 4.4. and 4.2 api
    for fcu in action.layers[0].strips[0].channelbag(action.slots[0]).fcurves\
        if blender_version_higher_44 else action.fcurves:
        if fcu.data_path == data_path and fcu.array_index == array_index:
            return fcu

    return (action.layers[0].strips[0].channelbag(action.slots[0]).fcurves
            if blender_version_higher_44 else action.fcurves).new(data_path=data_path, index=array_index)


def translatePositionInterpolator(node, action, ancestry):
    key = node.getFieldAsArray('key', 0, ancestry)
    keyValue = node.getFieldAsArray('keyValue', 3, ancestry)

    loc_x = action_fcurve_ensure(action, "location", 0)
    loc_y = action_fcurve_ensure(action, "location", 1)
    loc_z = action_fcurve_ensure(action, "location", 2)

    for i, time in enumerate(key):
        try:
            x, y, z = keyValue[i]
        except:
            continue

        loc_x.keyframe_points.insert(time, x)
        loc_y.keyframe_points.insert(time, y)
        loc_z.keyframe_points.insert(time, z)

    for fcu in (loc_x, loc_y, loc_z):
        for kf in fcu.keyframe_points:
            kf.interpolation = 'LINEAR'


def translateOrientationInterpolator(node, action, ancestry):
    key = node.getFieldAsArray('key', 0, ancestry)
    keyValue = node.getFieldAsArray('keyValue', 4, ancestry)

    rot_x = action_fcurve_ensure(action, "rotation_euler", 0)
    rot_y = action_fcurve_ensure(action, "rotation_euler", 1)
    rot_z = action_fcurve_ensure(action, "rotation_euler", 2)

    for i, time in enumerate(key):
        try:
            x, y, z, w = keyValue[i]
        except:
            continue

        mtx = translateRotation((x, y, z, w))
        eul = mtx.to_euler()
        rot_x.keyframe_points.insert(time, eul.x)
        rot_y.keyframe_points.insert(time, eul.y)
        rot_z.keyframe_points.insert(time, eul.z)

    for fcu in (rot_x, rot_y, rot_z):
        for kf in fcu.keyframe_points:
            kf.interpolation = 'LINEAR'


# Untested!
def translateScalarInterpolator(node, action, ancestry):
    key = node.getFieldAsArray('key', 0, ancestry)
    keyValue = node.getFieldAsArray('keyValue', 4, ancestry)

    sca_x = action_fcurve_ensure(action, "scale", 0)
    sca_y = action_fcurve_ensure(action, "scale", 1)
    sca_z = action_fcurve_ensure(action, "scale", 2)

    for i, time in enumerate(key):
        try:
            x, y, z = keyValue[i]
        except:
            continue

        sca_x.keyframe_points.new(time, x)
        sca_y.keyframe_points.new(time, y)
        sca_z.keyframe_points.new(time, z)


def translateTimeSensor(node, action, ancestry):
    """
    Apply a time sensor to an action, VRML has many combinations of loop/start/stop/cycle times
    to give different results, for now just do the basics
    """

    # XXX25 TODO
    if 1:
        return

    time_cu = action.addCurve('Time')
    time_cu.interpolation = Blender.IpoCurve.InterpTypes.LINEAR

    cycleInterval = node.getFieldAsFloat('cycleInterval', None, ancestry)

    startTime = node.getFieldAsFloat('startTime', 0.0, ancestry)
    stopTime = node.getFieldAsFloat('stopTime', 250.0, ancestry)

    if cycleInterval is not None:
        stopTime = startTime + cycleInterval

    loop = node.getFieldAsBool('loop', False, ancestry)

    time_cu.append((1 + startTime, 0.0))
    time_cu.append((1 + stopTime, 1.0 / 10.0))  # annoying, the UI uses /10

    if loop:
        time_cu.extend = Blender.IpoCurve.ExtendTypes.CYCLIC  # or - EXTRAP, CYCLIC_EXTRAP, CONST,


# -----------------------------------------------------------------------------------
# X3D XML ROUTE-driven animation (TimeSensor -> interpolators -> Transform)


def _x3d_transform_matrix(tx, rot, sca, cent=None, scaori=None):
    """Compose an X3D Transform matrix: T * C * R * SR * S * -SR * -C."""
    mat = Matrix.Translation(tx) if tx else Matrix()
    if cent:
        mat = mat @ Matrix.Translation(cent)
    if rot:
        mat = mat @ translateRotation(rot)
    if scaori:
        mat = mat @ translateRotation(scaori)
    if sca:
        mat = mat @ translateScale(sca)
    if scaori:
        mat = mat @ translateRotation(scaori).inverted()
    if cent:
        mat = mat @ Matrix.Translation(cent).inverted()
    return mat


def _interpolate_channel(keys, values, time, kind):
    """Linear (or slerp for rotations) interpolation of an X3D interpolator at ``time``."""
    if not keys:
        return None
    if time <= keys[0]:
        return values[0]
    if time >= keys[-1]:
        return values[-1]
    for index in range(1, len(keys)):
        if keys[index] >= time:
            span = keys[index] - keys[index - 1]
            factor = 0.0 if span <= 0.0 else (time - keys[index - 1]) / span
            left, right = values[index - 1], values[index]
            if kind == "rotation":
                q_left = Quaternion(Vector(left[:3]).normalized() if Vector(left[:3]).length else Vector((0, 0, 1)), left[3])
                q_right = Quaternion(Vector(right[:3]).normalized() if Vector(right[:3]).length else Vector((0, 0, 1)), right[3])
                q = q_left.slerp(q_right, factor)
                axis, angle = q.to_axis_angle()
                return (axis.x, axis.y, axis.z, angle)
            return tuple(a + (b - a) * factor for a, b in zip(left, right))
    return values[-1]


# -----------------------------------------------------------------------------------
# HAnim import: HAnimHumanoid -> armature, HAnimJoint -> bone, skin Shapes -> skinned meshes


def _hanim_joint_children(joint):
    """Child HAnimJoints of a joint node, excluding USE references (the joints list)."""
    return [child for child in joint.getRealNode().getChildrenBySpec('HAnimJoint') if not child.reference]


def _hanim_skeleton_roots(humanoid):
    roots = []
    for child in humanoid.getRealNode().getChildrenBySpec('HAnimJoint'):
        if child.reference:
            continue
        if _attribute_raw(child, 'containerField', 'skeleton') in {'skeleton', 'children'}:
            roots.append(child)
    return roots


def _hanim_local_matrix(node, ancestry):
    """World matrix of an HAnimHumanoid: enclosing Transforms times its own transform fields."""
    own = translateTransform(node, ancestry)  # humanoid shares Transform's translation/rotation/scale/center fields
    return getFinalMatrix(node, own, ancestry, Matrix())


def importHumanoid(bpycollection, node, ancestry, global_matrix):
    """Create an armature for an HAnimHumanoid and skinned meshes for its skin Shapes."""
    real = node.getRealNode()
    name = node.getDefName() or _attribute_raw(real, 'name', None) or 'Humanoid'
    if name.startswith('hanim_') and len(name) > 6:
        name = name[6:]

    armature_data = bpy.data.armatures.new(name)
    armature = bpy.data.objects.new(name, armature_data)
    bpycollection.objects.link(armature)
    armature.matrix_world = global_matrix @ _hanim_local_matrix(real, ancestry)
    node.blendData = node.blendObject = armature

    roots = _hanim_skeleton_roots(real)
    if not roots:
        logger.warning("HAnimHumanoid %r has no skeleton joints", name)

    # Bones need edit mode; the object must be active and visible in the view layer.
    previous_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    joint_bones = {}
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = armature_data.edit_bones

        def add_joint(joint, parent_bone, parent_center):
            joint_name = _attribute_raw(joint, 'name', None) or joint.getDefName() or 'joint'
            center = joint.getFieldAsFloatTuple('center', (0.0, 0.0, 0.0), ancestry)
            head = Vector(center)
            bone = edit_bones.new(joint_name)
            bone.head = head
            children = _hanim_joint_children(joint)
            if children:
                tail = Vector((0.0, 0.0, 0.0))
                for child in children:
                    tail += Vector(child.getFieldAsFloatTuple('center', center, ancestry))
                tail /= len(children)
            elif parent_center is not None and (head - Vector(parent_center)).length > 1e-6:
                tail = head + (head - Vector(parent_center)).normalized() * max(0.1, (head - Vector(parent_center)).length * 0.5)
            else:
                tail = head + Vector((0.0, 0.1, 0.0))
            if (tail - head).length < 1e-6:
                tail = head + Vector((0.0, 0.1, 0.0))
            bone.tail = tail
            if parent_bone is not None:
                bone.parent = parent_bone
                bone.use_connect = (Vector(parent_bone.tail) - head).length < 1e-6
            joint_bones[joint.getRealNode()] = bone.name
            joint.getRealNode().blendData = armature  # lets ROUTEs find the armature
            for child in children:
                add_joint(child, bone, center)

        for root in roots:
            add_joint(root, None, None)
    finally:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass
        bpy.context.view_layer.objects.active = previous_active

    # Record joint -> bone name on the humanoid for the animation pass
    real.hanim_bones = {joint_node.getDefName() or '': bone_name for joint_node, bone_name in joint_bones.items()}
    real.hanim_joint_nodes = {joint_node: bone_name for joint_node, bone_name in joint_bones.items()}

    # Skin: shared skinCoord points and the Shapes marked containerField="skin"
    skin_coord = None
    for coord in real.getChildrenBySpec('Coordinate'):
        if _attribute_raw(coord, 'containerField', '') == 'skinCoord':
            skin_coord = coord
            break
    skin_points = skin_coord.getFieldAsArray('point', 3, ancestry, conversion_scale) if skin_coord is not None else []
    if skin_coord is not None and skin_coord.canHaveReferences():
        skin_coord.parsed = skin_points

    # Per-joint weights indexed into skin_points
    weights = {}  # bone name -> list of (index, weight)
    for joint_node, bone_name in joint_bones.items():
        indices = joint_node.getFieldAsArray('skinCoordIndex', 0, ancestry)
        values = joint_node.getFieldAsArray('skinCoordWeight', 0, ancestry)
        if indices and values:
            weights[bone_name] = list(zip([int(i) for i in indices], [float(w) for w in values]))

    skins = []
    for shape in real.getChildrenBySpec('Shape'):
        if _attribute_raw(shape, 'containerField', '') != 'skin':
            continue
        skins.append(_import_skin_shape(bpycollection, shape, ancestry, armature, skin_points, weights, global_matrix))

    # node board batch 11: segments, sites, displacers and motions (hanim_parts.py)
    for label, step in (("segments and sites", lambda: _import_hanim_segments(bpycollection, armature, joint_bones)),
                        ("displacers", lambda: _import_hanim_displacers(armature, joint_bones,
                                                                        [skin for skin in skins if skin], skin_points)),
                        ("motions", lambda: _import_hanim_motions(armature, real, joint_bones))):
        try:
            step()
        except Exception as exc:  # the humanoid itself is in; a part that fails must not take it away
            logger.error("HAnimHumanoid %r: %s not imported: %s", name, label, exc, exc_info=True)

    return armature


def _import_skin_shape(bpycollection, shape, ancestry, armature, skin_points, weights, global_matrix):
    geom = shape.getChildBySpec('IndexedFaceSet')
    if geom is None:
        logger.warning("HAnim skin Shape without IndexedFaceSet is not supported; skipped")
        return None
    coord = _coordinate_of(geom)
    points = skin_points
    if coord is not None:
        if coord.reference and coord.getRealNode().parsed:
            points = coord.getRealNode().parsed
        elif not coord.reference:
            points = coord.getFieldAsArray('point', 3, ancestry, conversion_scale)
    index = geom.getFieldAsArray('coordIndex', 0, ancestry)
    ccw = geom.getFieldAsBool('ccw', True, ancestry)
    faces = []
    face = []
    for value in index:
        if value == -1:
            if len(face) >= 3:
                faces.append(face if ccw else face[::-1])
            face = []
        else:
            face.append(int(value))
    if len(face) >= 3:
        faces.append(face if ccw else face[::-1])

    # The exporter splits vertices per normal/UV; weld coincident skin points
    # that carry identical weights back into one Blender vertex so the
    # deformation data comes back at the original resolution.
    signature = {}
    for bone_name, pairs in weights.items():
        for vertex_index, weight in pairs:
            signature.setdefault(vertex_index, []).append((bone_name, round(weight, 6)))
    welded_index = {}
    welded_points = []
    remap = []
    for old_index, point in enumerate(points):
        key = (tuple(round(float(c), 6) for c in point), tuple(sorted(signature.get(old_index, ()))))
        new_index = welded_index.get(key)
        if new_index is None:
            new_index = len(welded_points)
            welded_index[key] = new_index
            welded_points.append(tuple(point))
        remap.append(new_index)
    welded_faces = []
    loop_sources = []
    for face in faces:
        new_face = [remap[i] for i in face]
        if len(set(new_face)) < 3:
            continue
        welded_faces.append(new_face)
        loop_sources.extend(face)

    mesh_name = geom.getDefName() or shape.getDefName() or f"{armature.name}_skin"
    if mesh_name.startswith("ME_"):
        mesh_name = mesh_name[3:]
    mesh = bpy.data.meshes.new(mesh_name)
    mesh.from_pydata(welded_points, [], welded_faces)
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True

    tex_coord = geom.getChildBySpec('TextureCoordinate')
    if tex_coord is not None:
        uvs = tex_coord.getFieldAsArray('point', 2, ancestry)
        if len(uvs) >= len(points) and len(mesh.loops) == len(loop_sources):
            uv_layer = mesh.uv_layers.new(name="UVMap")
            for loop in mesh.loops:
                uv_layer.data[loop.index].uv = uvs[loop_sources[loop.index]]

    appr = shape.getChildBySpec('Appearance')
    if appr:
        bpymat, _bpyima, _alpha = importShape_LoadAppearance(mesh_name, appr, ancestry, shape, False)
        if bpymat is not None:
            mesh.materials.append(bpymat)
            if appr.getChildBySpec(('PhysicalMaterial', 'UnlitMaterial')):
                bpymat.use_backface_culling = geometry_solid(geom, ancestry)

    # the export names a skin's geometry ME_<object>_skin; the object keeps <object>, or each round trip adds a "_skin"
    object_name = mesh_name[:-len("_skin")] if (geom.getDefName() or "").endswith("_skin") and len(mesh_name) > 5 else mesh_name
    obj = bpy.data.objects.new(object_name, mesh)
    bpycollection.objects.link(obj)
    obj.parent = armature
    obj.matrix_world = armature.matrix_world.copy()
    obj.select_set(True)
    shape.blendData = shape.blendObject = obj

    vertex_count = len(mesh.vertices)
    for bone_name, pairs in weights.items():
        group = obj.vertex_groups.new(name=bone_name)
        for vertex_index, weight in pairs:
            if 0 <= vertex_index < len(remap) and weight > 0.0:
                new_index = remap[vertex_index]
                if new_index < vertex_count:
                    group.add([new_index], weight, 'REPLACE')
    modifier = obj.modifiers.new("Armature", 'ARMATURE')
    modifier.object = armature
    return obj, remap


def _hanim_fields(node, names):
    """The fields of ``node`` in ``names`` that the file wrote, as written."""
    out = {}
    for field in names:
        raw = _attribute_raw(node, field, None)
        if raw is not None:
            out[field] = raw
    return out


def _hanim_bone_parent(obj, armature, bone_name):
    """Parent ``obj`` to the bone, keeping its matrix_basis as its place in humanoid space at the rest pose (a child of
    a bone hangs from the bone's tail)."""
    bone = armature.data.bones[bone_name]
    basis = obj.matrix_basis.copy()
    obj.parent = armature
    obj.parent_type = 'BONE'
    obj.parent_bone = bone_name
    obj.matrix_parent_inverse = (bone.matrix_local @ Matrix.Translation((0.0, bone.length, 0.0))).inverted()
    obj.matrix_basis = basis


def _import_hanim_segments(bpycollection, armature, joint_bones):
    """HAnimSegment and HAnimSite (node board batch 11): each segment Shape becomes a mesh object and each site an
    Empty, bone-parented to the joint's bone; the segment's fields go on the bone (hanim_parts.SEGMENT_PROPERTY)."""
    from . import hanim_parts
    for joint, bone_name in joint_bones.items():
        segments = [child for child in joint.getChildrenBySpec('HAnimSegment') if not child.reference]
        if len(segments) > 1:
            logger.warning("HAnimJoint %r has %d segments; the fields of the first are kept, the Shapes of all",
                           bone_name, len(segments))
        for number, segment in enumerate(segments):
            if number == 0:
                record = {"name": _attribute_raw(segment, 'name', None) or "", "def": segment.getDefName() or "",
                          "fields": _hanim_fields(segment, hanim_parts.SEGMENT_FIELDS)}
                raw = _hanim_raw_displacers(segment)
                if raw:
                    record["displacers"] = raw
                bone = armature.data.bones[bone_name]
                bone[hanim_parts.SEGMENT_PROPERTY] = hanim_parts.dump(record)
                for field, width in hanim_parts.SEGMENT_NUMBERS.items():
                    raw_number = _attribute_raw(segment, field, None)
                    numbers = hanim_parts.floats(raw_number)
                    if raw_number is not None and len(numbers) == width:
                        bone[hanim_parts.SEGMENT_NUMBER_PREFIX + field] = numbers[0] if width == 1 else numbers
            if segment.getChildrenBySpec('Coordinate'):
                logger.warning("HAnimSegment %r: its coord is not imported", bone_name)
            _import_hanim_segment_children(bpycollection, armature, bone_name, segment, [segment])


def _import_hanim_segment_children(bpycollection, armature, bone_name, parent, chain):
    from . import hanim_parts
    for child in parent.getRealNode().children:
        spec = child.getSpec()
        if spec == 'Shape':
            made_before = child.getRealNode().blendObject if child.reference else None
            importShape(bpycollection, child, chain, Matrix(), False, 0.0)
            obj = child.blendObject
            if obj is not None and obj is not made_before:
                _hanim_bone_parent(obj, armature, bone_name)
        elif spec in ('Transform', 'Group') and not child.reference:
            _import_hanim_segment_children(bpycollection, armature, bone_name, child, chain + [child])
        elif spec == 'HAnimSite' and not child.reference:
            def_name = child.getDefName() or ""
            site_name = _attribute_raw(child, 'name', None) or ""
            object_name = (def_name[6:] if def_name.startswith("hanim_") and len(def_name) > 6 else def_name) \
                or site_name or "Site"
            empty = bpy.data.objects.new(object_name, None)
            empty.empty_display_type = 'SPHERE'
            empty.empty_display_size = 0.05
            bpycollection.objects.link(empty)
            own = translateTransform(child, chain)
            empty.matrix_basis = getFinalMatrix(child, own, chain, Matrix())
            _hanim_bone_parent(empty, armature, bone_name)
            empty[hanim_parts.SITE_PROPERTY] = hanim_parts.dump(
                {"name": site_name, "fields": _hanim_fields(child, hanim_parts.SITE_FIELDS)})
            if def_name:
                empty["x3d_def"] = def_name
            child.blendData = child.blendObject = empty
            if child.getRealNode().children:
                logger.warning("HAnimSite %r: its children are not imported", object_name)


def _hanim_raw_displacers(node):
    """The HAnimDisplacers of ``node`` as written: [{name, def, coordIndex, displacements, weight, fields}]."""
    from . import hanim_parts
    out = []
    for displacer in node.getChildrenBySpec('HAnimDisplacer'):
        if displacer.reference:
            continue
        out.append({"name": _attribute_raw(displacer, 'name', None) or "", "def": displacer.getDefName() or "",
                    "coordIndex": _attribute_raw(displacer, 'coordIndex', "") or "",
                    "displacements": _attribute_raw(displacer, 'displacements', "") or "",
                    "weight": _attribute_raw(displacer, 'weight', None),
                    "fields": _hanim_fields(displacer, hanim_parts.DISPLACER_FIELDS)})
    return out


def _import_hanim_displacers(armature, joint_bones, skins, skin_points):
    """HAnimDisplacer of a joint (node board batch 11): a shape key on each skin mesh, its key points the basis plus the
    displacements at coordIndex (into skinCoord), its value the weight. With no skin to key they stay on the bone as
    written (hanim_parts.RAW_DISPLACERS_PROPERTY)."""
    from . import hanim_parts
    for joint, bone_name in joint_bones.items():
        displacers = [d for d in joint.getChildrenBySpec('HAnimDisplacer') if not d.reference]
        if not displacers:
            continue
        if not skins:
            armature.data.bones[bone_name][hanim_parts.RAW_DISPLACERS_PROPERTY] = hanim_parts.dump(
                _hanim_raw_displacers(joint))
            continue
        for number, displacer in enumerate(displacers):
            key_name = _attribute_raw(displacer, 'name', None) or displacer.getDefName() or f"{bone_name}_displacer{number}"
            indices = [int(i) for i in displacer.getFieldAsArray('coordIndex', 0, ())]
            offsets = displacer.getFieldAsArray('displacements', 3, (), conversion_scale)
            weight = displacer.getFieldAsFloat('weight', 0.0, ())
            record = {"joint": bone_name, "def": displacer.getDefName() or "",
                      "fields": _hanim_fields(displacer, hanim_parts.DISPLACER_FIELDS)}
            for obj, remap in skins:
                mesh = obj.data
                if mesh.shape_keys is None:
                    obj.shape_key_add(name="Basis", from_mix=False)
                key = obj.shape_key_add(name=key_name, from_mix=False)
                key_name = key.name
                for index, offset in zip(indices, offsets):
                    if 0 <= index < len(remap) and remap[index] < len(key.data):
                        vertex = remap[index]
                        key.data[vertex].co = Vector(mesh.vertices[vertex].co) + Vector(offset)
                key.slider_min = min(0.0, weight)
                key.slider_max = max(1.0, weight)
                key.value = weight
                kept = hanim_parts.load(obj.get(hanim_parts.DISPLACERS_PROPERTY), {})
                kept[key.name] = record
                obj[hanim_parts.DISPLACERS_PROPERTY] = hanim_parts.dump(kept)


def _hanim_assign_action(armature, action):
    if armature.animation_data is None:
        armature.animation_data_create()
    armature.animation_data.action = action
    try:
        if hasattr(action, "slots") and armature.animation_data.action_slot is None:
            slot = action.slots[0] if len(action.slots) else action.slots.new(id_type='OBJECT', name=armature.name)
            armature.animation_data.action_slot = slot
    except Exception:
        pass


def _import_hanim_motions(armature, real, joint_bones):
    """HAnimMotion (node board batch 11): a Blender Action per motion, keyed per frame on each named joint's pose bone
    (frame i at scene start + i * frameDuration * fps); the first is the armature's action. The node's fields are kept as
    written on the action (hanim_parts.MOTION_PROPERTY), its values too, so an unedited action writes them back as
    they were."""
    from . import hanim_parts
    motions = [m for m in real.getChildrenBySpec('HAnimMotion') if not m.reference]
    if not motions:
        return
    scene = bpy.context.scene
    fps = scene.render.fps / scene.render.fps_base
    bones_by_name = {}
    for joint_node, bone_name in joint_bones.items():
        bones_by_name.setdefault(_attribute_raw(joint_node, 'name', None) or bone_name, bone_name)
    first = None
    last_frame = scene.frame_start
    for number, motion in enumerate(motions):
        motion_name = _attribute_raw(motion, 'name', None) or ""
        action = bpy.data.actions.new(motion_name or motion.getDefName() or f"{armature.name}_motion")
        action.use_fake_user = True
        raw_values = _attribute_raw(motion, 'values', None)
        fields = _hanim_fields(motion, hanim_parts.MOTION_FIELDS)
        action[hanim_parts.MOTION_PROPERTY] = hanim_parts.dump(
            {"humanoid": armature.name, "name": motion_name, "def": motion.getDefName() or "", "order": number,
             "fields": fields, "values": raw_values, "start": scene.frame_start, "fps": fps})
        _hanim_assign_action(armature, action)
        first = first or action
        groups = hanim_parts.parse_channels(fields.get("channels", ""), fields.get("joints", ""))
        width = sum(len(channels) for _, channels in groups)
        values = hanim_parts.floats(raw_values)
        frames = len(values) // width if width else 0
        duration = motion.getFieldAsFloat('frameDuration', 0.1, ())
        for frame_number in range(frames):
            row = values[frame_number * width:(frame_number + 1) * width]
            frame = scene.frame_start + frame_number * duration * fps
            last_frame = max(last_frame, frame)
            offset = 0
            for joint_name, channels in groups:
                cells, offset = row[offset:offset + len(channels)], offset + len(channels)
                bone_name = bones_by_name.get(joint_name)
                if bone_name is None or bone_name not in armature.pose.bones:
                    continue
                translation = [0.0, 0.0, 0.0]
                rotation = Matrix()
                for channel, value in zip(channels, cells):
                    if channel in hanim_parts.POSITION_CHANNELS:
                        translation[hanim_parts.POSITION_CHANNELS[channel]] = value * conversion_scale
                    elif channel in hanim_parts.ROTATION_CHANNELS:
                        rotation = rotation @ Matrix.Rotation(value, 4, hanim_parts.ROTATION_CHANNELS[channel])
                bone = armature.data.bones[bone_name]
                rest = bone.matrix_local
                center = bone.head_local
                joint_matrix = Matrix.Translation(Vector(translation)) @ Matrix.Translation(center) @ rotation \
                    @ Matrix.Translation(-center)
                loc, quat, _scale = (rest.inverted() @ joint_matrix @ rest).decompose()
                pose_bone = armature.pose.bones[bone_name]
                pose_bone.rotation_mode = 'QUATERNION'
                pose_bone.location = loc
                pose_bone.rotation_quaternion = quat
                pose_bone.keyframe_insert("location", frame=frame)
                pose_bone.keyframe_insert("rotation_quaternion", frame=frame)
        for fcu in _action_fcurves(action):
            for kf in fcu.keyframe_points:
                kf.interpolation = 'LINEAR'
    _hanim_assign_action(armature, first)
    for pose_bone in armature.pose.bones:     # the rest pose until the timeline plays
        pose_bone.location = (0.0, 0.0, 0.0)
        pose_bone.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
    _fit_frame_end(scene, last_frame)


def _hanim_joint_target(defDict, target_def):
    """Return (armature object, bone name) when target_def names an imported HAnimJoint."""
    joint = defDict.get(target_def)
    if joint is None or joint.getSpec() != 'HAnimJoint':
        return None, None
    armature = getattr(joint.getRealNode(), 'blendData', None)
    if armature is None or armature.type != 'ARMATURE':
        return None, None
    for bone in armature.data.bones:
        if bone.name == (_attribute_raw(joint, 'name', None) or ''):
            return armature, bone.name
    return None, None


# -----------------------------------------------------------------------------------
# Inline bridge (X3D, VRML, glTF, Gaussian-splat files) and the X3D 4.1 GaussianSplats node

_INLINE_STACK = []  # files being inlined right now, to stop self-references
_inline_loads = 0   # Inline files loaded by this import (budget.inline_limit)
_GLTF_TO_BLENDER = None


def _gltf_to_blender_matrix():
    """The Y-up to Z-up conversion Blender's glTF importer applies to its output."""
    global _GLTF_TO_BLENDER
    if _GLTF_TO_BLENDER is None:
        from bpy_extras.io_utils import axis_conversion
        _GLTF_TO_BLENDER = axis_conversion(from_forward='-Z', from_up='Y', to_forward='Y', to_up='Z').to_4x4()
    return _GLTF_TO_BLENDER


def _resolve_inline_url(node, url):
    base = os.path.dirname(node.getFilename() or current_file_path or "")
    # Relative URLs belong to the containing document, never the process's unrelated working directory.
    candidates = ([url] if os.path.isabs(url) else
                  [os.path.join(base, url), os.path.join(base, os.path.basename(url))])
    for candidate in candidates:
        for variant in (candidate, bpy.path.resolve_ncase(candidate)):
            if os.path.isfile(variant):
                return os.path.abspath(variant)
    return None


def _inverted(matrix, what="matrix"):
    """The inverse of a 4x4 transform, computed in float64.

    Matrix.inverted() works in float32, where the determinant of a uniform scale of 1e-16 is 1e-48 and underflows
    to 0, so a unit scale of one light-year raised "matrix does not have an inverse". A scale of exactly 0 (which X3D
    allows) really is singular: that logs a warning and gives the pseudo-inverse, which still undoes the matrix on
    everything it can reach, all that a flattened parent's children occupy (the identity would apply it twice).
    An inverse beyond float32 range logs a warning and gives the identity.
    """
    import numpy as np
    values = np.array(matrix, dtype=np.float64)
    try:
        inverse = np.linalg.inv(values)
    except np.linalg.LinAlgError:
        logger.warning("%s is singular (a Transform scale of 0?); using its pseudo-inverse", what)
        inverse = np.linalg.pinv(values)
    if not np.abs(inverse).max() <= np.finfo(np.float32).max:
        logger.warning("%s has no inverse in float32 range; using the identity", what)
        return Matrix()
    return Matrix(inverse.tolist())


def _parent_keep_world(obj, parent, *, parent_inverse=None):
    obj.parent = parent
    obj.matrix_parent_inverse = parent_inverse if parent_inverse is not None else _inverted(parent.matrix_world, parent.name)


def _splat_attributes(mesh, splats):
    """Store IRGaussianSplats per-point data as mesh attributes."""
    count = len(mesh.vertices)

    def fill_vector(name, values, data_type="FLOAT_VECTOR", key="vector"):
        attr = mesh.attributes.new(name, data_type, 'POINT')
        flat = [float(c) for value in values for c in value]
        attr.data.foreach_set(key, flat)

    if len(splats.scales) == count:
        fill_vector("splat_scale", splats.scales)
    if len(splats.orientations) == count:
        attr = mesh.attributes.new("splat_rotation", 'QUATERNION', 'POINT')
        # Blender quaternions are (w, x, y, z)
        attr.data.foreach_set("value", [float(c) for (x, y, z, w) in splats.orientations for c in (w, x, y, z)])
    if len(splats.opacities) == count:
        attr = mesh.attributes.new("splat_opacity", 'FLOAT', 'POINT')
        attr.data.foreach_set("value", [float(o) for o in splats.opacities])
    for (degree, coef), values in sorted(splats.sh.items()):
        if len(values) == count:
            fill_vector(f"splat_sh{degree}_{coef}", values)
    dc = splats.sh.get((0, 0))
    if dc and len(dc) == count:
        from .splat_io import sh0_to_rgb
        color = mesh.color_attributes.new("Color", 'FLOAT_COLOR', 'POINT')
        opacities = splats.opacities if len(splats.opacities) == count else [1.0] * count
        color.data.foreach_set("color", [c for i, coefficient in enumerate(dc) for c in (*sh0_to_rgb(coefficient), opacities[i])])
        mesh.color_attributes.active_color = color
        mesh.color_attributes.render_color_index = 0


def _splat_import_target():
    """'pointcloud' (Blender's native splat type, 5.3+) or 'mesh' (vertices plus splat_* attributes).

    X3D_SPLAT_IMPORT=pointcloud|mesh overrides the automatic choice.
    """
    from .splat_native import pointcloud_buildable, pointcloud_type_supported
    if not pointcloud_buildable():
        return "mesh"
    forced = os.environ.get("X3D_SPLAT_IMPORT", "").strip().lower()
    if forced in {"pointcloud", "mesh"}:
        return forced
    return "pointcloud" if pointcloud_type_supported() else "mesh"


def _build_splat_object(bpycollection, name, splats):
    if _splat_import_target() == "pointcloud":
        from .splat_native import build_native_splat_pointcloud
        pointcloud = build_native_splat_pointcloud(name, splats)
        if "Color" in pointcloud.attributes:
            # Blender's glTF exporter writes a PointCloud's COLOR_0 only when its material reads a named colour
            # attribute: an unlit material on ``Color`` (the splats' base colours) puts the colours in the glb, as the
            # mesh target's loose vertices carry them. Before, the glb held POSITION only.
            pointcloud.materials.append(line_point_material(name, (1.0, 1.0, 1.0), 1.0, 'RGB'))
        obj = bpy.data.objects.new(name, pointcloud)
        bpycollection.objects.link(obj)
        obj.select_set(True)
        return obj
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(p) for p in splats.positions], [], [])
    mesh.update()
    mesh["x3d_gaussian_splats"] = True
    mesh["x3d_splat_color_space"] = splats.color_space
    _splat_attributes(mesh, splats)
    obj = bpy.data.objects.new(name, mesh)
    bpycollection.objects.link(obj)
    obj.select_set(True)
    return obj


def importGaussianSplats(bpycollection, node, ancestry, global_matrix):
    """X3D 4.1 GaussianSplats node -> native splat PointCloud (Blender 5.3+) or splat mesh."""
    from .ir import IRGaussianSplats

    real = node.getRealNode()
    existing = getattr(real, "blendObject", None)
    mesh_name = node.getDefName() or "GaussianSplats"
    if mesh_name.startswith("GS_") and len(mesh_name) > 3:
        mesh_name = mesh_name[3:]
    # Like Shapes, the object takes the enclosing Transform's DEF name when there is one
    name = mesh_name
    for parent in reversed(ancestry):
        parent_name = parent.getDefName() if hasattr(parent, "getDefName") else None
        if parent_name:
            name = parent_name[3:] if parent_name.startswith("OB_") and len(parent_name) > 3 else parent_name
            break
    if existing is not None:
        obj = existing.copy()
        obj.name = name
        bpycollection.objects.link(obj)
    else:
        splats = IRGaussianSplats(name=mesh_name, color_space=_attribute_raw(real, 'colorSpace', 'SRGB_REC709_DISPLAY'))
        splats.positions = [tuple(p) for p in real.getFieldAsArray('positions', 3, ancestry, conversion_scale)]
        # scales are lengths in the same units as positions
        splats.scales = [tuple(s) for s in real.getFieldAsArray('scales', 3, ancestry, conversion_scale)]
        splats.orientations = [tuple(q) for q in real.getFieldAsArray('orientations', 4, ancestry)]
        splats.opacities = [float(o) for o in real.getFieldAsArray('opacities', 0, ancestry)]
        for degree in range(4):
            coefficients = [real.getFieldAsArray(f'sphericalHarmonicsDegree{degree}Coef{coef}', 3, ancestry)
                            for coef in range(2 * degree + 1)]
            if not all(coefficients):
                break  # a partial degree counts as absent, and so does every degree above it
            for coef, values in enumerate(coefficients):
                splats.sh[(degree, coef)] = [tuple(v) for v in values]
        obj = _build_splat_object(bpycollection, name, splats)
        obj.data.name = mesh_name
        real.blendData = real.blendObject = obj
    matrix_safety.set_world_exact(obj, getFinalMatrix(node, None, ancestry, global_matrix))
    node.blendData = node.blendObject = obj
    return obj


def importInline(bpycollection, node, ancestry, global_matrix, *, PREF_FLAT, PREF_CIRCLE_DIV, solidify, solidify_value,
                 PREF_HIERARCHY=False):
    """Inline node -> placeholder empty with the referenced asset loaded underneath it.

    X3D and VRML files go through this importer recursively, glTF through
    Blender's glTF importer, and .ply / .splat files become splat meshes.
    The empty keeps the URL in ``x3d_inline_url`` so the exporter writes an
    Inline again instead of the loaded content.
    """
    global current_file_path, material_cache, texture_cache, image_alpha_cache, line_material_cache
    global unlit_surface_cache, unlit_colour_cache, physical_colour_cache

    urls = node.getFieldAsMFStringArray('url', [], ancestry)
    name = node.getDefName() or (os.path.splitext(os.path.basename(urls[0]))[0] if urls else "Inline")
    if name.startswith("IN_") and len(name) > 3:
        name = name[3:]
    # The placeholder's frame is Blender's; the asset underneath is converted Y-up -> Z-up
    # like Blender's own importers do, so the Inline's matrix carries that rotation.
    frame = _gltf_to_blender_matrix()
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = 'PLAIN_AXES'
    empty.matrix_world = getFinalMatrix(node, None, ancestry, global_matrix) @ frame.inverted()
    empty["x3d_inline_url"] = urls[0] if urls else ""
    bpycollection.objects.link(empty)
    empty.select_set(True)
    node.blendData = node.blendObject = empty
    if not urls:
        logger.warning("Inline %r has no url", name)
        return empty

    resolved = None
    for url in urls:
        resolved = _resolve_inline_url(node, url)
        if resolved:
            break
    if resolved is None:
        logger.warning("Inline URL could not be found: %s", urls)
        empty["x3d_inline_missing"] = True
        return empty
    if resolved in _INLINE_STACK or resolved == os.path.abspath(current_file_path or ""):
        logger.warning("Can't Inline a file that is already being loaded: %s", resolved)
        return empty
    global _inline_loads
    _inline_loads += 1
    if _inline_loads > budget.inline_limit():
        # ten Inlines per level, five levels deep: 100,000 file loads ran past 90 s (chaos round 2.7.3)
        if _inline_loads == budget.inline_limit() + 1:
            logger.warning("More than %d Inline loads in one import; the rest are left as empties (set %s)",
                           budget.inline_limit(), budget.MAX_INLINES_ENV)
        empty["x3d_inline_skipped"] = True
        return empty
    empty["x3d_inline_resolved_path"] = mfstring.portable_path(resolved, os.path.dirname(current_file_path or ""))
    record_inline_source(empty.session_uid, empty["x3d_inline_url"], resolved)   # session only; the export rebases the url from it (D3)

    before = set(bpy.data.objects)
    lower = resolved.lower()
    parent_inverse = None
    _INLINE_STACK.append(resolved)
    # load_web3d replaces these file-scoped caches. A child file's relative texture URLs describe different assets
    # from the same spelling in its parent; never leave the child's description cache active when returning.
    saved_file = current_file_path
    saved_caches = (material_cache, texture_cache, image_alpha_cache, line_material_cache,
                    unlit_surface_cache, unlit_colour_cache, physical_colour_cache)
    try:
        if lower.endswith(('.x3d', '.x3dz', '.x3dv', '.wrl', '.wrz')):
            load_web3d(bpy.context, resolved, PREF_FLAT=PREF_FLAT, PREF_CIRCLE_DIV=PREF_CIRCLE_DIV,
                       global_scale=conversion_scale, global_matrix=empty.matrix_world @ frame,
                       solidify=solidify, solidify_value=solidify_value, PREF_HIERARCHY=PREF_HIERARCHY)
            parent_inverse = _inverted(empty.matrix_world, name)
        elif lower.endswith(('.gltf', '.glb')):
            from .bridge_gltf import import_gltf
            import_gltf(resolved)
            parent_inverse = Matrix()  # already Z-up, exactly the placeholder's frame
            # X_ITE draws an Inlined glTF with PhysicalMaterial, so its meshes count for the light units
            lit_surfaces.extend((obj, 'physical', None, None) for obj in bpy.data.objects
                                if obj not in before and obj.type == 'MESH')
        elif lower.endswith(('.ply', '.splat')):
            from .splat_io import read_splats
            splats = read_splats(resolved, name=name)
            _build_splat_object(bpycollection, name + "_splats", splats)
            parent_inverse = frame  # splat files are Y-up like X3D
        else:
            logger.warning("Inline asset type not supported: %s", resolved)
            empty["x3d_inline_unsupported"] = True
    except Exception as exc:
        logger.error("Inline %r failed to load: %s", resolved, exc, exc_info=True)
    finally:
        _INLINE_STACK.pop()
        current_file_path = saved_file
        (material_cache, texture_cache, image_alpha_cache, line_material_cache,
         unlit_surface_cache, unlit_colour_cache, physical_colour_cache) = saved_caches

    for obj in bpy.data.objects:
        if obj in before or obj.parent is not None:
            continue
        if obj.name not in bpycollection.objects:
            try:
                bpycollection.objects.link(obj)
            except RuntimeError:
                pass
        _parent_keep_world(obj, empty, parent_inverse=parent_inverse)
    for obj in bpy.data.objects:
        if obj not in before:
            obj["x3d_inline_source"] = urls[0]
    return empty


def _import_coordinate_morphs(morphs, timers_for_interp, defDict, scene, fps, frame_start):
    """CoordinateInterpolator -> Coordinate.set_point becomes relative shape keys with keyframed values.

    Every distinct state of the interpolator (a state equal to the mesh's own points is the Basis) becomes one shape key.
    Its value is 1 at the keys where the interpolator is in that state and 0 at the neighbouring keys, linear in between,
    so the blend of the keys is the interpolator's linear interpolation of the absolute positions. The glTF exporter turns
    shape keys and their animation into morph targets and weights.
    Returns the last frame used.
    """
    import numpy as np
    last_frame = frame_start
    for coord_def, interp_def in morphs.items():
        interp = defDict.get(interp_def)
        if interp is None or interp.getSpec() != 'CoordinateInterpolator':
            continue
        keys = [float(k) for k in interp.getFieldAsArray('key', 0, ())]
        flat = interp.getFieldAsArray('keyValue', 3, (), conversion_scale)
        if not keys or not flat or len(flat) % len(keys):
            logger.warning("CoordinateInterpolator %r: keyValue does not hold a whole number of points per key; skipped", interp_def)
            continue
        n_points = len(flat) // len(keys)
        states = np.array(flat, dtype=np.float64).reshape(len(keys), n_points, 3)
        timer = defDict.get(timers_for_interp.get(interp_def, ''))
        cycle_interval = timer.getFieldAsFloat('cycleInterval', 1.0, ()) if timer is not None else 1.0
        meshes = [m for m in bpy.data.meshes if m.get("x3d_coord_def") == coord_def and m.users]
        if not meshes:
            logger.warning("Coordinate %r is animated but no imported IndexedFaceSet uses it; skipped", coord_def)
        for mesh in meshes:
            obj = next((o for o in bpy.data.objects if o.data is mesh), None)
            point_map = list(mesh["x3d_point_map"]) if "x3d_point_map" in mesh else list(range(len(mesh.vertices)))
            if obj is None or mesh.shape_keys is not None or len(point_map) != len(mesh.vertices) or (point_map and max(point_map) >= n_points):
                logger.warning("Mesh %r cannot take the morph of %r; skipped", mesh.name, coord_def)
                continue
            sub = states[:, point_map, :]
            rest = np.array([tuple(v.co) for v in mesh.vertices], dtype=np.float64)
            # Classes of identical states (to float32 round-off), in order of first appearance.
            reps, cls = [], []
            for state in sub:
                for index, rep in enumerate(reps):
                    if np.abs(state - sub[rep]).max() <= 1e-5:
                        cls.append(index)
                        break
                else:
                    reps.append(len(cls))
                    cls.append(len(reps) - 1)
            basis_class = next((i for i, rep in enumerate(reps) if np.abs(sub[rep] - rest).max() <= 1e-5), None)
            obj.shape_key_add(name="Basis", from_mix=False)
            for index, rep in enumerate(reps):
                if index == basis_class:
                    continue
                block = obj.shape_key_add(name=f"{coord_def}_{index:02d}", from_mix=False)
                block.data.foreach_set("co", sub[rep].astype(np.float32).ravel())
                block.slider_min, block.slider_max = 0.0, 1.0
                wanted = sorted({j for i, c in enumerate(cls) if c == index for j in (i - 1, i, i + 1) if 0 <= j < len(keys)})
                for j in wanted:
                    block.value = 1.0 if cls[j] == index else 0.0
                    frame = frame_start + keys[j] * cycle_interval * fps
                    last_frame = max(last_frame, frame)
                    block.keyframe_insert("value", frame=frame)
                block.value = 0.0
            action = mesh.shape_keys.animation_data.action if mesh.shape_keys.animation_data else None
            for fcu in (_action_fcurves(action) if action else []):
                for kf in fcu.keyframe_points:
                    kf.interpolation = 'LINEAR'
            obj["x3d_morph_coord"] = coord_def
            obj["x3d_morph_interpolator"] = interp_def
            obj["x3d_morph_states"] = len(reps)
    return last_frame


_CONSUMED_ROUTES = {("fraction", "fraction"), ("value", "translation"), ("value", "rotation"),
                    ("value", "scale"), ("value", "point")}
_EVENT_NODES = {"TouchSensor", "ProximitySensor", "VisibilitySensor", "PlaneSensor", "CylinderSensor", "SphereSensor",
                "KeySensor", "StringSensor", "BooleanFilter", "BooleanToggle", "BooleanTrigger", "BooleanSequencer",
                "IntegerTrigger", "IntegerSequencer", "TimeTrigger", "Script"}
_NEVER_STARTED = 1e29      # the exporter writes startTime 1e+30 for a timer only a trigger may start


def _object_by_def(def_name):
    import bpy
    for obj in bpy.data.objects:
        if obj.get("x3d_def") == def_name or obj.get("x3d_def_path") == def_name:
            return obj
    return None


def _static_triple(transform, field, default):
    values = transform.getFieldAsFloatTuple(field, None, ()) if transform is not None else None
    return tuple(values[:3]) if values and len(values) >= 3 else default


class _Rebuilt:
    """What ``rebuild_interaction`` turned back into custom properties: node DEFs and exact ROUTE edges."""

    def __init__(self):
        self.nodes: set[str] = set()
        self.edges: set[tuple[str, str, str, str]] = set()
        self.unpreserved: list[dict] = []      # field-level losses on a sensor that was therefore not rebuilt


def _route_tuple(attrs):
    return (attrs["fromNode"], attrs["fromField"], attrs["toNode"], attrs["toField"])


def _timer_problems(timer, tour=False):
    """Why a TimeSensor is not the exporter's timer: a triggered chain is play-once, never started at load and enabled;
    a tour timer may autostart or loop (``loop``/``startTime`` are read as tour settings) but must still be enabled."""
    real = timer.getRealNode()
    names = {attr.name: attr.value for attr in real.x3dNode.attributes.values()} if hasattr(real.x3dNode, "attributes") else {}
    problems = []
    for name, value in names.items():
        if name in ("DEF", "cycleInterval", "containerField"):
            continue
        if name == "loop":
            if not tour and str(value).strip().lower() == "true":
                problems.append("loop=true")
        elif name == "enabled":
            if str(value).strip().lower() != "true":
                problems.append(f"enabled={value}")
        elif name == "startTime":
            continue
        else:
            problems.append(f"{name}={value}")
    if not tour and timer.getFieldAsFloat("startTime", 0.0, ()) < _NEVER_STARTED:
        problems.append("starts at load (startTime below 1e+29)")
    return problems


# the exact event fields each exporter pattern routes from (isOver is hover, isActive is press; touchTime is a click)
_START_FIELD = {"TouchSensor": "touchTime", "ProximitySensor": "enterTime"}
_BIND_FIELD = {"TouchSensor": "isActive", "ProximitySensor": "isActive"}


def _timer_chain(timer_def, route_attrs, defs):
    """Edges and target Transform DEFs of the interpolator chain a timer drives: timer -> interpolators -> Transforms."""
    edges, targets = set(), set()
    for first in route_attrs:
        if first["fromNode"] != timer_def or first["fromField"] != "fraction_changed" or first["toField"] != "set_fraction":
            continue
        edges.add(_route_tuple(first))
        for second in route_attrs:
            if second["fromNode"] == first["toNode"] and second["fromField"] == "value_changed" \
                    and second["toField"] in ("set_translation", "set_rotation", "set_scale"):
                edges.add(_route_tuple(second))
                targets.add(second["toNode"])
    return edges, targets


def _sensor_field_problems(node, spec, parent):
    """Attributes of a sensor the exporter does not write and the custom properties cannot hold."""
    real = node.getRealNode()
    names = {attr.name: attr.value for attr in real.x3dNode.attributes.values()} if hasattr(real.x3dNode, "attributes") else {}
    problems = []
    for name, value in names.items():
        if name in ("DEF", "description", "containerField"):
            continue
        if name == "enabled":
            if str(value).strip().lower() != "true":
                problems.append(f"enabled={value}")
        elif spec == "ProximitySensor" and name == "center":
            if any(abs(float(v)) > 1e-9 for v in str(value).replace(",", " ").split()):
                problems.append(f"center={value} (a centred box is all the properties hold)")
        elif spec == "ProximitySensor" and name == "size":
            sizes = [float(v) for v in str(value).replace(",", " ").split()]
            scale = _static_triple(parent, "scale", (1.0, 1.0, 1.0))
            world = [abs(a) * abs(b) for a, b in zip(sizes, scale)] if len(sizes) == 3 else []
            if len(world) != 3 or min(sizes) <= 0 or min(world) <= 0 or max(world) - min(world) > 1e-6 * max(1.0, max(world)):
                problems.append(f"size={value} (only a box that is a cube in world space, 2 x radius, is kept)")
        else:
            problems.append(f"{name}={value}")
    return problems


def _action_from_routes(sensor_def, route_attrs, defs, all_nodes):
    """``[action, target]`` read off the ROUTEs a sensor starts, for a sensor that carries no description."""
    for attrs in route_attrs:
        if attrs["fromNode"] != sensor_def:
            continue
        if attrs["toField"] == "set_bind" and attrs["fromField"] == "isActive" and attrs["toNode"].startswith("CA_"):
            return ["viewpoint", attrs["toNode"][3:]]
        if attrs["toField"] == "set_boolean" and attrs["fromField"] == "isActive":   # click: sensor -> BooleanFilter -> set_bind
            for second in route_attrs:
                if second["fromNode"] == attrs["toNode"] and second["fromField"] == "inputTrue" \
                        and second["toField"] == "set_bind" and second["toNode"].startswith("CA_"):
                    return ["viewpoint", second["toNode"][3:]]
        if attrs["toField"] == "set_startTime" and attrs["fromField"] in ("touchTime", "enterTime"):
            _edges, targets = _timer_chain(attrs["toNode"], route_attrs, defs)
            for name in sorted(targets):
                target = defs.get(name)
                if target is None:
                    continue
                if any(getattr(n, "x3dNode", None) is not None and n.getSpec() == "Viewpoint" and a and a[-1] is target
                       for n, a in all_nodes):
                    return ["tour"]
                return ["animate", name[3:] if name.startswith("OB_") else name]
    return None


def _quaternion(axis_angle):
    from math import cos, sin, sqrt
    x, y, z, angle = axis_angle
    length = sqrt(x * x + y * y + z * z) or 1.0
    half = angle / 2.0
    return (cos(half), sin(half) * x / length, sin(half) * y / length, sin(half) * z / length)


def _same_pose(position_a, rotation_a, position_b, rotation_b):
    from math import dist
    if dist(position_a, position_b) > 1e-3:
        return False
    qa, qb = _quaternion(rotation_a), _quaternion(rotation_b)
    return abs(sum(u * v for u, v in zip(qa, qb))) > 1.0 - 1e-6


def _rebuild_tour(all_nodes, route_attrs, defs, rebuilt):
    import bpy
    for attrs in route_attrs:
        if attrs["toField"] != "set_translation" or attrs["fromField"] != "value_changed":
            continue
        interp, rig = defs.get(attrs["fromNode"]), defs.get(attrs["toNode"])
        if interp is None or rig is None or interp.getSpec() != "PositionInterpolator" or rig.getSpec() != "Transform":
            continue
        views = [n for n, a in all_nodes if getattr(n, "x3dNode", None) is not None and n.getSpec() == "Viewpoint"
                 and a and a[-1] is rig]
        timer_def = next((r["fromNode"] for r in route_attrs if r["toNode"] == attrs["fromNode"] and r["toField"] == "set_fraction"), None)
        timer = defs.get(timer_def)
        if not views or timer is None or timer.getSpec() != "TimeSensor":
            continue
        timer_problems = _timer_problems(timer, tour=True)
        if timer_problems:
            rebuilt.unpreserved.append({"kind": "tour", "node": f"TimeSensor {timer_def}",
                                        "detail": "not preserved: " + "; ".join(timer_problems)})
            continue
        orient_attrs = next((r for r in route_attrs if r["toNode"] == attrs["toNode"] and r["toField"] == "set_rotation"
                             and r["fromField"] == "value_changed"
                             and defs.get(r["fromNode"]) is not None and defs[r["fromNode"]].getSpec() == "OrientationInterpolator"), None)
        keys = [float(k) for k in interp.getFieldAsArray("key", 0, ())]
        values = [tuple(float(v) for v in value) for value in interp.getFieldAsArray("keyValue", 3, ())]
        if orient_attrs is None or len(keys) < 2 or len(keys) % 2 or len(values) < len(keys):
            continue
        orient = defs[orient_attrs["fromNode"]]
        rotations = [tuple(float(v) for v in value) for value in orient.getFieldAsArray("keyValue", 4, ())]
        if len(rotations) < len(keys):
            continue
        total = timer.getFieldAsFloat("cycleInterval", 1.0, ())
        candidates = [(vnode, vanc[-1]) for vnode, vanc in
                      ((n, a) for n, a in all_nodes if getattr(n, "x3dNode", None) is not None and n.getSpec() == "Viewpoint")
                      if vanc and vanc[-1] is not rig]
        used, stops = set(), []
        for index in range(len(keys) // 2):
            match = None
            for vnode, vparent in candidates:
                if id(vnode) in used:
                    continue
                pos = _static_triple(vparent, "translation", (0.0, 0.0, 0.0))
                rot = vparent.getFieldAsFloatTuple("rotation", None, ())
                rot = tuple(rot[:4]) if rot and len(rot) >= 4 else (0.0, 0.0, 1.0, 0.0)
                if _same_pose(pos, rot, values[2 * index], rotations[2 * index]):
                    match = vnode
                    break
            if match is None:
                stops = []
                break
            used.add(id(match))
            stops.append((match, (keys[2 * index + 1] - keys[2 * index]) * total, keys[2 * index]))
        if not stops:
            rebuilt.unpreserved.append({"kind": "tour", "node": f"Transform {attrs['toNode']}",
                                        "detail": "tour stops could not each be matched to one camera by position and orientation"})
            continue
        gaps = [(stops[i + 1][2] - keys[2 * i + 1]) * total for i in range(len(stops) - 1)]
        if gaps and max(gaps) - min(gaps) > 1e-3:
            rebuilt.unpreserved.append({"kind": "tour", "node": f"Transform {attrs['toNode']}",
                                        "detail": "flight times between stops differ; one x3d_tour_travel cannot hold them"})
            continue
        for order, (vnode, dwell, _arrive) in enumerate(stops, start=1):
            camera = _object_by_def(vnode.getDefName())
            if camera is not None:
                camera["x3d_tour_order"] = order
                camera["x3d_tour_dwell"] = round(dwell, 6)
        scene = bpy.context.scene
        if gaps:
            scene["x3d_tour_travel"] = round(sum(gaps) / len(gaps), 6)
        autostart = timer.getFieldAsFloat("startTime", 0.0, ()) < _NEVER_STARTED
        scene["x3d_tour_autostart"] = bool(autostart)
        scene["x3d_tour_loop"] = bool(timer.getFieldAsBool("loop", False, ())) and not autostart
        for view in views:                               # the rig's own camera is rebuilt from the tour, not kept as an object
            rig_camera = _object_by_def(view.getDefName())
            if rig_camera is not None:
                action = rig_camera.animation_data.action if rig_camera.animation_data else None
                bpy.data.objects.remove(rig_camera, do_unlink=True)
                if action is not None and action.users == 0:
                    bpy.data.actions.remove(action)
        rebuilt.nodes.add(timer_def)
        rebuilt.edges.add(_route_tuple(next(r for r in route_attrs if r["fromNode"] == attrs["fromNode"] and r["toNode"] == attrs["toNode"]
                                           and r["toField"] == "set_translation")))
        rebuilt.edges.add(_route_tuple(orient_attrs))
        for r in route_attrs:
            if r["fromNode"] == timer_def and r["toNode"] in (attrs["fromNode"], orient_attrs["fromNode"]) and r["toField"] == "set_fraction":
                rebuilt.edges.add(_route_tuple(r))
            if r["fromNode"] == timer_def and r["fromField"] == "isActive" and r["toField"] == "set_bind" \
                    and defs.get(r["toNode"]) in views:
                rebuilt.edges.add(_route_tuple(r))
        rebuilt.nodes.add(timer_def)
        return True
    return False


def rebuild_interaction(all_nodes):
    """Turn the exporter's sensor, timer and tour patterns back into the custom properties that author them.

    A sensor is rebuilt only when everything it says is something the properties hold: its parent Transform maps to an
    object (``OB_<name>`` finds the object whose ``x3d_def`` it is), ``enabled`` is true, a proximity box is a centred
    cube, there are no other attributes, and the action and target read from its ``description`` (or, for a file written
    before the description existed, from its ROUTE chain) are consistent with the chain it starts. Only the ROUTE edges
    of that one chain count as rebuilt, so a second edge (a fan-out to another timer) stays a loss. A tour is rebuilt
    only when every stop matches exactly one camera by position *and* orientation. Returns a ``_Rebuilt``.
    """
    rebuilt = _Rebuilt()
    routes = [n for n, _a in all_nodes if getattr(n, "x3dNode", None) is not None and n.getSpec() == "ROUTE"]
    route_attrs = [{k: _attribute_raw(r, k, "") for k in ("fromNode", "fromField", "toNode", "toField")} for r in routes]
    defs = {n.getDefName(): n for n, _a in all_nodes if getattr(n, "x3dNode", None) is not None and n.getDefName()}
    tour_edges_pending = []        # sensor -> timer edges that become consumed only if the tour itself is rebuilt

    for node, ancestry in all_nodes:
        if getattr(node, "x3dNode", None) is None or node.getSpec() not in ("TouchSensor", "ProximitySensor"):
            continue
        spec, name = node.getSpec(), node.getDefName()
        parent = ancestry[-1] if ancestry else None
        if parent is None or parent.getSpec() != "Transform" or not parent.getDefName():
            continue
        obj = _object_by_def(parent.getDefName())
        if obj is None:
            continue
        problems = _sensor_field_problems(node, spec, parent)
        if problems:
            rebuilt.unpreserved.append({"kind": "field", "node": f"{spec} {name}".strip(),
                                        "detail": "not preserved: " + "; ".join(problems)})
            continue
        parts = (_attribute_raw(node, "description", "") or "").split(None, 1)
        if not parts or parts[0] not in ("animate", "viewpoint", "tour"):
            parts = _action_from_routes(name, route_attrs, defs, all_nodes)   # a file written before the description
        if not parts:
            continue
        action, target = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        target_defs = set()
        if action == "animate" and target:
            found = _object_by_def("OB_" + target)
            target_defs = {"OB_" + target, target}
            target = found.name if found is not None else target
        elif action == "viewpoint" and target:
            found = _object_by_def("CA_" + target)
            target_defs = {"CA_" + target, target}
            target = found.name if found is not None else target

        edges = set()
        outgoing = [r for r in route_attrs if r["fromNode"] == name]
        if action == "animate":
            chosen = None
            for attrs in outgoing:
                if attrs["toField"] != "set_startTime" or attrs["fromField"] != _START_FIELD[spec]:
                    continue
                timer = defs.get(attrs["toNode"])
                if timer is None or timer.getSpec() != "TimeSensor" or _timer_problems(timer):
                    continue
                chain_edges, targets = _timer_chain(attrs["toNode"], route_attrs, defs)
                if (target_defs & targets) or (not target_defs and chain_edges):
                    chosen = (attrs, chain_edges)
                    break
            if chosen is None:
                continue
            edges = {_route_tuple(chosen[0])} | chosen[1]
            rebuilt.nodes.add(chosen[0]["toNode"])
        elif action == "viewpoint":
            for attrs in outgoing:
                if attrs["fromField"] != _BIND_FIELD[spec]:
                    continue
                if spec == "ProximitySensor" and attrs["toField"] == "set_bind" and attrs["toNode"] in target_defs:
                    edges = {_route_tuple(attrs)}
                elif spec == "TouchSensor" and attrs["toField"] == "set_boolean":
                    for second in route_attrs:
                        if second["fromNode"] == attrs["toNode"] and second["fromField"] == "inputTrue" \
                                and second["toField"] == "set_bind" and second["toNode"] in target_defs:
                            edges = {_route_tuple(attrs), _route_tuple(second)}
                            rebuilt.nodes.add(attrs["toNode"])
            if not edges:
                continue
        elif action == "tour":
            for attrs in outgoing:
                if attrs["toField"] == "set_startTime" and attrs["fromField"] == _START_FIELD[spec]:
                    tour_edges_pending.append((_route_tuple(attrs), attrs["toNode"]))
            if not tour_edges_pending:
                continue

        obj["x3d_trigger"] = "click" if spec == "TouchSensor" else "proximity"
        obj["x3d_action"] = action
        if target:
            obj["x3d_target"] = target
        if spec == "ProximitySensor":
            size = node.getFieldAsFloatTuple("size", None, ())
            if size and len(size) >= 3:
                scale = _static_triple(parent, "scale", (1.0, 1.0, 1.0))
                obj["x3d_radius"] = round(float(size[0]) * abs(scale[0]) / 2.0, 6)
        rebuilt.nodes.add(name)
        rebuilt.edges |= edges

    if _rebuild_tour(all_nodes, route_attrs, defs, rebuilt):
        for edge, timer_def in tour_edges_pending:
            if timer_def in rebuilt.nodes:
                rebuilt.edges.add(edge)
    return rebuilt


def import_loss_records(all_nodes, rebuilt=None):
    """What a file says that the importer cannot keep, as ``[{kind, node, detail}]``.

    The importer turns interpolator chains into keyframes and discards the rest of the event graph. Dropping it
    silently let export, import, export turn a click-to-open door into a different scene that still validated, so every
    sensor, event utility, ROUTE edge and timer whose behaviour is not kept is listed here, and so is every sensor field
    (``enabled``, an offset or non-cubic proximity box) the custom properties cannot hold.
    """
    rebuilt = rebuilt or _Rebuilt()
    losses = list(rebuilt.unpreserved)
    timers = {}
    for node, _ancestry in all_nodes:
        if getattr(node, "x3dNode", None) is None:
            continue
        spec = node.getSpec()
        name = node.getDefName() or ""
        if name in rebuilt.nodes:
            continue
        if spec in _EVENT_NODES:
            losses.append({"kind": "node", "node": f"{spec} {name}".strip(), "detail": "event node not imported"})
        elif spec == "TimeSensor":
            timers[name] = node
        elif spec == "ROUTE":
            attrs = {k: _attribute_raw(node, k, "") for k in ("fromNode", "fromField", "toNode", "toField")}
            if _route_tuple(attrs) in rebuilt.edges:
                continue
            pair = (attrs["fromField"].replace("_changed", ""), attrs["toField"].replace("set_", ""))
            if pair not in _CONSUMED_ROUTES:
                losses.append({"kind": "route", "node": f"{attrs['fromNode']}.{attrs['fromField']} -> {attrs['toNode']}.{attrs['toField']}",
                               "detail": "ROUTE not imported"})
    for name, node in timers.items():
        loop = node.getFieldAsBool("loop", False, ())
        start = node.getFieldAsFloat("startTime", 0.0, ())
        extra = [p for p in _timer_problems(node) if not p.startswith(("loop=", "starts at load"))]
        if not loop or start != 0.0 or extra:
            losses.append({"kind": "timer", "node": f"TimeSensor {name}".strip(),
                           "detail": f"loop={str(loop).lower()} startTime={start:g}"
                                     + "".join(f" {p}" for p in extra) + ": play-once, disabled or delayed start is not kept "
                                     "(the animation is keyed from frame 1 and re-exported as a looping SceneTimer)"})
    return losses


defer_routes_to_caller = False     # set by load(defer_route_losses=...)
deferred_route_losses = []     # "ROUTE not imported" records that load(defer_route_losses=True) left to its caller


def report_deferred_route_losses(bpycontext, kept=None):
    """Report the deferred ROUTE losses the caller's behaviour graph did not keep (``kept(record)`` is true for those
    it did) exactly as report_import_losses does: log, scene property, ``X3D_IMPORT_STRICT=1``."""
    import json
    losses = [r for r in deferred_route_losses if not (kept and kept(r))]
    deferred_route_losses.clear()
    if not losses:
        return losses
    for record in losses:
        logger.warning("X3D import loss: %s %s: %s", record["kind"], record["node"], record["detail"])
    try:
        raw = bpycontext.scene.get("x3d_import_losses")
        bpycontext.scene["x3d_import_losses"] = json.dumps((json.loads(raw) if raw else []) + losses)
    except Exception:  # pragma: no cover - a scene that cannot hold a property
        pass
    if os.environ.get("X3D_IMPORT_STRICT", "").lower() in ("1", "true", "yes"):
        raise ValueError(f"X3D import lost {len(losses)} behaviour record(s) (X3D_IMPORT_STRICT=1): "
                         + "; ".join(f"{r['kind']} {r['node']}" for r in losses[:5]))
    return losses


def report_import_losses(all_nodes, bpycontext, defer_routes=False):
    """Log the loss records, store them on the scene, and raise under ``X3D_IMPORT_STRICT=1``."""
    import json
    losses = import_loss_records(all_nodes, rebuild_interaction(all_nodes))
    deferred_route_losses.clear()
    if defer_routes:
        deferred_route_losses.extend(r for r in losses if r["kind"] == "route" and r["detail"] == "ROUTE not imported")
        losses = [r for r in losses if not any(r is d for d in deferred_route_losses)]
    if not losses:
        return losses
    for record in losses:
        logger.warning("X3D import loss: %s %s: %s", record["kind"], record["node"], record["detail"])
    try:
        bpycontext.scene["x3d_import_losses"] = json.dumps(losses)
    except Exception:  # pragma: no cover - a scene that cannot hold a property
        pass
    if os.environ.get("X3D_IMPORT_STRICT", "").lower() in ("1", "true", "yes"):
        raise ValueError(f"X3D import lost {len(losses)} behaviour record(s) (X3D_IMPORT_STRICT=1): "
                         + "; ".join(f"{r['kind']} {r['node']}" for r in losses[:5]))
    return losses


def _parent_in_place(child, parent, world, parent_world):
    """Parent ``child`` to ``parent`` without moving it: the local matrix as location / rotation / scale, or, when
    parent and child together hold shear (a rotated child of a non-uniformly scaled parent), the parent's inverse in
    matrix_parent_inverse so the world matrix stays exact. The export writes parent_world^-1 @ child_world either way."""
    import numpy as np
    child.parent = parent
    local = _inverted(parent_world, parent.name) @ world
    loc, rot, scale = matrix_safety.decompose_exact(local) if matrix_safety.has_flat_axis(local) else local.decompose()
    nearest = Matrix.LocRotScale(loc, rot, scale)
    size = max(float(np.abs(np.array(local, dtype=np.float64)).max()), 1e-30)
    if float(np.abs(np.array(nearest, dtype=np.float64) - np.array(local, dtype=np.float64)).max()) <= 1e-6 * size:
        child.matrix_parent_inverse = Matrix()
        matrix_safety.set_basis_exact(child, nearest)
    else:
        child.matrix_parent_inverse = _inverted(parent_world, parent.name)
        child.matrix_basis = world


def _chain_matrix(ancestry, global_matrix, upto=None):
    """global_matrix @ every Transform in ``ancestry`` (up to index ``upto``, inclusive): the exact world matrix of a
    node below them, shear included."""
    matrix = Matrix()
    for anc in ancestry[: None if upto is None else upto + 1]:
        if anc.getSpec() in TRANSFORM_SPECS:
            matrix = matrix @ translateTransform(anc, ancestry)
    return global_matrix @ matrix


_PART = re.compile(r"^ME_(.+)_m(\d+)$")


def _join_material_parts(objs, name):
    """The export writes a Blender mesh with several materials as one Transform holding a Shape per material, their
    geometry DEF'd ME_<mesh>_m0, ME_<mesh>_m1, ... Join such Shapes back into one object with one material slot each
    (glTF importers do the same for a node's primitives). Only that exact pattern, on meshes nothing else uses, at one
    world matrix, without animation: a hand-written Transform with several Shapes keeps one object per Shape under an
    Empty. The modern exporter writes anonymous Shapes under an OB_ Transform; explicit Shape DEF/USE identities
    must never be consumed by this heuristic. Returns the joined object, or None."""
    if len(objs) < 2 or any(ob.type != 'MESH' or ob.data.users != 1 or ob.animation_data is not None
                            or ob.data.shape_keys is not None for ob in objs):
        return None
    if any(ob.get(X3D_DEF_PROPERTY) != "OB_" + name or ob.get(X3D_USE_PROPERTY) for ob in objs):
        return None
    parts = [_PART.match(ob.data.get(X3D_DEF_PROPERTY, "") or "") for ob in objs]
    if not all(parts) or len({m.group(1) for m in parts}) != 1:
        return None
    if sorted(int(m.group(2)) for m in parts) != list(range(len(objs))):
        return None
    world = objs[0].matrix_world
    if any(max(abs(a - b) for ra, rb in zip(world, ob.matrix_world) for a, b in zip(ra, rb)) > 1e-6 for ob in objs):
        return None
    ordered = [ob for _k, ob in sorted(zip((int(m.group(2)) for m in parts), objs), key=lambda item: item[0])]
    first = ordered[0]
    with bpy.context.temp_override(active_object=first, object=first, selected_objects=ordered,
                                   selected_editable_objects=ordered):
        bpy.ops.object.join()
    first.name = name
    first.data.name = parts[0].group(1)
    first.data[X3D_DEF_PROPERTY] = "ME_" + parts[0].group(1)
    return first


def _group_has_metadata(node):
    """True for a Group whose own metadata field holds a Metadata* node (host_metadata reads the same field)."""
    return host_metadata(node) is not None


def _record_cad(transforms, owners, created, key_of, file_order=None):
    """The CAD product structure on the objects that stand for it (node board batch 12): each CADLayer, CADAssembly and
    CADPart owner gets X3D_CAD_PROPERTY (its type, DEF and the fields the file wrote) and the part's ``name`` as its
    object name, so the Outliner reads like the CAD tree; the object a CADFace holds (its Shape's, or its Transform's)
    gets the face's DEF and fields under "face". A CADFace has no object of its own: it holds one node, and an Empty
    for it would add a level on every round trip."""
    def merge(ob, extra):
        try:
            record = json.loads(ob.get(X3D_CAD_PROPERTY) or "{}")
        except (TypeError, ValueError):
            record = {}
        record.update(extra)
        ob[X3D_CAD_PROPERTY] = json.dumps(record)

    for key, owner in owners.items():
        node = transforms[key][0]
        spec = node.getSpec()
        if spec not in CAD_FRAME_SPECS:
            continue
        real = node.getRealNode()
        fields = raw_fields(real, CAD_RAW_FIELDS)
        merge(owner, {"node": spec, "def": real.getDefName() or "", "fields": fields,
                      "order": (file_order or {}).get(id(node), 0)})
        if fields.get("name", "").strip():
            owner.name = fields["name"].strip()[:63]
    marked = set()
    for ob, ancestry in created:
        face = next((i for i in range(len(ancestry) - 1, -1, -1) if ancestry[i].getSpec() == 'CADFace'), None)
        if ob is None or face is None:
            continue
        try:
            ob.name                                   # a part the hierarchy rebuild joined away
        except ReferenceError:
            continue
        if face + 1 < len(ancestry) and ancestry[face + 1].getSpec() in TRANSFORM_SPECS:
            ob = owners.get(key_of(ancestry, face + 1), ob)
        face_key = key_of(ancestry, face)
        if face_key in marked:
            continue
        marked.add(face_key)
        real = ancestry[face].getRealNode()
        order = (file_order or {}).get(id(ancestry[face]), 0)
        merge(ob, {"face": {"def": real.getDefName() or "", "fields": raw_fields(real, CAD_RAW_FIELDS), "order": order}})
        if "order" not in json.loads(ob[X3D_CAD_PROPERTY]):      # a face object's place among its part's faces
            merge(ob, {"order": order})


def rebuild_hierarchy(created, global_matrix, bpycollection, all_nodes=(), carried=()):
    """Give the flat import the file's Transform hierarchy back (the import option keep_hierarchy).

    ``created`` lists (object, ancestry) for every object the import made, in the file's order, each already at its
    world matrix. Each X3D Transform gets one Blender object to stand for it: the object of the Transform's only
    Shape, light, Viewpoint, humanoid or Inline (the export writes Blender object X as <Transform DEF="OB_X"> around
    its Shapes), the export's Shapes of one multi-material mesh joined back into one object (_join_material_parts),
    or else an Empty named after the Transform (several objects, child Transforms only, or an exported Empty: a
    Transform DEF'd OB_ with nothing in it). Every object is then parented to the object of its nearest Transform.
    Group, Switch, LOD and the other grouping nodes have no matrix and are not kept as objects, except a Group that
    carries its own Metadata, which gets an Empty so its Metadata and its place in the tree survive. Objects that already
    have a parent (a skin on its armature, an Inline's content on its placeholder) keep it.

    World matrices come from the file, shear included: the flat import bakes the shear of a rotated child under a
    non-uniformly scaled parent into the child's mesh, which a parented child does not need (Blender composes the
    parent's scale with the child's rotation itself), so that bake is undone here.

    Returns {Transform node: [objects]}; importRoutesXML keys every DEF/USE occurrence owner, so its children follow it."""
    def key_of(ancestry, upto):
        return tuple(id(a) for a in ancestry[:upto + 1])

    transforms = {}      # key -> (Transform node, its ancestry)
    parent_key = {}      # key -> key of the Transform above it, or None
    members = {}         # key -> [objects whose nearest Transform it is]
    worlds = {}          # object -> exact world matrix
    branch_owners = set()  # Transforms whose direct objects lie behind a Switch/LOD visibility boundary

    def register(ancestry, indices):
        previous = None
        for i in indices:
            key = key_of(ancestry, i)
            if key not in transforms:
                transforms[key] = (ancestry[i], ancestry[:i])
                parent_key[key] = previous
            previous = key
        return previous

    def frame_like(a):
        # a Transform, or a Group that carries its own Metadata: IFC's spatial tree (Site, Building, Storey) travels
        # as such Groups, and without an Empty of its own the Group's Metadata and the nesting are lost on export.
        return a.getSpec() in TRANSFORM_SPECS or a.getSpec() in CAD_FRAME_SPECS \
            or (a.getSpec() == 'Group' and _group_has_metadata(a))

    for ob, ancestry in created:
        if ob is None or ob.parent is not None:
            continue
        transform_indices = [i for i, a in enumerate(ancestry) if frame_like(a)]
        nearest = register(ancestry, transform_indices)
        if nearest is not None and any(a.getSpec() in {'Switch', 'LOD', 'GeoLOD'}
                                       for a in ancestry[transform_indices[-1] + 1:]):
            # A branch's Shape cannot own the Transform above the selector: hiding that Shape would also hide
            # child Transforms belonging to other branches (or content outside the selector).
            branch_owners.add(nearest)
        unbaked = _UNBAKED_DATA.pop(ob.as_pointer(), None)
        if unbaked is not None:
            baked = ob.data
            ob.data = unbaked
            if baked.users == 0:
                bpy.data.meshes.remove(baked) if isinstance(baked, bpy.types.Mesh) else None
            worlds[ob] = _chain_matrix(ancestry, global_matrix)
        else:
            worlds[ob] = ob.matrix_world.copy()
        if nearest is not None:
            members.setdefault(nearest, [])
            if ob not in members[nearest]:
                members[nearest].append(ob)
    # an exported Empty: <Transform DEF="OB_X"> with no object below it
    for node, ancestry in all_nodes:
        if node.getSpec() == 'Transform' and (node.getDefName() or "").startswith("OB_") \
                and not any(a.getSpec() == 'HAnimHumanoid' for a in ancestry):
            path = list(ancestry) + [node]
            register(path, [i for i, a in enumerate(path) if frame_like(a)])
    # a Transform holding only carried nodes (find_carried): it needs an object for them to ride on (place_carried
    # looks for the nearest Transform, so the key is the Transform's, not a metadata Group's)
    holds_carried = {register(ancestry, [i for i, a in enumerate(ancestry) if a.getSpec() == 'Transform'])
                     for _node, ancestry, _xml in carried} - {None}

    has_children = {k for k in parent_key.values() if k is not None}
    owners = {}
    for key, (node, ancestry) in transforms.items():
        objs = members.get(key, [])
        name = node.getRealNode().getDefName() or "Transform"
        name = name[3:] if name.startswith("OB_") and len(name) > 3 else name
        joined = None
        if len(objs) > 1 and key not in branch_owners:
            saved = {ob.name: worlds.pop(ob) for ob in objs}   # before the join removes all but one of them
            joined = _join_material_parts(objs, name)
            if joined is None:
                worlds.update({bpy.data.objects[n]: w for n, w in saved.items()})
            else:
                worlds[joined] = next(iter(saved.values()))
                members[key] = objs = [joined]
        if len(objs) == 1 and key not in branch_owners:
            owners[key] = objs[0]
        elif objs or key in has_children or key in holds_carried or (node.getDefName() or "").startswith("OB_"):
            empty = bpy.data.objects.new(name, None)
            bpycollection.objects.link(empty)
            empty.empty_display_type = 'PLAIN_AXES'
            empty.empty_display_size = 0.2
            worlds[empty] = getFinalMatrix(node, None, ancestry, global_matrix)
            empty.matrix_world = worlds[empty]
            tag_x3d_identity(empty, node, ancestry)
            chain = group_chain(node, ancestry)       # a Transform on a Switch branch or LOD level: the export regroups it
            if chain:
                empty[GROUP_CHAIN_PROPERTY] = json.dumps(chain)
            owners[key] = empty

    def owner_above(key):
        key = parent_key.get(key)
        while key is not None and key not in owners:
            key = parent_key.get(key)
        return owners.get(key) if key is not None else None

    links = []
    for key, owner in owners.items():
        above = owner_above(key)
        if above is not None and above is not owner:
            links.append((len(key), owner, above))
        for ob in members.get(key, []):
            if ob is not owner:
                links.append((len(key) + 1, ob, owner))
    parented = set()
    for _depth, child, parent in sorted(links, key=lambda item: item[0]):
        if child.parent is None:
            _parent_in_place(child, parent, worlds[child], worlds[parent])
            parented.add(child)
    for ob, world in worlds.items():   # a root whose shear bake was undone: its matrix as the file gives it
        if ob not in parented and ob.parent is None:
            _set_world_matrix(ob, world)

    for key, owner in owners.items():
        # the object that stands for a Transform carries that Transform's Metadata (a joined or single Shape object
        # keeps its own Shape Metadata under METADATA_PROPERTY as before)
        if TRANSFORM_METADATA_PROPERTY not in owner:
            keep_host_metadata(owner, transforms[key][0], TRANSFORM_METADATA_PROPERTY)

    _record_cad(transforms, owners, created, key_of, {id(n): i for i, (n, _a) in enumerate(all_nodes)})

    by_node = {}
    for key, owner in owners.items():
        node = transforms[key][0].getRealNode()
        # A DEF may occur under several parents through USE. Keep the ancestry with each owner: neither a single
        # pointer nor the DEF's own ancestry describes all occurrences of an animated Transform.
        node.hierarchy_owners.append((owner, transforms[key][1]))
        by_node.setdefault(node, []).append(owner)
    if not _INLINE_STACK:
        # once, by the outermost file: a depsgraph update walks every object in the scene, so an Inline fan-out paid
        # it once per Inline file over a growing scene (4.2 of 5.6 s at 300 Inlines, chaos round 2.7.3)
        bpy.context.view_layer.update()
    return by_node


def importRoutesXML(all_nodes, global_matrix, bpycontext):
    """Turn XML <ROUTE> chains into keyframes on the objects under animated Transforms.

    Objects are imported flat (world matrices), so for every key the world
    matrix is rebuilt as global * ancestors * animated Transform * descendants.
    """
    routes = []
    for node, _ancestry in all_nodes:
        if getattr(node, "x3dNode", None) is None or node.getSpec() != 'ROUTE':
            continue
        attrs = {name: _attribute_raw(node, name) for name in ('fromNode', 'fromField', 'toNode', 'toField')}
        if all(attrs.values()):
            routes.append(attrs)
    if not routes:
        return

    root = all_nodes[0][0]
    defDict = root.getDefDict()

    timers_for_interp = {}
    morphs = {}  # Coordinate DEF -> CoordinateInterpolator DEF
    channels = {}  # target DEF -> {'translation': node, 'rotation': node, 'scale': node}
    for route in routes:
        from_field = route['fromField'].replace('_changed', '')
        to_field = route['toField'].replace('set_', '')
        if from_field == 'fraction' and to_field == 'fraction':
            timers_for_interp[route['toNode']] = route['fromNode']
        elif from_field == 'value' and to_field in {'translation', 'rotation', 'scale'}:
            channels.setdefault(route['toNode'], {})[to_field] = route['fromNode']
        elif from_field == 'value' and to_field == 'point':
            morphs[route['toNode']] = route['fromNode']

    scene = bpycontext.scene
    fps = scene.render.fps / scene.render.fps_base
    frame_start = scene.frame_start
    last_frame = frame_start

    if morphs:
        last_frame = max(last_frame, _import_coordinate_morphs(morphs, timers_for_interp, defDict, scene, fps, frame_start))

    for target_def, channel_defs in channels.items():
        target = defDict.get(target_def)
        if target is not None and target.getSpec() == 'HAnimJoint':
            _animate_joint(defDict, target_def, target, channel_defs, timers_for_interp, scene, fps, frame_start)
            continue
        if target is None or target.getSpec() not in TRANSFORM_SPECS:
            logger.warning("ROUTE target %r is not a Transform; skipped", target_def)
            continue

        key_lists = {}
        value_lists = {}
        cycle_interval = None
        loop = False
        for field, interp_def in channel_defs.items():
            interp = defDict.get(interp_def)
            if interp is None:
                continue
            width = 4 if field == 'rotation' else 3
            keys = [float(k) for k in interp.getFieldAsArray('key', 0, ())]
            values = [tuple(float(v) for v in value) for value in interp.getFieldAsArray('keyValue', width, ())]
            if not keys or len(values) < len(keys):
                continue
            key_lists[field] = keys
            value_lists[field] = values[:len(keys)]
            timer = defDict.get(timers_for_interp.get(interp_def, ''))
            if timer is not None and cycle_interval is None:
                cycle_interval = timer.getFieldAsFloat('cycleInterval', 1.0, ())
                loop = timer.getFieldAsBool('loop', False, ())
        if not key_lists:
            continue
        # TimeSensor loop is deliberately not turned into a CYCLES modifier:
        # the modifier wraps the last key onto the first, which hides the
        # final pose; users can add cycling in the graph editor. (Dropped once
        # per target here: inside the per-object loop below it raised
        # UnboundLocalError for the second object under the same Transform.)
        del loop
        cycle_interval = cycle_interval or 1.0
        union_keys = sorted({k for keys in key_lists.values() for k in keys})

        # Static fields of the animated Transform
        static_tx = target.getFieldAsFloatTuple('translation', None, ())
        static_rot = target.getFieldAsFloatTuple('rotation', None, ())
        static_sca = target.getFieldAsFloatTuple('scale', None, ())
        cent = target.getFieldAsFloatTuple('center', None, ())
        scaori = target.getFieldAsFloatTuple('scaleOrientation', None, ())

        # Objects whose ancestry passes through the animated Transform; under keep_hierarchy only the object that
        # stands for the Transform (rebuild_hierarchy), in its parent's space, and its children follow it
        owners = target.getRealNode().hierarchy_owners
        if owners:
            keyed = [(owner, None, ancestry) for owner, ancestry in owners]
        else:
            keyed = [(getattr(n, 'blendObject', None), n, anc) for n, anc in all_nodes]
        for bpyob, node, ancestry in keyed:
            if bpyob is None:
                continue
            if node is None:   # the hierarchy owner: the target itself is the last Transform
                ancestry = list(ancestry) + [target]
            elif target not in ancestry:
                continue
            index = ancestry.index(target)
            above = Matrix()
            for anc in ancestry[:index]:
                if anc.getSpec() in TRANSFORM_SPECS:
                    above = above @ translateTransform(anc, ancestry)
            below = Matrix()
            for anc in ancestry[index + 1:]:
                if anc.getSpec() in TRANSFORM_SPECS:
                    below = below @ translateTransform(anc, ancestry)
            if node is not None and node.getSpec() in TRANSFORM_SPECS:
                below = below @ translateTransform(node, ancestry)

            # Non-Transform nodes (lights, viewpoints) carry their own local offset
            # in the static world matrix; recover it so it is kept per key.
            static_world = bpyob.matrix_world.copy()
            static_chain = global_matrix @ above @ _x3d_transform_matrix(static_tx, static_rot, static_sca, cent, scaori) @ below
            own_offset = _inverted(static_chain, bpyob.name) @ static_world

            if bpyob.animation_data is None:
                bpyob.animation_data_create()
            action = bpy.data.actions.new(f"{bpyob.name}_x3d")
            bpyob.animation_data.action = action
            try:  # Blender 4.4+ slotted actions
                if hasattr(action, "slots") and not action.slots:
                    slot = action.slots.new(id_type='OBJECT', name=bpyob.name)
                    bpyob.animation_data.action_slot = slot
            except Exception:
                pass
            bpyob.rotation_mode = 'QUATERNION'

            union_keys = budget.thin_keys(sorted(union_keys), budget.MAX_IMPORT_KEYS, f"The animation of {bpyob.name}")
            for key in union_keys:
                tx = _interpolate_channel(key_lists.get('translation'), value_lists.get('translation'), key, 'translation') or static_tx
                rot = _interpolate_channel(key_lists.get('rotation'), value_lists.get('rotation'), key, 'rotation') or static_rot
                sca = _interpolate_channel(key_lists.get('scale'), value_lists.get('scale'), key, 'scale') or static_sca
                world = global_matrix @ above @ _x3d_transform_matrix(tx, rot, sca, cent, scaori) @ below @ own_offset
                if bpyob.parent is not None:
                    world = _inverted(bpyob.parent.matrix_world @ bpyob.matrix_parent_inverse, bpyob.parent.name) @ world
                frame = frame_start + key * cycle_interval * fps
                last_frame = max(last_frame, frame)
                loc, quat, scale = world.decompose()
                bpyob.location = loc
                bpyob.rotation_quaternion = quat
                bpyob.scale = scale
                bpyob.keyframe_insert("location", frame=frame)
                bpyob.keyframe_insert("rotation_quaternion", frame=frame)
                bpyob.keyframe_insert("scale", frame=frame)

            for fcu in _action_fcurves(action):
                for kf in fcu.keyframe_points:
                    kf.interpolation = 'LINEAR'

    _fit_frame_end(scene, last_frame)


def _fit_frame_end(scene, last_frame):
    """End the timeline where the file's animation ends.

    The export samples scene.frame_start..frame_end, so a 2 s file imported into the default 1..250 timeline came back
    as a 10.4 s cycle that holds still for its last 8.4 s. When the scene had no animation before this import
    (_timeline_fit_pending, set by load_web3d) the first animation fits frame_end to its own end; later ones, and every
    import into an already animated scene, only extend it, so a user's longer timeline is never cut."""
    global _timeline_fit_pending
    end = int(round(last_frame))
    if end <= scene.frame_start:
        return
    if _timeline_fit_pending:
        scene.frame_end = end
        _timeline_fit_pending = False
    elif end > scene.frame_end:
        scene.frame_end = end


_timeline_fit_pending = False


def _animate_joint(defDict, target_def, joint, channel_defs, timers_for_interp, scene, fps, frame_start):
    """Keyframe a pose bone from HAnimJoint rotation/translation interpolators.

    HAnim applies J = T(t) T(c) R T(-c) in the parent joint's frame; the
    pose bone's basis is L^-1 @ J @ L with L the bone's rest matrix.
    """
    armature, bone_name = _hanim_joint_target(defDict, target_def)
    if armature is None:
        logger.warning("ROUTE to HAnimJoint %r has no imported bone; skipped", target_def)
        return
    key_lists, value_lists = {}, {}
    cycle_interval = None
    for field, interp_def in channel_defs.items():
        interp = defDict.get(interp_def)
        if interp is None or field not in {'rotation', 'translation'}:
            continue
        width = 4 if field == 'rotation' else 3
        keys = [float(k) for k in interp.getFieldAsArray('key', 0, ())]
        values = [tuple(float(v) for v in value) for value in interp.getFieldAsArray('keyValue', width, ())]
        if not keys or len(values) < len(keys):
            continue
        key_lists[field] = keys
        value_lists[field] = values[:len(keys)]
        timer = defDict.get(timers_for_interp.get(interp_def, ''))
        if timer is not None and cycle_interval is None:
            cycle_interval = timer.getFieldAsFloat('cycleInterval', 1.0, ())
    if not key_lists:
        return
    cycle_interval = cycle_interval or 1.0
    center = Vector(joint.getFieldAsFloatTuple('center', (0.0, 0.0, 0.0), ()))
    bone = armature.data.bones[bone_name]
    rest = bone.matrix_local
    rest_inv = rest.inverted()
    pose_bone = armature.pose.bones[bone_name]
    pose_bone.rotation_mode = 'QUATERNION'
    if armature.animation_data is None:
        armature.animation_data_create()
    if armature.animation_data.action is None:
        action = bpy.data.actions.new(f"{armature.name}_x3d")
        armature.animation_data.action = action
        try:
            if hasattr(action, "slots") and not action.slots:
                armature.animation_data.action_slot = action.slots.new(id_type='OBJECT', name=armature.name)
        except Exception:
            pass
    last_frame = frame_start
    for key in sorted({k for keys in key_lists.values() for k in keys}):
        rot = _interpolate_channel(key_lists.get('rotation'), value_lists.get('rotation'), key, 'rotation') or (0.0, 0.0, 1.0, 0.0)
        tx = _interpolate_channel(key_lists.get('translation'), value_lists.get('translation'), key, 'translation') or (0.0, 0.0, 0.0)
        joint_matrix = Matrix.Translation(Vector(tx)) @ Matrix.Translation(center) @ translateRotation(rot) @ Matrix.Translation(-center)
        basis = rest_inv @ joint_matrix @ rest
        loc, quat, scale = basis.decompose()
        pose_bone.location = loc
        pose_bone.rotation_quaternion = quat
        pose_bone.scale = scale
        frame = frame_start + key * cycle_interval * fps
        last_frame = max(last_frame, frame)
        pose_bone.keyframe_insert("location", frame=frame)
        pose_bone.keyframe_insert("rotation_quaternion", frame=frame)
        pose_bone.keyframe_insert("scale", frame=frame)
    for fcu in _action_fcurves(armature.animation_data.action):
        for kf in fcu.keyframe_points:
            kf.interpolation = 'LINEAR'
    _fit_frame_end(scene, last_frame)


def _action_fcurves(action):
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None and len(fcurves):
        return fcurves
    try:
        return action.layers[0].strips[0].channelbag(action.slots[0]).fcurves
    except Exception:
        return fcurves if fcurves is not None else []


def importRoute(node, ancestry):
    """
    Animation route only at the moment
    """

    if not hasattr(node, 'fields'):
        return

    routeIpoDict = node.getRouteIpoDict()

    def getIpo(act_id):
        try:
            action = routeIpoDict[act_id]
        except:
            action = routeIpoDict[act_id] = bpy.data.actions.new('web3d_ipo')
        return action

    # for getting definitions
    defDict = node.getDefDict()
    """
    Handles routing nodes to each other

ROUTE vpPI.value_changed TO champFly001.set_position
ROUTE vpOI.value_changed TO champFly001.set_orientation
ROUTE vpTs.fraction_changed TO vpPI.set_fraction
ROUTE vpTs.fraction_changed TO vpOI.set_fraction
ROUTE champFly001.bindTime TO vpTs.set_startTime
    """

    # from_id, from_type = node.id[1].split('.')
    # to_id, to_type = node.id[3].split('.')

    # value_changed
    set_position_node = None
    set_orientation_node = None
    time_node = None

    for field in node.fields:
        if field and field[0] == 'ROUTE':
            try:
                from_id, from_type = field[1].split('.')
                to_id, to_type = field[3].split('.')
            except:
                logger.warning("Invalid ROUTE %s" % field)
                continue

            if from_type == 'value_changed':
                if to_type == 'set_position':
                    action = getIpo(to_id)
                    set_data_from_node = defDict[from_id]
                    translatePositionInterpolator(set_data_from_node, action, ancestry)

                if to_type in {'set_orientation', 'rotation'}:
                    action = getIpo(to_id)
                    set_data_from_node = defDict[from_id]
                    translateOrientationInterpolator(set_data_from_node, action, ancestry)

                if to_type == 'set_scale':
                    action = getIpo(to_id)
                    set_data_from_node = defDict[from_id]
                    translateScalarInterpolator(set_data_from_node, action, ancestry)

            elif from_type == 'bindTime':
                action = getIpo(from_id)
                time_node = defDict[to_id]
                translateTimeSensor(time_node, action, ancestry)


def importHeadMeta(bpyscene, root_node):
    """Keep the <head> meta statements of an X3D (XML) file on the scene, for the X3D 4.0 export to write back.

    Every name/content pair is kept in file order, repeated names (several reference entries, say) included;
    which of them the export carries over is decided there. Pairs already on the scene from an earlier import
    stay, and an exact repeat is stored once.
    """
    x3d_element = getattr(root_node, "x3dNode", None)
    if x3d_element is None:  # classic VRML encoding
        return
    entries = scene_head_meta(bpyscene)
    count = len(entries)
    for head in x3d_element.childNodes:
        if head.nodeType != head.ELEMENT_NODE or head.tagName != "head":
            continue
        for meta in head.childNodes:
            if meta.nodeType != meta.ELEMENT_NODE or meta.tagName != "meta" or not meta.hasAttribute("content"):
                continue
            pair = (meta.getAttribute("name"), meta.getAttribute("content"))
            if pair[0] and pair not in entries:
                entries.append(pair)
    if len(entries) > count:
        bpyscene[HEAD_META_PROPERTY] = [{"name": name, "content": content} for name, content in entries]


# Elements that can sit inside a Switch in the XML encoding without being one of its children (whichChoice counts children only)
_NOT_SWITCH_CHILDREN = {'ROUTE', 'IS', 'field', 'fieldValue', 'connect', 'ProtoDeclare', 'ExternProtoDeclare', 'IMPORT', 'EXPORT'}


def _switch_child_counts(node):
    spec = node.getSpec()
    return spec is not None and not spec.startswith('Metadata') and spec not in _NOT_SWITCH_CHILDREN


def switch_hides(node, ancestry):
    """True when a Switch above ``node`` does not choose the branch it sits on.

    ``whichChoice`` indexes the Switch's children (``choice`` in VRML97); -1, the default, or an index past the last child
    chooses none. Nested Switches all have to choose the branch. A USE'd Switch reads its fields from the DEF'd node.
    """
    chain = tuple(ancestry) + (node,)
    for i, anc in enumerate(ancestry):
        if anc.getSpec() != 'Switch':
            continue
        choice = anc.getFieldAsInt('whichChoice', -1, ancestry[:i])
        kids = [c for c in anc.getRealNode().children if _switch_child_counts(c)]
        if not (0 <= choice < len(kids)) or kids[choice] is not chain[i + 1]:
            return True
    return False


SWITCH_BRANCH_PROPERTY = "x3d_switch"      # on an object made under a DEF'd Switch: "DEF:branch:whichChoice" for each Switch above it


def switch_branches(node, ancestry):
    """"DEF:branch:whichChoice" for each DEF'd Switch above ``node``, outermost first, space-separated: the branch (index
    among the Switch's children) ``node`` sits on and the Switch's own whichChoice in the file. The behaviour graph's Play
    uses it to show and hide what a ROUTE to ``whichChoice`` chooses. A Switch with no DEF cannot be routed to, so is left out."""
    chain = tuple(ancestry) + (node,)
    entries = []
    for i, anc in enumerate(ancestry):
        if anc.getSpec() != 'Switch':
            continue
        real = anc.getRealNode()
        name = real.getDefName()
        kids = [c for c in real.children if _switch_child_counts(c)]
        branch = next((n for n, kid in enumerate(kids) if kid is chain[i + 1]), None)
        if name and branch is not None:
            entries.append(f"{name}:{branch}:{anc.getFieldAsInt('whichChoice', -1, ancestry[:i])}")
    return " ".join(entries)


GROUP_CHAIN_PROPERTY = "x3d_group_chain"     # on an object made under a Switch or LOD: JSON, outermost first, for the export
group_keys = {}                              # id(real Switch/LOD node) -> its key in GROUP_CHAIN_PROPERTY (DEF, else made up)


# Grouping nodes the import dissolves but records for the export (group_chain), with the fields kept as the file wrote
# them (their attribute text: geospatial values are doubles, and a string list keeps its quoting)
GROUP_RAW_FIELDS = {
    'Billboard': ('axisOfRotation',),
    'GeoLocation': ('geoCoords', 'geoSystem'),
    'GeoLOD': ('center', 'geoSystem', 'range', 'rootUrl', 'child1Url', 'child2Url', 'child3Url', 'child4Url'),
    'StaticGroup': ('visible', 'bboxCenter', 'bboxSize', 'bboxDisplay'),   # node board batch 12
}
GEO_ORIGIN_FIELDS = ('geoCoords', 'geoSystem', 'rotateYUp')


def raw_fields(node, names):
    """{field: attribute text} for the fields the file sets on ``node`` (XML encoding only; empty otherwise)."""
    out = {}
    for name in names:
        value = _attribute_raw(node, name)
        if value is not None:
            out[name] = value
    return out


def group_chain(node, ancestry):
    """Every Switch and LOD above ``node``, outermost first, as the exporter needs them to write the node back: its type,
    DEF (or a key unique in this import), the branch ``node`` sits on, how many branches there are, and the Switch's
    whichChoice or the LOD's range and center (in the file's units). Billboard, GeoLocation and GeoLOD come with their fields
    as the file wrote them (GROUP_RAW_FIELDS) and their GeoOrigin, as one group of children."""
    chain = tuple(ancestry) + (node,)
    out = []
    for i, anc in enumerate(ancestry):
        spec = anc.getSpec()
        if spec not in ('Switch', 'LOD', *GROUP_RAW_FIELDS):
            continue
        real = anc.getRealNode()
        kids = [c for c in real.children if _switch_child_counts(c) and c.getSpec() != 'GeoOrigin']
        index = next((n for n, kid in enumerate(kids) if kid is chain[i + 1]), None)
        if index is None:
            continue
        name = anc.getDefName() or real.getDefName() or ""
        key = group_keys.setdefault(id(real), name or f"{spec}_{len(group_keys) + 1}")
        entry = {"node": spec, "key": key, "def": name, "branch": index, "branches": len(kids)}
        if spec in GROUP_RAW_FIELDS:
            # one group of children (no branches): the fields as written, and a GeoOrigin child if there is one
            entry.update(branch=0, branches=1, fields=raw_fields(anc, GROUP_RAW_FIELDS[spec]))
            origin = real.getChildBySpec('GeoOrigin')
            if origin is not None:
                entry["geoOrigin"] = raw_fields(origin, GEO_ORIGIN_FIELDS)
        elif spec == 'Switch':
            entry["whichChoice"] = anc.getFieldAsInt('whichChoice', -1, ancestry[:i])
        else:
            entry["range"] = [float(v) for v in (anc.getFieldAsArray('range', 0, ancestry[:i], 1.0) or [])]
            entry["center"] = [float(v) for v in anc.getFieldAsFloatTuple('center', (0.0, 0.0, 0.0), ancestry[:i])]
        out.append(entry)
    return out


# -- rigid body physics as Blender rigid bodies (node board batch 6) ---------------------------------------------------
# A RigidBodyCollection becomes the scene's rigid body world, each RigidBody's object a Blender rigid body, and a
# SingleAxisHingeJoint an empty with a HINGE constraint. What Blender holds (mass, fixed, damping, gravity, the hinge's
# anchor, axis and limits) is read back from Blender on export, so editing it in Blender reaches the file; every field
# is also kept as the file wrote it (RIGID_*_PROPERTY, JSON) for what Blender cannot hold (linearVelocity, the
# CollisionCollection, a joint's forceOutput...).
RIGID_WORLD_PROPERTY = "x3d_rigid_world"      # on the scene
RIGID_BODY_PROPERTY = "x3d_rigid_body"        # on a body's object
RIGID_JOINT_PROPERTY = "x3d_rigid_joint"      # on a joint's empty
RIGID_COLLECTION_FIELDS = ('autoDisable', 'constantForceMix', 'contactSurfaceThickness', 'disableAngularSpeed',
                           'disableLinearSpeed', 'disableTime', 'enabled', 'errorCorrection', 'gravity', 'iterations',
                           'maxCorrectionSpeed', 'preferAccuracy')
RIGID_BODY_FIELDS = ('angularDampingFactor', 'angularVelocity', 'autoDamp', 'autoDisable', 'centerOfMass',
                     'disableAngularSpeed', 'disableLinearSpeed', 'disableTime', 'enabled', 'finiteRotationAxis', 'fixed',
                     'forces', 'inertia', 'linearDampingFactor', 'linearVelocity', 'mass', 'orientation', 'position',
                     'torques', 'useFiniteRotation', 'useGlobalGravity')
COLLIDABLE_FIELDS = ('enabled', 'rotation', 'translation')
COLLISION_COLLECTION_FIELDS = ('appliedParameters', 'bounce', 'enabled', 'frictionCoefficients', 'minBounceSpeed',
                               'slipFactors', 'softnessConstantForceMix', 'softnessErrorCorrection', 'surfaceSpeed')
HINGE_FIELDS = ('anchorPoint', 'axis', 'forceOutput', 'maxAngle', 'minAngle', 'stopBounce', 'stopErrorCorrection')
# the settable fields of the other joints (their output-only ones, such as separation or hinge1Angle, are never kept)
JOINT_FIELDS = {
    'SingleAxisHingeJoint': HINGE_FIELDS,
    'BallJoint': ('anchorPoint', 'forceOutput'),
    'SliderJoint': ('axis', 'forceOutput', 'maxSeparation', 'minSeparation', 'stopBounce', 'stopErrorCorrection'),
    'DoubleAxisHingeJoint': ('anchorPoint', 'axis1', 'axis2', 'desiredAngularVelocity1', 'desiredAngularVelocity2',
                             'forceOutput', 'maxAngle1', 'maxTorque1', 'maxTorque2', 'minAngle1', 'stop1Bounce',
                             'stop1ConstantForceMix', 'stop1ErrorCorrection', 'suspensionErrorCorrection',
                             'suspensionForce'),
    'UniversalJoint': ('anchorPoint', 'axis1', 'axis2', 'forceOutput', 'stop1Bounce', 'stop1ErrorCorrection',
                       'stop2Bounce', 'stop2ErrorCorrection'),
}
JOINT_CONSTRAINT = {'SingleAxisHingeJoint': 'HINGE', 'BallJoint': 'POINT', 'SliderJoint': 'SLIDER',
                    'DoubleAxisHingeJoint': 'GENERIC', 'UniversalJoint': 'GENERIC'}
COLLISION_SHAPE_OF = {'Box': 'BOX', 'Sphere': 'SPHERE', 'Cylinder': 'CYLINDER', 'Cone': 'CONE'}


def _container_of(node):
    element = getattr(node, "x3dNode", None)
    return element.getAttribute('containerField') if element is not None and element.hasAttribute('containerField') else ""


def _floats(text, default):
    try:
        values = [float(v) for v in str(text).replace(",", " ").split()]
    except ValueError:
        return default
    return values if len(values) == len(default) else default


def import_rigid_bodies(all_nodes, global_matrix, bpycontext):
    """Every RigidBodyCollection: Blender's rigid body world, rigid bodies and hinge constraints (see above). The
    objects already stand where the bodies place them (RigidBody is a frame, PHYSICS_FRAME_SPECS)."""
    import json
    scene = bpycontext.scene
    axes = global_matrix.to_3x3().normalized()
    for node, ancestry in all_nodes:
        if node.getSpec() != 'RigidBodyCollection' or node.node_type == NODE_REFERENCE:
            continue
        real = node.getRealNode()
        if scene.rigidbody_world is None:
            with bpycontext.temp_override(scene=scene):
                bpy.ops.rigidbody.world_add()
        world = scene.rigidbody_world
        fields = raw_fields(node, RIGID_COLLECTION_FIELDS)
        scene.gravity = axes @ Vector(_floats(fields.get('gravity', '0 -9.8 0'), [0.0, -9.8, 0.0]))
        if 'iterations' in fields:
            world.solver_iterations = max(1, int(_floats(fields['iterations'], [10.0])[0]))
        record = {"def": node.getDefName() or real.getDefName() or "", "fields": fields, "collider": None}
        objects = {}           # id(real RigidBody node) -> object
        for body in real.children:
            if body.getSpec() == 'CollisionCollection':
                record["collider"] = {"def": body.getDefName() or "", "fields": raw_fields(body, COLLISION_COLLECTION_FIELDS),
                                      "collidables": [c.getRealNode().getDefName() for c in body.getRealNode().children
                                                      if c.getSpec() in ('CollidableShape', 'CollidableOffset')
                                                      and c.getRealNode().getDefName()]}
            if body.getSpec() != 'RigidBody' or body.node_type == NODE_REFERENCE:
                continue
            ob, collidable, offsets = _body_object(body)
            if ob is None:
                logger.warning("RigidBody %s: no shape was imported for it; not made a Blender rigid body",
                               body.getDefName() or "(no DEF)")
                continue
            objects[id(body.getRealNode())] = ob
            body_fields = raw_fields(body, RIGID_BODY_FIELDS)
            with bpycontext.temp_override(scene=scene, object=ob, active_object=ob, selected_objects=[ob]):
                bpy.ops.rigidbody.object_add(type='PASSIVE' if body_fields.get('fixed', 'false') == 'true' else 'ACTIVE')
            rb = ob.rigid_body
            rb.mass = max(0.001, _floats(body_fields.get('mass', '1'), [1.0])[0])
            auto = body_fields.get('autoDamp', 'false') == 'true'
            rb.linear_damping = _floats(body_fields.get('linearDampingFactor', '0.001'), [0.001])[0] if auto else 0.0
            rb.angular_damping = _floats(body_fields.get('angularDampingFactor', '0.001'), [0.001])[0] if auto else 0.0
            rb.enabled = body_fields.get('enabled', 'true') != 'false'
            primitive = json.loads(ob.data.get(PRIMITIVE_PROPERTY, "{}") or "{}") if ob.type == 'MESH' else {}
            rb.collision_shape = COLLISION_SHAPE_OF.get(primitive.get("node"), 'CONVEX_HULL')
            ob[RIGID_BODY_PROPERTY] = json.dumps({"def": body.getDefName() or "", "fields": body_fields,
                                                  "collidable": collidable, "offsets": offsets})
        for joint in real.children:
            if joint.getSpec() in JOINT_CONSTRAINT and joint.node_type != NODE_REFERENCE:
                _joint(joint, objects, axes, global_matrix, bpycontext, scene)
            elif joint.getSpec() == 'MotorJoint':
                logger.info("MotorJoint %s: not made a Blender constraint (Blender has no motor joint between two "
                            "bodies with three axes)", joint.getDefName() or "")
        scene[RIGID_WORLD_PROPERTY] = json.dumps(record)


def _body_object(body):
    """(the object the import made for a RigidBody's first collidable shape, that collidable's record, the
    CollidableOffsets between the body and it, outermost first)."""
    offsets = []
    for geometry in body.getRealNode().children:
        node = geometry
        while node is not None and node.getSpec() == 'CollidableOffset':
            offsets.append({"def": node.getRealNode().getDefName() or "", "fields": raw_fields(node, COLLIDABLE_FIELDS)})
            node = next((c for c in node.getRealNode().children if c.getSpec() in ('CollidableShape', 'CollidableOffset')),
                        None)
        if node is None or node.getSpec() != 'CollidableShape':
            offsets = []
            continue
        shape = next((c for c in node.getRealNode().children if c.getSpec() == 'Shape'), None)
        ob = getattr(shape.getRealNode(), "blendObject", None) if shape is not None else None
        try:
            if ob is not None and ob.name:
                return ob, {"def": node.getRealNode().getDefName() or "", "fields": raw_fields(node, COLLIDABLE_FIELDS)}, offsets
        except ReferenceError:
            pass
        offsets = []
    return None, None, []


def _joint(joint, objects, axes, global_matrix, bpycontext, scene):
    """A joint as an empty with a Blender rigid body constraint between its two bodies (JOINT_CONSTRAINT): at the
    anchor (a SliderJoint, which has none, at its first body), turned so the constraint's own axes are the joint's:
    HINGE turns about Z (axis); SLIDER slides along X (axis), limited by min/maxSeparation; GENERIC (Double axis hinge,
    Universal) frees Z (axis1) and X (axis2), Z limited by min/maxAngle1 on a DoubleAxisHingeJoint; POINT is a ball."""
    import json
    import math
    spec = joint.getSpec()
    fields = raw_fields(joint, JOINT_FIELDS[spec])
    ends = {}
    for child in joint.getRealNode().children:
        if child.getSpec() == 'RigidBody':
            ends[_container_of(child) or ("body1" if "body1" not in ends else "body2")] = objects.get(id(child.getRealNode()))
    zero = [0.0, 0.0, 0.0]
    if 'anchorPoint' in JOINT_FIELDS[spec]:
        anchor = global_matrix @ Vector(_floats(fields.get('anchorPoint', '0 0 0'), zero))
    else:
        first = ends.get("body1") or ends.get("body2")
        anchor = first.matrix_world.translation.copy() if first is not None else global_matrix @ Vector(zero)

    def direction(name, default):
        v = axes @ Vector(_floats(fields.get(name, default), zero))
        return v.normalized() if v.length > 1e-9 else None
    if spec == 'SingleAxisHingeJoint':
        z, x = direction('axis', '0 0 0'), None
    elif spec == 'SliderJoint':
        z, x = None, direction('axis', '0 1 0')
    elif spec in ('DoubleAxisHingeJoint', 'UniversalJoint'):
        z, x = direction('axis1', '0 0 0'), direction('axis2', '0 0 0')
    else:
        z = x = None
    rotation = _frame_rotation(z, x)
    empty = bpy.data.objects.new(joint.getDefName() or spec, None)
    scene.collection.objects.link(empty)
    empty.empty_display_type, empty.empty_display_size = 'ARROWS', 0.3
    empty.matrix_world = Matrix.Translation(anchor) @ rotation.to_4x4()
    # the operator reads the view layer's active object: an override alone leaves the joint without a constraint on
    # Blender 5.1 and older (or crashes it), so the empty is made active there too
    scene.view_layers[0].objects.active = empty
    with bpycontext.temp_override(scene=scene, object=empty, active_object=empty, selected_objects=[empty]):
        bpy.ops.rigidbody.constraint_add(type=JOINT_CONSTRAINT[spec])
    con = empty.rigid_body_constraint
    con.object1, con.object2 = ends.get("body1"), ends.get("body2")
    if spec == 'SingleAxisHingeJoint':
        low = _floats(fields.get('minAngle', str(-math.pi)), [-math.pi])[0]
        high = _floats(fields.get('maxAngle', str(math.pi)), [math.pi])[0]
        if low > -math.pi or high < math.pi:          # X3D's default is no stop
            con.use_limit_ang_z = True
            con.limit_ang_z_lower, con.limit_ang_z_upper = low, high
    elif spec == 'SliderJoint':
        # X3D's separation is the bodies' distance along the axis; Blender's slider limits count from where they start
        b1, b2 = ends.get("body1"), ends.get("body2")
        start = ((b2.matrix_world.translation - b1.matrix_world.translation).dot(x)
                 if b1 is not None and b2 is not None and x is not None else 0.0)
        low = _floats(fields.get('minSeparation', '0'), [0.0])[0] * conversion_scale
        high = _floats(fields.get('maxSeparation', '1'), [1.0])[0] * conversion_scale
        con.use_limit_lin_x = True
        con.limit_lin_x_lower, con.limit_lin_x_upper = low - start, high - start
    elif spec in ('DoubleAxisHingeJoint', 'UniversalJoint'):
        # a two-axis joint: no sliding, no turning about Y; free about Z (axis1) and X (axis2)
        for name in ('lin_x', 'lin_y', 'lin_z', 'ang_y'):
            setattr(con, f"use_limit_{name}", True)
            setattr(con, f"limit_{name}_lower", 0.0)
            setattr(con, f"limit_{name}_upper", 0.0)
        if spec == 'DoubleAxisHingeJoint':
            low = _floats(fields.get('minAngle1', str(-math.pi)), [-math.pi])[0]
            high = _floats(fields.get('maxAngle1', str(math.pi)), [math.pi])[0]
            if low > -math.pi or high < math.pi:
                con.use_limit_ang_z = True
                con.limit_ang_z_lower, con.limit_ang_z_upper = low, high
    empty[RIGID_JOINT_PROPERTY] = json.dumps({"node": spec, "def": joint.getDefName() or "", "fields": fields})


def _frame_rotation(z, x):
    """A rotation whose local Z is ``z`` and local X ``x`` (either may be None; x is made square to z)."""
    if z is None and x is None:
        return Matrix.Identity(3)
    if z is None:
        return Vector((1.0, 0.0, 0.0)).rotation_difference(x).to_matrix()
    if x is None or abs(x.dot(z)) > 1.0 - 1e-9:
        return Vector((0.0, 0.0, 1.0)).rotation_difference(z).to_matrix()
    x = (x - z * x.dot(z)).normalized()
    y = z.cross(x)
    return Matrix((x, y, z)).transposed()


# -- carry: nodes the import has no handler for, kept as written and written back in place ------------------------------
# X3D child nodes the import otherwise drops without a trace (node board read rung "none"): Sound and its audio graph,
# volume data, particle systems, layering, texture projectors, NURBS interpolators... Blender does nothing with them;
# their XML, exactly as the file wrote it, rides on the object of their nearest Transform (or the scene) and the X3D 4.0
# export writes it back there. A node a later batch builds natively leaves this list. DIS is left out on purpose: another
# agent is bringing it natively.
CARRIED_PROPERTY = "x3d_carried"            # JSON list of XML texts, on an object or the scene
CARRIED_ROUTES_PROPERTY = "x3d_carried_routes"   # on the scene: ROUTEs between carried nodes
CARRY_SPECS = frozenset((
    'Analyser', 'AudioDestination', 'BiquadFilter', 'BufferAudioSource', 'CADFace', 'ChannelMerger', 'ChannelSelector',
    'ChannelSplitter', 'ClipPlane', 'Convolver', 'Delay',
    'DynamicsCompressor', 'Gain', 'GeoMetadata', 'IsoSurfaceVolumeData', 'Layout',
    'ListenerPointSource', 'LocalFog', 'MicrophoneSource', 'NurbsOrientationInterpolator', 'NurbsPositionInterpolator',
    'NurbsSet', 'NurbsSurfaceInterpolator', 'OscillatorSource', 'ParticleSystem', 'PeriodicWave', 'PickableGroup',
    'SegmentedVolumeData', 'SpatialSound', 'StreamAudioDestination', 'StreamAudioSource',
    'TextureProjector', 'TextureProjectorParallel', 'Viewport', 'VolumeData', 'WaveShaper'))
# what the import builds: a subtree holding any of these is not carried (it would be written twice)
CARRY_BLOCKERS = frozenset(('Shape', 'Inline', 'HAnimHumanoid', 'Viewpoint', 'OrthoViewpoint', 'GeoViewpoint',
                            'PointLight', 'SpotLight', 'DirectionalLight', 'Transform', 'GaussianSplats'))
CARRY_PASS_THROUGH = frozenset(('Group', 'StaticGroup'))     # between a carried node and its Transform


def find_carried(all_nodes):
    """[(node, ancestry, xml)] for the nodes to carry, and the ids of every node inside them (the import skips those)."""
    items, inside, tops = [], set(), set()
    for node, ancestry in all_nodes:          # depth first: a node's ancestors come before it
        if any(id(a) in tops for a in ancestry):
            inside.add(id(node))
            continue
        if node.getSpec() not in CARRY_SPECS:
            continue
        element = getattr(node, "x3dNode", None)
        if element is None:                      # the classic VRML encoding: no XML to keep
            continue
        top = next((i for i in range(len(ancestry) - 1, -1, -1) if ancestry[i].getSpec() == 'Transform'), None)
        between = ancestry[(top + 1) if top is not None else 0:]
        if any(a.getSpec() not in CARRY_PASS_THROUGH and a.getSpec() not in ('X3D', 'Scene', None) for a in between):
            continue                             # under a node the writer dissolves or rebuilds: no place to put it
        if any(e.tagName in CARRY_BLOCKERS for e in element.getElementsByTagName('*')):
            continue
        items.append((node, ancestry, element.toxml()))
        inside.add(id(node))
        tops.add(id(node))
    return items, inside


def place_carried(items, bpyscene, global_matrix=None, base_dir=".", collection=None):
    """Each carried node's XML onto its nearest Transform's object (the one made for that ancestry), else the scene.
    ROUTEs between carried nodes are kept with them; one with a single carried end is reported, not guessed at.
    An audio graph the sound bridge models is made audible (sound_bridge): a SpatialSound becomes a Speaker that keeps
    its XML instead, a destination graph stays carried and gets a sound strip."""
    import json
    if not items:
        return
    document = items[0][0].x3dNode.ownerDocument
    routed = {route.getAttribute(end) for route in document.getElementsByTagName('ROUTE')
              for end in ('fromNode', 'toNode')}
    speakers = strips = 0
    for node, ancestry, xml in items:
        top = next((i for i in range(len(ancestry) - 1, -1, -1) if ancestry[i].getSpec() == 'Transform'), None)
        owner = bpyscene
        if top is not None:
            transform = ancestry[top].getRealNode()
            owners = getattr(transform, "hierarchy_owners", None) or []
            owner = next((ob for ob, anc in owners if len(anc) == top and all(a is b for a, b in zip(anc, ancestry))),
                         None) or getattr(transform, "blendObject", None)
            if owner is None:
                logger.warning("%s %s: its Transform made no object; not carried", node.getSpec(), node.getDefName() or "")
                continue
        bridged = _bridge_sound(xml, owner, ancestry, top, routed, bpyscene, global_matrix, base_dir, collection)
        if bridged == "speaker":
            speakers += 1
            continue                             # the Speaker keeps the XML
        strips += bridged == "strip"
        kept = json.loads(owner.get(CARRIED_PROPERTY, "[]") or "[]")
        kept.append(xml)
        owner[CARRIED_PROPERTY] = json.dumps(kept)
    carried_defs = set()
    for node, _ancestry, _xml in items:
        for element in [node.x3dNode, *node.x3dNode.getElementsByTagName('*')]:
            if element.hasAttribute('DEF'):
                carried_defs.add(element.getAttribute('DEF'))
    routes, half = [], 0
    for route in document.getElementsByTagName('ROUTE'):
        ends = (route.getAttribute('fromNode'), route.getAttribute('toNode'))
        if all(end in carried_defs for end in ends):
            routes.append(route.toxml())
        elif any(end in carried_defs for end in ends):
            half += 1
    if routes:
        bpyscene[CARRIED_ROUTES_PROPERTY] = json.dumps(routes)
    if half:
        logger.warning("%d ROUTE(s) join a carried node to one the import builds; they are not carried", half)
    logger.info("carried %d node(s) the import has no handler for (written back as the file wrote them)", len(items))
    if speakers or strips:
        logger.info("sound bridge: %d SpatialSound graph(s) as Speakers, %d destination graph(s) as sound strips",
                    speakers, strips)


def _bridge_sound(xml, owner, ancestry, top, routed, bpyscene, global_matrix, base_dir, collection):
    """"speaker", "strip" or None (left to carry alone). Never stops the import."""
    from . import sound_bridge
    root = sound_bridge.bridgeable(xml, routed)
    if root is None:
        return None
    try:
        if root.tag in sound_bridge.SPEAKER_ROOTS:
            if top is not None and len(getattr(ancestry[top].getRealNode(), "hierarchy_owners", None) or []) > 1:
                return None                      # under a USE'd Transform: one graph, several places
            sound_bridge.make_speaker(root, xml, owner, bpyscene, global_matrix or Matrix(), base_dir,
                                      collection or bpyscene.collection)
            return "speaker"
        sound_bridge.make_strip(root, bpyscene, base_dir)
        return "strip"
    except Exception as exc:                     # the graph is still carried as written
        logger.warning("%s %s: not rendered (%s); carried as written", root.tag, root.get("DEF") or "", exc)
        return None


X3D_LOD_HIDDEN_PROPERTY = LOD_HIDDEN_PROPERTY   # "x3d_lod_hidden", on an object of an LOD / GeoLOD level a viewer at the first Viewpoint does not see
X3D_LOD_PROPERTY = "x3d_lod"                  # on the same object: "<LOD name>:<level>"

# LOD and GeoLOD nodes met by the import, and the objects made under them. Which level a viewer sees depends on the first
# Viewpoint, which may come later in the file (or in the file that inlines this one), so the levels are settled by
# finalize_lod() once every file is in.
lod_records = {}   # id(node, ancestry) -> {"node", "ancestry", "global_matrix", "count"}
lod_members = []   # (object, [(record key, level index), ...])


def lod_key(node, ancestry):
    return (id(node), tuple(id(a) for a in ancestry))


def lod_chain(node, ancestry):
    """The LOD / GeoLOD nodes above ``node`` as (record key, level index of the branch ``node`` sits on). A LOD's
    ``children`` are its levels; a GeoLOD's ``rootNode`` children are its level 0 (the child URLs are not imported)."""
    chain = tuple(ancestry) + (node,)
    out = []
    for i, anc in enumerate(ancestry):
        spec = anc.getSpec()
        if spec not in ('LOD', 'GeoLOD'):
            continue
        kids = [c for c in anc.getRealNode().children if _switch_child_counts(c)]
        index = next((n for n, kid in enumerate(kids) if kid is chain[i + 1]), None)
        if index is None:
            continue
        out.append((lod_key(anc, ancestry[:i]), 0 if spec == 'GeoLOD' else index))
    return out


# X_ITE 16.7.1 LOD.js: without a range the level follows the browser's frame rate, averaged over 180 frames from a start-up
# value of 60 fps, between 20 fps (the coarsest level) and 55 fps (the finest)
XITE_LOD_START_FRAME_RATE = 60.0
XITE_LOD_FRAME_RATE_MIN = 20.0
XITE_LOD_FRAME_RATE_MAX = 55.0


def lod_level_without_range(count, frame_rate=XITE_LOD_START_FRAME_RATE):
    """The level X_ITE 16.7.1's LOD.getLevel picks for an empty ``range`` at a given averaged frame rate: none for no
    child, the only child, ``+(frame_rate > 55)`` for two, else the share of the way down from 55 to 20 fps (the first
    child above 55 fps, the last at or below 20 fps)."""
    if count <= 0:
        return -1
    if count == 1:
        return 0
    if count == 2:
        return int(frame_rate > XITE_LOD_FRAME_RATE_MAX)
    fraction = 1.0 - min(max((frame_rate - XITE_LOD_FRAME_RATE_MIN) / (XITE_LOD_FRAME_RATE_MAX - XITE_LOD_FRAME_RATE_MIN), 0.0), 1.0)
    return min(int(fraction * count), count - 1)


def lod_level(distance, ranges, count):
    """The level X_ITE 16.7.1 draws: the first ``range`` entry above the viewer's distance from the node's centre (LOD.js
    getLevel: upperBound over ``range``), at most the last child. No ``range`` leaves the choice to the browser's frame
    rate (``lod_level_without_range``): the import takes X_ITE's start-up state, 60 fps, which is the first child of one
    or of three and more, and the second of two. What X_ITE draws later depends on the frame rate it measures (two
    children go back to the first once the average falls to 55 fps, three and more drift towards the last as it falls
    towards 20), so a still import can match only that first frame."""
    if count <= 0:
        return -1
    if not ranges:
        return lod_level_without_range(count)
    level = 0
    for r in ranges:
        if r > distance:
            break
        level += 1
    return min(level, count - 1)


def lod_centre_world(record):
    """The LOD's ``center`` in Blender world coordinates (a GeoLOD's in its geoSystem, as geocentric metres)."""
    node, ancestry, global_matrix = record["node"], record["ancestry"], record["global_matrix"]
    if node.getSpec() == 'GeoLOD':
        import numpy as np
        gs = geo_system_of(node, ancestry)
        origin, frame = geo_origin_of(node, gs, ancestry)
        coords = node.getFieldAsFloatTuple('center', (0.0, 0.0, 0.0), ancestry)
        local = geo_to_local(np.array(geospatial.to_geocentric(gs, *coords)), origin, frame)
        centre = Vector(local * conversion_scale)
    else:
        centre = Vector(node.getFieldAsFloatTuple('center', (0.0, 0.0, 0.0), ancestry, conversion_scale))
    return getFinalMatrix(node, Matrix.Translation(centre), ancestry, global_matrix).translation


def finalize_lod():
    """Show only the LOD level the first Viewpoint selects, as X_ITE does, and hide the rest.

    X_ITE 16.7.1 draws a LOD's one level: the first ``range`` entry above the distance between the viewer and the centre,
    both in the world, ``range`` unscaled by the Transforms above (a LOD of range 1000 under a scale of 0.001 and 10
    units from the viewer still draws level 0). Every level is imported, as for a Switch, so nothing is lost when the scene
    goes out again; the objects of the other levels are hidden in the viewport and the render and carry
    ``x3d_lod_hidden`` (the level) and ``x3d_lod``. ``forceTransitions`` only paces the change from level to level in
    X_ITE (one level per frame); the level a still viewer ends on is the one chosen here. A LOD without ``range`` takes
    X_ITE's start-up level (``lod_level_without_range``). A GeoLOD's child URLs are
    not imported, so its ``rootNode`` content stays shown whichever level the viewer is on (reported).
    """
    global lod_records, lod_members
    records, members = lod_records, lod_members
    lod_records, lod_members = {}, []
    if not records:
        return
    try:
        eye = bound_view.matrix_world.translation if bound_view is not None else default_view.translation
    except (ReferenceError, AttributeError):
        eye = default_view.translation if default_view is not None else Vector((0.0, 0.0, 10.0 * conversion_scale))
    levels = {}
    for key, rec in records.items():
        node, ancestry = rec["node"], rec["ancestry"]
        name = node.getDefName() or node.getSpec()
        distance = (eye - lod_centre_world(rec)).length / (conversion_scale or 1.0)
        if node.getSpec() == 'GeoLOD':
            range_ = node.getFieldAsFloat('range', 10.0, ancestry)
            level = 1 if distance < range_ else 0
            levels[key] = 0
            urls = [f for f in ('child1Url', 'child2Url', 'child3Url', 'child4Url') if node.getFieldAsMFStringArray(f, [], ancestry)]
            if level == 1 and urls:
                logger.warning("GeoLOD %s: the viewer is %.4g from its center, inside its range %.4g, so X_ITE draws the child "
                               "URLs; they are not imported, its rootNode content stays shown", name, distance, range_)
            else:
                logger.info("GeoLOD %s: the viewer is %.4g from its center, range %.4g: level %d (rootNode)",
                            name, distance, range_, level)
            continue
        ranges = list(node.getFieldAsArray('range', 0, ancestry, 1.0) or [])
        level = lod_level(distance, ranges, rec["count"])
        levels[key] = level
        logger.info("LOD %s: the viewer is %.4g from its center, range %s (forceTransitions %s): level %d of %d shown",
                    name, distance, ranges or "empty (X_ITE picks by frame rate; its 60 fps start-up level)",
                    node.getFieldAsBool('forceTransitions', False, ancestry), level, rec["count"])
    hidden = []
    for ob, chain in members:
        for key, index in chain:
            if levels.get(key) not in (None, index):
                hidden.append((ob, index, records[key]["node"].getDefName() or records[key]["node"].getSpec()))
                break
    done = set()
    for ob, index, name in hidden:
        try:
            family = [ob, *ob.children_recursive]    # with an Inline's loaded content
        except ReferenceError:
            continue
        for member in family:
            if member.name in done:
                continue
            done.add(member.name)
            member.hide_render = True
            try:
                member.hide_set(True)
            except RuntimeError:  # not in the view layer
                member.hide_viewport = True
            member[X3D_LOD_HIDDEN_PROPERTY] = index
            member[X3D_LOD_PROPERTY] = f"{name}:{index}"


def load_web3d(
        bpycontext,
        filepath,
        *,
        PREF_FLAT=False,
        PREF_CIRCLE_DIV=16,
        file_unit='M',
        global_scale=1.0,
        global_matrix=None,
        HELPER_FUNC=None,
        as_collection=False,
        solidify=False,
        solidify_value=0.1,
        PREF_HIERARCHY=False
):

    global current_file_path
    current_file_path = filepath
    if not _INLINE_STACK:
        _METADATA_PLACED.clear()
        # only the outermost file: an Inline's own load_web3d ran in the middle of its parent's and wiped the parent's
        # record of which meshes carry a baked shear (a USE after an Inline then copied the baked mesh, and
        # keep_hierarchy could not undo the bake)
        _UNBAKED_DATA.clear()
    # Used when adding blender primitives
    GLOBALS['CIRCLE_DETAIL'] = PREF_CIRCLE_DIV

    global conversion_scale, navigation_headlight
    conversion_scale = global_scale

    # NOTE - reset material cache
    # (otherwise we might get "StructRNA of type Material has been removed" errors)
    global material_cache, texture_cache, image_alpha_cache, line_material_cache, unlit_surface_cache
    global unlit_colour_cache, physical_colour_cache
    material_cache = {}
    line_material_cache = {}
    unlit_surface_cache = {}
    unlit_colour_cache = {}
    physical_colour_cache = {}
    # Same reason for textures: a cached Image outlives File > New and the next import fails with
    # "StructRNA of type Image has been removed".
    texture_cache = {}
    image_alpha_cache = {}

    bpyscene = bpycontext.scene
    global _timeline_fit_pending
    _timeline_fit_pending = not any(ob.animation_data is not None and ob.animation_data.action is not None
                                    for ob in bpyscene.objects)

    if as_collection:
        active_collection = bpy.context.view_layer.active_layer_collection.collection
        bpycollection = bpy.data.collections.new(os.path.basename(filepath))
        active_collection.children.link(bpycollection)
    else:
        bpycollection = bpy.context.view_layer.active_layer_collection.collection

    # root_node = vrml_parse('/_Cylinder.wrl')
    if filepath.lower().endswith(('.x3d', '.x3dz')):
        root_node, msg = x3d_parse(filepath)
    else: # .wrl, #.x3dv
        root_node, msg = vrml_parse(filepath)

    if not root_node:
        logger.warning(msg)
        return msg
    if not _INLINE_STACK:  # the head of an inlined file describes that file, not the scene
        importHeadMeta(bpyscene, root_node)

    if global_matrix is None:
        global_matrix = Matrix()
    global default_view
    if not _INLINE_STACK and default_view is None:
        default_view = global_matrix @ Matrix.Translation((0.0, 0.0, 10.0 * conversion_scale))

    # fill with tuples - (node, [parents-parent, parent])
    all_nodes = root_node.getSerialized([], [])
    created = []  # (object, ancestry) of every object this file's nodes made, for rebuild_hierarchy
    # the first Background of the file is the one a browser shows; an inlined file's does not count
    background_seen = bool(_INLINE_STACK)
    fog_seen = bool(_INLINE_STACK)     # Fog is bindable too: the file's first one
    # objects a Switch does not choose; collected as each is made, since a node under a USE'd Switch (or a USE'd Shape)
    # makes one object per instance and keeps only the last in node.blendObject
    switch_hidden = []
    switch_members = []   # (object, "DEF:branch:choice ..."): which branch of which DEF'd Switch an object is on, for Play
    # objects made under a node whose visible field is false (X3D 4.0: X3DGroupingNode and X3DShapeNode have one)
    visible_false = []

    carried, carried_inside = find_carried(all_nodes)
    for node, ancestry in all_nodes:
        if id(node) in carried_inside:
            continue           # carried as written (place_carried): nothing of it is built
        # if 'castle.wrl' not in node.getFilename():
        #   continue
        made_before = node.blendObject

        spec = node.getSpec()
        '''
        prefix = node.getPrefix()
        if prefix=='PROTO':
            pass
        else
        '''
        if HELPER_FUNC and HELPER_FUNC(node, ancestry):
            # Note, include this function so the VRML/X3D importer can be extended
            # by an external script. - gets first pick
            pass
        if any(parent.getSpec() == 'HAnimHumanoid' for parent in ancestry):
            # Skin and segment geometry are handled by importHumanoid
            continue
        if spec == 'HAnimHumanoid':
            try:
                importHumanoid(bpycollection, node, ancestry, global_matrix)
            except Exception as exc:  # a broken humanoid must not abort the rest of the file
                logger.error("HAnimHumanoid import failed: %s", exc, exc_info=True)
        elif spec == 'Shape':
            importShape(bpycollection, node, ancestry, global_matrix, solidify, solidify_value)
        elif spec == 'Inline':
            importInline(bpycollection, node, ancestry, global_matrix, PREF_FLAT=PREF_FLAT,
                         PREF_CIRCLE_DIV=PREF_CIRCLE_DIV, solidify=solidify, solidify_value=solidify_value,
                         PREF_HIERARCHY=PREF_HIERARCHY)
        elif spec == 'GaussianSplats':
            importGaussianSplats(bpycollection, node, ancestry, global_matrix)
        elif spec in {'PointLight', 'DirectionalLight', 'SpotLight'}:
            importLamp(bpycollection, node, spec, ancestry, global_matrix)
        elif spec in {'Viewpoint', 'GeoViewpoint', 'OrthoViewpoint'}:
            importViewpoint(bpycollection, node, ancestry, global_matrix)
        elif spec in TRANSFORM_SPECS:
            # Only use transform nodes when we are not importing a flat object hierarchy
            if not PREF_FLAT:
                importTransform(bpycollection, node, ancestry, global_matrix)
        elif spec == 'NavigationInfo' and not _INLINE_STACK and navigation_headlight is None:
            navigation_headlight = node.getFieldAsBool('headlight', True, ancestry)
        elif spec in ('Background', 'TextureBackground') and not background_seen:
            importBackground(bpyscene, node, ancestry)
            background_seen = True
        elif spec == 'Fog' and not fog_seen:
            importFog(bpyscene, node, ancestry)
            fog_seen = True
        elif spec == 'Sound':
            importAudio(bpycollection, node, ancestry, global_matrix)
            '''
        # These are delt with later within importRoute
        elif spec=='PositionInterpolator':
            action = bpy.data.ipos.new('web3d_ipo', 'Object')
            translatePositionInterpolator(node, action)
            '''
        if node.blendObject is not None and node.blendObject is not made_before:
            created.append((node.blendObject, list(ancestry)))
        if node.blendObject is not None and node.blendObject is not made_before \
                and any(anc.getSpec() == 'Switch' for anc in ancestry) and switch_hides(node, ancestry):
            switch_hidden.append(node.blendObject)
        if node.blendObject is not None and node.blendObject is not made_before \
                and any(anc.getSpec() == 'Switch' for anc in ancestry):
            switch_members.append((node.blendObject, switch_branches(node, ancestry)))
        if node.blendObject is not None and node.blendObject is not made_before and not all(
                item.getFieldAsBool('visible', True, chain) is not False
                for item, chain in [(anc, ancestry[:i]) for i, anc in enumerate(ancestry)] + [(node, ancestry)]):
            visible_false.append(node.blendObject)
        if node.blendObject is not None and node.blendObject is not made_before \
                and any(anc.getSpec() in ('Switch', 'LOD', *GROUP_RAW_FIELDS) for anc in ancestry):
            chain = group_chain(node, ancestry)
            if chain:
                node.blendObject[GROUP_CHAIN_PROPERTY] = json.dumps(chain)
        if spec in ('LOD', 'GeoLOD'):
            lod_records[lod_key(node, ancestry)] = {
                "node": node, "ancestry": list(ancestry), "global_matrix": global_matrix,
                "count": len([c for c in node.getRealNode().children if _switch_child_counts(c)])}
        if node.blendObject is not None and node.blendObject is not made_before \
                and any(anc.getSpec() in ('LOD', 'GeoLOD') for anc in ancestry):
            lod_path = lod_chain(node, ancestry)
            if lod_path:
                lod_members.append((node.blendObject, lod_path))

    if PREF_HIERARCHY and PREF_FLAT:
        try:
            rebuild_hierarchy(created, global_matrix, bpycollection, all_nodes, carried)
        except Exception as exc:  # the objects are already in place; a failed rebuild leaves the flat import
            logger.error("Hierarchy rebuild failed, objects stay flat: %s", exc, exc_info=True)
    try:
        place_carried(carried, bpyscene, global_matrix, os.path.dirname(os.path.abspath(filepath)), bpycollection)
    except Exception as exc:  # carrying must never stop an import
        logger.error("Carried nodes not kept: %s", exc, exc_info=True)

    # After we import all nodes, route events - anim paths
    for node, ancestry in all_nodes:
        importRoute(node, ancestry)
    try:
        importRoutesXML(all_nodes, global_matrix, bpycontext)
    except Exception as exc:  # animation must never break a geometry import
        logger.error("XML ROUTE animation import failed: %s", exc, exc_info=True)
    try:
        keep_scene_metadata(bpyscene, all_nodes)
    except Exception as exc:  # metadata must never stop an import
        logger.error("Scene-level Metadata not kept: %s", exc, exc_info=True)
    try:
        import_rigid_bodies(all_nodes, global_matrix, bpycontext)
    except Exception as exc:  # physics must never stop the geometry import
        logger.error("Rigid body physics not made: %s", exc, exc_info=True)
    report_import_losses(all_nodes, bpycontext, defer_routes_to_caller)

    # Switch: every child is imported, so nothing is lost on the way back out, but only the chosen one is shown; the others
    # are hidden in the viewport and the render, as an X3D browser draws them
    for bpyob in {o for ob in switch_hidden for o in [ob, *ob.children_recursive]}:  # with an Inline's loaded content
        bpyob.hide_render = True
        try:
            bpyob.hide_set(True)
        except RuntimeError:  # not in the view layer
            bpyob.hide_viewport = True
        bpyob[SWITCH_HIDDEN_PROPERTY] = True
    for bpyob, branches in switch_members:
        if branches:
            bpyob[SWITCH_BRANCH_PROPERTY] = branches
    # visible="false": drawn by no browser until an event says otherwise; hidden here the same way, and written back
    for bpyob in {o for ob in visible_false for o in [ob, *ob.children_recursive]}:
        bpyob.hide_render = True
        try:
            bpyob.hide_set(True)
        except RuntimeError:  # not in the view layer
            bpyob.hide_viewport = True
        bpyob[VISIBLE_FALSE_PROPERTY] = True

    for node, ancestry in all_nodes:
        if node.isRoot():
            # we know that all nodes referenced from will be in
            # routeIpoDict so no need to run node.getDefDict() for every node.
            routeIpoDict = node.getRouteIpoDict()
            defDict = node.getDefDict()

            for key, action in routeIpoDict.items():

                # Assign anim curves
                node = defDict[key]
                if node.blendData is None:  # Add an object if we need one for animation
                    bpyob = node.blendData = node.blendObject = bpy.data.objects.new('AnimOb', None)  # , name)
                    bpycollection.objects.link(bpyob)
                    bpyob.select_set(True)

                if node.blendData.animation_data is None:
                    node.blendData.animation_data_create()

                node.blendData.animation_data.action = action

    # Add in hierarchy
    if PREF_FLAT is False:
        child_dict = {}
        for node, ancestry in all_nodes:
            if node.blendObject:
                blendObject = None

                # Get the last parent
                i = len(ancestry)
                while i:
                    i -= 1
                    blendObject = ancestry[i].blendObject
                    if blendObject:
                        break

                if blendObject:
                    # Parent Slow, - 1 liner but works
                    # blendObject.makeParent([node.blendObject], 0, 1)

                    # Parent FAST
                    try:
                        child_dict[blendObject].append(node.blendObject)
                    except:
                        child_dict[blendObject] = [node.blendObject]

        # Parent
        for parent, children in child_dict.items():
            for c in children:
                c.parent = parent

        # update deps
        bpycontext.view_layer.update()
        del child_dict


def load_with_profiler(
        context,
        filepath,
        *,
        global_matrix=None
):
    import cProfile
    import pstats
    pro = cProfile.Profile()
    pro.runctx("load_web3d(context, filepath, PREF_FLAT=True, "
               "PREF_CIRCLE_DIV=16, global_matrix=global_matrix)",
               globals(), locals())
    st = pstats.Stats(pro)
    st.sort_stats("time")
    st.print_stats(0.1)


GPU_INSTANCES_ENV = "BLENDER_X3D_GPU_INSTANCES"


def resolve_gpu_instances(value):
    """On when the option is set or BLENDER_X3D_GPU_INSTANCES is 1, true, yes or on (the operator's checkbox is a plain
    bool, so the environment can only add to it, as the rig and a headless convert do)."""
    return bool(value) or os.environ.get(GPU_INSTANCES_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def group_instances(objects, min_count=2):
    """Parent every set of >= min_count loose mesh objects that share one mesh to an Empty named "<mesh>.instances".

    With keep_hierarchy off the import is flat, and a Group or a Transform with a USE below it leaves its instances
    as scene roots (with it on, only instances that are scene roots are grouped), and Blender's glTF exporter writes EXT_mesh_gpu_instancing only for children of one Empty that share a mesh
    and have no children of their own. The Empty sits at the origin with an identity matrix, so no world matrix
    changes; it carries the custom property ``x3d_instance_group`` (the mesh name). Returns the new Empties."""
    by_mesh = {}
    for ob in objects:
        if ob.type == 'MESH' and ob.data is not None and ob.parent is None and not ob.children:
            by_mesh.setdefault(ob.data.name, []).append(ob)
    groups = []
    for mesh_name, members in by_mesh.items():
        if len(members) < min_count:
            continue
        collection = members[0].users_collection[0] if members[0].users_collection else bpy.context.scene.collection
        empty = bpy.data.objects.new(mesh_name + ".instances", None)
        collection.objects.link(empty)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.2
        empty["x3d_instance_group"] = mesh_name
        for ob in members:
            world = ob.matrix_world.copy()
            ob.parent = empty
            ob.matrix_world = world
        groups.append(empty)
    return groups


def _load_one(context, file, divisions, global_scale, global_matrix, as_collection, solidify, solidify_value,
              keep_hierarchy):
    """One file of load(): None, or why it could not be read."""
    return load_web3d(context, file,
                      PREF_FLAT=True,
                      PREF_CIRCLE_DIV=divisions,
                      global_scale=global_scale,
                      global_matrix=global_matrix,
                      as_collection=as_collection,
                      solidify=solidify,
                      solidify_value=solidify_value,
                      PREF_HIERARCHY=bool(keep_hierarchy)
                      )


# why the last load() could not read its files: the operator reports these when it cancels
load_errors: list[str] = []


def load(context,
         filepath,
         *,
         files=None,
         directory=None,
         global_scale=1.0,
         global_matrix=None,
         as_collection=False,
         solidify=False,
         solidify_value=0.1,
         circle_divisions=None,
         color_space=None,
         light_units=None,
         gpu_instances=None,
         keep_hierarchy=True,
         defer_route_losses=False
         ):
    """circle_divisions: segments for Sphere, Cylinder, Cone and the 2D circles (None: BLENDER_X3D_CIRCLE_DIV, else
    16). X3D leaves the tessellation of its primitives to the browser; renders at 4K or 8K want 64 or more.
    color_space: 'AS_IS' or 'SRGB' (see COLOUR_SPACES; None or 'AUTO': BLENDER_X3D_COLOR_SPACE, else 'SRGB').
    light_units: 'BLENDER' or 'X_ITE' (see LIGHT_UNITS; None or 'AUTO': BLENDER_X3D_LIGHT_UNITS, else X_ITE with
    the SRGB colour space and BLENDER with AS_IS).
    gpu_instances: group objects that share a mesh under one Empty each, so the glTF exporter's GPU Instances option
    writes EXT_mesh_gpu_instancing (also on when BLENDER_X3D_GPU_INSTANCES is 1; see group_instances).
    keep_hierarchy: parent objects as the file's Transforms nest them (rebuild_hierarchy); False imports every object
    at its world matrix without parents, as before."""
    global colour_space, lighting_units, navigation_headlight, bound_view, default_view, defer_routes_to_caller
    defer_routes_to_caller = bool(defer_route_losses)
    import_target = os.environ.get("BLENDER_X3D_IMPORT_TARGET", "AUTO").upper()
    divisions = resolve_circle_divisions(circle_divisions or None)       # the operator's 0 means: not set here
    colour_space = resolve_colour_space(color_space)
    lighting_units = resolve_light_units(light_units, colour_space)
    imported_lights.clear()
    lit_surfaces.clear()
    lit_by_node.clear()
    lod_records.clear()
    lod_members.clear()
    group_keys.clear()
    navigation_headlight = None
    bound_view = default_view = None

    if import_target in {"MODERN", "X3D40", "MODERN_INLINE"}:
        from .parse_x3d40 import parse_file
        from .populate import populate_scene

        paths = [os.path.join(directory, name.name) for name in files] if files else [filepath]
        objects_before = {ob.name for ob in bpy.data.objects}
        for file in paths:
            ir_scene = parse_file(file)
            populate_scene(context, ir_scene)
        matrix_safety.push_scale_to_children([ob for ob in bpy.data.objects if ob.name not in objects_before])
        return {'FINISHED'}

    paths = [os.path.join(directory, name.name) for name in files] if files else [filepath]

    if getattr(context, "scene", None) is not None:
        # a scene whose imported objects were deleted carries the last file's headlight, lighting model, Background and
        # animation mark; the file coming in must not inherit the ones it does not set itself
        clear_stale_scene_properties(context.scene)
    objects_before = {ob.name for ob in bpy.data.objects}
    actions_before = {action.name for action in bpy.data.actions}
    _derived_materials.clear()
    load_errors.clear()
    _VRML_INLINE_STACK.clear()
    global _transform_cache_on
    _transform_cache.clear()
    _transform_cache_on = True
    global _inline_loads
    _inline_loads = 0
    for file in paths:
        # loadWithProfiler(operator, context, filepath, global_matrix)
        try:
            failed = _load_one(context, file, divisions, global_scale, global_matrix, as_collection, solidify,
                               solidify_value, keep_hierarchy)
        except RecursionError:
            # deeper than the recursion headroom (100,000 nested Groups): refuse the file, do not end Blender's
            # operator with a traceback (chaos round 2.7.3)
            failed = f"{os.path.basename(file)} is nested too deeply to import"
            logger.error(failed)
        if failed:
            load_errors.append(failed)
    if load_errors and len(load_errors) == len(paths):
        # nothing could be read: say why and cancel, instead of FINISHED with an empty scene (chaos round 2.7.3)
        return {'CANCELLED'}
    finalize_lod()
    settle_derived_material_names()
    new_objects = [ob for ob in bpy.data.objects if ob.name not in objects_before]
    for ob in new_objects:
        ob[IMPORTED_OBJECT_PROPERTY] = True     # what the scene-level flags (headlight, lighting model...) apply to
    # Blender inverts parent matrices in float32: an Inline under scale 1e-16 (one unit = one light-year) would
    # export to glTF about 1e8 too small. Move such scales onto the children; no world matrix changes.
    matrix_safety.push_scale_to_children(new_objects)
    if resolve_gpu_instances(gpu_instances):
        group_instances(new_objects)
    finalize_light_units(context.scene if context is not None else None, lighting_units)
    if context is not None and getattr(context, "scene", None) is not None:
        context.scene[COLOUR_SPACE_PROPERTY] = colour_space
        if any(action.name not in actions_before for action in bpy.data.actions):
            # interpolators and TimeSensors came in as keyframes: the X3D 4.0/4.1 export keeps them unless Animation is
            # set off by hand (ExportX3D.execute)
            context.scene[IMPORTED_ANIMATION_PROPERTY] = True

    return {'FINISHED'}
