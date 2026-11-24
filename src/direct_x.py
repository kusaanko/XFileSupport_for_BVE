import re
import mathutils
import struct
import time
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

# パフォーマンス用の定数 / Constants for tokenizing performance
_ASCII_SKIP_CHARS = frozenset((" ", "\r", "\n", "\t"))
_SPECIAL_CHARS = frozenset(("{", "}", "[", "]", ";", ",", '"'))

# テキストXファイル用の高速トークナイザ / Fast tokenizer for text X files
# コメント・空白・特殊文字・単語をC実装の正規表現エンジンでまとめて切り出す /
#  Match comments, whitespace, special chars and words at once with the C regex engine
_TOKEN_RE = re.compile(
    r"#[^\r\n]*"  # コメント / comment
    r"|[\s\u0100-\U0010ffff]+"  # 空白と非ASCII文字 / whitespace and non-ASCII chars
    r"|[{}\[\];,\"]"  # 特殊文字 / special chars
    r"|[^{}\[\];,\"\s\u0100-\U0010ffff]+"  # 単語 / word
)

# 数値の一括読み込み用 / For reading numbers in bulk
# 数値と区切り文字が途切れる位置を探す / Find where numbers and separators end
_RUN_END_RE = re.compile(r"[^0-9eE+\-.,;\s]")
_NUMBER_TRANS = str.maketrans({";": " ", ",": " "})


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


class TextXParser:
    """テキストXファイルのパーサ / Parser for text X files.

    bpy.types.Operator は属性アクセスが非常に遅いため、パース状態は
    プレーンな Python オブジェクトで保持する /
    Attribute access on bpy.types.Operator is very slow, so the parse state is
    kept in a plain Python object.
    """

    def __init__(self, content: str):
        self.content = content
        self.pos = 0
        self.brace_count = 0

    def parse(self) -> XModelNode:
        root_node = XModelNode()
        token = self.get_next_token()
        while token is not None:
            if self.brace_count == 0:
                if token == "template":
                    # テンプレート本体は使わないので丸ごと飛ばす /
                    #  The template body is unused, so skip it entirely
                    brace_index = self.content.find("{", self.pos)
                    if brace_index != -1:
                        self.pos = brace_index
                        self.skip_block()
                elif token == "Mesh":
                    self.parse_mesh(root_node.mesh)
                elif token == "Material":
                    self.parse_material(root_node.mesh)
                elif token == "Frame":
                    self.parse_frame(root_node)
                elif self.skip_unknown_block(token):
                    pass
            token = self.get_next_token()
        return root_node

    def get_next_token(self):
        # 正規表現でトークンを一括抽出する / Extract tokens in bulk with regex
        content = self.content
        length = len(content)
        pos = self.pos
        while pos < length:
            match = _TOKEN_RE.match(content, pos)
            if match is None:
                self.pos = length
                return None
            token = match.group(0)
            pos = match.end()
            first = token[0]
            # コメントと空白は読み飛ばす / Skip comments and whitespace
            if first == "#" or first in _ASCII_SKIP_CHARS or ord(first) > 255:
                continue
            self.pos = pos
            if first in _SPECIAL_CHARS:
                if first == "{":
                    self.brace_count += 1
                elif first == "}":
                    self.brace_count -= 1
            return token
        self.pos = pos
        return None

    def skip_until(self, target):
        while self.get_next_token() != target:
            pass

    def skip_next_token(self, expected):
        token = self.get_next_token()
        if token != expected:
            raise Exception(f"Unexpected token: {token}")

    def get_next_int(self):
        token = self.get_next_token()
        while token == ";" or token == ",":
            token = self.get_next_token()
        if token is None:
            raise Exception("Unexpected end of file")
        return int(token)

    def get_next_float(self):
        token = self.get_next_token()
        while token == ";" or token == ",":
            token = self.get_next_token()
        if token is None:
            raise Exception("Unexpected end of file")
        return float(token)

    def next_is_open_brace(self):
        # 次のトークンが '{' かどうかを空白だけ読み飛ばして判定する /
        #  Check whether the next token is '{' while skipping only whitespace
        content = self.content
        length = len(content)
        pos = self.pos
        while pos < length and content[pos].isspace():
            pos += 1
        return pos < length and content[pos] == "{"

    def skip_block(self):
        # ブロックを波括弧の対応を数えながら一括で読み飛ばす /
        #  Skip a block in bulk by counting matching braces
        content = self.content
        length = len(content)
        open_index = content.find("{", self.pos)
        if open_index == -1:
            self.pos = length
            return
        depth = 0
        index = open_index
        while True:
            open_index = content.find("{", index)
            close_index = content.find("}", index)
            if close_index == -1:
                self.pos = length
                return
            if open_index != -1 and open_index < close_index:
                depth += 1
                index = open_index + 1
            else:
                depth -= 1
                index = close_index + 1
                if depth == 0:
                    break
        self.pos = index

    def skip_unknown_block(self, token) -> bool:
        # 認識しないブロックは中身を読まずに飛ばす / Skip unknown blocks without reading them
        if token in _SPECIAL_CHARS:
            return False
        if self.next_is_open_brace():
            self.skip_block()
            return True
        return False

    def read_number_run(self):
        # 数値と区切り文字だけが続く範囲を一括で読み取る /
        #  Read a contiguous region of numbers and separators in bulk
        content = self.content
        match = _RUN_END_RE.search(content, self.pos)
        if match is None:
            end = len(content)
        else:
            end = match.start()
        segment = content[self.pos : end]
        self.pos = end
        if not segment:
            return []
        return list(map(float, segment.translate(_NUMBER_TRANS).split()))

    def get_next_string(self):
        self.skip_until('"')
        content = self.content
        length = len(content)
        pos = self.pos
        start = pos
        chunks = []
        while pos < length:
            char = content[pos]
            if char == "\\":
                pos += 2
                continue
            if char == '"':
                chunks.append(content[start:pos])
                pos += 1
                break
            pos += 1
        self.pos = pos
        ret = "".join(chunks)
        if len(ret) == 0:
            return None
        return ret

    def get_object_name(self):
        token = self.get_next_token()
        if token == "{":
            return None
        self.skip_next_token("{")
        return token

    def parse_mesh(self, mesh: XModelMesh):
        self.get_object_name()
        values = self.read_number_run()
        if not values:
            raise Exception("Unexpected end of file")
        index = 0
        vertex_size = int(values[index])
        index += 1
        vertex_end = index + vertex_size * 3
        mesh.vertices.extend(
            [values[i : i + 3] for i in range(index, vertex_end, 3)]
        )
        index = vertex_end
        faces_size = int(values[index])
        index += 1
        for _ in range(faces_size):
            length = int(values[index])
            index += 1
            mesh.faces.append([int(value) for value in values[index : index + length]])
            index += length

        brace_count = self.brace_count
        token = self.get_next_token()
        while token is not None and self.brace_count >= brace_count:
            if brace_count == self.brace_count:
                if token == "MeshMaterialList":
                    self.parse_mesh_material_list(mesh)
                elif token == "MeshTextureCoords":
                    self.parse_mesh_texture_coords(mesh)
                elif token == "MeshNormals":
                    self.parse_mesh_normals(mesh)
                elif self.skip_unknown_block(token):
                    pass
            token = self.get_next_token()

    def parse_mesh_normals(self, mesh: XModelMesh):
        self.get_object_name()
        values = self.read_number_run()
        if not values:
            raise Exception("Unexpected end of file")
        index = 0
        normal_size = int(values[index])
        index += 1
        normal_end = index + normal_size * 3
        mesh.normals.extend(
            [values[i : i + 3] for i in range(index, normal_end, 3)]
        )
        index = normal_end
        face_size = int(values[index])
        index += 1
        for _ in range(face_size):
            normal_face_size = int(values[index])
            index += 1
            mesh.normal_faces.append(
                [int(value) for value in values[index : index + normal_face_size]]
            )
            index += normal_face_size

    def parse_mesh_texture_coords(self, mesh: XModelMesh):
        self.get_object_name()
        values = self.read_number_run()
        if not values:
            raise Exception("Unexpected end of file")
        vertex_size = int(values[0])
        index = 1
        end = index + vertex_size * 2
        mesh.tex_coords.extend(
            [values[i : i + 2] for i in range(index, end, 2)]
        )

    def parse_mesh_material_list(self, mesh: XModelMesh):
        self.get_object_name()
        values = self.read_number_run()
        if len(values) < 2:
            raise Exception("Unexpected end of file")
        mesh.material_count = int(values[0])
        face_count = int(values[1])
        mesh.material_face_indexes.extend(
            int(value) for value in values[2 : 2 + face_count]
        )

        brace_count = self.brace_count
        token = self.get_next_token()
        while token is not None and self.brace_count >= brace_count:
            if brace_count == self.brace_count:
                if token == "Material":
                    self.parse_material(mesh)
                elif self.skip_unknown_block(token):
                    pass
            token = self.get_next_token()

    def parse_material(self, mesh: XModelMesh):
        object_name = self.get_object_name()
        color = (
            self.get_next_float(),
            self.get_next_float(),
            self.get_next_float(),
            self.get_next_float(),
        )
        power = self.get_next_float()
        specular_color = (
            self.get_next_float(),
            self.get_next_float(),
            self.get_next_float(),
        )
        self.skip_next_token(";")
        emissive_color = (
            self.get_next_float(),
            self.get_next_float(),
            self.get_next_float(),
        )
        material = XMaterial()
        material.face_color = color
        material.power = power
        material.specular_color = specular_color
        material.emission_color = emissive_color
        material.name = object_name

        brace_count = self.brace_count
        token = self.get_next_token()
        while token is not None and self.brace_count >= brace_count:
            if brace_count == self.brace_count:
                if token == "TextureFilename":
                    material.texture_path = self.get_next_string()
                    self.skip_next_token(";")
                elif self.skip_unknown_block(token):
                    pass
            token = self.get_next_token()
        mesh.materials.append(material)

    def parse_frame(self, node: XModelNode):
        child = XModelNode()
        child.node_name = self.get_object_name()

        brace_count = self.brace_count
        token = self.get_next_token()
        while token is not None and self.brace_count >= brace_count:
            if brace_count == self.brace_count:
                if token == "FrameTransformMatrix":
                    self.skip_until("{")
                    matrix = [
                        [
                            self.get_next_float(),
                            self.get_next_float(),
                            self.get_next_float(),
                            self.get_next_float(),
                        ]
                        for _ in range(4)
                    ]
                    child.transform_matrix = mathutils.Matrix(matrix)
                    self.skip_until("}")
                elif token == "Mesh":
                    self.parse_mesh(child.mesh)
                elif token == "Frame":
                    c = XModelNode()
                    self.parse_frame(c)
                    node.children.append(c)
                elif self.skip_unknown_block(token):
                    pass
            token = self.get_next_token()
        node.children.append(child)


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
    # 一括で書き込む / Write in bulk
    f.write(struct.pack("<%dH" % len(shorts), *shorts))


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
    # 一括で書き込む / Write in bulk
    f.write(struct.pack("<%di" % len(i_list), *i_list))


def write_float_list(f, f_list):
    write_short(f, TOKEN_FLOAT_LIST)
    write_int(f, len(f_list))
    # 一括で書き込む / Write in bulk
    f.write(struct.pack("<%df" % len(f_list), *(float(i) for i in f_list)))


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
        self.bin_brace_count = 0
        self.object_index = 0
        # 名前でマテリアルを参照できるようにする / Allow referencing materials by name
        self.materials_by_name: dict[str, XMaterial] = {}

    def create_obj_from_node(self, matrix: mathutils.Matrix, node: XModelNode):
        if matrix is None:
            matrix = mathutils.Matrix.Identity(4)
        # プロパティアクセスは高コストなのでローカルにキャッシュ /
        #  Property access is expensive, so cache it locally
        scale = self.scale

        for child in node.children:
            self.create_obj_from_node(matrix @ child.transform_matrix, child)

        mesh = node.mesh

        vertex_index = 0
        mesh_vertexes = []
        # 辞書で重複判定を行いO(n^2)を回避 / Use a dict to avoid O(n^2) duplicate search
        vertex_redirect_map = {}
        # 元の頂点インデックス -> 統合後のインデックス / Original vertex index -> merged index
        mesh_vertexes_redirect = []
        redirect_append = mesh_vertexes_redirect.append
        for vertex in mesh.vertices:
            # DirectX X Y Z
            # Blender X Z Y
            vector = (
                vertex[0] * scale,
                vertex[2] * scale,
                vertex[1] * scale,
            )
            # 重複した座標は1つにまとめる / Combine duplicate coordinates into one
            redirect = vertex_redirect_map.get(vector)
            if redirect is None:
                redirect = len(mesh_vertexes)
                vertex_redirect_map[vector] = redirect
                mesh_vertexes.append(vector)
            redirect_append(redirect)
        mesh_faces = []
        mesh_faces_exact = []
        mesh_normal_faces = []
        mesh_tex_coord = []
        mesh_material_face_indexes = []
        mesh_materials: list[XMaterial] = []
        has_normals = len(mesh.normals) > 0 and len(mesh.normal_faces) >= len(mesh.faces)
        normal_sign = -1.0 if scale < 0 else 1.0
        mesh_normals = [
            (normal[0] * normal_sign, normal[2] * normal_sign, normal[1] * normal_sign)
            for normal in mesh.normals
        ]
        for face_index, indexes in enumerate(mesh.faces):
            # Blenderに記録する際に使用する頂点のインデックス / Index of the vertex used when recording in Blender
            indexes.reverse()
            mesh_faces.append([mesh_vertexes_redirect[idx] for idx in indexes])
            # Xファイルに記述された実際の使用する頂点のインデックス(UV登録時に使用) / Actual vertex index used in the X file (used when registering UV)
            mesh_faces_exact.append(indexes)
            if has_normals:
                # 面の頂点順に合わせて法線のインデックスも反転する /
                #  Reverse the normal indices to match the face vertex order
                normal_indexes = mesh.normal_faces[face_index]
                normal_indexes.reverse()
                mesh_normal_faces.append(normal_indexes)

        for vertex in mesh.tex_coords:
            vertex[1] = -vertex[1] + 1
            mesh_tex_coord.append(vertex)

        mesh_material_face_indexes.extend(mesh.material_face_indexes)

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

        # 単一マテリアルなら全頂点をそのまま使えるので変換を省略する /
        #  With a single material all vertices can be used as-is, so skip the remap
        single_material = material_count <= 1
        uv_flat_all = None
        normals_flat_all = None
        if single_material:
            uv_flat_all = [
                value
                for face in mesh_faces_exact
                for k in face
                for value in mesh_tex_coord[k]
            ]
            if has_normals:
                normals_flat_all = [
                    value
                    for normal_face in mesh_normal_faces
                    for k in normal_face
                    for value in mesh_normals[k]
                ]

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
            if single_material:
                vertexes_data = mesh_vertexes
                faces_data = mesh_faces
                uv_flat = uv_flat_all
                normals_flat = normals_flat_all if normals_flat_all is not None else []
            else:
                vertexes_data = []
                # 辞書で重複判定を行いO(n^2)を回避 / Use a dict to avoid O(n^2) duplicate search
                vertexes_data_map = {}
                uv_flat = []
                normals_flat = []
                for i in faces:
                    face = mesh_faces[i]
                    exact_face = mesh_faces_exact[i]
                    normal_face = mesh_normal_faces[i] if has_normals else None
                    face_data = []
                    for corner, k in enumerate(face):
                        index = vertexes_data_map.get(k)
                        if index is None:
                            index = len(vertexes_data)
                            vertexes_data_map[k] = index
                            vertexes_data.append(mesh_vertexes[k])
                        face_data.append(index)
                        uv_flat.extend(mesh_tex_coord[exact_face[corner]])
                        if normal_face is not None:
                            normals_flat.extend(mesh_normals[normal_face[corner]])
                    faces_data.append(face_data)

            # メッシュを作成 / Create mesh
            mesh = bpy.data.meshes.new("mesh")

            # メッシュに頂点・面・UVを一括で挿入 / Insert vertices, faces and UVs in bulk
            vertex_count = len(vertexes_data)
            mesh.vertices.add(vertex_count)
            mesh.vertices.foreach_set(
                "co", [value for vertex in vertexes_data for value in vertex]
            )

            loop_count = sum(len(face) for face in faces_data)
            mesh.loops.add(loop_count)
            mesh.loops.foreach_set(
                "vertex_index", [index for face in faces_data for index in face]
            )

            mesh.polygons.add(len(faces_data))
            loop_starts = []
            loop_totals = []
            loop_start = 0
            for face in faces_data:
                loop_starts.append(loop_start)
                loop_totals.append(len(face))
                loop_start += len(face)
            mesh.polygons.foreach_set("loop_start", loop_starts)
            mesh.polygons.foreach_set("loop_total", loop_totals)

            # UVレイヤーの作成 / Create UV layer
            uv = mesh.uv_layers.new(name="UVMap")
            uv.data.foreach_set("uv", uv_flat)

            mesh.update(calc_edges=True)

            # 法線をカスタム法線として適用 / Apply normals as custom split normals
            if len(normals_flat) == loop_count * 3:
                mesh.normals_split_custom_set(
                    [
                        normals_flat[i : i + 3]
                        for i in range(0, len(normals_flat), 3)
                    ]
                )

            # メッシュでオブジェクトを作成 / Create an object with the mesh
            obj = bpy.data.objects.new(model_name, mesh)
            obj.data = mesh
            obj.data.materials.append(material)

            # オブジェクトをシーンに追加 / Add object to scene
            scene = bpy.context.scene
            scene.collection.objects.link(obj)

    def is_ascii(self, c):
        return ord(c) <= 255 and c not in _ASCII_SKIP_CHARS

    def parse_token(self):
        # limit to the current mesh brace depth
        if self.bin_brace_count < 0:
            raise utility.ByteBufferError("Unexpected end of file")
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
            # 一括でunpackする / Unpack in bulk
            self.ret_integer_list = list(self.byte_buffer.get_int_list(length))
        elif token == TOKEN_FLOAT_LIST:
            length = self.byte_buffer.get_int()
            # 一括でunpackする / Unpack in bulk
            if self.float_size == 64:
                self.ret_float_list = list(
                    self.byte_buffer.get_float_list(length, 8)
                )
            else:
                self.ret_float_list = list(
                    self.byte_buffer.get_float_list(length, 4)
                )
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
        vertex_count = self.ret_integer_list[0]
        floats = self.ret_float_list
        # スライスで一括変換 / Convert in bulk with slices
        mesh.vertices = [floats[i : i + 3] for i in range(0, vertex_count * 3, 3)]
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        mesh.faces = []
        indexes = self.ret_integer_list
        i = 1
        while i < len(indexes):
            length = indexes[i]
            mesh.faces.append(indexes[i + 1 : i + 1 + length])
            i += length + 1

        token = self.parse_token()
        depth = self.bin_brace_count          # mesh's own brace depth
        while self.bin_brace_count >= depth:
            if self.bin_brace_count == depth and token == TOKEN_NAME:
                if self.ret_string == "MeshTextureCoords":
                    self.parse_mesh_texture_coords_bin(mesh)
                elif self.ret_string == "MeshMaterialList":
                    self.parse_mesh_material_list_bin(mesh)
                elif self.ret_string == "MeshNormals":
                    self.parse_mesh_normals_bin(mesh)
            token = self.parse_token()

    def parse_mesh_normals_bin(self, mesh: XModelMesh):
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        self.parse_token_loop(TOKEN_FLOAT_LIST)
        normal_count = self.ret_integer_list[0]
        floats = self.ret_float_list
        mesh.normals = [floats[i : i + 3] for i in range(0, normal_count * 3, 3)]
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        mesh.normal_faces = []
        indexes = self.ret_integer_list
        i = 1
        while i < len(indexes):
            length = indexes[i]
            mesh.normal_faces.append(indexes[i + 1 : i + 1 + length])
            i += length + 1

    def parse_mesh_texture_coords_bin(self, mesh: XModelMesh):
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        self.parse_token_loop(TOKEN_FLOAT_LIST)
        floats = self.ret_float_list
        # スライスで一括変換 / Convert in bulk with slices
        if len(floats) % 2 != 0:
            raise Exception("Invalid texture coordinate count")
        mesh.tex_coords = [floats[i : i + 2] for i in range(0, len(floats), 2)]

    def skip_to_depth(self, depth):
        while self.bin_brace_count > depth:
            self.parse_token()

    def parse_mesh_material_list_bin(self, mesh: XModelMesh):
        self.parse_token_loop(TOKEN_INTEGER_LIST)
        mesh.material_count = self.ret_integer_list[0]
        mesh.material_face_indexes = self.ret_integer_list[
            2 : self.ret_integer_list[1] + 2
        ]
        depth = self.bin_brace_count          # material list's own brace depth
        token = self.parse_token()
        while self.bin_brace_count >= depth:
            if token == TOKEN_OBRACE and self.bin_brace_count == depth + 1:
                # 参照用の "{ Name }" ブロック / Reference block "{ Name }"
                reference = self.parse_token()
                if reference == TOKEN_NAME:
                    self.parse_token_loop(TOKEN_CBRACE)
                    material = self.materials_by_name.get(self.ret_string)
                    if material is not None:
                        mesh.materials.append(material)
                else:
                    # 不明なブロックは閉じ括弧まで読み飛ばす / Skip unknown block
                    self.skip_to_depth(self.bin_brace_count - 1)
            elif self.bin_brace_count == depth and token == TOKEN_NAME:
                if self.ret_string == "Material":
                    self.parse_material_bin(mesh)
            token = self.parse_token()

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
        if material.name:
            self.materials_by_name[material.name] = material

    def parse_frame_bin(self, node: XModelNode):
        child = XModelNode()
        token = self.parse_token()
        name = ""
        if token == TOKEN_NAME:
            name = self.ret_string
        child.node_name = name
        token = self.parse_token()          # OBRACE of the frame
        depth = self.bin_brace_count        # frame's own brace depth
        token = self.parse_token()
        while self.bin_brace_count >= depth:
            if self.bin_brace_count == depth and token == TOKEN_NAME:
                if self.ret_string == "FrameTransformMatrix":
                    self.parse_token_loop(TOKEN_FLOAT_LIST)
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
            token = self.parse_token()
        node.children.append(child)

    def execute(self, context):
        # 処理時間の記録 / Timing log
        t_start = time.perf_counter()

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
            t_parse_end = time.perf_counter()
        else:
            # テキスト / Text
            with open(self.filepath) as f:
                x_model_file_string = f.read()
            root_node = TextXParser(x_model_file_string).parse()
            t_parse_end = time.perf_counter()

        print(
            f"[X import] {os.path.basename(self.filepath)}: "
            f"read+parse {t_parse_end - t_start:.3f}s "
            f"({'compressed' if self.is_compressed else 'binary' if self.is_binary else 'text'})"
        )
        mesh = root_node.mesh
        print(
            f"[X import] data: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces, "
            f"{len(mesh.tex_coords)} uvs, {len(mesh.materials)} materials"
        )
        self.create_obj_from_node(mathutils.Matrix.Identity(4), root_node)
        print(
            f"[X import] create objects: {time.perf_counter() - t_parse_end:.3f}s"
            f" (total {time.perf_counter() - t_start:.3f}s)"
        )

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

        # 処理時間の記録 / Timing log
        t_total = time.perf_counter()
        t_start = t_total

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

        def print_timing(step):
            nonlocal t_start
            now = time.perf_counter()
            print(f"[X export] {step}: {now - t_start:.3f}s")
            t_start = now

        print(
            f"[X export] data: {len(vertexes)} vertices, {len(faces)} faces, "
            f"{len(normals)} normals, {len(uv_data)} uvs, {len(x_materials)} materials"
        )
        print_timing("prepare")

        is_binary = False
        if self.mode == "binary":
            is_binary = True
        if self.mode == "binary_zip":
            is_binary = True

        if is_binary:
            with open(self.filepath, mode="wb") as f:
                # テンプレート
                # すべてメモリにバッファリングし、最後に一括で書き込む /
                #  Buffer everything in memory and write it in bulk at the end
                if self.mode == "binary_zip":
                    f.write(b"xof 0302bzip0032")
                else:
                    f.write(b"xof 0302bin 0032")
                target = utility.ByteBuffer(bytes())
                uncompressed_buffer = target if self.mode == "binary_zip" else None
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
                print_timing("build binary buffer")
                # flate圧縮 / Flate compression
                if self.mode == "binary_zip" and uncompressed_buffer is not None:
                    data = uncompressed_buffer.array
                    f.write(struct.pack("<I", len(data) + 16))
                    MSZIP_BLOCK = 0x8000
                    for offset in range(0, len(data), MSZIP_BLOCK):
                        block = data[offset : offset + MSZIP_BLOCK]
                        compressed_data = zlib.compress(block)[2:]
                        f.write(struct.pack("<HH", len(block), len(compressed_data) + 2))
                        f.write(b"CK")
                        f.write(compressed_data)
                else:
                    # 一括で書き込む / Write in bulk
                    f.write(target.array)
                print_timing("write file")
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

            # 各セクションは「ヘッダ + カンマ区切りの行 + 最後の要素」で構成する /
            #  Each section is "header + comma-separated lines + final element"
            def append_list(lines, prefix, last_line=None):
                nonlocal x_file_content
                if not lines:
                    return
                x_file_content += prefix + str(len(lines)) + ";\n"
                if last_line is None:
                    lines[-1] = lines[-1][:-2] + ";\n"
                else:
                    lines[-1] = last_line
                x_file_content += "".join(lines)

            # 頂点データ / Vertex data
            append_list([" " + vertex_to_str(vertex) + ";,\n" for vertex in vertexes], " ")
            print_timing("vertices")

            # 面データ / Face data
            append_list(
                [
                    " " + str(len(face)) + ";" + str(face).replace(" ", "")[1:-1] + ";,\n"
                    for face in faces
                ],
                " ",
            )
            x_file_content += "\n"
            print_timing("faces")

            # マテリアルデータ / Material data
            x_file_content += " MeshMaterialList {\n"
            x_file_content += "  " + str(len(x_materials)) + ";\n"
            # 面が1つもない場合、リストは書き出さない / Don't write the list when there are no faces
            if faces_use_material:
                append_list(
                    ["  " + str(material_index) + ",\n" for material_index in faces_use_material],
                    "  ",
                )
            x_file_content += "\n"
            print_timing("material list")

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
                x_file_content += "  }\n"
            x_file_content += " }\n\n"
            print_timing("materials")

            # 法線データ / Normal data
            x_file_content += "MeshNormals {\n"
            append_list(["  " + vertex_to_str(normal) + ";,\n" for normal in normals], " ")
            append_list(
                [
                    "  " + str(len(vertex)) + ";" + str(vertex).replace(" ", "")[1:-1] + ";,\n"
                    for vertex in vertex_use_normal
                ],
                " ",
            )
            x_file_content += "}\n\n"
            print_timing("normals")

            # UVデータ / UV data
            x_file_content += "MeshTextureCoords {\n"
            append_list(
                [
                    "  "
                    + float_to_str(vertex[0])
                    + ";"
                    + float_to_str(-vertex[1] + 1)
                    + ";,\n"
                    for vertex in uv_data
                ],
                " ",
            )
            # MeshTextureCoords と Mesh を閉じる / Close MeshTextureCoords and Mesh
            x_file_content += " }\n}\n"
            print_timing("uvs")

            with open(self.filepath, mode="w") as f:
                f.write(x_file_content)
            print_timing("write file")

        print(f"[X export] done: {time.perf_counter() - t_total:.3f}s total")

        return {"FINISHED"}
