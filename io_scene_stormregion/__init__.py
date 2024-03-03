# SPDX-License-Identifier: GPL-2.0-or-later


'''
Version history

1.2
- Support for RfB models

3/10/23
- Load bones as empties for visual reference

1.1
- Support for PANZERS Phase 1, Phase 2 vehicles/objects
- Support for "walker" units loading (animation skeleton is wrong though)
- Support for SWINE objects, vehicles


'''

bl_info = {
    "name": "Import Stormregion 4D Model (.4d)",
    "author": "lorddevereux and others",
    "version": (1, 2, 0),
    "blender": (3, 6, 0),
    "location": "File > Import-Export",
    "description": "Import Stormregion 4d files from Gepard1/2 v100 and v101",
    "warning": "",
    "doc_url": "none",
    "category": "Import-Export",
}


import os
import struct
import math
import mathutils
import pprint

import bpy
import bpy_extras.image_utils
import bpy_extras.node_shader_utils

import collections

# v100 - SWINE and some leftover in Panzers Phase 1/2
# v101 - Panzers phase 1 + 2
file_version = "v101"

objects = []
numBones = 0
bones = []
dummy_name_id_map = {}
dummies = []
scene_animations = {}
mesh_obj_ptr = None
bones_by_object = {}

def read_kind(file):
    return file.read(4).decode()

def read_char(file):
    raw_data = file.read(1)
    #print("++C " + raw_data.hex())
    return int.from_bytes(raw_data, 'little')

def read_uint(file):
    raw_data = file.read(4)
    #print("++U " + raw_data.hex())
    return struct.unpack('<I', raw_data)[0]

def read_sint(file):
    raw_data = file.read(4)
    #print("++I " + raw_data.hex())
    return struct.unpack('<i', raw_data)[0]

def read_ushort(file):
    raw_data = file.read(2)
    #print("++S " + raw_data.hex())
    return struct.unpack('<H', raw_data)[0]

def read_float(file):
    raw_data = file.read(4)
    #print("++F " + raw_data.hex())
    return struct.unpack('<f', raw_data)[0]

def read_string(file):
    length = read_ushort(file)
    raw_data = file.read(length)
    #print("++S " + raw_data.hex())
    result = raw_data.decode()
    return result

def read_vec(file, components):
    res = mathutils.Vector()
    
    for i in range(components):
        res[i] = read_float(file)
        
    return res

def iter_chunks(file, limit):    
    while(file.tell() < limit):
        kind = read_kind(file)
        size = read_uint(file)
        
        last = file.tell() + size
    
        yield (kind, last)
    
        file.seek(last)


class ParsingContext():
    def __init__(self):
        # 0.001  = 1:1 scale (metres)
        # 0.0001 = 1:10 scale (metres)
        self.scale =  0.001

        self.folder   = None        
        self.objects = []
        self.parents = []

        self.mesh = None
        self.obj  = None


def parse_anims(file, limit, ctx):
    num_anims = read_uint(file)

    for (kind, limit) in iter_chunks(file, limit):    
        print(f"  - {kind}")

        nom = read_string(file)
        fname = read_string(file)
        scene_animations[nom] = fname


def parse_material(file, limit, ctx):
    
    # TODO: These properties are actually unsupported, first DIFF applies to whole object
    if file_version == "v101":
        numFaces = read_uint(file)      # actually numIndis
        vertexStart = read_uint(file)
        vertexEnd = read_uint(file)
    else:
        # 100
        numFaces    = read_uint(file)
        vertexStart = read_uint(file)
        vertexEnd   = read_uint(file) + vertexStart

    diffuse = None
    specular = None
    
    for (kind, limit) in iter_chunks(file, limit):    
        if kind == 'DIFF':
            diffuse = read_string(file)

            print(f"  > Parsed DIFF: {diffuse} with {vertexStart} and {vertexEnd} and {numFaces}")
            
            #  textures stored as .tga, but actually DDS
            diffuse = diffuse.replace('.tga', '.dds')

        elif kind == 'SPEC':
            specular = read_string(file)
            print(f"  > Parsed SPEC: {specular} with {vertexStart} and {vertexEnd} and {numFaces}")


        elif kind == "STRP":
            parse_material(file, limit, ctx)


        elif kind == "MTBL":
            numMTBL = read_uint(file)

            print(f"  > Found MTBL section with {numMTBL} indexes")

            mtbl = []

            for idx in range(numMTBL):
                mtbl.append(read_uint(file))

            print(mtbl)

        else:
            print(f"  > Unsupported MTL kind {kind}")
            
        # Other settings are not supported
        pass

    # Sanity check
    if not diffuse:
        return

    # Assign material to mesh vertices
    uid = diffuse

    # Reuse existing material if exists, create in worst case
    material = bpy.data.materials.get(uid)
    
    if not material:
        material = bpy.data.materials.new(uid)

        wrapper = bpy_extras.node_shader_utils.PrincipledBSDFWrapper(material, is_readonly=False)  

        wrapper.base_color = (1, 1, 1)
        wrapper.use_nodes  = True

        # Load/create the diffuse texture for this material
        wrapper.base_color_texture.image = bpy_extras.image_utils.load_image(diffuse, ctx.folder, place_holder=True)
    
    # Associate material with the current object
    materialID = len(ctx.mesh.materials)

    ctx.mesh.materials.append(material)

    # Apply material selectively to the selected polygons
    for poly in ctx.mesh.polygons:
        for vertexID in poly.vertices:
            
            if vertexStart <= vertexID and vertexID <= vertexEnd:
                poly.material_index = materialID


def parse_object(file, limit, ctx, kind = "MESH"):
    global mesh_obj_ptr

    name     = read_string(file)
    parentID = read_sint(file)
    print(f"Parsed {kind}: {name} with parent ID {parentID}")

    is_stripe = False
    indis = []
    indiNum = 0
    
    if file_version == "v101":
        # waste 8 bytes
        print("> Wasting 8 bytes for 101")
        read_sint(file)
        read_sint(file)

    if kind == "MESH" or kind == "SKVS":
        # Allocate associated blender structures
        ctx.mesh = bpy.data.meshes.new(name)
        ctx.obj  = bpy.data.objects.new(name, ctx.mesh)

    elif kind == "DUMY":
        ctx.obj = bpy.data.objects.new(name, None)
    
    # Add to parsing context
    ctx.objects.append(ctx.obj)
    ctx.parents.append(parentID)

    # Parse transformation, location
    ctx.obj.matrix_local = (
        (read_float(file), read_float(file), read_float(file), 0),
        (read_float(file), read_float(file), read_float(file), 0),
        (read_float(file), read_float(file), read_float(file), 0),
        (0,                0,                0,                1)
    )

    ctx.obj.location = read_vec(file, 3) * ctx.scale
    
    # Parse various object attributes
    vertex_pos  = None
    vertex_norm = None
    vertex_uv   = None
    vertex_data = []
    groups_created = {}
    srefs = {}

    faces = []

    if kind == "DUMY":
        dummy_name_id_map[name] = len(dummies)
        dummies.append(ctx.obj)
        return
    
    root_kind = kind

    for (kind, limit) in iter_chunks(file, limit):

        print(f"> Parsing kind {kind}")

        # VRT2 is used by RfB, seems to be mostly the same as VERT
                
        # normal VERT, for objects and vehicles
        if (kind == 'VERT' or kind == 'VRT2') and root_kind != "SKVS":
            vertexNum    = read_uint(file)
            vertexFormat = read_uint(file)

            if vertexNum > 0xFFFF:
                raise IOError('Too many vertices')

            # vertexFormat 0 = 8 floats per vertex
            # vertexFormat 1 = 6 floats
    
            if vertexFormat != 0 and vertexFormat != 1: 
                raise IOError('Unsupported vertex format {vertexFormat}')
            
            if vertexFormat == 0:
                print(" > Vertex format 0")
                vertex_pos  = []
                vertex_norm = []
                vertex_uv   = []
                print(f" > Found {vertexNum} vertices for this mesh")
                for idx in range(vertexNum):
                    vertex_pos.append( read_vec(file, 3) * ctx.scale )
                    vertex_norm.append( read_vec(file, 3) )
                    
                    # Whacky coordinate systems..
                    vertex_uv.append((
                        0 + read_float(file), 
                        1 - read_float(file)
                    ))

            else:
                # note - SWINE doesn't seem to support/use these ones
                #        mesh imports OK but UV mapping is wrong
                #        Don't know what "other" is for
                vertex_pos  = []
                vertex_norm = []
                vertex_uv   = []
                print(" > Vertex format 1 - UV will be wrong")
                print(f" > Found {vertexNum} vertices for this mesh")
                for idx in range(vertexNum):
                    pos = read_vec(file, 3) * ctx.scale
                    vertex_pos.append( pos )
                    norm = read_vec(file, 3)
                    vertex_norm.append( norm )
                    
                    # Whacky coordinate systems..
                    vertex_uv.append((
                        0 + read_float(file), 
                        1 - read_float(file)
                    ))
                    other = read_float(file)


        # VERT inside SKVS is used by "walker"s (humans)
        elif (kind == "VERT" or kind == "VRT2") and root_kind == "SKVS":
            vertexNum    = read_uint(file)
            vertexFormat = read_uint(file)
            vertexUnknown = read_uint(file)

            print(f" > Read vertex format SKVS: {vertexNum}, {vertexFormat}, {vertexUnknown}")

            vertex_pos  = []
            vertex_norm = []
            vertex_uv   = []
            

            for idx in range(vertexNum):
                vertex_pos.append( read_vec(file, 3) * ctx.scale )
                vertex_norm.append( read_vec(file, 3) )
                
                # Whacky coordinate systems..
                vertex_uv.append((
                    0 + read_float(file), 
                    1 - read_float(file)
                ))

                bone_numbers = []
                group = 0
                for i in range(4):
                    group = read_char(file)
                    bone_numbers.append(group)
                
                print(f" > > Bone num {bone_numbers}")

                bone_weights = []
                material_floats = []

                for i in range(4):
                    bone_weights.append(read_float(file))

                print(f" > > Bone weights {bone_weights}")

                mtbl_numbers = []
                for i in range(4):
                    mtbl_numbers.append(read_char(file))
                
                print(f" > > MTBL {mtbl_numbers}")

                for i in range(4):
                    material_floats.append(read_float(file))

                # create vertex groups with weights
                for i in range(4):
                    if bone_numbers[i] not in groups_created:
                        ctx.obj.vertex_groups.new(name = f"{bone_numbers[i]}")
                        print(f"Create vertex group {bone_numbers[i]}")
                        groups_created[bone_numbers[i]] = []
                    
                    groups_created[bone_numbers[i]].append((int(idx), bone_weights[i]))



        elif kind == "BONS":
            if name not in bones_by_object:
                bones_by_object[name] = {}
            numBones = read_uint(file)

            for idx in range(numBones):
                bone_id = read_uint(file) - 1
                matrix = read_vec(file, 3)
                matrix2 = read_vec(file, 3)
                matrix3 = read_vec(file, 3)
                pos = read_vec(file, 3)
                this_bone = ( matrix, matrix2, matrix3, pos)
  
                bones_by_object[name][bone_id] = this_bone
                print(f" > Bone {bone_id}: {matrix}")
                print(f" >         {matrix2}")
                print(f" >         {matrix3}")
                print(f" >         {pos}")
                

            print(f" > Loaded {numBones} bones for this object")


        elif kind == 'INDI':
            indiNum = read_uint(file)

            print(f" > Found {indiNum} indexes for this mesh")

            for idx in range(indiNum):
                indis.append(read_ushort(file))
                

        elif kind == 'FACE':
            faceNum = read_uint(file)

            print(f" > Found {faceNum} faces for this mesh")
            
            for idx in range(faceNum):
                faces.append((
                    read_ushort(file),
                    read_ushort(file),
                    read_ushort(file)          
                ))
                
            # Fill mesh data with geometry (vertices, faces)
            ctx.mesh.from_pydata(vertex_pos, [], faces)
            ctx.mesh.update()
            
            # Create UV mapping
            uv_layer = ctx.mesh.uv_layers.new()

            for idx, loop in enumerate(ctx.mesh.loops):
                uv_layer.data[idx].uv = vertex_uv[loop.vertex_index]
        

        elif kind == 'MTLS' or kind == 'SSQS':
            materialNum = read_uint(file)
            
            for (kind, limit) in iter_chunks(file, limit):
                if kind == 'MATE' or kind == "STRP":
                    parse_material(file, limit, ctx)

                if kind == "STRP":
                    is_stripe = True

                else:
                    print(f"Unsupported MTL type {kind}")

        elif kind == "BBOX":
                coords = []
                for i in range(8):
                    coords.append(read_vec(file, 3))

                print(" > Read bounding box for MESH")
                print(coords)

        else:
            print(f"> Unsupported kind {kind}")
            
        pass
    
    # generate blender mesh
    if indiNum > 0:
        if is_stripe:
            for i in range(len(indis)):
                if i + 2 >= len(indis):
                    continue

                if i % 2 == 0:
                    # even
                    faces.append([indis[i+1],
                                    indis[i],
                                    indis[i+2]])
                else:
                    # odd
                    faces.append([indis[i],
                                    indis[i+1],
                                    indis[i+2]])
                    
        else:
            for i in range(len(indis)):
                if (3 * i) + 2 >= len(indis):
                    continue
                
                faces.append([indis[3*i],
                                    indis[3*i + 1],
                                    indis[3*i + 2]])


        # Fill mesh data with geometry (vertices, faces)
        ctx.mesh.from_pydata(vertex_pos, [], faces)
        ctx.mesh.update()
        
        # Create UV mapping
        uv_layer = ctx.mesh.uv_layers.new()

        mesh_obj_ptr = len(ctx.objects) - 1

        print(f"Set mesh_obj_ptr: {mesh_obj_ptr}")

        for idx, loop in enumerate(ctx.mesh.loops):
            uv_layer.data[idx].uv = vertex_uv[loop.vertex_index]

        for group in ctx.obj.vertex_groups:
            print(group)
            igroup = int(group.name)
            print(f"Adding to vtx group {group.name}")
            print(groups_created[igroup][0])
            print(groups_created[igroup][1])
            for vertex in groups_created[igroup]:
                group.add( [vertex[0]], vertex[1], 'ADD' )

                #if pid != -1:
                #    joint.parent = armature.edit_bones[pid]
                #    joint.head = joint.parent.tail
            

    # End of MESH chunks
    return


def parse_4d_model(filepath, file):
    global file_version

    if file.read(8) != b'\x53\x72\x1A\x1B\x0D\x0A\x87\x0A':
        raise IOError('Not a Stormregion file')

    # Setup parsing context
    ctx = ParsingContext()
    ctx.folder = os.path.dirname(filepath)

    scene_name = filepath.split("/")[-1].replace(".4d", "")

    print(f"Parsing {filepath}...")

    # Create root object representing the model
    root = bpy.data.objects.new('4d_model', None)
    
    #root.empty_display_type = 'CIRCLE'
    #root.empty_display_size = 1

    # Add to parsing context, everything will be parented to this
    ctx.objects.append(root)
    ctx.parents.append(None)

    # ONE section should follow immediately
    for (kind, limit) in iter_chunks(file, 128):
        if kind != 'SCEN':
            raise IOError('Not a SCEN file')
    
        file_version = file.read(4).decode("utf-8")
        print(f"SCEN version {file_version}")

        # v100: Rotate root object to compensate some the wacky coordinate system
        # v101: No correction
        if file_version == "v100":
            root.rotation_euler = (math.radians(90), 0, 0)
            
        for (kind, limit) in iter_chunks(file, limit):
            if kind == 'MESH' or kind == "DUMY" or kind == "SKVS" or kind == "BSP_":
                parse_object(file, limit, ctx, kind)

            elif kind == "SSQS":
                parse_anims(file, limit, ctx)

            else:
                print(f'Unsupported scene entry of type {kind}')
                continue
        
        '''
            name = "smg_man"
            armature = bpy.data.armatures.new(f"arm_{name}")
            armature_object = bpy.data.objects.new(f"obj_{name}", armature)
            armature.show_names = True
                
            bpy.context.collection.objects.link(armature_object)
            bpy.context.view_layer.objects.active = armature_object
            bpy.ops.object.mode_set(mode = 'EDIT')

            print(f"Found {len(bones)}")
            for idx in range(len(bones)):
                dummy_id = bones[idx][0] - 1
                joint = armature.edit_bones.new("bone_%03d" % idx)
                joint.parent = dummies[dummy_id]

                print(f"Add bone {idx} with dummy ID {dummy_id}")
                
                matrix_local = (
                    (bones[1][0], bones[1][1], bones[1][2], 0),
                    (bones[2][0], bones[2][1], bones[2][2], 0),
                    (bones[3][0], bones[3][1], bones[3][2], 0),
                    (0,                0,                0, 1)
                

                #joint.location = bones[4]
        '''
            
            
    # Restore parent hierarchy between the objects
    for idx, obj in enumerate(ctx.objects):
        try:
            bpy.context.scene.collection.objects.link(obj)
        except:
            print(f"{obj.name} is already in the right place, skipped")
            continue

        parentID = ctx.parents[idx]

        print(f"Object {obj} with ID {idx} pairs to {parentID}")
        
        if parentID is not None:        
            obj.parent      = ctx.objects[parentID +1]
            obj.parent_type = 'OBJECT'


    if len(bones_by_object) > 0:
        #armature = bpy.data.armatures.new(f"arm_{scene_name}")
        #armature_object = bpy.data.objects.new(f"obj_{scene_name}", armature)
        #armature.show_names = True
            
        #bpy.context.collection.objects.link(armature_object)
        #bpy.context.view_layer.objects.active = armature_object
        #bpy.ops.object.mode_set(mode = 'EDIT')
        
        # create a list of dummies that are relevant
        bones_to_create = {}
        print(f"Found {len(bones)} bones to process")

        # get a list of dummy names -> IDs
        print("DUMMIES:")
        print(dummies)

        # now find the head and tail of them all
        for object in bones_by_object:
            for dummy in bones_by_object[object]:
                print(f"Parsing DUMY {dummy}...")
                dumy_object = dummies[dummy]

                if dummy in bones_to_create:
                    print("WARNING: duplicate bone INDEX!!!")
                else:
                    bones_to_create[dummy] = {}

                if dumy_object.parent == None:
                    print(f"Can't deal with DUMY without a parent: {dumy_object.name}")
                    continue

                parent_id = dummy_name_id_map[dumy_object.parent.name]

                if parent_id not in bones_by_object[object]:
                    print(f"Found root armature node {dumy_object.parent.name}")
                    bones_to_create[dummy]["name"] = dumy_object.name
                    bones_to_create[dummy]["parent"] = None

                else:
                    print(f"{dumy_object.name} bone {dummy_name_id_map[dumy_object.name]} is a child of {dumy_object.parent} which is bone {parent_id}")
                    bones_to_create[dummy]["name"] = dumy_object.name
                    bones_to_create[dummy]["parent"] = parent_id

        print("BONES TO CREATE:")
        pprint.pprint(bones_to_create)

        for object in bones_by_object:
            print(f"Object {object}")

            joints = {}
            bones_added_to_scene = []

            iterate_list = list(bones_to_create.keys())
            idx = 0

            while len(bones_added_to_scene) < len(bones_to_create):
                if idx >= len(iterate_list):
                    idx = 0

                bone_index = iterate_list[idx]
                idx += 1

                print(f"Trying bone_index {bone_index}...")

                if bone_index in bones_added_to_scene:
                    print(f"> Duplicate")
                    continue

                bprops = bones_to_create[bone_index]
                idx += 1

                if bprops["parent"] is not None:
                    if bprops["parent"] not in joints:
                        print(f"> Parent {bprops['parent']} not created yet")
                        continue

                    parent = joints[bprops["parent"]]
                else:
                    parent = root

                dummy_name = dummies[bone_index]
                bone_properties = bones_by_object[object][bone_index]

                ctx.obj = bpy.data.objects.new(bprops["name"] + "_bone", None)
                ctx.obj.parent = parent

                # Parse transformation, location
                ctx.obj.matrix_local = (
                                      (bone_properties[0][0], bone_properties[0][1], bone_properties[0][2], 0),
                                      (bone_properties[1][0], bone_properties[1][1], bone_properties[1][2], 0),
                                      (bone_properties[2][0], bone_properties[2][1], bone_properties[2][2], 0),
                                      (0 , 0, 0, 1))

                ctx.obj.location = bone_properties[3] * ctx.scale
                joints[bone_index] = ctx.obj
                

                #joint = armature.edit_bones.new(f"{dummy_name}")
                #joints[bone_index] = joint
                #joint.parent = parent
                #joint.transform(mathutils.Matrix((
                 #                     (bone_properties[0][0], bone_properties[0][1], bone_properties[0][2], 0),
                 #                     (bone_properties[1][0], bone_properties[1][1], bone_properties[1][2], 0),
                 #                     (bone_properties[2][0], bone_properties[2][1], bone_properties[2][2], 0),
                 #                     (0 , 0, 0, 1))))

                bones_added_to_scene.append(bone_index)
                try:
                    bpy.context.scene.collection.objects.link(ctx.obj)
                except:
                    print(f"{ctx.obj.name} is already in the right place, skipped")
                    continue
    
                print(f"> Add bone {bone_index} with dummy ID {bprops['name']}_bone")

            '''
                    for group in ctx.objects[mesh_obj_ptr].vertex_groups:
                        print(group.name)

                    for group in ctx.objects[mesh_obj_ptr].vertex_groups:
                        igrp_name = int(group.name)
                        ctx.objects[mesh_obj_ptr].vertex_groups[group.name].name = bones_created_by_bone_index[igrp_name].name
                        print(bones_created_by_bone_index[igrp_name].name)

        
        for group in ctx.objects[mesh_obj_ptr].vertex_groups:
            print(group.name)
                        '''

    return {'FINISHED'}



from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator

class Import4DModel(Operator, ImportHelper):
    """Import Stormregion 4D model files"""
    
    bl_idname = "import_4d.model" 
    bl_label  = "Import 4D Model"

    # ImportHelper mixin class uses this
    filename_ext = ".4d"

    filter_glob: StringProperty(default="*.4d", options={'HIDDEN'}, maxlen=255)

    def execute(self, context):
        with open(self.filepath, 'rb') as file:
            return parse_4d_model(self.filepath, file)


def menu_func_import(self, context):
    self.layout.operator(Import4DModel.bl_idname, text="Import Stormregion 4D Model (.4d)")

def register():
    bpy.utils.register_class(Import4DModel)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(Import4DModel)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

if __name__ == "__main__":
    register()

    # Trigger import action immediately
    # bpy.ops.import_4d.model('INVOKE_DEFAULT')
