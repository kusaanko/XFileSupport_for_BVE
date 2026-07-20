import bpy
from bpy.props import (
    StringProperty,
    BoolProperty,
    FloatProperty,
)
from bpy_extras.io_utils import ExportHelper
from .model_data_utility import ModelDataUtility
from .utility import float_to_str, vertex_to_str


# CSVファイルに出力 / Export to CSV file
class ExportOpenBveCSVFile(bpy.types.Operator, ExportHelper):
    bl_idname = "export.csv_for_open_bve"
    bl_description = "Export to OpenBVE CSV file (.csv)"
    bl_label = "Export OpenBVE CSV File"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_options = {"UNDO"}

    filepath: StringProperty(name="export file", subtype="FILE_PATH")

    filename_ext = ".csv"

    filter_glob: StringProperty(
        default="*.csv",
        options={"HIDDEN"},
    )

    scale: FloatProperty(
        name="Scale",
        default=1.0,
    )

    export_selected_only: BoolProperty(
        name="Export only selected objects",
        default=False,
    )

    gamma_correction: BoolProperty(
        name="Gamma correction",
        default=True,
    )

    use_texture_name: BoolProperty(
        name="Use texture name instead of texture path",
        description="This is useful when you want to use a relative path",
        default=False,
    )

    use_add_face2: BoolProperty(
        name="Use AddFace2",
        description="Use AddFace2 instead of AddFace",
        default=False,
    )

    use_emissive_power: BoolProperty(
        name="Use emissive power",
        description="Multiply emissive color by emissive power",
        default=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def execute(self, context):
        if not self.filepath.endswith(".csv"):
            return {"CANCELLED"}

        model_data_utility = ModelDataUtility()
        model_data_utility.execute(
            context,
            export_selected_only=self.export_selected_only,
            scale=self.scale,
            gamma_correction=self.gamma_correction,
        )
        vertexes = model_data_utility.vertexes
        faces = model_data_utility.faces
        normals = model_data_utility.normals
        normal_faces = model_data_utility.vertex_use_normal
        x_materials = model_data_utility.x_materials
        faces_use_material = model_data_utility.faces_use_material
        uv_data = model_data_utility.uv_data

        csv_file_content = ""

        # マテリアルごとに作成 / Create for each material
        for material_index in range(len(x_materials)):
            face_command = "AddFace2" if self.use_add_face2 else "AddFace"
            csv_file_content += "CreateMeshBuilder,\n"
            vertices_dict = {}
            vertices_list = []
            uv_vertices_list = []
            faces_no_duplicates = []
            x_material = x_materials[material_index]
            openbve_csv_property = x_material.openbve_csv_property
            if x_material.openbve_csv_property is not None:
                face_command = (
                    "AddFace2"
                    if x_material.openbve_csv_property.use_add_face_2
                    else "AddFace"
                )
            for face_index in range(len(faces)):
                x_material_index = faces_use_material[face_index]
                if x_material_index != material_index:
                    continue
                vertex_indices = []
                face = faces[face_index]
                normal_face = normal_faces[face_index]
                for i in range(len(face)):
                    vertex_index = face[i]
                    vertex = vertexes[vertex_index]
                    normal = normals[normal_face[i]]
                    # 頂点が他のデータと重複していたらそれを使用する / Use it if the vertex overlaps with other data
                    # 頂点とUVはセットなのでセットで重複を調べる / Vertices and UVs are sets, so check for duplicates in sets
                    uv = uv_data[vertex_index]
                    if x_material.texture_path == "":
                        uv = (0.0, 0.0)
                    key = vertex_to_str(vertex) + vertex_to_str(normal) + str(uv)
                    if key not in vertices_dict.keys():
                        vertices_dict[key] = len(vertices_dict.keys())
                        vertices_list.append(
                            [
                                vertex[0],
                                vertex[1],
                                vertex[2],
                                normal[0],
                                normal[1],
                                normal[2],
                            ]
                        )
                        uv_vertices_list.append(uv)
                    vertex_indices.append(vertices_dict[key])
                faces_no_duplicates.append(vertex_indices)
            # 頂点データ / Vertex data
            for vertex in vertices_list:
                csv_file_content += (
                    "AddVertex,"
                    + float_to_str(vertex[0])
                    + ","
                    + float_to_str(vertex[2])
                    + ","
                    + float_to_str(vertex[1])
                    + ","
                    + float_to_str(vertex[3])
                    + ","
                    + float_to_str(vertex[5])
                    + ","
                    + float_to_str(vertex[4])
                    + "\n"
                )
            # 面データ / Face data
            for face in faces_no_duplicates:
                csv_file_content += face_command + ","
                for vertex_index in face:
                    csv_file_content += str(vertex_index) + ","
                csv_file_content = csv_file_content[0:-1] + "\n"
            has_texture = False
            if x_material.texture_path != "":
                nighttime_texture_path = (
                    openbve_csv_property.nighttime_texture_path
                    if openbve_csv_property is not None
                    else ""
                )
                texture_path = x_material.texture_path
                if self.use_texture_name and x_material.texture_name != "":
                    texture_path = x_material.texture_name
                csv_file_content += (
                    f"LoadTexture,{texture_path},{nighttime_texture_path}\n"
                )
                if (
                    openbve_csv_property is not None
                    and openbve_csv_property.use_decal_transparent_color
                ):
                    csv_file_content += (
                        "SetDecalTransparentColor,"
                        + str(
                            round(openbve_csv_property.decal_transparent_color[0] * 255)
                        )
                        + ","
                        + str(
                            round(openbve_csv_property.decal_transparent_color[1] * 255)
                        )
                        + ","
                        + str(
                            round(openbve_csv_property.decal_transparent_color[2] * 255)
                        )
                        + "\n"
                    )
                if x_material.texture_extension == "REPEAT":
                    csv_file_content += "SetWrapMode,RepeatRepeat\n"
                elif x_material.texture_extension == "EXTEND":
                    csv_file_content += "SetWrapMode,ClampClamp\n"
                has_texture = True
            # 面色 / Face color
            csv_file_content += (
                "SetColor,"
                + str(round(x_material.face_color[0] * 255))
                + ","
                + str(round(x_material.face_color[1] * 255))
                + ","
                + str(round(x_material.face_color[2] * 255))
                + ","
                + str(round(x_material.face_color[3] * 255))
                + "\n"
            )
            # OpenBVEでは放射色に対応 / OpenBVE supports emissive color
            emissive_color = x_material.emission_color
            if self.use_emissive_power:
                emissive_color = x_material.emission_color_calculated
            csv_file_content += (
                "SetEmissiveColor,"
                + str(round(emissive_color[0] * 255))
                + ","
                + str(round(emissive_color[1] * 255))
                + ","
                + str(round(emissive_color[2] * 255))
                + "\n"
            )
            if openbve_csv_property is not None:
                # Enable cross-fading
                if openbve_csv_property.enable_cross_fading:
                    csv_file_content += "EnableCrossFading,true\n"
                if openbve_csv_property.use_blend_mode:
                    csv_file_content += f"SetBlendMode,{openbve_csv_property.blend_mode},{openbve_csv_property.glow_half_distance},{openbve_csv_property.glow_attenuation_mode}\n"
            # UVデータ / UV data
            if has_texture:
                for i in range(0, len(uv_vertices_list)):
                    csv_file_content += (
                        "SetTextureCoordinates,"
                        + str(i)
                        + ","
                        + float_to_str(uv_vertices_list[i][0])
                        + ","
                        + float_to_str(-uv_vertices_list[i][1] + 1)
                        + "\n"
                    )

        with open(self.filepath, mode="w") as f:
            f.write(csv_file_content)
        return {"FINISHED"}
