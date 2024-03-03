
import os
import struct
import math
import sys
from PIL import Image
from enum import Enum

from stormregion_def import *

'''
Version history

8/10/23 - Fix parsing of RODJ, add most of PATH and LOCS, add basic for TRIG
7/10/23 - Workflow to generate height + splatmaps + texturemap working mostly properly
3/10/23 - Added CEUP and CESP for *.anim files
2/10/23 - Fix SWINE compatibility
1/10/23 - Add support for more MAP file node types (ROD5/RODJ)

'''


import collections

file_version = "v101"
just_scene_tree = True
debug_print = False

objects = []
scene_animations = {}
dummies = []
bones_by_object = {}


class stormregion_map:
    DATABLOCK_END   = 0xffffffff
    DATABLOCK_NEXT  = 0x7fffffff

    TLAYER_NORMAL = 0
    TLAYER_BLOCKER = 1
    TLAYER_GRASS = 2
    TLAYER_FORD  = 4
    TLAYER_MASK_TYPE = 0xF
    TLAYER_MASK_WALKER = 0x10
    TLAYER_MASK_INVISIBLE = 0x80

    size_x  : int   = 0
    size_y  : int   = 0
    version : int   = 0

    imported_size_x : int = 0
    imported_size_y : int = 0
    crop_x1 : int = 0
    crop_y1 : int = 0

    export_size : int = 0

    map_name        = ""

    atmosphere      = ""
    skybox          = ""
    config          = ""
    aircraft_type   = ""
    ambient_music   = ""

    heightmap       = []    # heightmap values
    tlayers         = []    # material name + properties
    blend           = []    # for textured layers
    blend_special   = []    # for blocked/onlywalker layers

    objects         = []
    decals          = []
    ambient_sounds  = []
    locations       = []
    paths           = []

    roads           = []
    junctions       = []

    tvars           = {}    # variables, dict by name


    def is_pow2plus1(self, x):
        x = x - 1
        return (x & (x - 1)) == 0
    

    def crop_to(self, x1: int, x2: int, y1: int, y2: int):
        '''
        Crop a terrain to a specified size
        
        '''

        new_heightmap = []
        new_blend = []

        x_count = 0
        y_count = 0
        abs_count = -1
        for pixel in self.heightmap:
            abs_count += 1
            #print(f"pixel: {x_count}, {y_count}, {abs_count}, {(y_count * self.size_x)+x_count}")

            if x_count > self.size_x:
                # newline
                x_count = 1
                y_count += 1

            if y_count < y1:
                x_count += 1
                continue

            if x_count < x1 or x_count >= x2:
                x_count += 1
                continue

            if y_count >= y2:
                break

            new_heightmap.append(pixel)
            x_count += 1

        self.heightmap = new_heightmap

        x_count = 0
        y_count = 0

        for pixel in self.blend:
            if x_count > self.size_x:
                # newline
                x_count = 1
                y_count += 1

            if y_count < y1:
                x_count += 1
                continue

            if x_count < x1 or x_count >= x2:
                x_count += 1
                continue

            if y_count >= y2:
                break

            new_blend.append(pixel)
            x_count += 1

        self.blend = new_blend

        self.imported_size_x = self.size_x
        self.imported_size_y = self.size_y

        self.size_x = x2 - x1
        self.size_y = y2 - y1

        self.crop_x1 = x1
        self.crop_y1 = y1


        print(f"Heightmap cropped to {x2-x1} by {y2-y1}, new length is {len(new_heightmap)} and {len(new_blend)}")


    def export_prep(self):
        '''
        Normalise the size of the map so it's a power of 2
        Instead of cropping the terrain, expand it so that
        any undefined area will be flat
        '''

        if self.size_x != self.size_y:
            self.export_size = self.size_x if self.size_x > self.size_y else self.size_y
            print(f"WARNING: Heightmap is not square ({self.size_x} x {self.size_y}), it will be expanded to {self.export_size} in both dimensions")
        else:
            self.export_size = self.size_x

        if not self.is_pow2plus1(self.export_size):
            next_pow2 = int(math.pow(2, (math.ceil(math.log(self.export_size, 2))))) + 1
            print(f"WARNING: Map size ({self.size_x} x {self.size_y}) was not a power of 2. Expanded to {next_pow2} square. Unused vertices will be 0 (flat)")

        self.export_size = next_pow2
        self.x_padding = self.export_size - self.size_x
        self.y_padding = self.export_size - self.size_y

        print(f"Export prepared to {self.export_size}pixels square with padding of {self.x_padding} and {self.y_padding}")


    def export_heightmap_to_raw(self, output_filename: str, to_png = False, padding_height: int = 0):
        '''
        Generates a 16bit unsigned RAW file
        from the heightmap and print scaling ranges

        Can also generate a PNG heightmap (8 bit unsigned)
        '''

        self.export_prep()

        max_value = 0
        min_value = 0
        scale = 65535.0

        for pixel in self.heightmap:
            if pixel > max_value:
                max_value = pixel       # 1.5
            elif pixel < min_value:
                min_value = pixel       # -1.5

        if to_png:
            scale = 255.0

        scale = (max_value - min_value) / scale  # 3

        wrote = 0

        pixel_origin = int((padding_height + abs(min_value)) / scale)
        
        if to_png:
            img = Image.new("RGB", (self.export_size, self.export_size))
            png_data = []

            x_count = 0
            y_count = 0
            for pixel in self.heightmap:
                raw_pixel = int((pixel + abs(min_value)) / scale)
                png_data.append((raw_pixel, raw_pixel, raw_pixel))
                wrote += 1

                x_count += 1

                # pad rest of row with 0s (pixel_origin equates to 0 once terrain is re-imported)
                if x_count >= self.size_x:
                    if self.x_padding > 0:
                        for i in range(self.x_padding):
                            png_data.append((pixel_origin, pixel_origin, pixel_origin))
                            wrote += 1
                    y_count += 1
                    x_count = 0
                
                # pad y_padding rows of export_size length
                if y_count >= self.size_y:
                    if self.y_padding > 0:
                        for i in range(self.y_padding):
                            for i in range(self.export_size):
                                png_data.append((pixel_origin, pixel_origin, pixel_origin))
                                wrote += 1

            img.putdata(png_data)
            #img = img.convert('L')
            img.save(output_filename, 'PNG')

        else:
            pixel_origin = pixel_origin.to_bytes(2, "little")
            with open(output_filename, "wb") as fp:
                x_count = 0
                y_count = 0
                for pixel in self.heightmap:
                    raw_pixel = int((pixel + abs(min_value)) / scale)
                    fp.write(raw_pixel.to_bytes(2, "little"))
                    wrote += 1

                    x_count += 1

                    # pad rest of row with 0s (pixel_origin equates to 0 once terrain is re-imported)
                    if x_count >= self.size_x:
                        if self.x_padding > 0:
                            for i in range(self.x_padding):
                                fp.write(pixel_origin)
                                wrote += 1
                        y_count += 1
                        x_count = 0
                    
                    # pad y_padding rows of export_size length
                    if y_count >= self.size_y:
                        if self.y_padding > 0:
                            for i in range(self.y_padding):
                                for i in range(self.export_size):
                                    fp.write(pixel_origin)
                                    wrote += 1
        
        print(f"Scale: {scale}, Max: {max_value}, Min: {min_value}")
        print(f"Wrote heightmap to file: {output_filename}, {wrote} bytes written")
        print(f"Layers needed: {self.tlayers}")


    def normalise_splatmap(self):
        '''
        Convert the BLEND layers to a set of splatmaps

        First normalise all the pixel values so they add up to 255 across (up to) 4 splatmaps

        Stormregion uses a "base layer" which doesn't have a BLEND parameter so we have
        to generate it manually. Using 255 for that layer makes it too strong, but 128 
        seems to be about right.
        '''

        base_layer_weight = 128

        new_map = []

        for t in range(len(self.blend)):
            new_map.append([])


        for pixel in range(len(self.blend)):
            total_weight = float(sum(self.blend[pixel])) + base_layer_weight

            # note: this makes base_layer_weight effectively 255, if all other layers are 0
            #       which is what we want

            #print(f"Pixel {pixel} T {total_weight}")
            
            new_map[pixel].append(int(float(base_layer_weight / total_weight) * 255 ))
            for layer in self.blend[pixel]:
                new_map[pixel].append(int(float(layer / total_weight) * 255))

        self.blend = new_map

        print("BLEND map normalised")


    def create_texturemap(self, output_filename: str, texture_size_pixels: int = 512):
        '''
        Create a merged grid of the necessary textures used by the splatmaps

        It will be auto-arranged into a square that fits them all (the rest padded white)
        '''

        texture_data = []
        missing_textures = 0

        for layer in self.tlayers:
            # ignore layers with unusual properties
            if ((layer['properties'] & self.TLAYER_MASK_TYPE) == self.TLAYER_NORMAL) and \
                ((layer['properties'] & self.TLAYER_MASK_WALKER) == 0) and \
                ((layer['properties'] & self.TLAYER_MASK_INVISIBLE) == 0):

                try:
                    texture_data.append(Image.open(f"texture/{layer['material']}_1.png"))
                except FileNotFoundError:
                    try:
                        texture_data.append(Image.open(f"../../stormregion-tools/gepard1and2/PanzersUnpacker/extractedFiles/tiles/{layer['material']}_1.dds"))
                        print(f"Importing DDS texture {layer['material']}")
                        texture_data[-1].save(f"texture/{layer['material']}_1.png", 'PNG')
                    except FileNotFoundError:
                        print(f"Missing texture locally and in game files: {layer['material']}_1.png")
                        missing_textures += 1
                        continue

        if missing_textures > 0:
            print("Missing textures - texturemap/splatmap NOT generated")
            exit()

        size_side = math.ceil(math.sqrt(len(texture_data)))
        size_pixels = size_side * texture_size_pixels
        print(f"Creating texturemap of {len(texture_data)} - {size_side} by {size_side}, image size will be {size_pixels} square")
        output_tex = Image.new('RGBA', (size_pixels, size_pixels), color=(0,0,0,0))

        x_pos = 0
        y_pos = 0
        for image in texture_data:
            output_tex.paste(image,(x_pos,y_pos))
            x_pos += texture_size_pixels
            if x_pos >= size_pixels:
                x_pos = 0
                y_pos += texture_size_pixels

        output_tex.save(output_filename, "PNG")


    def export_splatmaps(self, output_filename: str):
        '''
        Export all textured BLEND layers to a series of splatmaps
        Up to 4 layers per map (R, G, B, A)
        Client application will need to ensure that the texture channels in-game
        are matched with the order here (we use the order that tlayers are parsed)
        '''

        self.export_prep()

        self.normalise_splatmap()

        self.create_texturemap(f"{self.map_name}_texture_array.png")

        num_splatmaps = math.ceil(len(self.blend[0]) / 4)

        print(f"Require {num_splatmaps} splatmaps for {len(self.blend[0])} layers")

        output_data = []
        for splatmap_index in range(num_splatmaps):
            output_data.append([])

        pixel_index = 0
        x_index = 0
        y_index = 0

        # per pixel
        for pixel_map in self.blend:
            layer_index = 0

            pixel_cache = []

            # per layer
            for map in pixel_map:
                splatmap_index = math.floor(layer_index / 4)

                pixel_cache.append(map)
                
                if len(pixel_cache) == 4:
                    output_data[splatmap_index].append(tuple(pixel_cache))
                    splatmap_index += 1
                    pixel_cache = []

                layer_index += 1

            if len(pixel_cache) != 0:
                while len(pixel_cache) != 4:
                    #print(f"padding channel {len(pixel_cache) -1 }")
                    pixel_cache.append(0)
                output_data[splatmap_index].append(tuple(pixel_cache))
                pixel_cache = []
            
            x_index += 1
            pixel_index += 1

            # pad out undefined areas
            if x_index >= self.size_x:
                if self.x_padding > 0:
                    for q in range(self.x_padding):
                        for z in range(num_splatmaps):
                            output_data[z].append((0,0,0,0))
                        pixel_index += 1
                
                x_index = 0
                y_index += 1
                
            # pad out y with full rows of 0 (no texture at all)
            if y_index > self.size_y:
                if self.y_padding > 0:
                    for q in range(self.y_padding):
                        for u in range(self.export_size):
                            for z in range(num_splatmaps):
                                output_data[z].append((0,0,0,0))
                            pixel_index += 1


        print(f"{num_splatmaps} BLEND splatmaps generated")


        # export to file
        for splatmap_index in range(num_splatmaps):
            img = Image.new("RGBA", (self.export_size, self.export_size))
            img.putdata(output_data[splatmap_index])
            
            if splatmap_index == 0:
                fname = "splat.png"
            else:
                # game expects splat, splat2, splat3...
                fname = f"splat{splatmap_index+1}.png"
            img.save(fname, "PNG")
            splatmap_index += 1
        
        # todo: generate GRASS or FORD layers as "detail" layers
        

    def get_stats(self):
        print(f"Map Size        : {self.size_x} x {self.size_y}")
        print(f"Terrain Layers  : {len(self.tlayers)}")
        print(f"Roads           : {len(self.roads)}")
        print(f"Junctions       : {len(self.junctions)}")
        print(f"Objects         : {len(self.objects)}")
        print(f"Decals          : {len(self.decals)}")
        print(f"Sounds          : {len(self.ambient_sounds)}")
    

def read_kind(file):
    raw_data = file.read(4)
    if debug_print:
        print("++K " + raw_data.hex())
    return raw_data.decode()

def read_char(file):
    raw_data = file.read(1)
    if debug_print:
        pass#print("++C " + raw_data.hex())       
    return int.from_bytes(raw_data, 'little')

def read_uint(file):
    raw_data = file.read(4)
    if debug_print:
        print("++U " + raw_data.hex())
    return struct.unpack('<I', raw_data)[0]

def read_sint(file):
    raw_data = file.read(4)
    if debug_print:
        print("++I " + raw_data.hex())
    return struct.unpack('<i', raw_data)[0]

def read_ushort(file):
    raw_data = file.read(2)
    if debug_print:
        print("++S " + raw_data.hex())
    return struct.unpack('<H', raw_data)[0]

def read_float(file):
    raw_data = file.read(4)
    if debug_print:
        print("++F " + raw_data.hex())
    return struct.unpack('<f', raw_data)[0]

def read_string(file):
    length = read_ushort(file)
    if length > 4096:
        print("ERROR STRING WAS TOO LONG")
        exit()
    if length == 0:
        return ""
    #    data = read_ushort(file)
    #    if data != 0:
    #        print("READ_STRING LEN 0, DATA WAS NOT 0")
    #        #exit(0)
    #    else:
    #        return ""
    raw_data = file.read(length)
    if debug_print:
        print("++S " + raw_data.hex())
    result = raw_data.decode()
    return result

def read_vec(file, components):
    res = {}
    
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
        self.scale = 0.005  # Sr model files are HUGE in blender units..

        self.folder   = None        
        self.objects = []
        self.parents = []

        self.mesh = None
        self.obj  = None


def parse_anims(file, limit, ctx):
    srefs = {}
    num_anims = read_uint(file)

    for (kind, limit) in iter_chunks(file, limit):    
        sref_name = read_string(file)
        sref_anim = read_string(file)
        srefs[sref_name] = sref_anim
        #print(f" - Add SREF {sref_name} = {sref_anim}")


def parse_untd(file, limit_arbitrary = 0xffffffff, level = 0):
    unit = stormregion_map_unit_def()

    #if level > 0:
        #print("SUBUNIT START")
    next = read_uint(file)
    while True:
        field = read_string(file)

        if next == 5:
            value = read_string(file)

        elif next == 1:
            value = read_char(file)

        elif next == 2:
            value = read_uint(file)

        elif next == 8:
            x = read_float(file)
            y = read_float(file)
            value = f"{x} , {y}"  # x, y

        elif next == 10:
            value_a = read_uint(file)
            value_b = read_uint(file)
            if value_b == 0:
                value = "null"
            else:
                # num stored units
                # sub unit def interrupts current unit def
                kind = read_kind(file)
                if kind == "_mcl":
                    length = read_uint(file)
                    count = 1
                    next = parse_untd(file, length + file.tell(), level + 1)
                    next = read_uint(file)
                    if next != 0x6c636d5f:
                        continue
                    while next == 0x6c636d5f:
                        count += 1
                        length = read_uint(file)
                        next = parse_untd(file, length + file.tell(), level + 1)
                        print(next)

                    value = f"subunit_count{count}"

                
                

        elif next == 3:
            value = read_float(file)

        else:
            value = f"unknown format: {next}"

        spaces = ""
        for i in range(level):
            spaces = spaces + " "

        # create the unit object
        if field == "ClassName":
            unit.classname = value
        elif field == "Player":
            unit.player = value
        elif field == "XP":
            unit.xp = value
        elif field == "Pos":
            unit.x = x
            unit.y = y

        #print(f"  {spaces}> UNTD: {field} = {value}")
        
        next = read_uint(file)      # DATATYPE FOR NEXT THING?
        if next == 0:
            #print("return 0")
            return 0

        if next == 0x6c636d5f:
            #print("return mcl")
            return 0x6c636d5f

        if file.tell() >= limit_arbitrary:
            #print("return limit")
            return 1


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
        print(f"  - {kind}")

        if kind == 'DIFF':
            diffuse = read_string(file)

            if not just_scene_tree:
                print(f"  > Parsed DIFF: {diffuse} with {vertexStart} and {vertexEnd} and {numFaces}")
            
            # All textures are supposed to be .png files
            diffuse = diffuse.replace('.tga', '.png')

        elif kind == 'SPEC':
            specular = read_string(file)
            if not just_scene_tree:
                print(f"  > Parsed SPEC: {specular} with {vertexStart} and {vertexEnd} and {numFaces}")


        elif kind == "STRP":
            parse_material(file, limit, ctx)


        elif kind == "MTBL":
            numMTBL = read_uint(file)

            if not just_scene_tree:
                print(f"  > Found MTBL section with {numMTBL} indexes")

            mtbl = []

            for idx in range(numMTBL):
                mtbl.append(read_uint(file))

            if not just_scene_tree:
                print(mtbl)

        elif kind == "REFL":
            reflection = read_string(file)
            if not just_scene_tree:
                print(f"  > Parsed REFL: {reflection} with {vertexStart} and {vertexEnd} and {numFaces}")

        else:
            if not just_scene_tree:
                print(f"  > Unsupported MTL kind {kind}")


    # Sanity check
    if not diffuse:
        return


def parse_object(file, limit, ctx, kind = "MESH"):
    name     = read_string(file)
    parentID = read_sint(file)

    if not just_scene_tree:
        print(f"Parsed {kind}: {name} with parent ID {parentID}")

    is_stripe = False
    indis = []
    indiNum = 0
    
    if file_version == "v101":
        # waste 8 bytes
        if not just_scene_tree:
            print("> Wasting 8 bytes for 101")
        read_sint(file)
        read_sint(file)

    if kind == "MESH" or kind == "SKVS":
        # Allocate associated blender structures
        if not just_scene_tree:
            print("Allocated MESH/SKVS")

    elif kind == "DUMY":
        if not just_scene_tree:
            print("Allocated DUMY empty")
    
    if not just_scene_tree:
        print("> Transformation:")
    # Parse transformation, location
    transformation_matrix = (
        (read_float(file), read_float(file), read_float(file), 0),
        (read_float(file), read_float(file), read_float(file), 0),
        (read_float(file), read_float(file), read_float(file), 0),
        (0,                0,                0,                1)
    )

    print(f"Object {name}")
    print(transformation_matrix)
    
    if not just_scene_tree:
        print(transformation_matrix)

    print("Location:")
    location = read_vec(file, 3) #* ctx.scale
    print(location)
    
    # Parse various object attributes
    vertex_pos  = None
    vertex_norm = None
    vertex_uv   = None
    vertex_data = []
    srefs = {}

    if kind == "NODE":
        if not just_scene_tree:
            print("Unknown:")
        other_matrix = ( read_float(file), read_float(file), read_float(file), 
                        read_float(file), read_float(file), read_float(file), read_float(file))

        if not just_scene_tree:
            print(other_matrix)

    faces = []

    if kind == "DUMY":
        dummies.append(name)

    if kind == "DUMY":
        return
    
    root_kind = kind

    for (kind, limit) in iter_chunks(file, limit):

        print(f"- {kind} {hex(limit)}")
        
        # normal VERT, for objects and vehicles
        if kind == 'VERT' and root_kind != "SKVS":
            vertexNum    = read_uint(file)
            vertexFormat = read_uint(file)

            if vertexNum > 0xFFFF:
                raise IOError('Too many vertices')
    
            if vertexFormat != 0 and vertexFormat != 1: 
                raise IOError('Unsupported vertex format {vertexFormat}')
            
            if vertexFormat == 0:
                vertex_pos  = []
                vertex_norm = []
                vertex_uv   = []
                print(f" > Found {vertexNum} vertices for this mesh")
                for idx in range(vertexNum):
                    vertex_pos.append( read_vec(file, 3) ) #* ctx.scale )
                    vertex_norm.append( read_vec(file, 3) )
                    
                    # Whacky coordinate systems..
                    vertex_uv.append((
                        0 + read_float(file), 
                        1 - read_float(file)
                    ))

            else:
                vertex_pos  = []
                vertex_norm = []
                vertex_uv   = []
                print(f" > Found {vertexNum} vertices for this mesh")
                for idx in range(vertexNum):
                    pos = read_vec(file, 3) # * ctx.scale
                    vertex_pos.append( pos )
                    norm = read_vec(file, 3)
                    vertex_norm.append( norm )
                    
                    # Whacky coordinate systems..
                    vertex_uv.append((
                        0 + read_float(file), 
                        1 - read_float(file)
                    ))
                    other = read_float(file)
                    print(pos, norm, other)
                


        # VERT inside SKVS is used by "walker"s (humans)
        elif kind == "VERT" and root_kind == "SKVS":
            vertexNum    = read_uint(file)
            vertexFormat = read_uint(file)
            vertexUnknown = read_uint(file)

            print(f" > Read vertex format SKVS: {vertexNum}, {vertexFormat}, {vertexUnknown}")

            vertex_pos  = []
            vertex_norm = []
            vertex_uv   = []
            groups_created = {}
            

            for idx in range(vertexNum):
                vertex_pos.append( read_vec(file, 3) ) #* ctx.scale )
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
                
                #print(f" > > Bone num {bone_numbers}")

                bone_weights = []
                material_floats = []

                for i in range(4):
                    bone_weights.append(read_float(file))

                #print(f" > > Bone weights {bone_weights}")

                mtbl_numbers = []
                for i in range(4):
                    mtbl_numbers.append(read_char(file))
                
                #print(f" > > MTBL {mtbl_numbers}")

                for i in range(4):
                    material_floats.append(read_float(file))

                # create vertex groups with weights
                for i in range(4):
                    if bone_numbers[i] not in groups_created:
                        #ctx.obj.vertex_groups.new(name = f"{bone_numbers[i]}")
                        #print(f"Create vertex group {bone_numbers[i]}")
                        groups_created[bone_numbers[i]] = []
                    
                    groups_created[bone_numbers[i]].append((int(idx), bone_weights[i]))



        elif kind == "BONS":
            if name not in bones_by_object:
                bones_by_object[name] = {}
            numBones = read_uint(file)

            for idx in range(numBones):
                bone_id = read_uint(file)
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
                
            if not just_scene_tree:
                print(f" > Loaded {numBones} bones for this object")
                #print(bones)
                


        elif kind == 'INDI':
            indiNum = read_uint(file)

            if not just_scene_tree:
                print(f" > Found {indiNum} indexes for this mesh")

            for idx in range(indiNum):
                indis.append(read_ushort(file))
                

        elif kind == 'FACE':
            faceNum = read_uint(file)

            if not just_scene_tree:
                print(f" > Found {faceNum} faces for this mesh")
            
            for idx in range(faceNum):
                faces.append((
                    read_ushort(file),
                    read_ushort(file),
                    read_ushort(file)          
                ))
                
            # Fill mesh data with geometry (vertices, faces)
            #ctx.mesh.from_pydata(vertex_pos, [], faces)
            #ctx.mesh.update()
            
            # Create UV mapping
            #uv_layer = ctx.mesh.uv_layers.new()

            #or idx, loop in enumerate(ctx.mesh.loops):
            #    uv_layer.data[idx].uv = vertex_uv[loop.vertex_index]
        

        elif kind == 'MTLS' or kind == 'SSQS':
            materialNum = read_uint(file)
            
            for (kind, limit) in iter_chunks(file, limit):
                if kind == 'MATE' or kind == "STRP":
                    parse_material(file, limit, ctx)

                if kind == "STRP":
                    is_stripe = True

                else:
                    if not just_scene_tree:
                        print(f"Unsupported MTL type {kind}")

        elif kind == "BBOX":
                coords = []
                for i in range(8):
                    coords.append(read_vec(file, 3))

                if not just_scene_tree:
                    print(" > Read bounding box for MESH")
                    print(coords)


        # .anim files, child of NODE - position?
        elif kind == "CPSP":
            frames = read_uint(file)       # number of frames
            blank = read_uint(file)
            a = read_float(file)
            sh = read_ushort(file)
            print(f" > CPSP num frames: {frames}, {a}, {sh}")
            
            for i in range(frames):
                c = read_vec(file, 3)
                print(i, c)

            
        # .anim files, child of NODE - rotation?
        elif kind == "CEUP":
            frames = read_uint(file)
            blank = read_uint(file)
            a = read_float(file)
            sh = read_ushort(file)
            print(f" > CEUP num frames: {frames}, {a}, {sh}")

            for i in range(frames):
                c = read_vec(file, 3)
                print(i, c)

        else:
            if not just_scene_tree:
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
        #ctx.mesh.from_pydata(vertex_pos, [], faces)
        #ctx.mesh.update()
        
        # Create UV mapping
        #v_layer = ctx.mesh.uv_layers.new()

        #for idx, loop in enumerate(ctx.mesh.loops):
        #    uv_layer.data[idx].uv = vertex_uv[loop.vertex_index]

    # End of MESH chunks
    return

def parse_4d_model(filepath, file):
    global file_version

    if file.read(8) != b'\x53\x72\x1A\x1B\x0D\x0A\x87\x0A':
        raise IOError('Not a Stormregion file')

    # Setup parsing context
    ctx = ParsingContext()
    ctx.folder = os.path.dirname(filepath)

    # Create root object representing the model
    #root = bpy.data.objects.new('4d_model', None)
    
    #root.empty_display_type = 'CIRCLE'
    #root.empty_display_size = 1

    # Rotate root object to compensate some the wacky coordinate system
    #root.rotation_euler = (math.radians(90), 0, 0)

    # Add to parsing context, everything will be parented to this
    #ctx.objects.append(root)
    #ctx.parents.append(None)

    map_x = 0
    map_y = 0

    # ONE section should follow immediately
    for (kind, limit) in iter_chunks(file, 128):
        if kind == 'SCEN':
            print("MODEL file")
            file_version = file.read(4).decode("utf-8")
            print(f"SCEN version {file_version}")


        elif kind == "MAPF":
            print("MAP file")
            map_file = stormregion_map()
            file_version = read_uint(file)
            print(f"MAP version {file_version}")
            map_file.version = file_version
        
        elif kind == 'CANM':
            file_version = file.read(4).decode("utf-8")
            a = read_float(file)
            b = read_float(file)
            c = read_float(file)
            print(f"ANIM file CANM {file_version} with {a}, {b}, {c}")
        
        previous_limit = 0
        for (kind, limit) in iter_chunks(file, limit):
            print(kind, limit - previous_limit, hex(limit))
            length = limit - previous_limit
            previous_limit = limit

            if kind == 'MESH' or kind == "DUMY" or kind == "SKVS" or kind == "BSP_" or kind == "NODE":
                parse_object(file, limit, ctx, kind)

            elif kind == "SSQS":
                parse_anims(file, limit, ctx)

            elif kind == "FLYZ":
                print("Ignoring FLYZ")


            # -------  map files -----------

            elif kind == "MINA":
                # 2 bytes == 00
                pass

            elif kind == "TPAM":
                campaign = read_string(file)
                if not just_scene_tree:
                    print(f"Campaign: {campaign}")
                map_file.campaign = campaign

            elif kind == "INIM":
                file.read(2)
                map_config = read_string(file)
                map_file.config = map_config

            elif kind == "MINI":
                # mini map ??
                pass

            elif kind == "ATMS":
                atmosphere = read_string(file)
                if not just_scene_tree:
                    print(f"ATMS: {atmosphere}")
                map_file.atmosphere = atmosphere


            elif kind == "KSYB":
                atmosphere = read_string(file)
                if not just_scene_tree:
                    print(f"KSYB: {atmosphere}")
                map_file.skybox = atmosphere

            elif kind == "TERR":
                terr_version = file.read(4).decode("utf-8")
                print(f"TERR version: {terr_version}")

                current_pos = file.tell() + 8
                for (kind, limit) in iter_chunks(file, limit):
                    print(f" > Parsing {kind} length {limit-current_pos} limit {hex(limit)}") 
                    current_pos = limit

                    if kind == "HMAP":
                        map_file.size_x = read_uint(file) + 1
                        map_file.size_y = read_uint(file) + 1
                        print(f"   size {map_file.size_x} by {map_file.size_y}")     

                        # either 
                        for i in range(map_file.size_x * map_file.size_y):
                            map_file.heightmap.append(read_float(file))
                        
                        print(f" > HMAP Read {len(map_file.heightmap)} vertices")
 

                    elif kind == "TLAY":
                        num_tlays = read_uint(file)
                        # layer IDS: 0 = normal, 2 = grass (read_string again), 1 = blocker, 4 = ford, 0x10 = only walker, mask 0x80 = invisible

                        for i in range(num_tlays):
                            layer = read_string(file)
                            layer_id = read_uint(file)
                            map_file.tlayers.append({"material": layer, "properties": layer_id})

                        print(f" > {map_file.tlayers}")

                    elif kind == "TMAP":
                        pass


                    elif kind == "BLND":
                        # 1 byte per vertex 161x161 per tlayer
                        for i in range(len(map_file.tlayers) - 1):
      
                            if map_file.size_x == 0 or map_file.size_y == 0:
                                print("ERROR - not obtained dimensions of map from HMAP yet")
                                exit(0)

                            if ((map_file.tlayers[i]['properties'] & stormregion_map.TLAYER_MASK_TYPE) == stormregion_map.TLAYER_NORMAL) and \
                                ((map_file.tlayers[i]['properties'] & stormregion_map.TLAYER_MASK_WALKER) == 0) and \
                                ((map_file.tlayers[i]['properties'] & stormregion_map.TLAYER_MASK_INVISIBLE) == 0)     :

                                if map_file.blend == []:
                                    for t in range((map_file.size_x * map_file.size_y)):
                                        map_file.blend.append([])


                                # optimise: could just read the full datablock and switch
                                # when exported
                                for j in range(map_file.size_x * map_file.size_y):
                                    map_file.blend[j].append(read_char(file))

                                print(f" > BLEND: {map_file.tlayers[i]['material']}")

                        print(f"Loaded {len(map_file.blend[0])} blend maps")                    


                    elif kind == "DIFF":
                        # same length as HMAP exactly
                        pass


                    elif kind == "BLCK":
                        # big data set, 3.2mb
                        pass

            elif kind == "3WHR":
                file.read(4)
                whrs = []

                whrs.append(read_string(file))
                file.read(0x60)


            elif kind == "ROD5":
                # road map of some sort
                num_roads = read_uint(file)
                b = read_uint(file)
                c = read_uint(file)      
                print(f" > ROD5: {num_roads}, {b}, {c}")

                for rd in range(num_roads):
                    nodes = read_uint(file)         # ??
                    while nodes != stormregion_map.DATABLOCK_NEXT and nodes != stormregion_map.DATABLOCK_END:
                        nodes = read_uint(file)  

                    if nodes == stormregion_map.DATABLOCK_END:
                        break

                    material = read_string(file)
                    a = read_float(file)    # road tesselation distance (m)
                    b = read_float(file)
                    c = read_uint(file)     # 0x20 = U mirror, 0x40 = V mirror,
                    d = read_uint(file)  

                    road = stormregion_road(material, a, c)
                    print(f" > New road: {material} with: {b} {d}")

                    for i in range(d):
                        x = read_float(file)
                        y = read_float(file)
                        r1 = read_float(file)
                        r2 = read_float(file)
                        al = read_float(file)
                        ar = read_float(file)
                        itrp = read_float(file)
                        r3 = read_float(file)
                        jcn = read_uint(file)

                        node = stormregion_road_node(x, y, r1, r2, r3, al, ar, itrp, jcn)
                        road.add_node(node)

                    map_file.roads.append(road)

            elif kind == "RODJ":
                # road junction .?
                try:
                    a = read_uint(file)
                    b = read_uint(file)     # 13 = 1, 12 = 2 ???
                    num_junctions = read_uint(file)
                    c = read_uint(file)
                    print(f" > RODJ: {num_junctions}, {c}")

                    while c != stormregion_map.DATABLOCK_END and c != stormregion_map.DATABLOCK_NEXT:
                        c = read_uint(file)
                    

                    for jcn in range(num_junctions):
                        prefab = read_string(file)

                        a = read_float(file)    # not known
                        b = read_float(file)    # not known
                        c = read_uint(file)     # 0x20 = U mirror, 0x40 = V mirror,
                        print(f" > New jcn: {prefab} with {a}, {b} properties: {c}")

                        # unused properties in stormregion_jcn initialiser are not known/used
                        # in JCN type
                        x = read_float(file)
                        y = read_float(file)
                        r1 = read_float(file)
                        r2 = read_float(file)
                        al = read_float(file)
                        ar = read_float(file)
                        itrp = read_float(file)
                        r3 = read_float(file)
                        jcn = read_uint(file)

                        joint_count = read_uint(file)

                        # tells which ROD5's are connected to
                        # seems to be 12 connections per JCN, but only 4 or so max are used
                        # how to know which is which?
                        for i in range(joint_count):
                            joint_ref = read_uint(file)
                            joint_properties = read_char(file)

                        jcn = stormregion_jcn(prefab, c, x, y, r1, r2, r3)
                        map_file.junctions.append(jcn)

                        c = read_uint(file)
                        while c != stormregion_map.DATABLOCK_END and c != stormregion_map.DATABLOCK_NEXT:
                            c = read_uint(file)


                except:
                    print("ERROR IN RODJ - tbc")
                    exit()

            elif kind == "ENTS":
                ents_version = file.read(4).decode("utf-8")
                print(f"ENTS version: {ents_version}")

                current_pos = file.tell() + 8
                for (kind, limit) in iter_chunks(file, limit):
                    print(f" > Parsing {kind} length {limit-current_pos} limit {hex(limit)}") 
                    current_pos = limit

                    if kind == "DECS":
                        # stickers on the terrain, basically
                        num_deca = read_uint(file)

                        for (kind, limit) in iter_chunks(file, limit):
                            if kind == "DECA":  
                                deca_version = file.read(4).decode("utf-8")
                                deca_material = read_string(file)
                                deca_x = read_uint(file)
                                deca_y = read_uint(file)
                                deca_rot_deg = read_uint(file) * 90
                                #print(f"  > DECA: {deca_version}, {deca_material}, {deca_x}, {deca_y}, {deca_rot_deg}*")
                                map_file.decals.append(stormregion_decal(deca_material, deca_x, deca_y, deca_rot_deg))

                            else:
                                print(f"Unknown DECS sub-node {kind}")
                                exit(0)


                    elif kind == "DODS":
                        # objects - ()shader: multi-create)
                        # does not subscribe to the same rules of iter_chunks -.-

                        num_doods = read_uint(file)
                        a = read_uint(file)
                        b = read_uint(file)
                        ff = read_uint(file)
                        next = 0

                        while True:
                            if next == stormregion_map.DATABLOCK_END:
                                break
                            kind = file.read(4)                             # DOOD
                            size = read_uint(file)
                            dood_version = file.read(4).decode("utf-8")
                            dood_object = read_string(file)                 # 4d file
                            dood_x = read_float(file)                       # x
                            dood_z = read_float(file)                        # z?
                            dood_y = read_float(file)                       # y
                            dood_r = read_float(file)                            # rot
                            b = read_uint(file)
                            c = read_uint(file)
                            d = read_float(file)
                            e = read_char(file)
                            f = read_char(file)
                            g = read_char(file)
                            gb = read_ushort(file)
                            next = read_uint(file)
                            if next == 0x7fffffff or next == stormregion_map.DATABLOCK_END:
                                #print(f"  > DOOD: {dood_version}, {dood_object}, {dood_x}, {dood_y}, {dood_z}, {dood_r}, {b}, {c}, {d}, {e}, {gb}")
                                map_file.objects.append(stormregion_object(dood_object, dood_x, dood_y, dood_z, dood_r, 0))
                                continue

                            while (next != 0x7fffffff) and (next != stormregion_map.DATABLOCK_END):
                                #print(f"  > DOOD: {dood_version}, {dood_object}, {dood_x}, {dood_y}, {dood_z}, {dood_r}, {b}, {c}, {d}, {e}, {gb}, {next}")
                                map_file.objects.append(stormregion_object(dood_object, dood_x, dood_y, dood_z, dood_r, next))
                                next = read_uint(file)
                        

                    elif kind == "EEFS":
                        # effects
                        pass


                    elif kind == "UNDS":
                        # units - mostly done

                        for (kind, limit) in iter_chunks(file, limit):
                            if kind == "UNTD":
                                untd_version = file.read(4).decode("utf-8")
                                parse_untd(file)

                                #print(f"  > UNTD: {untd_version} ends -------------")


                    elif kind == "AMBS":          
                        next = read_uint(file)
                        while next != stormregion_map.DATABLOCK_NEXT:
                            next = read_uint(file)

                        while next != stormregion_map.DATABLOCK_END:
                            kind = read_kind(file)
                            kindlen = read_uint(file)
                            ambi_ver = file.read(4).decode("utf-8")
                            sound = read_string(file)
                            x = read_float(file)
                            y = read_float(file)
                            z = read_float(file)
                            v = read_float(file)
                            next = read_uint(file)
                            if next == 0x7fffffff or next == stormregion_map.DATABLOCK_END:
                                #print(f"  > {kind}: {ambi_ver} {sound} at {x}, {y}, {z} / {v}")
                                map_file.ambient_sounds.append(stormregion_sfx(sound, x, y, z, v, 0))
                                continue

                            while (next != 0x7fffffff) and (next != stormregion_map.DATABLOCK_END):
                                #print(f"  > {kind}: {ambi_ver} {sound} at {x}, {y}, {z} / {v}, {next}")
                                map_file.ambient_sounds.append(stormregion_sfx(sound, x, y, z, v, next))
                                next = read_uint(file)


            elif kind == "RVR3":
                # rivers, strangely enough
                # similar to roads, with some more
                print(f"> RVR3: Skipping rivers for now")


            elif kind == "TVAR":
                # variables for scripting - DONE
                num_slots = read_uint(file)
                b = read_uint(file)
                num_tvars = read_uint(file)

                while next != stormregion_map.DATABLOCK_NEXT:
                    next = read_uint(file)

                for tvar in range(num_tvars):
                    tvar_name = read_string(file)
                    initial_value = read_uint(file)         # FFFFFFFF == -1 etc
                    increment = read_uint(file)

                    map_file.tvars[tvar_name] = stormregion_tvar(tvar_name, initial_value, increment)
                    print(f" > TVAR: {tvar_name}")

                    if num_tvars > 1:
                        next = read_uint(file)
                



            elif kind == "TRIG":
                num_trig = read_uint(file)

                continue

                # todo : need to parse each trigger action/condition according to its
                #        type : good repetitive job for spare time kicking about

                for trig in range(num_trig):
                    hdr = read_uint(file)
                    trig_num = read_uint(file)   # 02 when enabled
                    a = read_uint(file)          # 01 = normal, 02 = parallel
                    trig_name = read_string(file)
                    event_type = read_uint(file)          # event (0 = periodical, 4 = unit_attacked)
                    # read payload according to type

                    condition_count = read_uint(file)          # conditions
                    # read payload according to type
                    for condition in range(condition_count):
                        condition = read_uint(file)

                    actions_count = read_uint(file)          # actions
                    # read payload according to type
                    for action in range(actions_count):
                        action = read_uint(file)

                    print(f" > TRIG: {trig_num}, {trig_name}, {a} {b} {c} {d} {e} {hdr}")
                

            elif kind == "LOCS":
                b = read_uint(file)
                a = read_uint(file)
                num_locs = read_uint(file)

                if num_locs == 0:
                    print(f" > LOCS: none in file")
                    continue

                next = read_uint(file)

                while next != stormregion_map.DATABLOCK_NEXT:
                    next = read_uint(file)

                while next != stormregion_map.DATABLOCK_END:
                    # x, y, x, y describing the size of the box
                    a = read_uint(file)
                    b = read_uint(file)
                    c = read_uint(file)
                    d = read_uint(file)
                    loc_name = read_string(file)
                    color = read_uint(file)     # not known?
                    print(f" > LOC: {loc_name} {a} {b} {c} {d} {color}")
                    loc = stormregion_loc(loc_name, a, b, c, d, color)
                    map_file.locations.append(loc)
                    next = read_uint(file)

                    while next != stormregion_map.DATABLOCK_END and next != stormregion_map.DATABLOCK_NEXT:
                        print(f" >      {next}")
                        next = read_uint(file)


            elif kind == "PATH":
                b = read_uint(file)             # if you create + delete slots, this number doesn't decrease with delete
                a = read_uint(file)
                num_paths = read_uint(file)     # this seems to be accurate to the number of slots

                if num_paths == 0:
                    print(f" > PATH: none in file")
                    continue

                next = read_uint(file)

                while next != stormregion_map.DATABLOCK_NEXT:
                    next = read_uint(file)

                while next != stormregion_map.DATABLOCK_END:
                    path_name = read_string(file)
                    a = read_char(file)     # always ff?
                    c = read_uint(file)     # path index?
                    nodes = read_uint(file)
                    path_locs = []

                    for q in range(nodes):
                        x = read_float(file)
                        y = read_float(file)
                        path_locs.append((x, y))

                    path = stormregion_path(path_name, path_locs)
                    print(f" > PATH: {path_name} with {nodes} nodes")
                    map_file.paths.append(path)
                    next = read_uint(file)

                    while next != stormregion_map.DATABLOCK_END and next != stormregion_map.DATABLOCK_NEXT:
                        print(next)
                        next = read_uint(file)
                
                print(f"Loaded {len(map_file.paths)} PATH nodes")


            elif kind == "LRIA":
                map_file.aircraft_type = read_string(file)
                print(f"> LRIA, Airplanes type: {map_file.aircraft_type}")
                
            elif kind == "ISUM":
                map_file.ambient_music = read_string(file)
                print(f"> ISUM: ambient music: {map_file.ambient_music}")

            else:
                print(f'Unsupported scene entry of type {kind}')
                continue
            
            
    print("END OF SCENE")
    map_file.crop_to(37, 140, 32, 140)
    map_file.export_heightmap_to_raw("output.raw", padding_height=-4)
    map_file.export_splatmaps("a")
    
    # Restore parent hierarchy between the objects
    for idx, obj in enumerate(ctx.objects):
        #bpy.context.scene.collection.objects.link(obj)

        parentID = ctx.parents[idx]

        print(f"Pair object to ID {parentID}")

        print(ctx.objects)
        
        if parentID is not None:  
            pass      
            #obj.parent      = ctx.objects[parentID +1]
            #obj.parent_type = 'OBJECT'

    for object in bones_by_object:
        print(f"Object {object}")

        for bone_idx in bones_by_object[object]:
            print(f"Linked bone number {bone_idx} with dummy {dummies[bone_idx-1]}")
            print(bones_by_object[object][bone_idx][0])
            print(bones_by_object[object][bone_idx][1])
            print(bones_by_object[object][bone_idx][2])
            print(bones_by_object[object][bone_idx][3])
            
    return {'FINISHED'}




if __name__ == "__main__":
    with open(sys.argv[1], 'rb') as file:
        parse_4d_model(sys.argv[1], file)

    # Trigger import action immediately
    # bpy.ops.import_4d.model('INVOKE_DEFAULT')
