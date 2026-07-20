import re
import bpy
import math

from .types import CustomOpenBveCsvNode

from .utility import vertex_to_str


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
    principled = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")

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

        target_objects = bpy.context.scene.objects
        if export_selected_only:
            target_objects = bpy.context.selected_objects
        for obj in target_objects:
            if obj.type == "MESH" and not obj.hide_get():
                # モディファイヤーを適用した状態のオブジェクトを取得
                depsgraph = bpy.context.evaluated_depsgraph_get()
                obj_tmp = obj.evaluated_get(depsgraph)

                # Meshに変換
                mesh = obj_tmp.to_mesh(
                    preserve_all_data_layers=True, depsgraph=depsgraph
                )

                # UVマップが存在しないメッシュではactiveがNoneになる
                uv_layer = mesh.uv_layers.active
                uv_vertexes = uv_layer.data if uv_layer is not None else None
                vertex_index = 0
                # 法線取得用
                loops = mesh.loops
                for polygon in mesh.polygons:
                    ver = []
                    normal = []
                    nor = polygon.normal
                    vertex_index += len(polygon.vertices) - 1
                    texture = ""
                    if len(mesh.materials) == 0:
                        if fake_material.name not in materials_dict.keys():
                            materials_dict[fake_material.name] = len(
                                materials_dict.keys()
                            )
                            materials.append(fake_material)
                        self.faces_use_material.append(
                            materials_dict[fake_material.name]
                        )
                    else:
                        for material in mesh.materials:
                            if material is None:
                                # マテリアルを追加したが、新規ボタンを押していない状態のマテリアルの場合
                                continue
                            if material.name not in materials_dict.keys():
                                materials_dict[material.name] = len(
                                    materials_dict.keys()
                                )
                                materials.append(material)
                            if material.use_nodes:
                                # ノードを取得
                                nodes = material.node_tree.nodes
                                # プリンシプルBSDFを取得
                                principled = next(
                                    n
                                    for n in nodes
                                    if n.bl_idname == "ShaderNodeBsdfPrincipled"
                                )
                                # テクスチャの有無を確認
                                if len(principled.inputs["Base Color"].links) > 0:
                                    for link in principled.inputs["Base Color"].links:
                                        if (
                                            link.from_node.bl_idname
                                            == "ShaderNodeTexImage"
                                        ):
                                            texture = bpy.path.basename(
                                                link.from_node.image.filepath
                                            )
                        self.faces_use_material.append(
                            materials_dict[mesh.materials[polygon.material_index].name]
                        )

                    for vertex, loop_index in zip(
                        reversed(polygon.vertices), reversed(polygon.loop_indices)
                    ):
                        # ワールド座標から変換
                        vertex_co = obj.matrix_world @ mesh.vertices[vertex].co
                        # 法線を取得する
                        nor = loops[loop_index].normal
                        mx_inv = obj.matrix_world.inverted()
                        mx_norm = mx_inv.transposed().to_3x3()
                        world_norm = mx_norm @ nor
                        world_norm.normalize()
                        # スケールに合わせる
                        vertex_co[0] *= scale
                        vertex_co[1] *= scale
                        vertex_co[2] *= scale
                        # 頂点が他のデータと重複していたらそれを使用する
                        # 頂点とUVはセットなのでセットで重複を調べる
                        if uv_vertexes is not None:
                            uv = uv_vertexes[vertex_index].uv
                        else:
                            uv = (0.0, 0.0)
                        if texture == "":
                            uv = (0.0, 0.0)
                        key = vertex_to_str(vertex_co) + str(uv)
                        if key not in vertexes_dict.keys():
                            vertexes_dict[key] = len(vertexes_dict.keys())
                            self.vertexes.append(vertex_co)
                            self.uv_data.append(uv)
                        if vertex_to_str(world_norm) not in normals_dict.keys():
                            normals_dict[vertex_to_str(world_norm)] = len(
                                normals_dict.keys()
                            )
                            self.normals.append(world_norm)
                        ver.append(vertexes_dict[key])
                        normal.append(normals_dict[vertex_to_str(world_norm)])
                        vertex_index -= 1
                    vertex_index += len(polygon.vertices) + 1
                    self.faces.append(ver)
                    self.vertex_use_normal.append(normal)

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
                    n for n in nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"
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
