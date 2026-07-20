import re
import mathutils
import struct
import zlib
import os
from typing import Self
import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .utility import float_to_str, vertex_to_str
from . import utility
from .model_data_utility import ModelDataUtility

TOKEN_NAME = 1
TOKEN_STRING = 2
TOKEN_INTEGER = 3
TOKEN_GUID = 5
TOKEN_INTEGER_LIST = 6
TOKEN_FLOAT_LIST = 7

TOKEN_OBRACE = 0x0A
TOKEN_CBRACE = 0x0B
TOKEN_OPAREN = 0x0C
TOKEN_CPAREN = 0x0D
TOKEN_OBRACKET = 0x0E
TOKEN_CBRACKET = 0x0F
TOKEN_OANGLE = 0x10
TOKEN_CANGLE = 0x11
TOKEN_DOT = 0x12
TOKEN_COMMA = 0x13
TOKEN_SEMICOLON = 0x14
TOKEN_TEMPLATE = 0x1F
TOKEN_WORD = 0x28
TOKEN_DWORD = 0x29
TOKEN_FLOAT = 0x2A
TOKEN_DOUBLE = 0x2B
TOKEN_CHAR = 0x2C
TOKEN_UCHAR = 0x2D
TOKEN_SWORD = 0x2E
TOKEN_SDWORD = 0x2F
TOKEN_VOID = 0x30
TOKEN_LPSTR = 0x31
TOKEN_UNICODE = 0x32
TOKEN_CSTRING = 0x33
TOKEN_ARRAY = 0x34


class XModelMesh:
    vertices = []
    faces: list[list[int]] = []
    tex_coords = []
    normals = []
    normal_faces = []
    materials = []
    material_face_indexes = []
    material_count = 0

    def __init__(self):
        self.vertices = []
        self.faces = []
        self.tex_coords = []
        self.normals = []
        self.normal_faces = []
        self.materials = []
        self.material_face_indexes = []
        self.material_count = 0


class XModelNode:
    node_name: str | None
    transform_matrix: mathutils.Matrix = mathutils.Matrix.Identity(4)
    mesh: XModelMesh = XModelMesh()
    children: list[Self] = []

    def __init__(self):
        self.node_name: str | None = ""
        self.transform_matrix = mathutils.Matrix.Identity(4)
        self.mesh = XModelMesh()
        self.children = []


class XElement:
    element_type = ""
    data = ""
    children = []
    end_line_num = 0
    name = ""


class XMaterial:
    face_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    power: float = 0.0
    specular_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    emission_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    texture_path: str | None = ""
    name: str | None = ""


def to_XElement(x_model_file_string, start_line_num):
    element_type = ""
    elem_data = ""
    end_index = 0
    children = []
    skip = 0
    element_name = ""
    for line_num in range(len(x_model_file_string))[start_line_num:]:
        if line_num <= skip:
            continue
        line = x_model_file_string[line_num]
        pos = line.find("{")
        if pos != -1 and "}" in line:
            continue

        if "{" in line:
            if element_type == "":
                element_type = re.sub("\t", "", line[0 : line.index("{")])
                element_type = re.sub("^ *", "", element_type)
                if element_type.find(" ") != -1:
                    element_name = element_type[element_type.find(" ") + 1 :]
                    element_type = element_type[0 : element_type.find(" ")]
                    search_result = re.search("[^ ]*", element_name)
                    if search_result:
                        element_name = search_result.group(0)
                if element_type == "":
                    element_type = "empty"
            else:
                x_element = to_XElement(x_model_file_string, line_num)
                children.append(x_element)
                skip = x_element.end_line_num
        else:
            if "}" in line:
                end_index = line_num
                break
            else:
                if len(element_type) > 0:
                    elem_data += line.replace("\r", "")
    result = XElement()
    result.element_type = element_type
    result.data = elem_data
    result.children = children
    result.end_line_num = end_index
    result.name = element_name
    return result


def write_int(f, i):
    f.write(i.to_bytes(4, byteorder="little"))


def write_short(f, i):
    f.write(i.to_bytes(2, byteorder="little"))


def write_float(f, i):
    f.write(struct.pack("<f", float(i)))


def write_shorts(f, shorts):
    for s in shorts:
        write_short(f, s)


def write_str(f, string):
    write_int(f, len(string))
    f.write(string.encode())


def write_guid(f, data1, data2, data3, data4):
    write_int(f, data1)
    write_shorts(f, [data2, data3])
    f.write(data4)


def write_integer_list(f, i_list):
    write_short(f, TOKEN_INTEGER_LIST)
    write_int(f, len(i_list))
    for i in i_list:
        write_int(f, i)


def write_float_list(f, f_list):
    write_short(f, TOKEN_FLOAT_LIST)
    write_int(f, len(f_list))
    for i in f_list:
        write_float(f, i)


class ImportDirectXXFile(bpy.types.Operator, ImportHelper):
    bl_idname = "import.directx_x_for_bve"
    bl_description = "Import from X file (.x)"
    bl_label = "Import DirectX X File"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_options = {"UNDO"}

    filepath: StringProperty(name="input file", subtype="FILE_PATH")

    filename_ext = ".x"

    filter_glob: StringProperty(
        default="*.x",
        options={"HIDDEN"},
    )

    remove_all: BoolProperty(
        name="Remove All Objects and Materials",
        default=True,
    )

    scale: FloatProperty(name="Scale", default=1.0)

    gamma_correction: BoolProperty(
        name="Gamma correction",
        default=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initialize()

    def initialize(self):
        self.is_binary = False
        self.float_size = 32
        self.ret_string = ""
        self.ret_integer = 0
        self.ret_float = 0
        self.ret_integer_list = []
        self.ret_float_list = []
        self.ret_uuid = ""
        self.byte_buffer = utility.ByteBuffer(bytes())
        self.text_content = ""
        self.text_pos = 0
        self.text_brace_count = 0
        self.bin_brace_count = 0
        self.object_index = 0

    def create_obj_from_node(self, matrix: mathutils.Matrix, node: XModelNode):
        if matrix is None:
            matrix = mathutils.Matrix.Identity(4)

        for child in node.children:
            self.create_obj_from_node(matrix @ child.transform_matrix, child)

        mesh = node.mesh

        vertex_index = 0
        mesh_vertexes = []
        mesh_vertexes_redirect = {}
        for vertex in mesh.vertices:
            # DirectX X Y Z
            # Blender X Z Y
            vector = (
                vertex[0] * self.scale,
                vertex[2] * self.scale,
                vertex[1] * self.scale,
            )
            # 重複した座標は1つにまとめる / Combine duplicate coordinates into one
            # リダイレクト先を登録しておく / Register the redirect destination
            if vector in mesh_vertexes:
                mesh_vertexes_redirect[vertex_index] = mesh_vertexes.index(vector)
            else:
                mesh_vertexes_redirect[vertex_index] = len(mesh_vertexes)
                mesh_vertexes.append(vector)
            vertex_index += 1
            if vertex_index == len(mesh.vertices):
                break
        indexes_size = 0
        mesh_faces = []
        mesh_faces_exact = []
        mesh_tex_coord = []
        mesh_material_face_indexes = []
        mesh_materials: list[XMaterial] = []
        for indexes in mesh.faces:
            # Blenderに記録する際に使用する頂点のインデックス / Index of the vertex used when recording in Blender
            indexes.reverse()
            vertexes = []
            for idx in range(len(indexes)):
                if indexes[idx] in mesh_vertexes_redirect:
                    vertexes.append(mesh_vertexes_redirect[indexes[idx]])
                else:
                    vertexes.append(indexes[idx])
            mesh_faces.append(vertexes)
            # Xファイルに記述された実際の使用する頂点のインデックス(UV登録時に使用) / Actual vertex index used in the X file (used when registering UV)
            mesh_faces_exact.append(indexes)
            if len(mesh_faces) == indexes_size:
                break

        for vertex in mesh.tex_coords:
            vertex[1] = -vertex[1] + 1
            mesh_tex_coord.append(vertex)

        for index in mesh.material_face_indexes:
            mesh_material_face_indexes.append(index)

        for material in mesh.materials:
            mesh_materials.append(material)
        material_faces: list[list[int]] = []
        material_count = mesh.material_count
        for i in range(material_count):
            material_faces.append([])

        # マテリアル別に面を整理 / Organize faces by material
        if material_count > 0:
            for i in range(len(mesh_faces)):
                if len(mesh_material_face_indexes) <= i:
                    mesh_material_face_indexes.append(0)
                material_id = mesh_material_face_indexes[i]
                material_faces[material_id].append(i)

        # モデル名を決定 / Determine the model name
        model_name = (
            node.node_name
            if node.node_name is not None and len(node.node_name) != 0
            else os.path.splitext(bpy.path.basename(self.filepath))[0]
        ) + str(self.object_index)
        self.object_index += 1

        # マテリアルごとにオブジェクトを作成 / Create objects for each material
        for j in range(len(material_faces)):
            faces_data = []
            vertexes_data = []
            faces = material_faces[j]
            if len(faces) == 0:
                continue
            # マテリアルの有無 / Presence or absence of materials
            available_material = (
                len(mesh_materials) > mesh_material_face_indexes[faces[0]]
            )
            x_material: XMaterial = mesh_materials[mesh_material_face_indexes[faces[0]]]
            # マテリアルを作成 / Create material
            material_name = model_name + "Material"
            if x_material.name:
                material_name = x_material.name
            material = bpy.data.materials.new(material_name)

            # ブレンドモードの設定 / Setting the blend mode
            material.blend_method = "CLIP"

            # ノードを有効化 / Enable nodes
            material.use_nodes = True
            nodes = material.node_tree.nodes
            # プリンシプルBSDFを取得 / Get the principle BSDF
            principled = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")

            color = (1.0, 1.0, 1.0)
            material.specular_intensity = 0.0
            if available_material:
                color = x_material.face_color
                material.specular_intensity = x_material.power
                material.specular_color = x_material.specular_color
                principled.inputs["Base Color"].default_value = color
                principled.inputs["Alpha"].default_value = x_material.face_color[3]
            material.diffuse_color = color

            # 鏡面反射 / Specular reflection
            principled.inputs["Specular IOR Level"].default_value = x_material.power
            principled.inputs["Specular Tint"].default_value = (
                *x_material.specular_color,
                1.0,
            )
            # 放射を設定 / Set emission
            principled.inputs["Emission Color"].default_value = (
                x_material.emission_color + (1.0,)
            )

            # テクスチャの紐付け / Linking textures
            if x_material.texture_path and x_material.texture_path != "":
                path = "/".join(
                    bpy.path.abspath(self.filepath).split(os.path.sep)[0:-1]
                )
                path = path + "/" + x_material.texture_path
                if os.path.exists(path):
                    x_material.texture_path = path

            if x_material.texture_path and os.path.exists(x_material.texture_path):
                # 画像ノードを作成 / Create image node
                texture = material.node_tree.nodes.new("ShaderNodeTexImage")
                texture.location = (-300, 150)

                # 画像を読み込み / Load image
                texture.image = bpy.data.images.load(filepath=x_material.texture_path)
                texture.image.colorspace_settings.name = "sRGB"
                # ベースカラーとテクスチャのカラーをリンクさせる / Link the base color and the texture color
                material.node_tree.links.new(
                    principled.inputs["Base Color"], texture.outputs["Color"]
                )
                # アルファとテクスチャのアルファをリンクさせる / Link the alpha and the texture alpha
                material.node_tree.links.new(
                    principled.inputs["Alpha"], texture.outputs["Alpha"]
                )
            elif self.gamma_correction:
                # ガンマノードを作成 / Create gamma node
                gamma_node = material.node_tree.nodes.new("ShaderNodeGamma")
                gamma_node.location = (-250, 250)

                gamma_node.inputs["Color"].default_value = color
                gamma_node.inputs["Gamma"].default_value = 2.2
                # ベースカラーとガンマのカラーをリンクさせる / Link the base color and the gamma color
                material.node_tree.links.new(
                    principled.inputs["Base Color"], gamma_node.outputs["Color"]
                )

            # 頂点データと面データを作成 / Create vertex data and face data
            # マテリアルが使う頂点だけを抽出、その頂点のインデックスに合わせて面の頂点のインデックスを変更 /
            #  Extract only the vertices used by the material, and change the vertex indexes of the faces to match the indexes of those vertices
            mesh_indexes = {}
            for i in faces:
                face = mesh_faces[i]
                # faces_data.append(face)
                for k in face:
                    if mesh_vertexes[k] in vertexes_data:
                        mesh_indexes[k] = vertexes_data.index(mesh_vertexes[k])
                    else:
                        mesh_indexes[k] = len(vertexes_data)
                        vertexes_data.append(mesh_vertexes[k])
                count = 0
                face_data = [0] * len(face)
                for k in face:
                    face_data[count] = mesh_indexes[k]
                    count += 1
                faces_data.append(face_data)

            # メッシュを作成 / Create mesh
            mesh = bpy.data.meshes.new("mesh")

            # メッシュに頂点と面のデータを挿入 / Insert vertex and face data into the mesh
            mesh.from_pydata(vertexes_data, [], faces_data)

            # UVレイヤーの作成 / Create UV layer
            mesh.uv_layers.new(name="UVMap")
            uv = mesh.uv_layers["UVMap"]

            # UVデータを頂点と紐付ける / Link UV data to vertices
            count = 0
            for i in faces:
                for k in mesh_faces_exact[i]:
                    uv.data[count].uv = mesh_tex_coord[k]
                    count += 1

            mesh.update()

            # メッシュでオブジェクトを作成 / Create an object with the mesh
            obj = bpy.data.objects.new(model_name, mesh)
            obj.data = mesh
            obj.data.materials.append(material)

            # オブジェクトをシーンに追加 / Add object to scene
            scene = bpy.context.scene
            scene.collection.objects.link(obj)

    def parse_mesh_text(self, mesh: XModelMesh):
        _object_name = self.get_object_name_text()
        vertex_size = self.get_next_int_text()
        for _ in range(vertex_size):
            vertex = [
                self.get_next_float_text(),
                self.get_next_float_text(),
                self.get_next_float_text(),
            ]
            mesh.vertices.append(vertex)
        faces_size = self.get_next_int_text()
        for i in range(faces_size):
            vertex_size = self.get_next_int_text()
            indexes = []
            for _ in range(vertex_size):
                indexes.append(self.get_next_int_text())
            mesh.faces.append(indexes)

        brace_count = self.text_brace_count

        token = self.get_next_token_text()
        while token is not None and self.text_brace_count >= brace_count:
            if brace_count == self.text_brace_count:
                if token == "MeshMaterialList":
                    self.parse_mesh_material_list_text(mesh)
                elif token == "MeshTextureCoords":
                    self.parse_mesh_texture_coords_text(mesh)
            token = self.get_next_token_text()

    def parse_mesh_texture_coords_text(self, mesh: XModelMesh):
        _object_name = self.get_object_name_text()
        vertex_size = self.get_next_int_text()
        for _ in range(vertex_size):
            uv = [self.get_next_float_text(), self.get_next_float_text()]
            mesh.tex_coords.append(uv)

    def parse_mesh_material_list_text(self, mesh: XModelMesh):
        _object_name = self.get_object_name_text()
        mesh.material_count = self.get_next_int_text()
        face_count = self.get_next_int_text()
        for _ in range(face_count):
            mesh.material_face_indexes.append(self.get_next_int_text())

        brace_count = self.text_brace_count
        token = self.get_next_token_text()
        while token is not None and self.text_brace_count >= brace_count:
            if brace_count == self.text_brace_count:
                if token == "Material":
                    self.parse_material_text(mesh)
            token = self.get_next_token_text()

    def parse_material_text(self, mesh: XModelMesh):
        object_name = self.get_object_name_text()
        color = (
            self.get_next_float_text(),
            self.get_next_float_text(),
            self.get_next_float_text(),
            self.get_next_float_text(),
        )
        power = self.get_next_float_text()
        specular_color = (
            self.get_next_float_text(),
            self.get_next_float_text(),
            self.get_next_float_text(),
        )
        self.skip_next_token_text(";")
        emissive_color = (
            self.get_next_float_text(),
            self.get_next_float_text(),
            self.get_next_float_text(),
        )
        material = XMaterial()
        material.face_color = color
        material.power = power
        material.specular_color = specular_color
        material.emission_color = emissive_color
        material.name = object_name

        brace_count = self.text_brace_count
        token = self.get_next_token_text()
        while token is not None and self.text_brace_count >= brace_count:
            if brace_count == self.text_brace_count:
                if token == "TextureFilename":
                    material.texture_path = self.get_next_string_text()
                    self.skip_next_token_text(";")
            token = self.get_next_token_text()
        mesh.materials.append(material)

    def parse_frame_text(self, node: XModelNode):
        child = XModelNode()
        child.node_name = self.get_object_name_text()

        brace_count = self.text_brace_count
        token = self.get_next_token_text()
        while token is not None and self.text_brace_count >= brace_count:
            if brace_count == self.text_brace_count:
                if token == "FrameTransformMatrix":
                    self.skip_until_text("{")
                    matrix = [
                        [
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                        ],
                        [
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                        ],
                        [
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                        ],
                        [
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                            self.get_next_float_text(),
                        ],
                    ]
                    child.transform_matrix = mathutils.Matrix(matrix)
                    self.skip_until_text("}")
                elif token == "Mesh":
                    self.parse_mesh_text(child.mesh)
                elif token == "Frame":
                    c = XModelNode()
                    self.parse_frame_text(c)
                    node.children.append(c)
            token = self.get_next_token_text()
        node.children.append(child)

    def get_next_token_text(self):
        start = False
        ret = ""
        while self.text_pos < len(self.text_content):
            # comment
            if (
                len(self.text_content) + 1 < self.text_pos
                and self.text_content[self.text_pos] == "/"
                and self.text_content[len(self.text_content) + 1] == "/"
                or self.text_content[self.text_pos] == "#"
            ):
                while self.text_pos < len(self.text_content):
                    if (
                        self.text_content[self.text_pos] == "\n"
                        or self.text_content[self.text_pos] == "\r"
                    ):
                        break
                    self.text_pos += 1
            if self.is_ascii(self.text_content[self.text_pos]):
                start = True
                c = self.text_content[self.text_pos]
                if (
                    c == "{"
                    or c == "}"
                    or c == "["
                    or c == "]"
                    or c == ";"
                    or c == ","
                    or c == '"'
                ):
                    if len(ret) == 0:
                        if c == "{":
                            self.text_brace_count += 1
                        elif c == "}":
                            self.text_brace_count -= 1
                        ret += c
                        self.text_pos += 1
                    return ret
                ret += c
            elif start:
                break

            self.text_pos += 1

        if len(ret) == 0:
            return None

        return ret

    def skip_until_text(self, target):
        token = ""
        while True:
            token = self.get_next_token_text()
            if token == target:
                break

    def skip_next_token_text(self, expected):
        token = self.get_next_token_text()
        if token != expected:
            raise Exception(f"Unexpected token: {token}")

    def get_next_int_text(self):
        token = self.get_next_token_text()
        while token == ";" or token == ",":
            token = self.get_next_token_text()

        if token is None:
            raise Exception("Unexpected end of file")

        return int(token)

    def get_next_float_text(self):
        token = self.get_next_token_text()
        while token == ";" or token == ",":
            token = self.get_next_token_text()

        if token is None:
            raise Exception("Unexpected end of file")

        return float(token)

    def get_next_string_text(self):
        self.skip_until_text('"')
        ret = ""
        while self.text_pos < len(self.text_content):
            if self.text_content[self.text_pos] == "\\":
                self.text_pos += 1
            elif self.text_content[self.text_pos] == '"':
                self.text_pos += 1
                break
            else:
                ret += self.text_content[self.text_pos]
            self.text_pos += 1
        if len(ret) == 0:
            return None
        return ret

    def get_object_name_text(self):
        token = self.get_next_token_text()
        if token == "{":
            return None
        self.skip_next_token_text("{")
        return token

    def is_ascii(self, c):
        return (
            ord(c) <= 255
            and ord(c) != ord(" ")
            and ord(c) != ord("\r")
            and ord(c) != ord("\n")
            and ord(c) != ord("\t")
        )

    def parse_token(self):
        token = self.byte_buffer.get_short()
        if token == TOKEN_NAME:
            length = self.byte_buffer.get_int()
            self.ret_string = self.byte_buffer.get_length(length).decode()
        elif token == TOKEN_INTEGER:
            self.ret_integer = self.byte_buffer.get_int()
        elif token == TOKEN_STRING:
            length = self.byte_buffer.get_int()
            self.ret_string = self.byte_buffer.get_length(length).decode()
            self.parse_token()
        elif token == TOKEN_GUID:
            # GUIDは使用しないため無視する / Ignore GUID as it is not used
            self.byte_buffer.get_int()
            self.byte_buffer.get_short()
            self.byte_buffer.get_short()
            self.byte_buffer.get_length(8)
        elif token == TOKEN_INTEGER_LIST:
            length = self.byte_buffer.get_int()
            self.ret_integer_list = [0] * length
            for i in range(length):
                self.ret_integer_list[i] = self.byte_buffer.get_int()
        elif token == TOKEN_FLOAT_LIST:
            length = self.byte_buffer.get_int()
            self.ret_float_list = [0.0] * length
            if self.float_size == 64:
                for i in range(length):
                    self.ret_float_list[i] = self.byte_buffer.get_double()
            else:
                for i in range(length):
                    self.ret_float_list[i] = self.byte_buffer.get_float()
        elif token == TOKEN_TEMPLATE:
            # テンプレートは使用する必要がないため無視する / Ignore templates as they are not needed
            self.parse_token_loop(TOKEN_CBRACE)
        elif token == TOKEN_OBRACE:
            self.bin_brace_count += 1
        elif token == TOKEN_CBRACE:
            self.bin_brace_count -= 1
        return token

    def parse_token_loop(self, token):
        while self.parse_token() != token:
            pass

    def parse_bin(self) -> XModelNode:
        root_node = XModelNode()
        while self.byte_buffer.has_remaining():
            token = self.parse_token()
            if token == TOKEN_NAME:
                if self.ret_string == "Mesh":
                    self.parse_mesh_bin(root_node.mesh)
                elif self.ret_string == "Material":
                    self.parse_material_bin(root_node.mesh)
                elif self.ret_string == "Frame":
                    self.parse_frame_bin(root_node)
        return root_node

    def parse_mesh_bin(self, mesh: XModelMesh):
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        self.parse_token_loop(TOKEN_FLOAT_LIST)
        mesh.vertices = []
        i = 0
        vertex_index = 0
        while vertex_index < self.ret_integer_list[0]:
            vertex = self.ret_float_list[i : i + 3]
            mesh.vertices.append(vertex)
            vertex_index += 1
            i += 3
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        mesh.faces = []
        i = 1
        while i < len(self.ret_integer_list):
            length = self.ret_integer_list[i]
            indexes = self.ret_integer_list[i + 1 : i + 1 + length]
            mesh.faces.append(indexes)
            i += length + 1

        brace_count = self.bin_brace_count
        token = self.parse_token()
        while brace_count <= self.bin_brace_count:
            if brace_count == self.bin_brace_count and token == TOKEN_NAME:
                if self.ret_string == "MeshTextureCoords":
                    self.parse_mesh_texture_coords_bin(mesh)
                elif self.ret_string == "MeshMaterialList":
                    self.parse_mesh_material_list_bin(mesh)
            token = self.parse_token()

    def parse_mesh_texture_coords_bin(self, mesh: XModelMesh):
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        self.parse_token_loop(TOKEN_FLOAT_LIST)
        i = 0
        while i < len(self.ret_float_list):
            vertex = [self.ret_float_list[i], self.ret_float_list[i + 1]]
            mesh.tex_coords.append(vertex)
            i += 2

    def parse_mesh_material_list_bin(self, mesh: XModelMesh):
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        mesh.material_count = self.ret_integer_list[0]
        mesh.material_face_indexes = self.ret_integer_list[
            2 : self.ret_integer_list[1] + 2
        ]
        pos = self.byte_buffer.pos
        while True:
            token = self.parse_token()
            if token == TOKEN_NAME and self.ret_string == "Material":
                self.parse_material_bin(mesh)
            else:
                self.byte_buffer.pos = pos
                break
            pos = self.byte_buffer.pos

    def parse_material_bin(self, mesh: XModelMesh):
        token = self.parse_token()
        material_name = ""
        if token == TOKEN_NAME:
            material_name = self.ret_string
        self.parse_token_loop(TOKEN_FLOAT_LIST)
        material = XMaterial()
        material.name = material_name
        material.face_color = (
            self.ret_float_list[0],
            self.ret_float_list[1],
            self.ret_float_list[2],
            self.ret_float_list[3],
        )
        material.power = self.ret_float_list[4]
        material.specular_color = (
            self.ret_float_list[5],
            self.ret_float_list[6],
            self.ret_float_list[7],
        )
        material.emission_color = (
            self.ret_float_list[8],
            self.ret_float_list[9],
            self.ret_float_list[10],
        )
        token = self.parse_token()
        if token == TOKEN_NAME and self.ret_string == "TextureFilename":
            self.parse_token_loop(TOKEN_STRING)
            material.texture_path = self.ret_string
            self.parse_token_loop(TOKEN_CBRACE)
        if token != TOKEN_CBRACE:
            self.parse_token_loop(TOKEN_CBRACE)
        mesh.materials.append(material)

    def parse_frame_bin(self, node: XModelNode):
        child = XModelNode()
        token = self.parse_token()
        name = ""
        if token == TOKEN_NAME:
            name = self.ret_string
        child.node_name = name
        brace_count = self.bin_brace_count
        token = self.parse_token()
        while brace_count <= self.bin_brace_count:
            if brace_count == self.bin_brace_count and token == TOKEN_NAME:
                if self.ret_string == "FrameTransformMatrix":
                    matrix = [
                        self.ret_float_list[0:4],
                        self.ret_float_list[4:8],
                        self.ret_float_list[8:12],
                        self.ret_float_list[12:16],
                    ]
                    child.transform_matrix = mathutils.Matrix(matrix)
                elif self.ret_string == "Mesh":
                    self.parse_mesh_bin(child.mesh)
                elif self.ret_string == "Frame":
                    c = XModelNode()
                    self.parse_frame_bin(c)
                    child.children.append(c)
        node.children.append(child)

    def execute(self, context):
        # すべてのオブジェクトとマテリアルを削除 / Delete all objects and materials
        if self.remove_all:
            for obj in bpy.context.scene.objects:
                if obj.type == "MESH":
                    bpy.data.objects.remove(obj)
            for material in bpy.data.materials:
                material.user_clear()
                bpy.data.materials.remove(material)

        self.initialize()
        # xファイルを読み込み / Load x file
        with open(self.filepath, "rb") as f:
            header = f.read(16)
            if header[0:4] == b"xof ":
                # フォーマットのチェック
                self.is_compressed = False
                if header[8:12] == b"txt ":
                    self.is_binary = False
                elif header[8:12] == b"bin ":
                    self.is_binary = True
                elif header[8:12] == b"bzip":
                    self.is_binary = True
                    self.is_compressed = True
                self.float_size = int(header[12:16].decode())
            else:
                raise Exception(
                    bpy.app.translations.pgettext("This file is not X file!")
                )

        if self.is_binary:
            # バイナリ / Binary

            # flate圧縮 / Flate compression
            if self.is_compressed:
                with open(self.filepath, "rb") as f:
                    f.read(16)
                    raw_data = f.read()
                    compressed_byte_buffer = utility.ByteBuffer(raw_data)
                    MSZIP_BLOCK = 0x8000
                    MSZIP_MAGIC = int.from_bytes("CK".encode(), byteorder="little")

                    _unzipped_size = compressed_byte_buffer.get_int()

                    self.byte_buffer = utility.ByteBuffer(bytes())
                    while compressed_byte_buffer.has_remaining():
                        _uncompressed_size = compressed_byte_buffer.get_short()
                        block_size = compressed_byte_buffer.get_short()
                        magic = compressed_byte_buffer.get_short()
                        if block_size > MSZIP_BLOCK:
                            raise Exception(
                                bpy.app.translations.pgettext(
                                    "Unexpected compressed block size!"
                                )
                            )
                        if magic != MSZIP_MAGIC:
                            raise Exception(
                                bpy.app.translations.pgettext(
                                    "Unexpected compressed block magic!"
                                )
                            )
                        compressed_data = compressed_byte_buffer.get_length(
                            block_size - 2
                        )
                        self.byte_buffer.append(
                            zlib.decompress(compressed_data, -8, MSZIP_BLOCK)
                        )
            else:
                with open(self.filepath, "rb") as f:
                    f.read(16)
                    data = f.read()
                    self.byte_buffer = utility.ByteBuffer(data)
            root_node = self.parse_bin()
        else:
            # テキスト / Text
            with open(self.filepath) as f:
                x_model_file_string = f.read()
                self.text_content = x_model_file_string

                root_node = XModelNode()

                token = self.get_next_token_text()
                while token is not None:
                    if self.text_brace_count == 0:
                        if token == "template":
                            self.get_next_token_text()
                        elif token == "Mesh":
                            self.parse_mesh_text(root_node.mesh)
                        elif token == "Material":
                            self.parse_material_text(root_node.mesh)
                        elif token == "Frame":
                            self.parse_frame_text(root_node)
                    token = self.get_next_token_text()

        self.create_obj_from_node(mathutils.Matrix.Identity(4), root_node)

        return {"FINISHED"}


# Xファイルに出力 / Export to X file
class ExportDirectXXFile(bpy.types.Operator, ExportHelper):
    bl_idname = "export.directx_x_for_bve"
    bl_description = "Export to X file (.x)"
    bl_label = "Export DirectX X File"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_options = {"UNDO"}

    filepath: StringProperty(name="export file", subtype="FILE_PATH")

    filename_ext = ".x"

    filter_glob: StringProperty(
        default="*.x",
        options={"HIDDEN"},
    )

    scale: FloatProperty(
        name="Scale",
        default=1.0,
    )

    mode: EnumProperty(
        items=[
            ("text", "Text", "Text mode"),
            ("binary", "Binary", "Binary mode"),
            ("binary_zip", "Binary + Compress", "Compressed binary mode"),
        ],
        name="Output mode",
    )

    export_material_name: BoolProperty(
        name="Export material name",
        default=True,
    )

    export_selected_only: BoolProperty(
        name="Export only selected objects",
        default=False,
    )

    export_minimum: BoolProperty(
        name="Export only necessary data",
        default=True,
    )

    gamma_correction: BoolProperty(
        name="Gamma correction",
        default=True,
    )

    use_emissive_power: BoolProperty(
        name="Use emissive power",
        description="Multiply emissive color by emissive power",
        default=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def execute(self, context):
        if not self.filepath.endswith(".x"):
            return {"CANCELLED"}

        # ModelDataUtilityでBlenderのデータを整形 / Format Blender data with ModelDataUtility
        model_data_utility = ModelDataUtility()
        model_data_utility.execute(
            context,
            export_selected_only=self.export_selected_only,
            scale=self.scale,
            gamma_correction=self.gamma_correction,
        )
        vertexes = model_data_utility.vertexes
        normals = model_data_utility.normals
        vertex_use_normal = model_data_utility.vertex_use_normal
        faces = model_data_utility.faces
        x_materials = model_data_utility.x_materials
        faces_use_material = model_data_utility.faces_use_material
        uv_data = model_data_utility.uv_data

        is_binary = False
        if self.mode == "binary":
            is_binary = True
        if self.mode == "binary_zip":
            is_binary = True

        if is_binary:
            with open(self.filepath, mode="wb") as f:
                # テンプレート
                if self.mode == "binary_zip":
                    f.write(b"xof 0302bzip0032")
                    uncompressed_buffer = utility.ByteBuffer(bytes())
                    target = uncompressed_buffer
                else:
                    f.write(b"xof 0302bin 0032")
                    target = f
                    uncompressed_buffer = None
                if not self.export_minimum:
                    # テンプレートデータを書き出す / Write template data
                    write_shorts(target, [TOKEN_TEMPLATE, TOKEN_NAME])
                    write_str(target, "Vector")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0x3D82AB5E,
                        0x62DA,
                        0x11CF,
                        b"\xab\x39\x00\x20\xaf\x71\xe4\x33",
                    )
                    write_shorts(target, [TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "x")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "y")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "z")
                    write_shorts(
                        target,
                        [TOKEN_SEMICOLON, TOKEN_CBRACE, TOKEN_TEMPLATE, TOKEN_NAME],
                    )
                    write_str(target, "MeshFace")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0x3D82AB5F,
                        0x62DA,
                        0x11CF,
                        b"\xab\x39\x00\x20\xaf\x71\xe4\x33",
                    )
                    write_shorts(target, [TOKEN_DWORD, TOKEN_NAME])
                    write_str(target, "nFaceVertexIndices")
                    write_shorts(
                        target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_DWORD, TOKEN_NAME]
                    )
                    write_str(target, "faceVertexIndices")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nFaceVertexIndices")
                    write_shorts(
                        target,
                        [
                            TOKEN_CBRACKET,
                            TOKEN_SEMICOLON,
                            TOKEN_CBRACE,
                            TOKEN_TEMPLATE,
                            TOKEN_NAME,
                        ],
                    )
                    write_str(target, "Mesh")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0x3D82AB44,
                        0x62DA,
                        0x11CF,
                        b"\xab\x39\x00\x20\xaf\x71\xe4\x33",
                    )
                    write_shorts(target, [TOKEN_DWORD, TOKEN_NAME])
                    write_str(target, "nVertices")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_NAME])
                    write_str(target, "Vector")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "vertices")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nVertices")
                    write_shorts(
                        target,
                        [TOKEN_CBRACKET, TOKEN_SEMICOLON, TOKEN_DWORD, TOKEN_NAME],
                    )
                    write_str(target, "nFaces")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_NAME])
                    write_str(target, "MeshFace")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "faces")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nFaces")
                    write_shorts(
                        target,
                        [
                            TOKEN_CBRACKET,
                            TOKEN_SEMICOLON,
                            TOKEN_OBRACKET,
                            TOKEN_DOT,
                            TOKEN_DOT,
                            TOKEN_DOT,
                            TOKEN_CBRACKET,
                            TOKEN_CBRACE,
                            TOKEN_TEMPLATE,
                            TOKEN_NAME,
                        ],
                    )
                    write_str(target, "MeshNormals")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0xF6F23F43,
                        0x7686,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_DWORD, TOKEN_NAME])
                    write_str(target, "nNormals")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_NAME])
                    write_str(target, "Vector")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "normals")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nNormals")
                    write_shorts(
                        target,
                        [TOKEN_CBRACKET, TOKEN_SEMICOLON, TOKEN_DWORD, TOKEN_NAME],
                    )
                    write_str(target, "nFaceNormals")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_NAME])
                    write_str(target, "MeshFace")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "faceNormals")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nFaceNormals")
                    write_shorts(
                        target,
                        [
                            TOKEN_CBRACKET,
                            TOKEN_SEMICOLON,
                            TOKEN_CBRACE,
                            TOKEN_TEMPLATE,
                            TOKEN_NAME,
                        ],
                    )
                    write_str(target, "Coords2d")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0xF6F23F44,
                        0x7686,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "u")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "v")
                    write_shorts(
                        target,
                        [TOKEN_SEMICOLON, TOKEN_CBRACE, TOKEN_TEMPLATE, TOKEN_NAME],
                    )
                    write_str(target, "MeshTextureCoords")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0xF6F23F40,
                        0x7686,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_DWORD, TOKEN_NAME])
                    write_str(target, "nTextureCoords")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_NAME])
                    write_str(target, "Coords2d")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "textureCoords")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nTextureCoords")
                    write_shorts(
                        target,
                        [
                            TOKEN_CBRACKET,
                            TOKEN_SEMICOLON,
                            TOKEN_CBRACE,
                            TOKEN_TEMPLATE,
                            TOKEN_NAME,
                        ],
                    )
                    write_str(target, "ColorRGBA")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0x35FF44E0,
                        0x6C7C,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "red")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "green")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "blue")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "alpha")
                    write_shorts(
                        target,
                        [TOKEN_SEMICOLON, TOKEN_CBRACE, TOKEN_TEMPLATE, TOKEN_NAME],
                    )
                    write_str(target, "ColorRGB")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0xD3E16E81,
                        0x7835,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "red")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "green")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "blue")
                    write_shorts(
                        target,
                        [TOKEN_SEMICOLON, TOKEN_CBRACE, TOKEN_TEMPLATE, TOKEN_NAME],
                    )
                    write_str(target, "Material")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0x3D82AB4D,
                        0x62DA,
                        0x11CF,
                        b"\xab\x39\x00\x20\xaf\x71\xe4\x33",
                    )
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "ColorRGBA")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "faceColor")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_FLOAT, TOKEN_NAME])
                    write_str(target, "power")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_NAME])
                    write_str(target, "ColorRGB")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "specularColor")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_NAME])
                    write_str(target, "ColorRGB")
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "emissiveColor")
                    write_shorts(
                        target,
                        [
                            TOKEN_SEMICOLON,
                            TOKEN_OBRACKET,
                            TOKEN_DOT,
                            TOKEN_DOT,
                            TOKEN_DOT,
                            TOKEN_CBRACKET,
                            TOKEN_CBRACE,
                            TOKEN_TEMPLATE,
                            TOKEN_NAME,
                        ],
                    )
                    write_str(target, "MeshMaterialList")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0xF6F23F42,
                        0x7686,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_DWORD, TOKEN_NAME])
                    write_str(target, "nMaterials")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_DWORD, TOKEN_NAME])
                    write_str(target, "nFaceIndexes")
                    write_shorts(
                        target, [TOKEN_SEMICOLON, TOKEN_ARRAY, TOKEN_DWORD, TOKEN_NAME]
                    )
                    write_str(target, "faceIndexes")
                    write_shorts(target, [TOKEN_OBRACKET, TOKEN_NAME])
                    write_str(target, "nFaceIndexes")
                    write_shorts(
                        target,
                        [TOKEN_CBRACKET, TOKEN_SEMICOLON, TOKEN_OBRACKET, TOKEN_NAME],
                    )
                    write_str(target, "Material")
                    write_shorts(target, [TOKEN_GUID])
                    write_guid(
                        target,
                        0x3D82AB4D,
                        0x62DA,
                        0x11CF,
                        b"\xab\x39\x00\x20\xaf\x71\xe4\x33",
                    )
                    write_shorts(
                        target,
                        [TOKEN_CBRACKET, TOKEN_CBRACE, TOKEN_TEMPLATE, TOKEN_NAME],
                    )
                    write_str(target, "TextureFilename")
                    write_shorts(target, [TOKEN_OBRACE, TOKEN_GUID])
                    write_guid(
                        target,
                        0xA42790E1,
                        0x7810,
                        0x11CF,
                        b"\x8f\x52\x00\x40\x33\x35\x94\xa3",
                    )
                    write_shorts(target, [TOKEN_LPSTR, TOKEN_NAME])
                    write_str(target, "filename")
                    write_shorts(target, [TOKEN_SEMICOLON, TOKEN_CBRACE])
                # メッシュ
                write_shorts(target, [TOKEN_NAME])
                write_str(target, "Mesh")
                write_shorts(target, [TOKEN_OBRACE])
                write_integer_list(target, [len(vertexes)])
                vertex_list = []
                for vertex in vertexes:
                    vertex_list.append(vertex[0])
                    vertex_list.append(vertex[2])
                    vertex_list.append(vertex[1])
                write_float_list(target, vertex_list)
                faces_list = [len(faces)]
                for face in faces:
                    faces_list.append(len(face))
                    for i in face:
                        faces_list.append(i)
                write_integer_list(target, faces_list)
                write_shorts(target, [TOKEN_NAME])
                write_str(target, "MeshNormals")
                write_shorts(target, [TOKEN_OBRACE])
                write_integer_list(target, [len(normals)])
                vertex_list = []
                for vertex in normals:
                    vertex_list.append(vertex[0])
                    vertex_list.append(vertex[2])
                    vertex_list.append(vertex[1])
                write_float_list(target, vertex_list)
                faces_list = [len(vertex_use_normal)]
                for face in vertex_use_normal:
                    faces_list.append(len(face))
                    for i in face:
                        faces_list.append(i)
                write_integer_list(target, faces_list)
                write_shorts(target, [TOKEN_CBRACE, TOKEN_NAME])
                write_str(target, "MeshTextureCoords")
                write_shorts(target, [TOKEN_OBRACE])
                write_integer_list(target, [len(uv_data)])
                vertex_list = []
                for uv in uv_data:
                    vertex_list.append(uv[0])
                    vertex_list.append(-uv[1] + 1)
                write_float_list(target, vertex_list)
                write_shorts(target, [TOKEN_CBRACE, TOKEN_NAME])
                write_str(target, "MeshMaterialList")
                write_shorts(target, [TOKEN_OBRACE])
                index_list = [len(x_materials), len(faces_use_material)]
                index_list[2 : len(faces_use_material) + 2] = faces_use_material
                write_integer_list(target, index_list)
                for x_material in x_materials:
                    write_shorts(target, [TOKEN_NAME])
                    write_str(target, "Material")
                    if self.export_material_name and x_material.name:
                        write_shorts(target, [TOKEN_NAME])
                        write_str(target, x_material.name)
                    write_shorts(target, [TOKEN_OBRACE])
                    color_list = [0.0] * 11
                    color_list[0:4] = x_material.face_color
                    color_list[4] = x_material.power
                    color_list[5:8] = x_material.specular_color[0:3]
                    emissive_color = x_material.emission_color
                    if self.use_emissive_power:
                        emissive_color = x_material.emission_color_calculated
                    color_list[8:11] = emissive_color[0:3]
                    write_float_list(target, color_list)
                    if x_material.texture_path != "":
                        write_shorts(target, [TOKEN_NAME])
                        write_str(target, "TextureFilename")
                        write_shorts(target, [TOKEN_OBRACE, TOKEN_STRING])
                        write_str(target, x_material.texture_path)
                        write_shorts(target, [TOKEN_SEMICOLON, TOKEN_CBRACE])
                    write_shorts(target, [TOKEN_CBRACE])
                write_shorts(target, [TOKEN_CBRACE, TOKEN_CBRACE])
                # flate圧縮 / Flate compression
                if self.mode == "binary_zip" and uncompressed_buffer is not None:
                    f.write(struct.pack("<I", uncompressed_buffer.length() + 16))
                    uncompressed_buffer.pos = 0
                    MSZIP_BLOCK = 0x8000
                    while uncompressed_buffer.has_remaining():
                        length = min(uncompressed_buffer.remaining(), MSZIP_BLOCK)
                        compressed_data = zlib.compress(
                            uncompressed_buffer.get_length(length)
                        )[2:]
                        f.write(struct.pack("<H", length))
                        f.write(struct.pack("<H", len(compressed_data) + 2))
                        f.write("CK".encode())
                        f.write(compressed_data)
        else:
            x_file_content = "xof 0302txt 0032\n"

            if not self.export_minimum:
                # テンプレートデータを書き出す / Write template data
                x_file_content += """
template Vector {
 <3d82ab5e-62da-11cf-ab39-0020af71e433>
 FLOAT x;
 FLOAT y;
 FLOAT z;
}

template MeshFace {
 <3d82ab5f-62da-11cf-ab39-0020af71e433>
 DWORD nFaceVertexIndices;
 array DWORD faceVertexIndices[nFaceVertexIndices];
}

template Mesh {
 <3d82ab44-62da-11cf-ab39-0020af71e433>
 DWORD nVertices;
 array Vector vertices[nVertices];
 DWORD nFaces;
 array MeshFace faces[nFaces];
 [...]
}

template MeshNormals {
 <f6f23f43-7686-11cf-8f52-0040333594a3>
 DWORD nNormals;
 array Vector normals[nNormals];
 DWORD nFaceNormals;
 array MeshFace faceNormals[nFaceNormals];
}

template Coords2d {
 <f6f23f44-7686-11cf-8f52-0040333594a3>
 FLOAT u;
 FLOAT v;
}

template MeshTextureCoords {
 <f6f23f40-7686-11cf-8f52-0040333594a3>
 DWORD nTextureCoords;
 array Coords2d textureCoords[nTextureCoords];
}

template ColorRGBA {
 <35ff44e0-6c7c-11cf-8f52-0040333594a3>
 FLOAT red;
 FLOAT green;
 FLOAT blue;
 FLOAT alpha;
}

template ColorRGB {
 <d3e16e81-7835-11cf-8f52-0040333594a3>
 FLOAT red;
 FLOAT green;
 FLOAT blue;
}

template Material {
 <3d82ab4d-62da-11cf-ab39-0020af71e433>
 ColorRGBA faceColor;
 FLOAT power;
 ColorRGB specularColor;
 ColorRGB emissiveColor;
 [...]
}

template MeshMaterialList {
 <f6f23f42-7686-11cf-8f52-0040333594a3>
 DWORD nMaterials;
 DWORD nFaceIndexes;
 array DWORD faceIndexes[nFaceIndexes];
 [Material <3d82ab4d-62da-11cf-ab39-0020af71e433>]
}

template TextureFilename {
 <a42790e1-7810-11cf-8f52-0040333594a3>
 STRING filename;
}

"""

            x_file_content += "Mesh {\n"
            x_file_content += " " + str(len(vertexes)) + ";\n"

            # 頂点データ / Vertex data
            for vertex in vertexes:
                x_file_content += " " + vertex_to_str(vertex) + ";,\n"
            x_file_content = x_file_content[0:-2] + ";\n"

            # 面データ / Face data
            x_file_content += " " + str(len(faces)) + ";\n"
            for face in faces:
                x_file_content += (
                    " "
                    + str(len(face))
                    + ";"
                    + str(face).replace(" ", "")[1:-1]
                    + ";,\n"
                )
            x_file_content = x_file_content[0:-2] + ";\n\n"

            # マテリアルデータ / Material data
            x_file_content += " MeshMaterialList {\n"
            x_file_content += "  " + str(len(x_materials)) + ";\n"
            x_file_content += "  " + str(len(faces_use_material)) + ";\n"
            for material_index in faces_use_material:
                x_file_content += "  " + str(material_index) + ",\n"
            x_file_content = x_file_content[0:-2] + ";\n\n"

            for x_material in x_materials:
                if self.export_material_name and x_material.name:
                    x_file_content += "  Material " + x_material.name + " {\n"
                else:
                    x_file_content += "  Material {\n"
                x_file_content += (
                    "   "
                    + float_to_str(x_material.face_color[0])
                    + ";"
                    + float_to_str(x_material.face_color[1])
                    + ";"
                    + float_to_str(x_material.face_color[2])
                    + ";"
                    + float_to_str(x_material.face_color[3])
                    + ";;\n"
                )
                x_file_content += "   " + float_to_str(x_material.power) + ";\n"
                x_file_content += (
                    "   "
                    + float_to_str(x_material.specular_color[0])
                    + ";"
                    + float_to_str(x_material.specular_color[1])
                    + ";"
                    + float_to_str(x_material.specular_color[2])
                    + ";;\n"
                )
                emissive_color = x_material.emission_color
                if self.use_emissive_power:
                    emissive_color = x_material.emission_color_calculated
                x_file_content += (
                    "   "
                    + float_to_str(emissive_color[0])
                    + ";"
                    + float_to_str(emissive_color[1])
                    + ";"
                    + float_to_str(emissive_color[2])
                    + ";;\n"
                )
                if x_material.texture_path != "":
                    x_file_content += "\n   TextureFilename {\n"
                    x_file_content += '    "' + x_material.texture_path + '";\n'
                    x_file_content += "   }\n"
                x_file_content += "  }\n\n"
            x_file_content = x_file_content[0:-1]
            x_file_content += " }\n\n"

            # 法線データ / Normal data
            x_file_content += " MeshNormals {\n"
            x_file_content += "  " + str(len(normals)) + ";\n"
            for normal in normals:
                x_file_content += "  " + vertex_to_str(normal) + ";,\n"
            x_file_content = x_file_content[0:-2] + ";\n"
            x_file_content += "  " + str(len(vertex_use_normal)) + ";\n"
            for vertex in vertex_use_normal:
                x_file_content += (
                    "  "
                    + str(len(vertex))
                    + ";"
                    + str(vertex).replace(" ", "")[1:-1]
                    + ";,\n"
                )
            x_file_content = x_file_content[0:-2] + ";\n"
            x_file_content += " }\n\n"

            # UVデータ / UV data
            x_file_content += " MeshTextureCoords {\n"
            x_file_content += "  " + str(len(uv_data)) + ";\n"
            for vertex in uv_data:
                x_file_content += (
                    "  "
                    + float_to_str(vertex[0])
                    + ";"
                    + float_to_str(-vertex[1] + 1)
                    + ";,\n"
                )
            x_file_content = x_file_content[0:-2] + ";\n"
            x_file_content += " }\n"
            x_file_content += "}\n"

            with open(self.filepath, mode="w") as f:
                f.write(x_file_content)

        return {"FINISHED"}
