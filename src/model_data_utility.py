import re
import bpy
import math
import time

from .types import CustomOpenBveCsvNode


class OpenBveCsvProperty:
    enable_cross_fading: bool = False
    use_blend_mode: bool = False
    blend_mode: str = "Normal"
    glow_half_distance: int = 0
    glow_attenuation_mode: str = "DivideExponent4"
    use_decal_transparent_color: bool = False
    decal_transparent_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    nighttime_texture_path: str | None = None
    use_add_face_2: bool = False


class Material:
    face_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    power = 0.0
    specular_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    emission_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    emissive_power = 0.0
    emission_color_calculated: tuple[float, float, float] = (0.0, 0.0, 0.0)
    texture_path = ""
    texture_name = ""
    name = ""
    openbve_csv_property: OpenBveCsvProperty | None = None
    texture_extension = "REPEAT"


def get_base_color_texture(material):
    # ノードが無効な場合はテクスチャなし / No texture when nodes are disabled
    if not material.use_nodes:
        return ""
    # プリンシプルBSDFを取得 / Get the Principled BSDF
    nodes = material.node_tree.nodes
    principled = next(
        (n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"),
        None,
    )
    if principled is None:
        raise Exception(
            bpy.app.translations.pgettext(
                "Principled BSDF node not found in material: "
            )
            + f" {material.name}"
        )
    # Base Colorに接続されたテクスチャを探す / Find the texture connected to Base Color
    for link in principled.inputs["Base Color"].links:
        if link.from_node.bl_idname == "ShaderNodeTexImage":
            return bpy.path.basename(link.from_node.image.filepath)
    return ""


def gen_fake_material():
    # 偽物のマテリアルを作成 / Create a fake material
    material = bpy.data.materials.new("NoneMaterial")

    material.specular_intensity = 0.0
    material.specular_color = (0.0, 0.0, 0.0)
    material.diffuse_color = (1.0, 1.0, 1.0, 1.0)

    # ブレンドモードの設定 / Set blend mode
    material.blend_method = "CLIP"

    # ノードを有効化 / Enable nodes
    material.use_nodes = True

    nodes = material.node_tree.nodes
    # プリンシプルBSDFを取得 / Get the Principled BSDF
    principled = next(n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")

    # ベースカラーを設定 / Set the base color
    principled.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)

    # スペキュラーを設定 / Set the specular
    principled.inputs["Specular Tint"].default_value = (1.0, 1.0, 1.0, 1.0)
    principled.inputs["Specular IOR Level"].default_value = 0.5

    # 放射を設定 / Set the emission
    principled.inputs["Emission Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    return material


# 出力用にデータを整形
class ModelDataUtility:
    def __init__(self):
        self.vertexes = []
        self.normals = []
        self.vertex_use_normal = []
        self.faces = []
        self.x_materials = []
        self.faces_use_material = []
        self.uv_data = []

    def execute(
        self, context, export_selected_only: bool, scale: float, gamma_correction: bool
    ):
        self.vertexes = []
        vertexes_dict = {}
        self.normals = []
        normals_dict = {}
        self.vertex_use_normal = []
        self.faces = []
        materials_dict: dict[str, int] = {}
        materials = []
        self.x_materials: list[Material] = []
        self.faces_use_material = []
        self.uv_data = []
        fake_material = gen_fake_material()

        material_name_set = set()

        # depsgraphはオブジェクトループの外で1回だけ取得 / Get the depsgraph once outside the object loop
        depsgraph = bpy.context.evaluated_depsgraph_get()
        target_objects = bpy.context.scene.objects
        if export_selected_only:
            target_objects = bpy.context.selected_objects
        for obj in target_objects:
            if obj.type == "MESH" and not obj.hide_get():
                t_obj = time.perf_counter()
                # モディファイヤーを適用した状態のオブジェクトを取得
                obj_tmp = obj.evaluated_get(depsgraph)

                # Meshに変換
                mesh = obj_tmp.to_mesh(
                    preserve_all_data_layers=True, depsgraph=depsgraph
                )
                print(
                    f"[X export] mesh '{obj.name}': {len(mesh.polygons)} polygons "
                    f"(to_mesh {time.perf_counter() - t_obj:.3f}s)"
                )

                # UVマップが存在しないメッシュではactiveがNoneになる
                uv_layer = mesh.uv_layers.active
                # 逆行列と法線変換行列は頂点ごとに計算せず、オブジェクトごとに1回だけ計算する /
                #  Compute the inverse and normal matrices once per object, not per vertex
                matrix_world = obj.matrix_world
                mx_inv = matrix_world.inverted()
                mx_norm = mx_inv.transposed().to_3x3()

                vertex_count = len(mesh.vertices)
                loop_count = len(mesh.loops)
                polygon_count = len(mesh.polygons)

                # bpyの要素アクセスは高コストなので foreach_get で一括取得する /
                #  Element access in bpy is expensive, so fetch everything with foreach_get
                coords = [0.0] * (vertex_count * 3)
                mesh.vertices.foreach_get("co", coords)
                loop_vertexes = [0] * loop_count
                mesh.loops.foreach_get("vertex_index", loop_vertexes)
                loop_normals = [0.0] * (loop_count * 3)
                try:
                    mesh.corner_normals.foreach_get("vector", loop_normals)
                except Exception:
                    mesh.loops.foreach_get("normal", loop_normals)
                loop_starts = [0] * polygon_count
                mesh.polygons.foreach_get("loop_start", loop_starts)
                loop_totals = [0] * polygon_count
                mesh.polygons.foreach_get("loop_total", loop_totals)
                polygon_materials = [0] * polygon_count
                mesh.polygons.foreach_get("material_index", polygon_materials)

                uv_coords = None
                if uv_layer is not None:
                    uv_coords = [0.0] * (loop_count * 2)
                    uv_layer.data.foreach_get("uv", uv_coords)

                # 行列の要素をローカルに取り出してベクトル生成を避ける /
                #  Take the matrix elements locally to avoid allocating Vectors
                m00, m01, m02, m03 = matrix_world[0]
                m10, m11, m12, m13 = matrix_world[1]
                m20, m21, m22, m23 = matrix_world[2]
                # ワールド座標の頂点を事前計算 / Precompute world-space vertices
                world_vertexes = [None] * vertex_count
                for i in range(vertex_count):
                    i3 = i * 3
                    x = coords[i3]
                    y = coords[i3 + 1]
                    z = coords[i3 + 2]
                    world_vertexes[i] = (
                        (m00 * x + m01 * y + m02 * z + m03) * scale,
                        (m10 * x + m11 * y + m12 * z + m13) * scale,
                        (m20 * x + m21 * y + m22 * z + m23) * scale,
                    )

                # ワールド法線を事前計算 / Precompute world-space normals
                n00, n01, n02 = mx_norm[0]
                n10, n11, n12 = mx_norm[1]
                n20, n21, n22 = mx_norm[2]
                sqrt = math.sqrt
                world_normals = [None] * loop_count
                for i in range(loop_count):
                    i3 = i * 3
                    x = loop_normals[i3]
                    y = loop_normals[i3 + 1]
                    z = loop_normals[i3 + 2]
                    nx = n00 * x + n01 * y + n02 * z
                    ny = n10 * x + n11 * y + n12 * z
                    nz = n20 * x + n21 * y + n22 * z
                    length = sqrt(nx * nx + ny * ny + nz * nz)
                    if length != 0.0:
                        nx /= length
                        ny /= length
                        nz /= length
                    world_normals[i] = (nx, ny, nz)

                materials_list = list(mesh.materials)
                material_names = [
                    material.name if material is not None else None
                    for material in materials_list
                ]
                material_count = len(materials_list)
                # マテリアルごとのテクスチャを事前に解決し、ポリゴンごとのノードツリー走査を避ける /
                #  Resolve per-material textures in advance to avoid scanning node trees per polygon
                mesh_material_textures = {}
                vertexes_dict_get = vertexes_dict.get
                normals_dict_get = normals_dict.get
                for p in range(polygon_count):
                    start = loop_starts[p]
                    total = loop_totals[p]
                    ver = []
                    normal = []
                    texture = ""
                    if material_count == 0:
                        if fake_material.name not in materials_dict:
                            materials_dict[fake_material.name] = len(materials_dict)
                            materials.append(fake_material)
                        self.faces_use_material.append(
                            materials_dict[fake_material.name]
                        )
                    else:
                        material_index = polygon_materials[p]
                        material = materials_list[material_index]
                        if material is not None:  # 新規ボタンを押していない状態のマテリアル
                            material_name = material_names[material_index]
                            if material_name not in materials_dict:
                                materials_dict[material_name] = len(materials_dict)
                                materials.append(material)
                            # 事前に解決したテクスチャを使用する / Use the pre-resolved texture
                            if material_name not in mesh_material_textures:
                                mesh_material_textures[material_name] = (
                                    get_base_color_texture(material)
                                )
                            texture = mesh_material_textures[material_name]
                            self.faces_use_material.append(
                                materials_dict[material_name]
                            )

                    for loop_index in range(start + total - 1, start - 1, -1):
                        vertex_co = world_vertexes[loop_vertexes[loop_index]]
                        # 頂点が他のデータと重複していたらそれを使用する
                        # 頂点とUVはセットなのでセットで重複を調べる
                        if uv_coords is not None and texture != "":
                            uv = (
                                uv_coords[loop_index * 2],
                                uv_coords[loop_index * 2 + 1],
                            )
                        else:
                            uv = (0.0, 0.0)
                        # 文字列連結の代わりに丸めたチュープルをキーにする /
                        #  Use a plain tuple of the raw floats as the key; floats hash
                        #  the same for values produced by the same computation
                        key = (
                            vertex_co[0],
                            vertex_co[1],
                            vertex_co[2],
                            uv[0],
                            uv[1],
                        )
                        index = vertexes_dict_get(key)
                        if index is None:
                            index = len(vertexes_dict)
                            vertexes_dict[key] = index
                            self.vertexes.append(vertex_co)
                            self.uv_data.append(uv)
                        world_norm = world_normals[loop_index]
                        normal_index = normals_dict_get(world_norm)
                        if normal_index is None:
                            normal_index = len(normals_dict)
                            normals_dict[world_norm] = normal_index
                            self.normals.append(world_norm)
                        ver.append(index)
                        normal.append(normal_index)
                    self.faces.append(ver)
                    self.vertex_use_normal.append(normal)
                print(f"[X export] mesh '{obj.name}' done: {time.perf_counter() - t_obj:.3f}s")

        for material in materials:
            if material is None:
                # マテリアルを追加したが、新規ボタンを押していない状態のマテリアルの場合
                continue
            # ノードを使用するかどうか
            x_material = Material()
            # マテリアル名はアルファベット英数字、アンダーバー、ハイフン
            x_material.name = re.sub(r"[^0-9A-Za-z_-]", "", material.name)
            if x_material.name in material_name_set:
                index = len(material_name_set)
                while True:
                    if x_material.name + str(index) not in material_name_set:
                        break
                    index += 1
                x_material.name = x_material.name + str(index)
            if re.match(r"^[0-9_]", x_material.name):
                x_material.name = ""
            if len(x_material.name) == 0:
                # マテリアル名の重複を避ける
                material_name_set.add(x_material.name)
            if material.use_nodes:
                texture = ""

                # ノードを取得
                nodes = material.node_tree.nodes
                # プリンシプルBSDFを取得
                principled = next(
                    (n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"),
                    None,
                )
                if principled is None:
                    raise Exception(
                        bpy.app.translations.pgettext(
                            "Principled BSDF node not found in material: "
                        )
                        + f" {material.name}"
                    )

                # ベースカラー
                if len(principled.inputs["Base Color"].links) > 0:
                    need_color = True
                    for link in principled.inputs["Base Color"].links:
                        print(link.from_node.bl_idname)
                        if link.from_node.bl_idname == "ShaderNodeTexImage":
                            texture = bpy.path.basename(link.from_node.image.filepath)
                            x_material.texture_extension = link.from_node.extension
                            x_material.texture_name = link.from_node.image.name
                        if link.from_node.bl_idname == "ShaderNodeRGB":
                            need_color = False
                            for out in link.from_node.outputs:
                                if out.bl_idname == "NodeSocketColor":
                                    x_material.face_color = (
                                        out.default_value[0],
                                        out.default_value[1],
                                        out.default_value[2],
                                        principled.inputs["Alpha"].default_value,
                                    )
                                    if gamma_correction:
                                        x_material.face_color = (
                                            math.pow(x_material.face_color[0], 1 / 2.2),
                                            math.pow(x_material.face_color[1], 1 / 2.2),
                                            math.pow(x_material.face_color[2], 1 / 2.2),
                                            x_material.face_color[3],
                                        )
                        if link.from_node.bl_idname == "ShaderNodeGamma":
                            for input in link.from_node.inputs:
                                if input.identifier == "Gamma":
                                    if round(input.default_value * 100) != 220:
                                        raise Exception(
                                            bpy.app.translations.pgettext(
                                                "Gamma correction is not 2.2"
                                            )
                                        )
                                if input.identifier == "Color":
                                    need_color = False
                                    x_material.face_color = (
                                        input.default_value[0],
                                        input.default_value[1],
                                        input.default_value[2],
                                        principled.inputs["Alpha"].default_value,
                                    )
                    if need_color:
                        x_material.face_color = (1.0, 1.0, 1.0, 1.0)
                else:
                    col = principled.inputs["Base Color"].default_value
                    x_material.face_color = (
                        col[0],
                        col[1],
                        col[2],
                        principled.inputs["Alpha"].default_value,
                    )
                    if gamma_correction:
                        x_material.face_color = (
                            math.pow(x_material.face_color[0], 1 / 2.2),
                            math.pow(x_material.face_color[1], 1 / 2.2),
                            math.pow(x_material.face_color[2], 1 / 2.2),
                            x_material.face_color[3],
                        )
                # 鏡面反射
                # default_valueへの参照を保持するとマテリアル削除後にクラッシュするため値をコピーする
                x_material.power = principled.inputs["Specular IOR Level"].default_value
                x_material.specular_color = tuple(
                    principled.inputs["Specular Tint"].default_value
                )

                # 放射色
                x_material.emission_color = tuple(
                    principled.inputs["Emission Color"].default_value
                )
                x_material.emissive_power = principled.inputs[
                    "Emission Strength"
                ].default_value

                if texture != "":
                    x_material.texture_path = texture

                # OpenBveCsvNodeを取得
                for n in nodes:
                    if n.bl_idname == CustomOpenBveCsvNode.bl_idname:
                        openbve_csv_node: CustomOpenBveCsvNode = n
                        if openbve_csv_node is not None:
                            x_material.openbve_csv_property = OpenBveCsvProperty()
                            x_material.openbve_csv_property.use_add_face_2 = (
                                openbve_csv_node.use_add_face_2
                            )
                            x_material.openbve_csv_property.enable_cross_fading = (
                                openbve_csv_node.enable_cross_fading
                            )
                            x_material.openbve_csv_property.use_blend_mode = (
                                openbve_csv_node.use_blend_mode
                            )
                            x_material.openbve_csv_property.blend_mode = (
                                openbve_csv_node.blend_mode
                            )
                            x_material.openbve_csv_property.glow_half_distance = (
                                openbve_csv_node.glow_half_distance
                            )
                            x_material.openbve_csv_property.glow_attenuation_mode = (
                                openbve_csv_node.glow_attenuation_mode
                            )
                            x_material.openbve_csv_property.use_decal_transparent_color = openbve_csv_node.use_decal_transparent_color
                            x_material.openbve_csv_property.decal_transparent_color = (
                                openbve_csv_node.decal_transparent_color[0],
                                openbve_csv_node.decal_transparent_color[1],
                                openbve_csv_node.decal_transparent_color[2],
                            )
                            x_material.openbve_csv_property.nighttime_texture_path = (
                                openbve_csv_node.nighttime_texture_path
                            )

            else:
                # ベースカラー
                x_material.face_color = tuple(material.diffuse_color)
                # 鏡面反射
                x_material.power = material.specular_intensity
                # 鏡面反射色
                x_material.specular_color = tuple(material.specular_color)
                # 放射色
                x_material.emission_color = (0.0, 0.0, 0.0, 1.0)
                # 放射強度
                x_material.emissive_power = 0.0

            # 放射色の計算
            x_material.emission_color_calculated = (
                x_material.emission_color[0] * min(x_material.emissive_power, 1.0),
                x_material.emission_color[1] * min(x_material.emissive_power, 1.0),
                x_material.emission_color[2] * min(x_material.emissive_power, 1.0),
            )
            self.x_materials.append(x_material)

        # 生成した偽物のマテリアルを削除
        fake_material.user_clear()

        bpy.data.materials.remove(fake_material)
